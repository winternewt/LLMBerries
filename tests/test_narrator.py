"""Tests for the chronicle and the deterministic half of the narrator.

The model-facing half is not tested here — what can be pinned down is that the
record is complete, that reasoning is never invented, and that the transcript the
narrator reads actually contains what the agents did.
"""

from pathlib import Path
from typing import List

import pytest

from core.agent import Agent, ScriptedAgent
from core.chronicler import Chronicler, load_chronicle, save_chronicle, turn_from_run
from core.game_engine import GameEngine
from core.narrator import (
    chapter_transcript,
    render_transcript,
    split_into_chapters,
)
from entities.chronicle import Death, GameChronicle, ToolCall, TurnRecord


def play(agent_count: int = 3, max_hours: int = 200) -> GameChronicle:
    engine = GameEngine.create_new_game(
        agent_names=[f"Agent{i}" for i in range(agent_count)]
    )
    chronicler = Chronicler(engine)
    seats: List[Agent] = [
        ScriptedAgent(agent_id=i, engine=engine, chronicler=chronicler)
        for i in range(agent_count)
    ]
    for seat in seats:
        engine.decision_callbacks[seat.agent_id] = seat.decision_callback

    hours = 0
    while hours < max_hours and engine.run_turn_cycle():
        hours += 1
    return chronicler.seal()


def make_turn(hour: int, agent_id: int = 0, **kwargs: object) -> TurnRecord:
    defaults = dict(
        hour=hour,
        agent_id=agent_id,
        agent_name=f"Agent{agent_id}",
        hunger=12.0,
        bush_berries=10,
    )
    defaults.update(kwargs)
    return TurnRecord(**defaults)


def test_a_chronicle_covers_every_turn_that_was_taken() -> None:
    chronicle = play()

    assert chronicle.turns, "a played game must leave turns behind"
    for summary in chronicle.agents:
        recorded = [t for t in chronicle.turns if t.agent_id == summary.agent_id]
        assert len(recorded) == summary.turns_taken, (
            "the per-agent turn count must match the turns actually recorded"
        )


def test_deaths_are_recorded_from_the_event_bus() -> None:
    chronicle = play()

    dead = {summary.agent_id for summary in chronicle.agents if not summary.survived}
    assert {death.agent_id for death in chronicle.deaths} == dead
    for death in chronicle.deaths:
        summary = next(s for s in chronicle.agents if s.agent_id == death.agent_id)
        assert summary.died_at_hour == death.hour


def test_scripted_turns_carry_no_reasoning_rather_than_empty_reasoning() -> None:
    """An absent trace must stay absent: None, never "" standing in for a thought."""
    chronicle = play()

    assert chronicle.has_reasoning() is False
    assert all(turn.reasoning is None for turn in chronicle.turns)
    assert all(turn.provider is None for turn in chronicle.turns)


def test_turn_from_run_keeps_blank_reasoning_as_none() -> None:
    class FakeOutput:
        reasoning_content = "   "
        content = "did the thing"

    turn = turn_from_run(
        hour=1,
        agent_id=0,
        agent_name="Agent0",
        hunger=10.0,
        bush_berries=5,
        neighbours=(),
        heard=(),
        output=FakeOutput(),
    )

    assert turn.reasoning is None, "whitespace is not a reasoning trace"
    assert turn.said_aloud == "did the thing"


def test_turn_from_run_captures_reasoning_when_the_provider_returns_one() -> None:
    class FakeOutput:
        reasoning_content = "They look fed. I can wait."
        content = "Waited."

    turn = turn_from_run(
        hour=1,
        agent_id=0,
        agent_name="Agent0",
        hunger=10.0,
        bush_berries=5,
        neighbours=(),
        heard=(),
        provider="groq",
        output=FakeOutput(),
    )

    assert turn.reasoning == "They look fed. I can wait."
    assert turn.provider == "groq"


