"""Where a run leaves its evidence.

Every game writes a directory of its own, named for the moment it started, and
nothing ever writes over an earlier one. This exists because the alternative was
tried: artifacts were opt-in, and every path was a fixed name the caller chose, so
a run that was not asked to record left nothing at all and a second run under the
same name destroyed the first. A study whose evidence depends on remembering to
ask for it has no evidence.

The session log is attached before the game starts and detached after the last
artifact is written, so a crash mid-game still leaves the log of everything up to
it — that is the run most worth reading.
"""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SESSION_LOG_NAME: str = "session.log"
TRANSCRIPT_NAME: str = "transcript.txt"
CHRONICLE_NAME: str = "chronicle.json"
STORY_NAME: str = "story.md"


def _stamp() -> str:
    """UTC, to the second, in a form that sorts and survives a filesystem."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def open_run_directory(root: Path) -> Path:
    """A fresh directory for this run. Never an existing one.

    Two runs starting in the same second get `-2`, `-3` and so on rather than
    sharing: overwriting a previous run's evidence is the failure this module
    exists to prevent, so it is not done even when the clock invites it.
    """
    root.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    candidate = root / stamp
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = root / f"{stamp}-{suffix}"
    candidate.mkdir()
    return candidate


class SessionLog:
    """Everything the run printed, on disk, for as long as the run lasts."""

    def __init__(self, path: Path, level: int = logging.DEBUG) -> None:
        self.path: Path = path
        self._handler: Optional[logging.Handler] = None
        self._level: int = level

    def attach(self, header: str = "") -> "SessionLog":
        handler = logging.FileHandler(self.path, mode="x", encoding="utf-8")
        handler.setLevel(self._level)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

        root = logging.getLogger()
        # The root logger gates every handler, so a root left at INFO would silently
        # throw away the DEBUG lines this file exists to keep. Lowering it would also
        # turn the console into a firehose, so every handler already attached is first
        # pinned at the level it was inheriting — the file gets more, the terminal the
        # same as before.
        if root.level > self._level:
            for existing in root.handlers:
                if existing.level == logging.NOTSET:
                    existing.setLevel(root.level)
            root.setLevel(self._level)
        root.addHandler(handler)
        self._handler = handler

        if header:
            logger.info("%s", header)
        return self

    def detach(self) -> None:
        if self._handler is None:
            return
        logging.getLogger().removeHandler(self._handler)
        self._handler.close()
        self._handler = None


def describe_invocation(seed: int) -> str:
    """The line that lets someone run this again."""
    return f"command: {' '.join(sys.argv)}\nseed in effect: {seed}\nstarted: {datetime.now(timezone.utc).isoformat()}"
