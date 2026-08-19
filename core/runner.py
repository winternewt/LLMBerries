"""Setting up and running one game, without an opinion about who is watching.

`main.py` drives this from a terminal and says things out loud between the steps;
the web layer drives it from a worker thread and says nothing. Both get the same
game: the split is prepare (seed, run directory, engine, seats, wiring), run
(the hour loop, the epilogue, the sealed chronicle), and write (the artifacts).
Nothing here prints — a caller with a terminal narrates around these calls.

One process runs one game at a time. `prepare_game` seeds the process-global RNG
and attaches the session log to the root logger, and the pacers and the ledger
are shared per provider — a second concurrent game would corrupt all three. The
web layer enforces this with a lock; the CLI enforces it by being a terminal.
"""

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from core.agent import Agent, LLMAgent, ScriptedAgent
from core.chronicler import Chronicler, save_chronicle
from core.framing import Framing
from core.game_engine import GameEngine
from core.narrator import render_transcript
from core.record import (
    CHRONICLE_NAME,
    SESSION_LOG_NAME,
    TRANSCRIPT_NAME,
    SessionLog,
    describe_invocation,
    open_run_directory,
)
from core.replay import REPLAY_NAME, save_replay
from core.zombie import ZombieAgent, ZombieFlavour
from entities.chronicle import GameChronicle
from entities.llm_configs import ProviderSpec

logger = logging.getLogger(__name__)

DEFAULT_NAMES: tuple[str, ...] = (
    "Alice", "Bob", "Charlie", "Dana", "Eli", "Fen", "Gus", "Hana",
)


def agent_names(count: int) -> List[str]:
    """Names for `count` agents, extending past the built-in list if asked."""
    if count <= len(DEFAULT_NAMES):
        return list(DEFAULT_NAMES[:count])
    extra = [f"Agent{i}" for i in range(len(DEFAULT_NAMES), count)]
    return list(DEFAULT_NAMES) + extra


def build_agents(
    engine: GameEngine,
    scripted: bool,
    providers: List[ProviderSpec],
    chronicler: Chronicler,
    zombies: Optional[List[ZombieFlavour]] = None,
    seed: Optional[int] = None,
    framing: Framing = Framing.SILENT,
) -> List[Agent]:
    """One agent per seat.

    Zombies take the last seats, so the thinking ones sit together and each has at
    least one babbling neighbour. Everyone else gets a provider round-robin, or is
    scripted when no keys are being spent.

    The framing goes to every thinking seat or to none of them. A ring where one body
    was told this is not a game and its neighbour was told nothing measures neither
    arm: whatever the two do differently could be the frame or could be the seat.
    """
    count = engine.current_state.agent_count
    zombies = zombies or []
    if len(zombies) > count:
        raise ValueError(f"{len(zombies)} zombies asked for but only {count} seats")

    first_zombie_seat = count - len(zombies)
    seats: List[Agent] = []

    for seat_id in range(count):
        if seat_id >= first_zombie_seat:
            seats.append(
                ZombieAgent(
                    agent_id=seat_id,
                    engine=engine,
                    chronicler=chronicler,
                    flavour=zombies[seat_id - first_zombie_seat],
                    seed=seed if seed is not None else 0,
                )
            )
        elif scripted:
            seats.append(ScriptedAgent(agent_id=seat_id, engine=engine, chronicler=chronicler))
        else:
            seats.append(
                LLMAgent(
                    agent_id=seat_id,
                    engine=engine,
                    chronicler=chronicler,
                    provider=providers[seat_id % len(providers)],
                    framing=framing,
                )
            )
    return seats


