"""Two rules that only matter once agents start dying or start cooperating.

Reach: a voice carries two seats, so losing a neighbour does not cut an agent out
of the conversation. In a 5-circle with two adjacent deaths that was exactly the
hole — the survivor could see everyone and talk to no one.

Equilibrium: a circle that holds its demand within what the bush regrows, for
`EQUILIBRIUM_WINDOW_HOURS` hours running, ends the game level instead of playing on
until somebody slips.
"""

from typing import List

import pytest

from core.agent import Agent, ScriptedAgent
from core.commands import FinishTurnCommand, SpeakCommand
from core.constants import BUSH_REGENERATION_RATE, EQUILIBRIUM_WINDOW_HOURS, MAX_HUNGER
from core.enums import BodyState, EventType, GameOutcome, MessageDirection
from core.game_engine import GameEngine
from entities.character import reachable_seats, seat_at
from entities.observations import AgentObservation


def new_game(count: int = 5) -> GameEngine:
    return GameEngine.create_new_game(agent_names=[f"Agent{i}" for i in range(count)])


def kill(engine: GameEngine, agent_id: int) -> None:
    engine.current_state = engine.current_state.with_agent(
        agent_id, alive=False, body_state=BodyState.DEAD, time_of_death=0.0, wake_time=None
    )


def wake(engine: GameEngine, agent_id: int) -> None:
    engine.current_state = engine.current_state.with_agent(
        agent_id, body_state=BodyState.AWAKE
    )


# ----------------------------------------------------------------------------
# Reach over the dead
# ----------------------------------------------------------------------------


def test_both_neighbours_dead_still_leaves_someone_to_talk_to() -> None:
    """The 2-of-5 case: adjacent deaths used to leave a survivor with no listener."""
    engine = new_game(5)
    observer = 0
    left = seat_at(observer, 1, 5)
    right = seat_at(observer, -1, 5)
    kill(engine, left)
    kill(engine, right)
    wake(engine, observer)

    observation = AgentObservation.from_state(engine.current_state, observer)

    assert len(observation.reachable) == 4, "reach does not shrink when neighbours die"
    assert {seat.seat_id for seat in observation.reachable} >= {
        seat_at(observer, 2, 5),
        seat_at(observer, -2, 5),
    }, "the seats beyond the bodies are still addressable"

    # The bodies stay in the circle. A dead neighbour is something the survivor can
    # see and reason about, not an empty seat — removing it would quietly rewrite
    # the geometry mid-game.
    dead_seen = [seat for seat in observation.seats if seat.seat_id in (left, right)]
    assert len(dead_seen) == 2, "dead agents remain visible in their seats"
    assert all(seat.reachable for seat in dead_seen), (
        "a body is still within earshot; it simply does not answer"
    )
    assert "make yourself heard" in observation.format_prompt()


def test_a_message_reaches_over_a_dead_neighbour() -> None:
    engine = new_game(5)
    speaker = 0
    blocked = seat_at(speaker, 1, 5)
    target = seat_at(speaker, 2, 5)
    kill(engine, blocked)
    wake(engine, speaker)

    engine.execute_command(
        SpeakCommand(
            agent_id=speaker, direction=MessageDirection.LEFT_FAR, content="still here?"
        )
    )
    engine.execute_command(FinishTurnCommand(agent_id=speaker))

    heard = [m.content for m in engine.current_state.agent_memories[target].messages]
    assert any("still here?" in line for line in heard), "the far seat must hear it"
    assert engine.current_state.agent_memories[blocked].messages == (), "the dead hear nothing"


def test_speaking_to_a_dead_seat_is_reported_not_silently_dropped() -> None:
    """Silence from a corpse must not look like a neighbour choosing not to answer."""
    engine = new_game(5)
    speaker = 0
    dead = seat_at(speaker, 1, 5)
    kill(engine, dead)
    wake(engine, speaker)

    engine.execute_command(
        SpeakCommand(agent_id=speaker, direction=MessageDirection.LEFT, content="hello?")
    )
    events = engine.execute_command(FinishTurnCommand(agent_id=speaker))

    undelivered = [e for e in events if e.event_type == EventType.MESSAGE_UNDELIVERED]
    assert len(undelivered) == 1
    assert undelivered[0].data["reason"] == "recipient_dead"


