"""Tests for the request pacer.

Timing assertions use generous margins: the point is that the limiter waits at all
and waits roughly the right amount, not that it is precise to the millisecond.
"""

import time

import pytest

from core.pacing import WINDOW_SECONDS, RateLimiter, get_pacer, reset_pacers


@pytest.fixture(autouse=True)
def clear_registry() -> None:
    reset_pacers()
    yield
    reset_pacers()


def test_first_request_is_not_delayed() -> None:
    limiter = RateLimiter(name="test", rpm=60)
    assert limiter.acquire() == 0.0


def test_second_request_waits_the_minimum_spacing() -> None:
    """The failure this exists to prevent: two calls back to back, second refused."""
    limiter = RateLimiter(name="test", rpm=120, safety_factor=1.0)  # 0.5s apart

    limiter.acquire()
    started = time.monotonic()
    waited = limiter.acquire()
    elapsed = time.monotonic() - started

    assert waited >= limiter.min_spacing * 0.9, "second call must be held back"
    assert elapsed >= limiter.min_spacing * 0.9, "the wait must be real time, not just reported"


def test_spacing_is_derived_from_the_effective_rate() -> None:
    limiter = RateLimiter(name="test", rpm=30, safety_factor=0.9)

    assert limiter.effective_rpm == pytest.approx(27.0)
    assert limiter.min_spacing == pytest.approx(WINDOW_SECONDS / 27.0)


def test_window_counts_only_requests_it_has_seen() -> None:
    limiter = RateLimiter(name="test", rpm=600, safety_factor=1.0)  # 0.1s apart

    assert limiter.requests_in_window() == 0
    for expected in range(1, 4):
        limiter.acquire()
        assert limiter.requests_in_window() == expected


def test_pacer_registry_shares_one_limiter_per_provider() -> None:
    """Agents on the same key draw on the same quota, so they must share a limiter."""
    first = get_pacer("groq", rpm=30)
    second = get_pacer("groq", rpm=30)

    assert first is second


def test_registry_refuses_to_re_register_with_a_different_rate() -> None:
    get_pacer("groq", rpm=30)

    with pytest.raises(ValueError, match="already exists with rpm=30"):
        get_pacer("groq", rpm=60)


@pytest.mark.parametrize("bad_rpm", [0, -1])
def test_non_positive_rpm_is_refused(bad_rpm: int) -> None:
    with pytest.raises(ValueError, match="rpm must be positive"):
        RateLimiter(name="test", rpm=bad_rpm)


@pytest.mark.parametrize("bad_factor", [0.0, 1.5, -0.5])
def test_out_of_range_safety_factor_is_refused(bad_factor: float) -> None:
    with pytest.raises(ValueError, match="safety_factor must be in"):
        RateLimiter(name="test", rpm=30, safety_factor=bad_factor)
