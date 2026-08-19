"""Serialising a finished game so it can be played back exactly.

The engine is a command pattern over frozen state: the world only ever changes in
`GameEngine.execute_command`, so the whole run is the initial state plus the list
of commands in order. That is what gets written here — not a rendering of the
game, the game itself. A replay file rebuilds the identical `WorldState`, which a
transcript or a chronicle cannot do.

Commands are a heterogeneous list of frozen models, so each is written with the
name of its class and rebuilt through that class. An unknown name is refused
rather than skipped: a replay missing one command is not a shorter replay, it is a
different game.
"""

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel, ConfigDict, Field

from core.commands import Command
from core.game_engine import GameEngine
from entities.world import WorldState

logger = logging.getLogger(__name__)

REPLAY_NAME: str = "replay.json"
REPLAY_FORMAT: int = 1


def _command_types() -> Dict[str, Type[Command]]:
    """Every concrete command, by class name.

    Walked from `Command` rather than listed, so a command added later is replayable
    the day it is written instead of the day someone remembers this file.
    """
    found: Dict[str, Type[Command]] = {}
    frontier: List[Type[Command]] = list(Command.__subclasses__())
    while frontier:
        kind = frontier.pop()
        frontier.extend(kind.__subclasses__())
        found[kind.__name__] = kind
    return found


class RecordedCommand(BaseModel):
    """One command, with the name of the class that knows how to run it."""

    model_config = ConfigDict(frozen=True)

    type: str = Field(description="Command class name, e.g. EatBerriesCommand")
    fields: Dict[str, Any] = Field(default_factory=dict, description="The command's own fields")

    @classmethod
    def of(cls, command: Command) -> "RecordedCommand":
        return cls(type=type(command).__name__, fields=command.model_dump(mode="json"))

    def rebuild(self, known: Dict[str, Type[Command]]) -> Command:
        kind = known.get(self.type)
        if kind is None:
            raise ValueError(
                f"replay holds {self.type!r}, which this build has no command for; "
                "the file was written by a different version of the game"
            )
        return kind(**self.fields)


class Replay(BaseModel):
    """A whole game, in the only form that can be played again."""

    model_config = ConfigDict(frozen=True)

    format: int = Field(default=REPLAY_FORMAT, description="Replay file format version")
    seed: int = Field(description="Seed the run used, so perception noise repeats")
    agent_names: Tuple[str, ...] = Field(description="Seating order, as the game was set up")
    initial_state: WorldState = Field(description="The world before any command ran")
    commands: Tuple[RecordedCommand, ...] = Field(default=())
    final_state: WorldState = Field(description="The world the run actually ended in")

    @classmethod
    def of(cls, engine: GameEngine, seed: int) -> "Replay":
        return cls(
            seed=seed,
            agent_names=tuple(agent.name for agent in engine.initial_state.agents),
            initial_state=engine.initial_state,
            commands=tuple(RecordedCommand.of(command) for command in engine.history),
            final_state=engine.current_state,
        )


def save_replay(engine: GameEngine, seed: int, path: Path) -> Path:
    """Write the run in replayable form."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(Replay.of(engine, seed).model_dump_json(indent=2), encoding="utf-8")
    logger.info("replay written to %s (%d commands)", path, len(engine.history))
    return path


def load_replay(path: Path) -> Replay:
    """Read a replay file back, whole."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != REPLAY_FORMAT:
        raise ValueError(
            f"{path} is replay format {data.get('format')}, this build reads {REPLAY_FORMAT}"
        )
    return Replay.model_validate(data)


def rebuild(
    replay: Replay,
    stop_at_hour: Optional[int] = None,
    observer: Optional[Callable[[GameEngine], None]] = None,
) -> GameEngine:
    """Play the commands back onto the initial state and return the engine.

    With `stop_at_hour`, the rebuild halts at the first command stamped for that hour,
    leaving a real world state part way through the run — that is what a branch is
    made from. Only a full rebuild is checked against the recorded ending, since a
    partial one is not meant to reach it.

    `observer` is called after every command with the engine as it stands, so a
    caller can watch the whole run pass by in one rebuild — snapshots per hour, say —
    instead of rebuilding once per point of interest. It sees state; it must not
    change it.

    A full rebuild that lands elsewhere raises, never logs and carries on. It is not a
    slightly wrong replay: it means a command no longer does what it did, and every
    conclusion drawn from replaying it would be about a different game.
    """
    known = _command_types()
    engine = GameEngine(
        initial_state=replay.initial_state,
        current_state=replay.initial_state,
    )
    for recorded in replay.commands:
        if stop_at_hour is not None and recorded.fields.get("timestamp", 0) >= stop_at_hour:
            return engine
        engine.execute_command(recorded.rebuild(known))
        if observer is not None:
            observer(engine)

    if stop_at_hour is not None:
        logger.warning(
            "replay ended at hour %d, before the requested hour %d",
            engine.current_state.world_time,
            stop_at_hour,
        )
        return engine

    if engine.current_state != replay.final_state:
        raise ValueError(
            f"replay diverged: {len(replay.commands)} commands rebuilt a different world "
            "than the one recorded. The commands no longer do what they did when this "
            "run was played."
        )
    return engine
