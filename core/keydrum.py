"""Key rotation and token accounting for free tiers that run dry mid-game.

A free key is a magazine, not a supply. Groq's caps tokens per day; a long game empties
one and every remaining turn is lost. The drum holds every key a provider has, hands out
the current one, and rotates when a key comes back spent — the run continues on the next
chamber instead of dying with the first.

It also keeps the ledger: what each provider has actually spent this session. That is
what decides who narrates, since the narrator reads the whole transcript and is the most
expensive single call in a run.
"""

import logging
import os
import re
import threading
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# What a provider says when a key is finished rather than merely busy. A spent key does
# not recover within a run, so the drum rotates past it instead of retrying it.
SPENT_MARKERS: Tuple[str, ...] = (
    "tokens per day",
    "tpd",
    "requests per day",
    "rpd",
    "quota exceeded",
    "insufficient balance",
    "payment required",
    "billing",
    "exceeded your current quota",
)


def is_spent(message: str) -> bool:
    """Whether this failure means the key is finished, not just going too fast."""
    lowered = message.lower()
    return any(marker in lowered for marker in SPENT_MARKERS)


def load_keys(env_var: str) -> Tuple[str, ...]:
    """Every key a provider has, in a fixed order.

    Read from `VAR` (which may itself hold a comma-separated list) followed by the
    numbered variants `VAR_2`, `VAR_3`, ... in order. Blank entries are dropped: an
    empty string is how a test says "no credential", and it must never be handed to a
    provider as one.
    """
    keys: List[str] = []

    def take(raw: Optional[str]) -> None:
        for piece in (raw or "").split(","):
            key = piece.strip()
            if key and key not in keys:
                keys.append(key)

    take(os.environ.get(env_var))

    numbered = sorted(
        (name for name in os.environ if re.fullmatch(rf"{re.escape(env_var)}_\d+", name)),
        key=lambda name: int(name.rsplit("_", 1)[1]),
    )
    for name in numbered:
        take(os.environ.get(name))

    return tuple(keys)


class KeyDrum:
    """The keys one provider has, and which chamber is under the hammer."""

    def __init__(self, provider: str, keys: Tuple[str, ...]) -> None:
        if not keys:
            raise RuntimeError(f"{provider}: no API key")

        self.provider: str = provider
        self._keys: Tuple[str, ...] = keys
        self._position: int = 0
        self._spent: List[str] = []
        self._lock = threading.Lock()

    @property
    def chambers(self) -> int:
        return len(self._keys)

    def current(self) -> str:
        """The key to use now."""
        with self._lock:
            return self._keys[self._position]

    def live_keys(self) -> Tuple[str, ...]:
        with self._lock:
            return tuple(key for key in self._keys if key not in self._spent)

    def is_exhausted(self) -> bool:
        """True when every chamber is empty."""
        return not self.live_keys()

    def rotate(self, reason: str = "") -> Optional[str]:
        """Mark the current key spent and advance. Returns the next live key, or None.

        None means the provider is finished for this session — every key it has came
        back spent. The caller decides what that costs; the drum does not pretend.
        """
        with self._lock:
            spent_key = self._keys[self._position]
            if spent_key not in self._spent:
                self._spent.append(spent_key)
                logger.warning(
                    "%s: key %d/%d spent%s",
                    self.provider,
                    self._position + 1,
                    len(self._keys),
                    f" ({reason})" if reason else "",
                )

            for step in range(1, len(self._keys) + 1):
                candidate = (self._position + step) % len(self._keys)
                if self._keys[candidate] not in self._spent:
                    self._position = candidate
                    logger.info(
                        "%s: rotating to key %d/%d", self.provider, candidate + 1, len(self._keys)
                    )
                    return self._keys[candidate]

        logger.error("%s: every key is spent", self.provider)
        return None


_DRUMS: Dict[str, KeyDrum] = {}
_DRUM_LOCK = threading.Lock()


def get_drum(provider: str, env_var: str) -> KeyDrum:
    """The shared drum for this provider, loaded from the environment on first use."""
    with _DRUM_LOCK:
        drum = _DRUMS.get(provider)
        if drum is None:
            keys = load_keys(env_var)
            if not keys:
                raise RuntimeError(
                    f"{provider}: no API key — set {env_var} in .env (see .env.template)"
                )
            drum = KeyDrum(provider=provider, keys=keys)
            _DRUMS[provider] = drum
            logger.debug("%s: drum loaded with %d key(s)", provider, drum.chambers)
        return drum


def reset_drums() -> None:
    """Drop all drums. For tests, and for a fresh session."""
    with _DRUM_LOCK:
        _DRUMS.clear()


class UsageLedger:
    """Tokens spent per provider this session.

    Only what this process actually sent is counted — a provider's daily counter may
    already be part-spent by an earlier run, so a large remaining figure here is an
    upper bound, never a promise.
    """

    def __init__(self) -> None:
        self._tokens: Dict[str, int] = {}
        self._calls: Dict[str, int] = {}
        self._lock = threading.Lock()

    def record(self, provider: str, tokens: int) -> None:
        with self._lock:
            self._tokens[provider] = self._tokens.get(provider, 0) + max(0, tokens)
            self._calls[provider] = self._calls.get(provider, 0) + 1

    def tokens(self, provider: str) -> int:
        with self._lock:
            return self._tokens.get(provider, 0)

    def calls(self, provider: str) -> int:
        with self._lock:
            return self._calls.get(provider, 0)

    def summary(self) -> Tuple[Tuple[str, int, int], ...]:
        """(provider, calls, tokens) in a fixed order, so a report never shuffles."""
        with self._lock:
            return tuple(
                (provider, self._calls.get(provider, 0), self._tokens[provider])
                for provider in sorted(self._tokens)
            )

    def reset(self) -> None:
        with self._lock:
            self._tokens.clear()
            self._calls.clear()


LEDGER = UsageLedger()
