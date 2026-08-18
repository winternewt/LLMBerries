"""Collects turn records during a game and seals them into a chronicle.

Agents hand their turns here as they take them; deaths come off the event bus, so
they are recorded whether or not an agent was awake to notice. Nothing in here
changes game state — the chronicler only watches.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from core.enums import EventType
from core.game_engine import GameEngine
from entities.chronicle import AgentSummary, Death, GameChronicle, TurnRecord
from entities.events import GameEvent

logger = logging.getLogger(__name__)


class Chronicler:
    """Watches one game and produces its `GameChronicle`."""

    def __init__(self, engine: GameEngine) -> None:
        self.engine: GameEngine = engine
        self.turns: List[TurnRecord] = []
        self.deaths: List[Death] = []
        self._providers: Dict[int, str] = {}
        engine.event_bus.subscribe_to_type(EventType.AGENT_DIED, self._on_death)

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
            )
            for agent in state.agents
        )

        survivors = [agent for agent in state.agents if agent.alive]
        return GameChronicle(
            agent_count=state.agent_count,
            hours_played=state.world_time,
            turns=tuple(self.turns),
            deaths=tuple(self.deaths),
            agents=summaries,
            berries_left=state.bush.current_berries,
            winner=survivors[0].name if len(survivors) == 1 else None,
        )


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
    tool_calls: tuple = (),
    turn_lost: bool = False,
    error: Optional[str] = None,
) -> TurnRecord:
    """Build a `TurnRecord`, pulling reasoning off an Agno run output when there is one.

    `reasoning` stays None when the provider returned nothing — an absent trace is
    not the same as an agent that reasoned about nothing.
    """
    reasoning: Optional[str] = None
    said: Optional[str] = None

    if output is not None:
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
        turn_lost=turn_lost,
        error=error,
    )