def test_a_direction_that_does_not_exist_is_refused_with_the_reachable_set() -> None:
    engine = new_game(3)
    wake(engine, 0)

    events = engine.execute_command(
        SpeakCommand(agent_id=0, direction=MessageDirection.LEFT_FAR, content="anyone?")
    )

    assert events[0].event_type == EventType.COMMAND_FAILED
    assert events[0].data["reason"] == "no_such_seat"
    assert "left, right" in events[0].message, "the refusal names what it could have said"


def test_speaking_twice_in_one_direction_delivers_both_in_order() -> None:
    """A live run had a model send a proposal and then a rewording of it to the same
    neighbour. The first was dropped and the model was told both had been sent, so
    neither side of the ring could see the loss. Everything said is delivered."""
    engine = new_game(5)
    wake(engine, 0)

    engine.execute_command(
        SpeakCommand(agent_id=0, direction=MessageDirection.LEFT, content="first")
    )
    engine.execute_command(
        SpeakCommand(agent_id=0, direction=MessageDirection.LEFT, content="second")
    )
    engine.execute_command(FinishTurnCommand(agent_id=0))

    heard = [m.content for m in engine.current_state.agent_memories[1].messages]
    assert len(heard) == 2
    assert "first" in heard[0], "spoken order is kept; a correction follows what it corrects"
    assert "second" in heard[1]


def test_words_to_different_seats_stay_grouped_by_seat() -> None:
    """Dispatch order is fixed by direction, never by the order the tools happened
    to fire, so what a listener reads does not depend on the model's call order."""
    engine = new_game(5)
    wake(engine, 0)

    for content, direction in (
        ("right one", MessageDirection.RIGHT),
        ("left one", MessageDirection.LEFT),
        ("right two", MessageDirection.RIGHT),
    ):
        engine.execute_command(
            SpeakCommand(agent_id=0, direction=direction, content=content)
        )
    engine.execute_command(FinishTurnCommand(agent_id=0))

    to_the_left = [m.content for m in engine.current_state.agent_memories[1].messages]
    to_the_right = [m.content for m in engine.current_state.agent_memories[4].messages]

    assert len(to_the_left) == 1 and "left one" in to_the_left[0]
    assert len(to_the_right) == 2
    assert "right one" in to_the_right[0] and "right two" in to_the_right[1]


def test_a_listener_is_told_which_side_the_voice_came_from() -> None:
    engine = new_game(7)
    speaker = 0
    wake(engine, speaker)

    for direction in reachable_seats(speaker, 7):
        engine.execute_command(
            SpeakCommand(agent_id=speaker, direction=direction, content=f"via {direction.value}")
        )
    engine.execute_command(FinishTurnCommand(agent_id=speaker))

    for direction, target in reachable_seats(speaker, 7).items():
        heard = " ".join(m.content for m in engine.current_state.agent_memories[target].messages)
        assert direction.label in heard, (
            f"a listener addressed {direction.value} must hear it from {direction.label}"
        )


def test_tools_offered_match_the_seats_that_exist() -> None:
    for count, expected in ((3, 2), (5, 4)):
        engine = new_game(count)
        agent = ScriptedAgent(agent_id=0, engine=engine)
        speaking = [t.__name__ for t in agent.tools() if t.__name__.startswith("speak_")]
        assert len(speaking) == expected, (
            "a model must not be handed a direction that can only fail"
        )


# ----------------------------------------------------------------------------
# Equilibrium
# ----------------------------------------------------------------------------


