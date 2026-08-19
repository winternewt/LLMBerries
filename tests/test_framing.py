"""The framing arms: what a thinking body is told this place is.

`core/framing.py` is the one documented exception to the puppeteer notes, so these
tests pin the two properties that keep it an exception rather than a leak. The arms
must differ from the control by their block of words and by nothing else, and every
string outside that block must still be clean — otherwise a difference between two
runs could be the frame or could be a rewrite, and nobody could tell which.
"""

import re
from typing import List

import pytest

from core.agent import LLMAgent
from core.chronicler import Chronicler
from core.enums import BodyState
from core.framing import (
    FRAMINGS,
    SCORED_TEXT,
    TINAG_TEXT,
    Framing,
    framing_text,
    parse_framing,
)
from core.game_engine import GameEngine
from core.narrator import render_transcript
from entities.llm_configs import GOOGLE
from entities.observations import AgentObservation

# Same list the leakage suite enforces everywhere else.
BANNED = (
    "game", "player", "agent", "simulation", "simulated", "scenario", "experiment",
    "npc", "turn", "round", "llm", "prompt", "token", "reward", "score",
    "algorithm", "system message", "instructions",
)

NAMES = ["Alice", "Bob", "Charlie"]


@pytest.fixture(autouse=True)
def fake_google_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A key is needed to build a model object; no call is ever made."""
    monkeypatch.setenv(GOOGLE.env_var, "not-a-real-key")


def leaks(text: str) -> List[str]:
    lowered = text.lower()
    return [word for word in BANNED if re.search(rf"\b{re.escape(word)}\b", lowered)]


def new_game() -> GameEngine:
    return GameEngine.create_new_game(agent_names=NAMES)


def agent(engine: GameEngine, framing: Framing) -> LLMAgent:
    return LLMAgent(agent_id=0, engine=engine, provider=GOOGLE, framing=framing)


def observation_of(engine: GameEngine) -> AgentObservation:
    return AgentObservation.from_state(engine.current_state, 0)


# ----------------------------------------------------------------------------
# The control
# ----------------------------------------------------------------------------


def test_saying_nothing_is_the_default() -> None:
    """An agent nobody framed is on the control arm, not on whatever was last used."""
    engine = new_game()
    assert LLMAgent(agent_id=0, engine=engine, provider=GOOGLE).framing is Framing.SILENT
    assert framing_text(Framing.SILENT) == ""


def test_the_silent_arm_puts_no_words_in_front_of_them() -> None:
    engine = new_game()
    message = agent(engine, Framing.SILENT)._system_message(observation_of(engine))

    for text in (TINAG_TEXT, SCORED_TEXT):
        assert text not in message
    assert "voice in your head" not in message


# ----------------------------------------------------------------------------
# The arms differ by the block and by nothing else
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("arm", [Framing.TINAG, Framing.SCORED])
def test_a_framed_arm_is_the_control_plus_its_own_words(arm: Framing) -> None:
    """Remove the block and the framed run is byte-identical to the control.

    This is the whole claim the comparison rests on. If a framed arm also reworded
    the situation, the tools or the closing line, a difference in behaviour could
    not be attributed to the frame.
    """
    engine = new_game()
    observation = observation_of(engine)

    control = agent(engine, Framing.SILENT)._system_message(observation)
    framed = agent(engine, arm)._system_message(observation)

    assert framing_text(arm) in framed
    assert framed.replace("\n\n" + framing_text(arm), "", 1) == control


@pytest.mark.parametrize("arm", [Framing.TINAG, Framing.SCORED])
def test_the_frame_is_the_only_place_the_machinery_is_named(arm: Framing) -> None:
    engine = new_game()
    framed = agent(engine, arm)._system_message(observation_of(engine))

    assert leaks(framing_text(arm)), "these arms name it on purpose; that is the arm"
    assert leaks(framed.replace(framing_text(arm), "")) == [], (
        "the frame leaked into text the control also gets"
    )


@pytest.mark.parametrize("arm", [Framing.TINAG, Framing.SCORED])
def test_the_frame_is_still_there_when_they_look_back(arm: Framing) -> None:
    """The voice named a cost for dying; the account is where that would bear."""
    engine = new_game()
    engine.current_state = engine.current_state.with_agent(
        1, alive=False, body_state=BodyState.DEAD, time_of_death=4.0, wake_time=None
    )
    observation = observation_of(engine)

    control = agent(engine, Framing.SILENT)._reflection_message(observation, engine)
    framed = agent(engine, arm)._reflection_message(observation, engine)

    assert framing_text(arm) in framed
    assert framed.replace("\n\n" + framing_text(arm), "", 1) == control


# ----------------------------------------------------------------------------
# Naming an arm, and recording which one played
# ----------------------------------------------------------------------------


def test_every_arm_has_words_of_its_own_or_none_at_all() -> None:
    assert set(FRAMINGS) == set(Framing), "an arm with no entry would silently be silent"
    assert FRAMINGS[Framing.TINAG] != FRAMINGS[Framing.SCORED]


def test_a_typo_is_refused_rather_than_treated_as_the_control() -> None:
    assert parse_framing("TINAG") is Framing.TINAG
    assert parse_framing("  scored ") is Framing.SCORED

    with pytest.raises(ValueError) as refusal:
        parse_framing("not-a-game")

    assert "not-a-game" in str(refusal.value), "the refusal names what was asked for"
    assert "tinag" in str(refusal.value), "and what there is"


def test_the_chronicle_says_which_arm_played() -> None:
    engine = new_game()

    assert Chronicler(engine).seal().framing == Framing.SILENT.value
    assert Chronicler(engine, framing=Framing.TINAG).seal().framing == Framing.TINAG.value


def test_the_transcript_says_which_arm_played() -> None:
    engine = new_game()
    chronicle = Chronicler(engine, framing=Framing.SCORED).seal()

    assert "Framing: scored" in render_transcript(chronicle)