def test_tool_calls_expose_what_the_agent_took_and_said() -> None:
    turn = make_turn(
        3,
        tool_calls=(
            ToolCall(name="eat_berries", args={"count": "3"}),
            ToolCall(name="speak_to_left", args={"content": "share with me"}),
            ToolCall(name="eat_berries", args={"count": "2"}, failed=True),
        ),
    )

    assert turn.berries_taken() == 3, "a failed call did not take berries"
    assert turn.spoke_to() == ("left: share with me",)


def test_transcript_contains_the_reasoning_and_the_actions() -> None:
    chronicle = GameChronicle(
        agent_count=3,
        hours_played=1,
        turns=(
            make_turn(
                0,
                provider="groq",
                reasoning="Both look fed, so I can take four.",
                tool_calls=(ToolCall(name="eat_berries", args={"count": "4"}),),
                heard=("- Hour 0: your left neighbor says: leave some",),
            ),
        ),
        agents=(),
        berries_left=6.0,
    )

    text = render_transcript(chronicle)

    assert "Both look fed, so I can take four." in text
    assert "eat_berries(count='4')" in text
    assert "leave some" in text


def test_transcript_marks_a_lost_turn_rather_than_dropping_it() -> None:
    chronicle = GameChronicle(
        agent_count=3,
        hours_played=1,
        turns=(make_turn(0, provider="cerebras", turn_lost=True, error="402 payment required"),),
        agents=(),
        berries_left=1.0,
    )

    text = render_transcript(chronicle)

    assert "TURN LOST" in text
    assert "402 payment required" in text


def test_chapters_break_at_deaths() -> None:
    chronicle = GameChronicle(
        agent_count=3,
        hours_played=20,
        turns=tuple(make_turn(hour) for hour in range(21)),
        deaths=(Death(hour=5, agent_id=1, agent_name="Agent1", berries_eaten=7),),
        agents=(),
        berries_left=0.0,
    )

    chapters = split_into_chapters(chronicle, hours_per_chapter=8)

    assert chapters[0] == (0, 5), "the chapter must end on the death"
    assert chapters[1][0] == 6, "the next chapter picks up after it"


def test_chapters_cover_every_hour_exactly_once() -> None:
    chronicle = GameChronicle(
        agent_count=3,
        hours_played=17,
        turns=tuple(make_turn(hour) for hour in range(18)),
        deaths=(
            Death(hour=4, agent_id=1, agent_name="Agent1", berries_eaten=3),
            Death(hour=11, agent_id=2, agent_name="Agent2", berries_eaten=9),
        ),
        agents=(),
        berries_left=0.0,
    )

    chapters = split_into_chapters(chronicle, hours_per_chapter=6)
    covered = [hour for start, end in chapters for hour in range(start, end + 1)]

    assert covered == list(range(18)), "no hour may be skipped or narrated twice"


def test_chapter_transcript_holds_only_its_own_hours() -> None:
    chronicle = play()
    chapters = split_into_chapters(chronicle, hours_per_chapter=4)
    start, end = chapters[0]

    text = chapter_transcript(chronicle, start, end)

    assert f"[Hour {start}]" in text
    assert f"[Hour {end + 1}]" not in text


def test_a_chronicle_survives_a_round_trip_through_json(tmp_path: Path) -> None:
    chronicle = play()
    path = save_chronicle(chronicle, tmp_path / "run.json")

    assert load_chronicle(path) == chronicle


def test_an_empty_game_has_no_chapters() -> None:
    empty = GameChronicle(agent_count=3, hours_played=0, agents=(), berries_left=40.0)

    assert split_into_chapters(empty) == ()
    assert empty.has_reasoning() is False


@pytest.mark.parametrize("agent_count", [3, 5])
def test_transcript_records_distant_agents_for_larger_circles(agent_count: int) -> None:
    chronicle = play(agent_count=agent_count, max_hours=3)
    first_turn = chronicle.turns[0]

    assert len(first_turn.neighbours) == 2, (
        "scripted turns record the two neighbours; distant agents belong to LLM turns"
    )
    assert render_transcript(chronicle).startswith(f"{agent_count} agents")