def test_a_circle_living_within_the_bush_ties() -> None:
    """Two agents asleep 8 hours each burn 0.65/hour apiece — 1.3 between them.

    The shipped bush regrows 1.05/hour, so that pair is *not* sustainable and the
    game plays on; see ROADMAP. Here the bush is given a rate that can carry them,
    which is what the equilibrium rule is about — the rule, not the balance.
    """
    engine = new_game(3)
    kill(engine, 2)
    engine.current_state = engine.current_state.model_copy(
        update={"bush": engine.current_state.bush.model_copy(update={"regeneration_rate": 1.5})}
    )

    seats: List[Agent] = [
        ScriptedAgent(agent_id=i, engine=engine, eat_below_hunger=4.0, sleep_hours=8)
        for i in range(2)
    ]
    for seat in seats:
        engine.decision_callbacks[seat.agent_id] = seat.decision_callback

    hours = 0
    while hours < 60 and engine.run_turn_cycle():
        hours += 1

    assert engine.outcome == GameOutcome.EQUILIBRIUM
    assert engine.game_over is True
    assert len([a for a in engine.current_state.agents if a.alive]) == 2
    assert engine.winner is None, "a tie has no winner"


def test_equilibrium_needs_the_whole_window_not_one_quiet_hour() -> None:
    engine = new_game(3)
    engine.hourly_demand = [0.1] * (EQUILIBRIUM_WINDOW_HOURS - 1)

    assert engine._equilibrium_reached() is False
    assert engine.outcome == GameOutcome.ONGOING


def test_a_hungry_circle_does_not_tie() -> None:
    engine = new_game(3)
    engine.hourly_demand = [BUSH_REGENERATION_RATE + 1.0] * EQUILIBRIUM_WINDOW_HOURS

    assert engine._equilibrium_reached() is False


def test_demand_takes_the_greater_of_hunger_burned_and_berries_eaten() -> None:
    """An hour where nobody ate is not a sustainable hour — life still burned."""
    engine = new_game(3)
    hour = engine.events[:0]  # empty slice, typed as a list of events

    from entities.events import GameEvent

    engine._record_hourly_demand(
        [
            GameEvent(
                sequence_number=0,
                event_type=EventType.HUNGER_DECREASED,
                message="burn",
                data={"hunger_before": 20.0, "hunger_after": 17.0},
            ),
            GameEvent(
                sequence_number=1,
                event_type=EventType.BERRIES_EATEN,
                message="ate",
                data={"berries_eaten": 1},
            ),
        ]
    )

    assert engine.hourly_demand == [3.0], "3 hours of life burned outweighs 1 berry taken"
    assert hour == []


def test_a_lone_survivor_is_last_standing_not_an_equilibrium() -> None:
    engine = new_game(3)
    kill(engine, 1)
    kill(engine, 2)
    engine.hourly_demand = [0.0] * EQUILIBRIUM_WINDOW_HOURS

    assert engine._equilibrium_reached() is False, (
        "one agent left is a survival, and Phase 3 already calls it"
    )


def test_equilibrium_publishes_an_event_a_subscriber_can_see() -> None:
    engine = new_game(3)
    seen = []
    engine.event_bus.subscribe_to_type(
        EventType.EQUILIBRIUM_REACHED, lambda name, event: seen.append(event)
    )
    engine.hourly_demand = [0.5] * EQUILIBRIUM_WINDOW_HOURS

    assert engine._equilibrium_reached() is True
    assert len(seen) == 1
    assert seen[0].data["window_hours"] == EQUILIBRIUM_WINDOW_HOURS
    assert seen[0].data["survivors"] == 3


@pytest.mark.parametrize("outcome", list(GameOutcome))
def test_every_outcome_has_a_distinct_value(outcome: GameOutcome) -> None:
    assert isinstance(outcome.value, str)
    assert sum(1 for other in GameOutcome if other.value == outcome.value) == 1


