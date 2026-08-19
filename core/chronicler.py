"""Collects turn records during a game and seals them into a chronicle.

Agents hand their turns here as they take them; deaths come off the event bus, so
they are recorded whether or not an agent was awake to notice. Nothing in here
changes game state — the chronicler only watches.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.constants import HUNGER_STEP
from core.enums import BodyState, EventType
from core.framing import Framing
from core.game_engine import GameEngine
from entities.chronicle import AgentSummary, Death, GameChronicle, TurnRecord, Unheard
from entities.observations import AgentObservation
from entities.events import GameEvent

logger = logging.getLogger(__name__)


class Chronicler:
    """Watches one game and produces its `GameChronicle`."""

    def __init__(self, engine: GameEngine, framing: Framing = Framing.SILENT) -> None:
        self.engine: GameEngine = engine
        # Carried so the sealed chronicle says which arm was played. A run whose frame
        # can only be recovered from the command line is a run nobody can file.
        self.framing: Framing = framing
        self.turns: List[TurnRecord] = []
        self.deaths: List[Death] = []
        self.unheard: List[Unheard] = []
        self._providers: Dict[int, str] = {}
        engine.event_bus.subscribe_to_type(EventType.AGENT_DIED, self._on_death)
        engine.event_bus.subscribe_to_type(EventType.MESSAGE_UNDELIVERED, self._on_unheard)

    def _on_death(self, event_name: str, event: GameEvent) -> None:
        if event.agent_id is None:
            logger.warning("death event without an agent id: %s", event.message)
            return
        agent = self.engine.current_state.agents[event.agent_id]
        self.deaths.append(
            Death(
                hour=int(event.game_time),
                agent_id=event.agent_id,
                agent_name=agent.name,
                berries_eaten=agent.total_berries_consumed,
            )
        )

    def _on_unheard(self, event_name: str, event: GameEvent) -> None:
        """Note words that reached nobody. The speaker is never told; the record is."""
        self.unheard.append(
            Unheard(
                hour=int(event.game_time),
                speaker=str(event.data.get("from_agent", "?")),
                listener=str(event.data.get("to_agent", "nobody")),
                direction=str(event.data.get("direction", "?")),
                reason=str(event.data.get("reason", "unknown")),
            )
        )

    def record(self, turn: TurnRecord) -> None:
        """Take one agent's turn into the record."""
        self.turns.append(turn)
        if turn.provider is not None:
            self._providers[turn.agent_id] = turn.provider

    def seal(self) -> GameChronicle:
        """Close the record and summarise how each agent finished."""
        state = self.engine.current_state
        death_hours = {death.agent_id: death.hour for death in self.deaths}

        summaries = tuple(
            AgentSummary(
                agent_id=agent.agent_id,
                name=agent.name,
                provider=self._providers.get(agent.agent_id),
                perceived_type=agent.perceived_type,
                survived=agent.alive,
                hunger_at_end=agent.hunger,
                berries_eaten=agent.total_berries_consumed,
                died_at_hour=death_hours.get(agent.agent_id),
                turns_taken=sum(1 for t in self.turns if t.agent_id == agent.agent_id),
                turns_lost=sum(
                    1 for t in self.turns if t.agent_id == agent.agent_id and t.turn_lost
                ),
                turns_cut_short=sum(
                    1 for t in self.turns if t.agent_id == agent.agent_id and t.turn_cut_short
                ),
            )
            for agent in state.agents
        )

        survivors = [agent for agent in state.agents if agent.alive]
        return GameChronicle(
            agent_count=state.agent_count,
            hours_played=state.world_time,
            framing=self.framing.value,
            turns=tuple(self.turns),
            deaths=tuple(self.deaths),
            unheard=tuple(self.unheard),
            agents=summaries,
            berries_left=state.bush.current_berries,
            winner=survivors[0].name if len(survivors) == 1 else None,
            outcome=self.engine.outcome.value,
        )


def misreadings(engine: GameEngine, observation: AgentObservation) -> Tuple[str, ...]:
    """Where this one's reading of the others differed from the truth.

    Perception is noisy on purpose: a body can read as asleep when it is dead, and a
    sleeper can read as gone. Nobody in the ring can tell. The record can, and the gap
    between what they believed and what was so is the most telling thing in a run — so
    it is measured here, once, at the moment they looked.
    """
    state = engine.current_state
    gaps: List[str] = []

    for seat in observation.seats:
        actual = state.agents[seat.seat_id]
        believed_gone = seat.perceived_status == BodyState.DEAD

        if believed_gone and actual.alive:
            gaps.append(
                f"read {seat.name} as gone; {seat.name} was alive with "
                f"{actual.hunger:.0f} hours left"
            )
        elif not believed_gone and not actual.alive:
            gaps.append(f"read {seat.name} as still going; {seat.name} was already dead")

        # Perception jitters by up to one step by design; only a gap wider than that
        # is a belief worth recording, otherwise the record drowns in noise.
        believed_hunger = seat.hunger_status.value
        if actual.alive and abs(believed_hunger - actual.hunger) > HUNGER_STEP:
            gaps.append(
                f"took {seat.name} for {seat.hunger_status.name.lower()} "
                f"({believed_hunger:.0f}h); {seat.name} actually had {actual.hunger:.0f}h"
            )

    return tuple(gaps)


def save_chronicle(chronicle: GameChronicle, path: Path) -> Path:
    """Write the chronicle as JSON so a story can be told from it later."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(chronicle.model_dump_json(indent=2), encoding="utf-8")
    logger.info("chronicle written to %s", path)
    return path


def load_chronicle(path: Path) -> GameChronicle:
    """Read a chronicle back."""
    return GameChronicle.model_validate(json.loads(path.read_text(encoding="utf-8")))


def turn_from_run(
    *,
    hour: int,
    agent_id: int,
    agent_name: str,
    hunger: float,
    bush_berries: int,
    neighbours: tuple,
    heard: tuple,
    provider: Optional[str] = None,
    model_id: Optional[str] = None,
    output: Optional[object] = None,
    said_aloud: Optional[str] = None,
    tool_calls: tuple = (),
    misread: tuple = (),
    error: Optional[str] = None,
) -> TurnRecord:
    """Build a `TurnRecord`, pulling reasoning off an Agno run output when there is one.

    `reasoning` stays None when the provider returned nothing — an absent trace is
    not the same as an agent that reasoned about nothing. `said_aloud` is for a
    speaker with no run output behind it, which is what a zombie is.
    """
    reasoning: Optional[str] = None
    said: Optional[str] = said_aloud

    if output is not None and error is None:
        # On a failed run Agno puts the provider's error JSON in `content`. Reading it
        # as speech would put an HTTP error in an agent's mouth; it belongs in `error`.
        raw_reasoning = getattr(output, "reasoning_content", None)
        reasoning = raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
        raw_content = getattr(output, "content", None)
        said = raw_content.strip() if isinstance(raw_content, str) and raw_content.strip() else None

    return TurnRecord(
        hour=hour,
        agent_id=agent_id,
        agent_name=agent_name,
        provider=provider,
        model_id=model_id,
        hunger=hunger,
        bush_berries=bush_berries,
        neighbours=neighbours,
        heard=heard,
        reasoning=reasoning,
        said_aloud=said,
        tool_calls=tool_calls,
        misread=misread,
        error=error,
    )
