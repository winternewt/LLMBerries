"""Tests for key rotation and the token ledger.

A free key is a magazine, not a supply. What matters here: every key a provider has is
found, a spent one is never returned to, a key that is merely going too fast is not
mistaken for a spent one, and the narrator is chosen by what is left rather than by
what happens to be first in the list.
"""

from typing import Tuple

import pytest

from core.keydrum import LEDGER, KeyDrum, get_drum, is_spent, load_keys, reset_drums
from entities.llm_configs import (
    GOOGLE,
    GROQ,
    ProviderSpec,
    get_drum_for,
    pick_narrator,
    remaining_budget,
)


@pytest.fixture(autouse=True)
def clean_state(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_drums()
    LEDGER.reset()
    for name in ("GOOGLE_API_KEY", "GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3"):
        monkeypatch.delenv(name, raising=False)
    yield
    reset_drums()
    LEDGER.reset()


def drum(*keys: str) -> KeyDrum:
    return KeyDrum(provider="test", keys=tuple(keys))


# ----------------------------------------------------------------------------
# Finding the keys
# ----------------------------------------------------------------------------


def test_a_single_key_is_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "one")
    assert load_keys("GROQ_API_KEY") == ("one",)


def test_numbered_keys_are_found_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "first")
    monkeypatch.setenv("GROQ_API_KEY_3", "third")
    monkeypatch.setenv("GROQ_API_KEY_2", "second")

    assert load_keys("GROQ_API_KEY") == ("first", "second", "third")


def test_a_comma_separated_variable_holds_several_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "one, two ,three")
    assert load_keys("GROQ_API_KEY") == ("one", "two", "three")


def test_blank_and_duplicate_entries_are_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty value is how a test says "no credential"; it must never become one."""
    monkeypatch.setenv("GROQ_API_KEY", "one,,one, ")
    monkeypatch.setenv("GROQ_API_KEY_2", "")

    assert load_keys("GROQ_API_KEY") == ("one",)


def test_a_provider_with_no_key_at_all_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "")

    with pytest.raises(RuntimeError, match="no API key"):
        get_drum("google", "GOOGLE_API_KEY")


# ----------------------------------------------------------------------------
# Turning the drum
# ----------------------------------------------------------------------------


def test_the_first_chamber_is_used_until_it_is_spent() -> None:
    magazine = drum("a", "b", "c")

    assert magazine.current() == "a"
    assert magazine.current() == "a", "the drum does not turn on its own"


def test_rotating_moves_to_the_next_live_key() -> None:
    magazine = drum("a", "b", "c")

    assert magazine.rotate("dry") == "b"
    assert magazine.current() == "b"


def test_a_spent_key_is_never_returned_to() -> None:
    magazine = drum("a", "b")

    magazine.rotate()  # a is spent, now on b
    magazine.rotate()  # b is spent too
    assert magazine.is_exhausted()
    assert magazine.live_keys() == ()


def test_an_exhausted_drum_says_so_rather_than_cycling() -> None:
    magazine = drum("only")

    assert magazine.rotate("dry") is None, "with nothing left it must not hand back the same key"
    assert magazine.is_exhausted() is True


def test_rotating_twice_on_one_key_does_not_lose_a_second_chamber() -> None:
    magazine = drum("a", "b", "c")

    magazine.rotate()  # a spent -> b
    assert magazine.current() == "b"
    assert len(magazine.live_keys()) == 2, "only the key in use was spent"


@pytest.mark.parametrize(
    "message",
    [
        "Rate limit reached ... on tokens per day (TPD): Limit 200000",
        "Insufficient Balance",
        "Payment required to access this resource. Visit your billing tab.",
        "You exceeded your current quota",
    ],
)
def test_a_finished_key_is_recognised(message: str) -> None:
    assert is_spent(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "Rate limit reached for model on tokens per minute (TPM)",
        "429 Too Many Requests, please slow down",
        "service temporarily unavailable",
    ],
)
def test_going_too_fast_is_not_the_same_as_being_finished(message: str) -> None:
    """Rotating on a per-minute limit would burn the whole drum inside a minute."""
    assert is_spent(message) is False


# ----------------------------------------------------------------------------
# The ledger, and who gets to narrate
# ----------------------------------------------------------------------------


def test_the_ledger_counts_calls_and_tokens() -> None:
    LEDGER.record("groq", 1200)
    LEDGER.record("groq", 800)
    LEDGER.record("google", 50)

    assert LEDGER.tokens("groq") == 2000
    assert LEDGER.calls("groq") == 2
    assert LEDGER.summary() == (("google", 1, 50), ("groq", 2, 2000))


def test_remaining_budget_counts_every_live_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "one,two")

    assert remaining_budget(GROQ) == GROQ.daily_token_budget * 2

    LEDGER.record("groq", 50_000)
    assert remaining_budget(GROQ) == GROQ.daily_token_budget * 2 - 50_000


def test_a_spent_key_takes_its_budget_with_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "one,two")
    get_drum_for(GROQ).rotate("dry")

    assert remaining_budget(GROQ) == GROQ.daily_token_budget


def test_an_unstated_budget_stays_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown is not unlimited, and must not be reported as a number."""
    monkeypatch.setenv("GOOGLE_API_KEY", "one")

    assert GOOGLE.daily_token_budget is None
    assert remaining_budget(GOOGLE) is None


def test_the_narrator_is_whoever_has_the_most_left(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "one,two")
    monkeypatch.setenv("GOOGLE_API_KEY", "one")

    pool: Tuple[ProviderSpec, ...] = (GOOGLE, GROQ)
    assert pick_narrator(pool) is GROQ, "400k stated beats an unstated budget"

    LEDGER.record("groq", 399_000)
    assert pick_narrator(pool) is GOOGLE, "once it is nearly dry, the unknown one is better"


def test_a_provider_with_every_key_spent_is_never_asked_to_narrate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "one")
    monkeypatch.setenv("GOOGLE_API_KEY", "one")
    get_drum_for(GROQ).rotate("dry")

    assert pick_narrator((GOOGLE, GROQ)) is GOOGLE


def test_providers_share_one_drum_across_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two agents on one provider must spend the same keys in the same order."""
    monkeypatch.setenv("GROQ_API_KEY", "one,two")

    first = get_drum_for(GROQ)
    second = get_drum_for(GROQ)

    assert first is second
    first.rotate("dry")
    assert second.current() == "two"