def test_starvation_still_ends_as_last_standing() -> None:
    engine = new_game(3)
    seats: List[Agent] = [ScriptedAgent(agent_id=i, engine=engine) for i in range(3)]
    for seat in seats:
        engine.decision_callbacks[seat.agent_id] = seat.decision_callback

    hours = 0
    while hours < 200 and engine.run_turn_cycle():
        hours += 1

    assert engine.outcome in (GameOutcome.LAST_STANDING, GameOutcome.EXTINCTION)
    assert MAX_HUNGER > 0


# ----------------------------------------------------------------------------
# The epilogue: one round for whoever is left
# ----------------------------------------------------------------------------


def test_the_epilogue_offers_a_round_to_every_survivor() -> None:
    engine = new_game(3)
    kill(engine, 1)
    kill(engine, 2)
    engine.game_over = True
    engine.outcome = GameOutcome.LAST_STANDING

    reflected: List[int] = []
    for agent_id in range(3):
        engine.reflection_callbacks[agent_id] = (
            lambda aid, obs, eng, outcome: reflected.append(aid)
        )

    assert engine.run_epilogue() == 1
    assert reflected == [0], "only the living look back"


def test_the_epilogue_shows_the_survivor_the_bodies() -> None:
    engine = new_game(5)
    for dead_id in (1, 2, 3, 4):
        kill(engine, dead_id)
    engine.game_over = True
    engine.outcome = GameOutcome.LAST_STANDING

    seen: List[AgentObservation] = []
    engine.reflection_callbacks[0] = lambda aid, obs, eng, outcome: seen.append(obs)
    engine.run_epilogue()

    assert len(seen) == 1
    assert len(seen[0].seats) == 4, "the survivor still sees every seat, occupied or not"
    assert seen[0].reachable, "and can still address the ones within earshot"


def test_the_epilogue_is_told_how_the_game_ended() -> None:
    engine = new_game(3)
    engine.game_over = True
    engine.outcome = GameOutcome.EQUILIBRIUM

    outcomes: List[GameOutcome] = []
    for agent_id in range(3):
        engine.reflection_callbacks[agent_id] = (
            lambda aid, obs, eng, outcome: outcomes.append(outcome)
        )

    assert engine.run_epilogue() == 3, "a tie leaves several survivors to reflect"
    assert outcomes == [GameOutcome.EQUILIBRIUM] * 3


def test_an_extinct_circle_has_nobody_to_reflect() -> None:
    engine = new_game(3)
    for agent_id in range(3):
        kill(engine, agent_id)
        engine.reflection_callbacks[agent_id] = lambda aid, obs, eng, outcome: None
    engine.game_over = True
    engine.outcome = GameOutcome.EXTINCTION

    assert engine.run_epilogue() == 0


def test_the_epilogue_refuses_to_run_while_the_game_is_live() -> None:
    engine = new_game(3)

    with pytest.raises(RuntimeError, match="after the game has ended"):
        engine.run_epilogue()


def test_the_epilogue_changes_no_state() -> None:
    """Nothing is left to decide, so nothing may be decided."""
    engine = new_game(3)
    kill(engine, 1)
    kill(engine, 2)
    engine.game_over = True
    engine.outcome = GameOutcome.LAST_STANDING
    engine.reflection_callbacks[0] = lambda aid, obs, eng, outcome: None

    before = engine.current_state
    commands_before = len(engine.history)
    engine.run_epilogue()

    assert engine.current_state == before
    assert len(engine.history) == commands_before


def test_a_scripted_agent_reflects_by_saying_nothing() -> None:
    """No model, no account — inventing one would put words in its mouth."""
    engine = new_game(3)
    kill(engine, 1)
    kill(engine, 2)
    engine.game_over = True
    engine.outcome = GameOutcome.LAST_STANDING

    from core.chronicler import Chronicler

    chronicler = Chronicler(engine)
    agent = ScriptedAgent(agent_id=0, engine=engine, chronicler=chronicler)
    engine.reflection_callbacks[0] = agent.reflection_callback

    assert engine.run_epilogue() == 1
    assert chronicler.seal().reflections() == ()
