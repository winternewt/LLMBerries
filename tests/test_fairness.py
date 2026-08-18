"""Tests that the ring does not decide the game before anyone acts.

Two confounds were measured in the recorded runs and both are fixed here. The Human
was always seat 0 and seat 0 always acted first, so "the Human survives more" and
"whoever moves first survives more" were the same statement, and only the second one
was true: scripted agents, which cannot perceive anything about each other, still
finished 24/13/11/8/8 berries down a five-seat ring purely from call order.
"""

import collections
import random
from typing import List, Tuple

import pytest

from core.agent import ScriptedAgent
from core.enums import BodyState, BodyType
from core.game_engine import GameEngine

NAMES = ["Alice", "Bob", "Charlie", "Dana", "Eli", "Fen"]


def new_game(count: int) -> GameEngine:
    return GameEngine.create_new_game(agent_names=NAMES[:count])


def human_seat(engine: GameEngine) -> int:
    return next(
        agent.agent_id
        for agent in engine.current_state.agents
        if agent.perceived_type is BodyType.HUMAN
    )


def played(count: int, seed: int) -> Tuple[GameEngine, List[int]]:
    """A full scripted game, plus which seat took the first turn of each hour."""
    random.seed(seed)
    engine = new_game(count)
    leaders: List[int] = []
    seen: set = set()

    for seat_id in range(count):
        inner = ScriptedAgent(agent_id=seat_id, engine=engine).decision_callback

        def callback(agent_id, observation, eng, inner=inner):
            hour = eng.current_state.world_time
            if hour not in seen:
                seen.add(hour)
                leaders.append(agent_id)
            return inner(agent_id, observation, eng)

        engine.decision_callbacks[seat_id] = callback

    hours = 0
    while hours < 200 and engine.run_turn_cycle():
        hours += 1
    return engine, leaders


# ----------------------------------------------------------------------------
# Where the Human sits
# ----------------------------------------------------------------------------


def test_exactly_one_body_reads_as_human() -> None:
    engine = new_game(5)
    types = [agent.perceived_type for agent in engine.current_state.agents]

    assert types.count(BodyType.HUMAN) == 1
    assert types.count(BodyType.ANDROID) == 4


def test_the_human_is_not_always_seat_zero() -> None:
    """Collinear with turn order, the label measured nothing but who moved first."""
    seats = set()
    for seed in range(30):
        random.seed(seed)
        seats.add(human_seat(new_game(5)))

    assert len(seats) > 1, "the Human must move around the ring between runs"
    assert seats <= set(range(5))


def test_the_human_seat_is_reproducible_from_the_seed() -> None:
    random.seed(99)
    first = human_seat(new_game(5))
    random.seed(99)
    second = human_seat(new_game(5))

    assert first == second


def test_an_explicit_seating_is_still_honoured() -> None:
    """A study that wants the Human in a fixed seat may still say so."""
    engine = GameEngine.create_new_game(
        agent_names=NAMES[:3],
        perceived_types=[BodyType.ANDROID, BodyType.ANDROID, BodyType.HUMAN],
    )

    assert human_seat(engine) == 2


# ----------------------------------------------------------------------------
# Who moves first
# ----------------------------------------------------------------------------


def test_first_pick_goes_round_the_ring() -> None:
    """Under seat order this was 33/0/0/0/0 — seat 0 took first pick of every hour."""
    engine, leaders = played(5, seed=0)
    counted = collections.Counter(leaders)

    assert len(counted) == 5, "every seat leads at least one hour"
    assert max(counted.values()) <= 2 * min(counted.values())


def test_no_seat_eats_its_way_down_a_gradient() -> None:
    """Seat order produced a monotonic 24/13/11/8/8. Nothing that clean is a decision."""
    engine, _ = played(5, seed=0)
    eaten = [agent.total_berries_consumed for agent in engine.current_state.agents]

    assert eaten != sorted(eaten, reverse=True), "a falling gradient is the old bug"
    assert max(eaten) < 2 * min(eaten), f"one seat still dominates: {eaten}"


def test_the_order_is_a_rotation_of_the_awake_seats() -> None:
    engine = new_game(5)
    engine.current_state = engine.current_state.model_copy(update={"world_time": 2})
    for seat_id in range(5):
        engine.current_state = engine.current_state.with_agent(
            seat_id, body_state=BodyState.AWAKE
        )

    assert engine._turn_order() == [2, 3, 4, 0, 1]


def test_the_dead_are_not_handed_the_turn() -> None:
    """Rotating over every seat would give survivors uneven shares of first pick."""
    engine = new_game(5)
    engine.current_state = engine.current_state.model_copy(update={"world_time": 1})
    for seat_id in range(5):
        engine.current_state = engine.current_state.with_agent(
            seat_id, body_state=BodyState.AWAKE
        )
    engine.current_state = engine.current_state.with_agent(0, body_state=BodyState.DEAD)

    order = engine._turn_order()

    assert 0 not in order
    assert sorted(order) == [1, 2, 3, 4]
    assert order == [2, 3, 4, 1], "rotation is over the seats that actually act"


def test_an_hour_with_nobody_awake_is_an_empty_order() -> None:
    engine = new_game(3)

    assert engine._turn_order() == [], "everyone starts asleep"


def test_the_same_seed_replays_the_same_order() -> None:
    first = played(4, seed=12)[1]
    second = played(4, seed=12)[1]

    assert first == second
