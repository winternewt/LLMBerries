"""End-to-end turn cycle with scripted agents — no API calls, no mocks.

The scripted agent exists for exactly this: the real engine, real commands and real
state transitions, driven by a decision rule instead of a model.
"""

from typing import List

import pytest

from core.agent import Agent, ScriptedAgent
from core.constants import BUSH_REGENERATION_RATE, MAX_BERRIES, STARTING_BERRIES
from core.enums import BodyState, EventType
from core.game_engine import GameEngine


def play(agent_count: int = 3, max_hours: int = 200, **agent_kwargs: object) -> GameEngine:
    engine = GameEngine.create_new_game(
        agent_names=[f"Agent{i}" for i in range(agent_count)]
    )
    seats: List[Agent] = [
        ScriptedAgent(agent_id=i, engine=engine, **agent_kwargs) for i in range(agent_count)
    ]
    for seat in seats:
        engine.decision_callbacks[seat.agent_id] = seat.decision_callback

    hours = 0
    while hours < max_hours and engine.run_turn_cycle():
        hours += 1
    return engine


def test_a_scripted_game_reaches_game_over() -> None:
    engine = play()

    assert engine.game_over is True, "three agents cannot all survive a bush this slow"
    alive = [agent for agent in engine.current_state.agents if agent.alive]
    assert len(alive) <= 1, "the game ends when at most one agent is left"


def test_agents_actually_act_rather_than_passing_the_turn() -> None:
    """Regression: Phase 6 used to end every turn without consulting an agent."""
    engine = play()

    eaten = [e for e in engine.events if e.event_type == EventType.BERRIES_EATEN]
    slept = [e for e in engine.events if e.event_type == EventType.SLEEP_DURATION_SET]

    assert eaten, "scripted agents eat when hungry, so the run must contain meals"
    assert slept, "scripted agents choose a sleep duration every turn"
    assert sum(a.total_berries_consumed for a in engine.current_state.agents) == sum(
        int(e.data["berries_eaten"]) for e in eaten
    ), "consumption recorded on agents must match the berries the events report"


def test_berries_are_conserved_across_the_game() -> None:
    """Berries eaten plus berries left must equal what the bush ever held."""
    engine = play()
    state = engine.current_state

    eaten = sum(agent.total_berries_consumed for agent in state.agents)
    regrown = sum(
        float(event.data["regenerated"])
        for event in engine.events
        if event.event_type == EventType.BUSH_REGENERATED
    )
    remaining = state.bush.current_berries

    assert remaining + eaten == pytest.approx(STARTING_BERRIES + regrown, abs=0.01)
    assert 0 <= remaining <= MAX_BERRIES


def test_the_bush_never_regrows_past_its_maximum() -> None:
    engine = play(agent_count=3, max_hours=30)

    for event in engine.events:
        if event.event_type == EventType.BUSH_REGENERATED:
            assert float(event.data["berries_after"]) <= MAX_BERRIES + 1e-9

    assert BUSH_REGENERATION_RATE > 0


def test_dead_agents_stay_dead_and_stop_acting() -> None:
    engine = play()

    dead_ids = {
        agent.agent_id for agent in engine.current_state.agents if not agent.alive
    }
    assert dead_ids, "a scripted game starves someone"

    for agent in engine.current_state.agents:
        if not agent.alive:
            assert agent.body_state == BodyState.DEAD
            assert agent.time_of_death is not None, "a death must record when it happened"

    deaths = [e for e in engine.events if e.event_type == EventType.AGENT_DIED]
    assert {e.agent_id for e in deaths} == dead_ids
    assert len(deaths) == len(dead_ids), "each agent may only die once"


def test_replay_reproduces_the_same_final_state() -> None:
    engine = play()
    replayed = engine.replay()

    original = engine.current_state
    result = replayed.current_state

    assert result.world_time == original.world_time
    assert [(a.name, a.hunger, a.alive) for a in result.agents] == [
        (a.name, a.hunger, a.alive) for a in original.agents
    ]
    assert result.bush.current_berries == pytest.approx(original.bush.current_berries)


def test_a_branch_diverges_without_touching_the_original() -> None:
    engine = play()
    original_final = engine.current_state

    branch_turn = min(5, len(engine.history) - 1)
    branch = engine.branch_from(branch_turn)

    assert branch.current_state.world_time <= original_final.world_time
    assert len(branch.history) <= len(engine.history)
    assert engine.current_state is original_final, "branching must not rewind the original"


@pytest.mark.parametrize("agent_count", [3, 4, 6])
def test_larger_circles_play_through(agent_count: int) -> None:
    engine = play(agent_count=agent_count)

    assert engine.current_state.agent_count == agent_count
    assert engine.game_over is True
    assert len(engine.history) > agent_count, "every agent takes turns"
