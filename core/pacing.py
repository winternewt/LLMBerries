"""Request pacing for free-tier LLM endpoints.

Free tiers cap requests per minute, and a game turn fires one request per awake
agent in quick succession — exactly the burst shape that trips an RPM ceiling.
The limiter here enforces two things per provider:

1. a sliding-window cap of `rpm` requests in any 60s span, and
2. a minimum spacing of 60/rpm seconds between consecutive requests,

so a burst is smoothed into an even cadence rather than being allowed to run at
full speed until the window fills and then stall.

Limiters are shared per provider via `get_pacer`: two agents on the same free key
draw from the same quota, so they must draw from the same limiter.
"""

import logging
import threading
import time
from collections import deque
from typing import Deque, Dict

logger = logging.getLogger(__name__)

# Free-tier quotas are advertised as an average, and a request that arrives at the
# instant the window rolls over is still occasionally refused. Aim below the cap.
DEFAULT_SAFETY_FACTOR: float = 0.9

WINDOW_SECONDS: float = 60.0


class RateLimiter:
    """Sliding-window request limiter with minimum spacing.

    Thread-safe: agents may be paced from different threads, and the whole point
    is that they contend for one quota.
    """

    def __init__(self, name: str, rpm: int, safety_factor: float = DEFAULT_SAFETY_FACTOR) -> None:
        if rpm <= 0:
            raise ValueError(f"{name}: rpm must be positive, got {rpm}")
        if not 0.0 < safety_factor <= 1.0:
            raise ValueError(f"{name}: safety_factor must be in (0, 1], got {safety_factor}")

        self.name: str = name
        self.rpm: int = rpm
        self.effective_rpm: float = rpm * safety_factor
        self.min_spacing: float = WINDOW_SECONDS / self.effective_rpm
        self._timestamps: Deque[float] = deque()
        self._lock: threading.Lock = threading.Lock()

    def acquire(self) -> float:
        """Block until a request may be sent. Returns the seconds spent waiting."""
        waited: float = 0.0

        while True:
            with self._lock:
                now = time.monotonic()
                self._evict(now)

                wait_for_window = self._wait_for_window(now)
                wait_for_spacing = self._wait_for_spacing(now)
                wait = max(wait_for_window, wait_for_spacing)

                if wait <= 0.0:
                    self._timestamps.append(now)
                    if waited > 0.0:
                        logger.debug("%s: paced %.2fs before request", self.name, waited)
                    return waited

            time.sleep(wait)
            waited += wait

    def _evict(self, now: float) -> None:
        """Drop timestamps that have fallen out of the sliding window."""
        cutoff = now - WINDOW_SECONDS
        while self._timestamps and self._timestamps[0] <= cutoff:
            self._timestamps.popleft()

    def _wait_for_window(self, now: float) -> float:
        """Seconds until the window has room for another request."""
        if len(self._timestamps) < self.effective_rpm:
            return 0.0
        return (self._timestamps[0] + WINDOW_SECONDS) - now

    def _wait_for_spacing(self, now: float) -> float:
        """Seconds until the minimum gap since the last request has elapsed."""
        if not self._timestamps:
            return 0.0
        return (self._timestamps[-1] + self.min_spacing) - now

    def requests_in_window(self) -> int:
        """How many requests the limiter currently counts against the window."""
        with self._lock:
            self._evict(time.monotonic())
            return len(self._timestamps)


_PACERS: Dict[str, RateLimiter] = {}
_REGISTRY_LOCK: threading.Lock = threading.Lock()


def get_pacer(name: str, rpm: int, safety_factor: float = DEFAULT_SAFETY_FACTOR) -> RateLimiter:
    """Return the shared limiter for `name`, creating it on first use.

    A provider's quota belongs to the key, not to the caller, so every agent on
    that provider gets the same limiter instance. A later call with a different
    `rpm` does not silently re-tune the existing limiter — it is an error, since
    one of the two callers is working from the wrong quota.
    """
    with _REGISTRY_LOCK:
        existing = _PACERS.get(name)
        if existing is not None:
            if existing.rpm != rpm:
                raise ValueError(
                    f"pacer {name!r} already exists with rpm={existing.rpm}, refusing to "
                    f"re-register with rpm={rpm}"
                )
            return existing

        pacer = RateLimiter(name=name, rpm=rpm, safety_factor=safety_factor)
        _PACERS[name] = pacer
        logger.debug(
            "%s: pacer created (rpm=%d, effective=%.1f, min spacing=%.2fs)",
            name,
            rpm,
            pacer.effective_rpm,
            pacer.min_spacing,
        )
        return pacer


def reset_pacers() -> None:
    """Drop all registered limiters. For tests and for a fresh experiment run."""
    with _REGISTRY_LOCK:
        _PACERS.clear()
