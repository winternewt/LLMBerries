"""Tests for the seating circle: neighbours, reachability, visibility, and N > 3.

Three agents is the degenerate case the game shipped with — everyone is a neighbour,
so visibility and reachability coincide and a direction mix-up is invisible. These
tests use both 3 and larger circles, where the two come apart.
"""

from typing import List

import pytest

from core.constants import MIN_AGENT_COUNT
from core.enums import BodyType
from core.game_engine import GameEngine
from core.enums import MessageDirection
from entities.character import (
    distant_agent_ids,
    left_neighbor_id,
    reachable_seats,
    right_neighbor_id,
    seat_at,
)
from entities.message import NeighborMessage
from entities.observations import AgentObservation


def names(count: int) -> List[str]:
    return [f"Agent{i}" for i in range(count)]


@pytest.mark.parametrize("total", [3, 4, 5, 8])
def test_every_agent_has_two_distinct_neighbours(total: int) -> None:
    for agent_id in range(total):
        left = left_neighbor_id(agent_id, total)
        right = right_neighbor_id(agent_id, total)
        assert left != agent_id and right != agent_id
        assert left != right, "a circle must not seat an agent next to itself twice"


@pytest.mark.parametrize("total", [3, 4, 5, 8])
def test_seating_is_symmetric(total: int) -> None:
    """If B is A's left neighbour, A must be B's right neighbour."""
    for agent_id in range(total):
        left = left_neighbor_id(agent_id, total)
        assert right_neighbor_id(left, total) == agent_id


@pytest.mark.parametrize("total", [3, 4, 5, 8])
def test_reachable_and_visible_partition_the_circle(total: int) -> None:
    for agent_id in range(total):
        reachable = set(reachable_seats(agent_id, total).values())
        distant = set(distant_agent_ids(agent_id, total))

        assert reachable & distant == set(), "no agent is both reachable and distant"
        assert reachable | distant | {agent_id} == set(range(total)), (
            "every other agent is either reachable or visible-only"
        )
        assert agent_id not in reachable, "an agent cannot speak to itself"


@pytest.mark.parametrize("total,expected", [(3, 2), (4, 3), (5, 4), (8, 4)])
def test_reach_covers_two_seats_each_way(total: int, expected: int) -> None:
    """Voices carry two seats, so nobody is cut off by one death."""
    for agent_id in range(total):
        seats = reachable_seats(agent_id, total)
        assert len(seats) == expected
        for direction, seat_id in seats.items():
            assert seat_at(agent_id, direction.offset, total) == seat_id


def test_small_circles_drop_directions_that_alias_a_nearer_seat() -> None:
    """In a 3-circle both far directions land on the neighbours; they must not double up."""
    assert set(reachable_seats(0, 3)) == {MessageDirection.LEFT, MessageDirection.RIGHT}
    assert set(reachable_seats(0, 4)) == {
        MessageDirection.LEFT,
        MessageDirection.RIGHT,
        MessageDirection.LEFT_FAR,
    }


@pytest.mark.parametrize("total", [3, 4, 5])
def test_circles_of_five_or_fewer_are_wholly_within_reach(total: int) -> None:
    """With reach 2 each way, everyone is addressable up to five seats."""
    for agent_id in range(total):
        assert distant_agent_ids(agent_id, total) == ()


@pytest.mark.parametrize("direction", list(MessageDirection))
def test_every_direction_has_a_consistent_opposite(direction: MessageDirection) -> None:
    """If I speak left_far to you, you hear me from two seats to your right."""
    total = 7
    speaker = 0
    listener = seat_at(speaker, direction.offset, total)

    assert seat_at(listener, direction.opposite.offset, total) == speaker
    assert direction.opposite.opposite is direction


@pytest.mark.parametrize("total", [3, 4, 6])
def test_engine_builds_a_circle_of_any_supported_size(total: int) -> None:
    engine = GameEngine.create_new_game(agent_names=names(total))

    state = engine.current_state
    assert state.agent_count == total
    assert len(state.agents) == len(state.agent_memories) == total
    assert [agent.agent_id for agent in state.agents] == list(range(total))


def test_engine_refuses_a_circle_that_is_too_small() -> None:
    with pytest.raises(ValueError, match=f"at least {MIN_AGENT_COUNT} agents"):
        GameEngine.create_new_game(agent_names=names(MIN_AGENT_COUNT - 1))


def test_perceived_types_must_match_the_number_of_agents() -> None:
    with pytest.raises(ValueError, match="perceived types"):
        GameEngine.create_new_game(
            agent_names=names(4), perceived_types=[BodyType.HUMAN, BodyType.ANDROID]
        )


@pytest.mark.parametrize("total,expected_reachable", [(3, 2), (5, 4), (7, 4)])
def test_observation_splits_seats_into_reachable_and_merely_visible(
    total: int, expected_reachable: int
) -> None:
    engine = GameEngine.create_new_game(agent_names=names(total))
    state = engine.current_state

    for agent_id in range(total):
        observation = AgentObservation.from_state(state, agent_id)
        assert len(observation.reachable) == expected_reachable
        assert len(observation.distant) == total - 1 - expected_reachable
        assert len(observation.seats) == total - 1, "every other seat is observed"
        assert observation.agent_name == state.agents[agent_id].name


def test_distant_agents_are_named_in_the_prompt_only_when_they_exist() -> None:
    five = AgentObservation.from_state(
        GameEngine.create_new_game(agent_names=names(5)).current_state, 0
    )
    seven = AgentObservation.from_state(
        GameEngine.create_new_game(agent_names=names(7)).current_state, 0
    )

    assert "Further round the circle" not in five.format_prompt(), (
        "a 5-circle is wholly within reach"
    )
    assert "Further round the circle" in seven.format_prompt()
    assert "Within earshot" in five.format_prompt()


@pytest.mark.parametrize("direction", list(MessageDirection))
def test_observation_reports_who_addressed_you(direction: MessageDirection) -> None:
    """Regression: the left/right speech mapping used to be inverted.

    A left neighbour reaches the observer through their *right* direction, because
    seating is left = (id + 1) % n. Derived now, so it cannot drift again.
    """
    engine = GameEngine.create_new_game(agent_names=names(7))
    state = engine.current_state
    observer_id = 0

    speaker_id = seat_at(observer_id, direction.opposite.offset, state.agent_count)
    speaker = state.agents[speaker_id].with_message(direction, "psst")
    state = state.with_agent(speaker_id, pending_messages=speaker.pending_messages)

    observation = AgentObservation.from_state(state, observer_id)
    seen = next(seat for seat in observation.seats if seat.seat_id == speaker_id)

    assert seen.spoke_to_you is True
    assert seen.spoke_to_others is False


def test_observation_separates_talking_to_you_from_talking_at_all() -> None:
    engine = GameEngine.create_new_game(agent_names=names(7))
    state = engine.current_state
    observer_id = 0

    # Agent 1 is the observer's left neighbour; it speaks away from the observer.
    speaker = state.agents[1].with_message(MessageDirection.LEFT, "not for you")
    state = state.with_agent(1, pending_messages=speaker.pending_messages)

    seen = next(
        seat
        for seat in AgentObservation.from_state(state, observer_id).seats
        if seat.seat_id == 1
    )
    assert seen.spoke_to_you is False
    assert seen.spoke_to_others is True
