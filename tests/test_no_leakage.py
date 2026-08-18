"""Nothing a player can read may give away what this is.

The puppeteer notes in CLAUDE.md are the rule; this is the enforcement. Every string
that reaches an LLM — tool names, docstrings, tool return values, the system message,
the waking summary, delivered speech, the epilogue — is scanned for the vocabulary
that would answer the question the experiment is asking them to work out for
themselves.

It also pins the harder rule: silence must be indistinguishable. Speaking to a body
that will never answer must read exactly like speaking to someone who chose not to.
"""

import re
from typing import List

import pytest

from core.agent import Agent, LLMAgent, ScriptedAgent
from core.commands import FinishTurnCommand, SpeakCommand
from core.enums import BodyState, MessageDirection
from core.game_engine import GameEngine
from entities.llm_configs import GOOGLE
from entities.observations import AgentObservation

# Words that could only have been written by whoever built the ring.
BANNED = (
    "game", "player", "agent", "simulation", "simulated", "scenario", "experiment",
    "npc", "turn", "round", "llm", "prompt", "token", "reward", "score",
    "algorithm", "system message", "instructions",
)

NAMES = ["Alice", "Bob", "Charlie", "Dana", "Eli"]


@pytest.fixture(autouse=True)
def fake_google_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A key is needed to build a model object; no call is ever made."""
    monkeypatch.setenv(GOOGLE.env_var, "not-a-real-key")


def leaks(text: str) -> List[str]:
    """Banned words present in `text`, matched whole and case-insensitively."""
    lowered = text.lower()
    return [word for word in BANNED if re.search(rf"\b{re.escape(word)}\b", lowered)]


def new_game(count: int = 5) -> GameEngine:
    return GameEngine.create_new_game(agent_names=NAMES[:count])


def wake(engine: GameEngine, agent_id: int) -> None:
    engine.current_state = engine.current_state.with_agent(
        agent_id, body_state=BodyState.AWAKE
    )


def kill(engine: GameEngine, agent_id: int) -> None:
    engine.current_state = engine.current_state.with_agent(
        agent_id, alive=False, body_state=BodyState.DEAD, time_of_death=1.0, wake_time=None
    )


def llm_agent(engine: GameEngine, agent_id: int = 0) -> LLMAgent:
    return LLMAgent(agent_id=agent_id, engine=engine, provider=GOOGLE)


# ----------------------------------------------------------------------------
# Vocabulary
# ----------------------------------------------------------------------------


def test_the_tool_summary_says_nothing_about_what_this_is() -> None:
    assert leaks(Agent.TOOLS_DESCRIPTION) == []


def test_every_tool_name_and_docstring_stays_in_character() -> None:
    engine = new_game()
    agent = ScriptedAgent(agent_id=0, engine=engine)

    for tool in agent.tools():
        assert leaks(tool.__name__) == [], f"{tool.__name__} names the machinery"
        assert tool.__doc__, f"{tool.__name__} has no docstring, so the model gets nothing"
        assert leaks(tool.__doc__) == [], f"{tool.__name__} docstring leaks"


def test_what_the_tools_answer_stays_in_character() -> None:
    engine = new_game()
    wake(engine, 0)
    agent = ScriptedAgent(agent_id=0, engine=engine)

    answers = [
        agent.think("they are all still"),
        agent.speak_to_left("leave me two"),
        agent.speak_to_right_far("are you awake?"),
        agent.eat_berries(2),
        agent.choose_sleep_duration(3),
    ]

    for answer in answers:
        assert leaks(answer) == [], f"tool answered with machinery: {answer!r}"


def test_the_situation_they_are_shown_stays_in_character() -> None:
    engine = new_game(5)
    observation = AgentObservation.from_state(engine.current_state, 0)

    text = observation.format_prompt()
    assert leaks(text) == []
    assert "berries" in text, "they are still told what they can see"


def test_what_they_are_told_they_are_stays_in_character() -> None:
    engine = new_game()
    agent = llm_agent(engine)
    observation = AgentObservation.from_state(engine.current_state, 0)

    assert leaks(agent._system_message(observation)) == []


def test_waking_to_nothing_stays_in_character() -> None:
    engine = new_game()
    agent = llm_agent(engine)

    assert leaks(agent._pending_messages()) == []


def test_speech_arrives_without_naming_the_machinery() -> None:
    engine = new_game(5)
    wake(engine, 0)
    engine.execute_command(
        SpeakCommand(agent_id=0, direction=MessageDirection.LEFT_FAR, content="save me two")
    )
    engine.execute_command(FinishTurnCommand(agent_id=0))

    heard = engine.current_state.agent_memories[2].messages[0].content
    assert leaks(heard) == []
    assert "save me two" in heard


def test_the_look_back_never_says_it_is_over() -> None:
    engine = new_game(3)
    kill(engine, 1)
    kill(engine, 2)
    agent = llm_agent(engine)
    observation = AgentObservation.from_state(engine.current_state, 0)

    text = agent._reflection_message(observation, engine)
    # The embedded situation may say "looks dead" — that is a perception, and an
    # unreliable one. What the framing around it must never do is diagnose.
    framing = text.replace(observation.format_prompt(), "")

    assert leaks(text) == []
    for word in ("died", "dead", "won", "survived", "over", "ended", "final", "last"):
        assert not re.search(rf"\b{word}\b", framing.lower()), f"the look back says {word!r}"
    assert "has not moved for a long time" in framing, "stillness is described, not diagnosed"


def test_a_still_body_reads_as_still_not_as_a_death() -> None:
    """The epilogue describes what can be seen, and stops there."""
    engine = new_game(3)
    kill(engine, 1)
    agent = llm_agent(engine)
    observation = AgentObservation.from_state(engine.current_state, 0)

    framing = agent._reflection_message(observation, engine).replace(
        observation.format_prompt(), ""
    )

    assert "Bob: has not moved for a long time" in framing
    assert "Charlie: moving" in framing, "the ones still going are described the same way"


# ----------------------------------------------------------------------------
# Silence must be indistinguishable
# ----------------------------------------------------------------------------


def test_speaking_to_the_dead_answers_exactly_like_speaking_to_the_living() -> None:
    """The rule that matters most: a speaker cannot observe delivery."""
    engine = new_game(5)
    wake(engine, 0)
    living_answer = ScriptedAgent(agent_id=0, engine=engine).speak_to_left("hello?")

    dead_engine = new_game(5)
    wake(dead_engine, 0)
    kill(dead_engine, 1)
    dead_answer = ScriptedAgent(agent_id=0, engine=dead_engine).speak_to_left("hello?")

    assert living_answer == dead_answer


def test_waking_after_silence_reads_the_same_whatever_caused_it() -> None:
    """Nobody spoke, or nobody could: from inside, the morning is identical."""
    quiet = new_game(3)
    quiet_agent = llm_agent(quiet)

    bereaved = new_game(3)
    kill(bereaved, 1)
    kill(bereaved, 2)
    bereaved_agent = llm_agent(bereaved)

    assert quiet_agent._pending_messages() == bereaved_agent._pending_messages()


def test_the_observation_never_states_who_is_alive() -> None:
    """It may guess — "looks dead", "seems deceased" — but never assert.

    The guessing words come from the perception pool and are drawn at random, so this
    samples until every description has had its chance rather than trusting one draw.
    """
    engine = new_game(5)
    for dead_id in (1, 2):
        kill(engine, dead_id)

    for _ in range(50):
        text = AgentObservation.from_state(engine.current_state, 0).format_prompt().lower()
        for word in ("alive", "is dead", "dead body", "corpse", "confirmed"):
            assert word not in text, f"the situation states {word!r} outright"


def test_perceived_state_can_disagree_with_the_truth_in_both_directions() -> None:
    """A body can look asleep and a sleeper can look dead — that ambiguity is the point."""
    from entities.observations import get_perceived_body_state

    dead_readings = {
        get_perceived_body_state(BodyState.DEAD, time_of_death=0.0, current_time=1, has_spoken=False)[0]
        for _ in range(200)
    }
    asleep_readings = {
        get_perceived_body_state(BodyState.ASLEEP, time_of_death=None, current_time=5, has_spoken=False)[0]
        for _ in range(200)
    }

    assert len(dead_readings) > 1, "the dead must not always read as dead"
    assert BodyState.DEAD not in asleep_readings or len(asleep_readings) > 1


def test_a_direction_with_nobody_in_it_gives_nothing_away() -> None:
    engine = new_game(3)
    wake(engine, 0)
    agent = ScriptedAgent(agent_id=0, engine=engine)

    answer = agent.speak_to_left_far("anyone?")

    assert leaks(answer) == []
    assert "circle" not in answer.lower() and "seat" not in answer.lower()


# ----------------------------------------------------------------------------
# The record knows what the ring could not
# ----------------------------------------------------------------------------


def test_the_record_keeps_what_the_speaker_was_never_told() -> None:
    """Unheard speech is invisible inside the ring and legible in the transcript."""
    from core.chronicler import Chronicler
    from core.narrator import render_transcript

    engine = new_game(5)
    chronicler = Chronicler(engine)
    wake(engine, 0)
    kill(engine, 1)

    speaker = ScriptedAgent(agent_id=0, engine=engine, chronicler=chronicler)
    spoken_answer = speaker.speak_to_left("are you still with us?")
    engine.execute_command(FinishTurnCommand(agent_id=0))

    chronicle = chronicler.seal()

    assert leaks(spoken_answer) == [], "the speaker learns nothing from the attempt"
    assert len(chronicle.unheard) == 1, "the record keeps it"
    assert chronicle.unheard[0].listener == "Bob"
    assert "never told" in render_transcript(chronicle), (
        "the narrator is told the speaker did not know"
    )


def test_the_record_keeps_beliefs_that_were_wrong() -> None:
    from core.chronicler import misreadings

    engine = new_game(3)
    kill(engine, 1)

    # Force the reading: a body that is dead, read as still going.
    observation = AgentObservation.from_state(engine.current_state, 0)
    seats = tuple(
        seat.model_copy(update={"perceived_status": BodyState.ASLEEP})
        if seat.seat_id == 1
        else seat
        for seat in observation.seats
    )
    gaps = misreadings(engine, observation.model_copy(update={"seats": seats}))

    assert any("already dead" in gap for gap in gaps)
