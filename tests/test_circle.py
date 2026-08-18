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
from entities.character import distant_agent_ids, left_neighbor_id, right_neighbor_id
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
        reachable = {left_neighbor_id(agent_id, total), right_neighbor_id(agent_id, total)}
        distant = set(distant_agent_ids(agent_id, total))

        assert reachable & distant == set(), "no agent is both a neighbour and distant"
        assert reachable | distant | {agent_id} == set(range(total)), (
            "every other agent is either reachable or visible-only"
        )
        assert len(distant) == total - 3


def test_three_agent_circle_collapses_visibility_into_reachability() -> None:
    """The property the original 3-agent design leaned on, stated explicitly."""
    for agent_id in range(3):
        assert distant_agent_ids(agent_id, 3) == ()


@pytest.mark.parametrize("total", [3, 5])
def test_message_direction_matches_the_seating_helpers(total: int) -> None:
    for sender in range(total):
        recipient = left_neighbor_id(sender, total)
        message = NeighborMessage(
            from_agent_id=sender,
            to_agent_id=recipient,
            content="hello",
            sender_type=BodyType.ANDROID,
            game_time_sent=0,
        )
        # The sender sits on the recipient's right: left = (id + 1) % n, so the agent
        # whose left neighbour is the recipient is the recipient's right neighbour.
        assert message.direction_from_recipient(total) == "right"
        assert "on your right says" in message.format_for_recipient(total).content


def test_message_from_across_the_circle_is_labelled_across() -> None:
    message = NeighborMessage(
        from_agent_id=2,
        to_agent_id=0,
        content="hello",
        sender_type=BodyType.HUMAN,
        game_time_sent=0,
    )
    assert message.direction_from_recipient(5) == "across"


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


@pytest.mark.parametrize("total", [3, 5, 7])
def test_observation_sees_two_neighbours_and_the_rest_at_a_distance(total: int) -> None:
    engine = GameEngine.create_new_game(agent_names=names(total))
    state = engine.current_state

    for agent_id in range(total):
        observation = AgentObservation.from_state(state, agent_id)
        assert len(observation.distant) == total - 3
        assert observation.agent_name == state.agents[agent_id].name


def test_distant_agents_are_named_in_the_prompt_only_when_they_exist() -> None:
    three = AgentObservation.from_state(
        GameEngine.create_new_game(agent_names=names(3)).current_state, 0
    )
    five = AgentObservation.from_state(
        GameEngine.create_new_game(agent_names=names(5)).current_state, 0
    )

    assert "Across the circle" not in three.format_prompt()
    assert "Across the circle" in five.format_prompt()


def test_observation_reports_a_left_neighbour_speaking_to_you() -> None:
    """Regression: the left/right speech mapping used to be inverted.

    A left neighbour reaches the observer through their *right* message, because
    seating is left = (id + 1) % n.
    """
    engine = GameEngine.create_new_game(agent_names=names(5))
    state = engine.current_state

    observer_id = 0
    left_id = left_neighbor_id(observer_id, state.agent_count)
    state = state.with_agent(left_id, right_message="psst")

    observation = AgentObservation.from_state(state, observer_id)
    assert observation.leftie.spoke_to_you is True
    assert observation.leftie.spoke_to_left is False


def test_observation_reports_a_right_neighbour_speaking_to_you() -> None:
    engine = GameEngine.create_new_game(agent_names=names(5))
    state = engine.current_state

    observer_id = 0
    right_id = right_neighbor_id(observer_id, state.agent_count)
    state = state.with_agent(right_id, left_message="psst")

    observation = AgentObservation.from_state(state, observer_id)
    assert observation.rightie.spoke_to_you is True
    assert observation.rightie.spoke_to_right is False