@dataclass
class GameConfig:
    """Everything a game needs decided before it starts."""

    agents: int
    scripted: bool = False
    zombies: List[ZombieFlavour] = field(default_factory=list)
    providers: List[ProviderSpec] = field(default_factory=list)
    framing: Framing = Framing.SILENT
    max_hours: int = 24 * 30
    seed: Optional[int] = None
    out: Path = Path("runs")
    record: bool = True
    # Researcher-side pacing only: a pause between hours so a scripted game is
    # watchable live. The agents never experience it — it sits between turn cycles.
    hour_delay: float = 0.0


@dataclass
class PreparedGame:
    """A game built and wired, one call away from being played."""

    config: GameConfig
    engine: GameEngine
    chronicler: Chronicler
    seats: List[Agent]
    run_dir: Optional[Path]
    session_log: Optional[SessionLog]
    seed: int

    def close(self) -> None:
        """Detach the session log. Last thing, after every artifact and every word."""
        if self.session_log is not None:
            self.session_log.detach()


def prepare_game(
    config: GameConfig,
    *,
    chronicler_factory: Callable[[GameEngine, Framing], Chronicler] = Chronicler,
    on_recording: Optional[Callable[[Path], None]] = None,
) -> PreparedGame:
    """Seed, open the run directory, build the engine and the seats, wire them up.

    A run with no seed cannot be replayed, and "I did not pass one" is not a reason
    to lose that: one is drawn, used, and written into the record either way.

    `on_recording` fires the moment the run directory exists, before the engine says
    anything — that is where the CLI announces the path, in the same breath it
    always has.
    """
    seed = config.seed if config.seed is not None else random.randrange(2**31)
    random.seed(seed)

    run_dir: Optional[Path] = None
    session_log: Optional[SessionLog] = None
    if config.record:
        run_dir = open_run_directory(config.out)
        session_log = SessionLog(run_dir / SESSION_LOG_NAME).attach(describe_invocation(seed))
        if on_recording is not None:
            on_recording(run_dir)

    engine = GameEngine.create_new_game(agent_names=agent_names(config.agents))
    chronicler = chronicler_factory(engine, config.framing)
    seats = build_agents(
        engine,
        scripted=config.scripted,
        providers=config.providers,
        chronicler=chronicler,
        zombies=config.zombies,
        seed=seed,
        framing=config.framing,
    )
    for seat in seats:
        engine.decision_callbacks[seat.agent_id] = seat.decision_callback
        engine.reflection_callbacks[seat.agent_id] = seat.reflection_callback

    return PreparedGame(
        config=config,
        engine=engine,
        chronicler=chronicler,
        seats=seats,
        run_dir=run_dir,
        session_log=session_log,
        seed=seed,
    )


def run_prepared(
    prepared: PreparedGame, *, stop: Optional[threading.Event] = None
) -> GameChronicle:
    """Play the hours out and seal the record.

    `stop` is cooperative and coarse: it is looked at between hours, so stopping
    mid-hour waits for that hour's turns to finish. A stopped game gets no epilogue,
    same as one that ran out of hours — the ring never learned it ended.
    """
    engine = prepared.engine
    config = prepared.config

    hours = 0
    while hours < config.max_hours and (stop is None or not stop.is_set()):
        if not engine.run_turn_cycle():
            break
        hours += 1
        if config.hour_delay > 0:
            time.sleep(config.hour_delay)

    if engine.game_over:
        engine.run_epilogue()

    return prepared.chronicler.seal()


def write_artifacts(prepared: PreparedGame, record: GameChronicle) -> str:
    """Write the run's evidence beside its log; return the rendered transcript.

    The transcript is a reading of the game; the replay is the game. Written beside
    each other, always, because the one that can be re-run is the one nobody thinks
    to ask for until they need it.
    """
    rendered = render_transcript(record)
    if prepared.run_dir is not None:
        save_chronicle(record, prepared.run_dir / CHRONICLE_NAME)
        (prepared.run_dir / TRANSCRIPT_NAME).write_text(rendered, encoding="utf-8")
        save_replay(prepared.engine, prepared.seed, prepared.run_dir / REPLAY_NAME)
    return rendered
