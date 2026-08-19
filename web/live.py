"""One game at a time, watched as it happens.

The game loop is synchronous and slow on purpose (the pacers sleep to honour
free-tier limits), so it runs on a worker thread; the web side reads a feed the
game thread appends to. Two sources feed it: the event bus, and a chronicler
subclass — turn records never cross the bus, so without the second source the
stream would show state changing with nobody's reasons attached.

Both sources run ON the game thread. They append under a lock and do nothing
else; any I/O here would stall the ring between two of its own heartbeats.
"""

import asyncio
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from core.chronicler import Chronicler
from core.framing import Framing
from core.game_engine import GameEngine
from core.runner import GameConfig, PreparedGame, prepare_game, run_prepared, write_artifacts
from entities.chronicle import TurnRecord
from entities.events import GameEvent
from web.runs import to_hour_state
from web.schemas import LaunchRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@dataclass(frozen=True)
class StreamItem:
    cursor: int
    kind: str  # event | turn | status
    payload: dict


class LiveFeed:
    """Everything one game has said so far, in order, readable from any thread.

    Append-only for the whole run — unlike the bus's 255-slot ring, nothing ages
    out, so a client that connects at hour 30 rebuilds the game from cursor 0.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: List[StreamItem] = []

    def push(self, kind: str, payload: dict) -> None:
        with self._lock:
            self._items.append(StreamItem(cursor=len(self._items), kind=kind, payload=payload))

    def since(self, cursor: int) -> List[StreamItem]:
        with self._lock:
            return self._items[cursor:]


class StreamingChronicler(Chronicler):
    """A chronicler that also drops each turn onto the live feed as it lands."""

    def __init__(self, engine: GameEngine, framing: Framing, feed: LiveFeed) -> None:
        super().__init__(engine, framing)
        self._feed = feed

    def record(self, turn: TurnRecord) -> None:
        super().record(turn)
        self._feed.push("turn", turn.model_dump(mode="json"))


class GameBusy(Exception):
    pass


class LiveGameManager:
    """Owns the single running game: its thread, its feed, its stop switch."""

    def __init__(self, runs_root: Path) -> None:
        self.runs_root = runs_root
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.feed = LiveFeed()
        self.phase: str = "idle"
        self.stamp: Optional[str] = None
        self.config: Optional[dict] = None
        self.outcome: Optional[str] = None
        self.latest_state = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def launch(self, request: LaunchRequest) -> dict:
        # The whole prepare happens under the lock, on the request thread. That is
        # not just tidiness: prepare_game seeds the process-global RNG and attaches
        # the session log to the root logger, and the one-game-at-a-time rule is
        # exactly what makes touching those globals here safe.
        with self._lock:
            if self.running:
                raise GameBusy("a game is already running")

            feed = LiveFeed()
            self.feed = feed
            self._stop = threading.Event()
            self.phase = "running"
            self.outcome = None
            self.latest_state = None
            self.config = request.model_dump(mode="json")

            prepared = prepare_game(
                request.to_config(self.runs_root),
                chronicler_factory=lambda engine, framing: StreamingChronicler(
                    engine, framing, feed
                ),
            )
            # Subscribing now, before the first hour, flushes the bus's buffered
            # setup events into the feed — a client sees the game from its very
            # first command whenever it connects.
            engine = prepared.engine

            def on_event(name: str, event: GameEvent) -> None:
                self.latest_state = engine.current_state
                feed.push("event", event.model_dump(mode="json"))

            engine.event_bus.subscribe("game.*", on_event)

            self.stamp = prepared.run_dir.name if prepared.run_dir else None
            self._thread = threading.Thread(
                target=self._run, args=(prepared,), daemon=True, name="llmberries-game"
            )
            self._thread.start()
            return {
                "stamp": self.stamp,
                "run_dir": str(prepared.run_dir) if prepared.run_dir else None,
                "seed": prepared.seed,
            }

    def _run(self, prepared: PreparedGame) -> None:
        try:
            record = run_prepared(prepared, stop=self._stop)
            write_artifacts(prepared, record)
            self.phase = "finished"
            self.outcome = record.outcome
            self.feed.push(
                "status", {"phase": "finished", "outcome": record.outcome, "stamp": self.stamp}
            )
        except Exception as boom:  # noqa: BLE001 — the thread's edge; nothing above catches
            logger.exception("live game failed")
            self.phase = "failed"
            self.feed.push("status", {"phase": "failed", "error": str(boom), "stamp": self.stamp})
        finally:
            prepared.close()

    def stop(self) -> None:
        self._stop.set()

    def shutdown(self, timeout: float = 30.0) -> None:
        """Server going down: ask the game to stop and give it a moment to seal."""
        if self.running:
            self._stop.set()
            self._thread.join(timeout=timeout)

    def snapshot(self) -> dict:
        state = self.latest_state
        return {
            "running": self.running,
            "phase": self.phase,
            "stamp": self.stamp,
            "hour": state.world_time if state is not None else None,
            "config": self.config,
            "outcome": self.outcome,
        }


def manager_of(request: Request) -> LiveGameManager:
    return request.app.state.games


@router.post("/games", status_code=201)
def launch_game(request: Request, launch: LaunchRequest) -> dict:
    try:
        return manager_of(request).launch(launch)
    except GameBusy as busy:
        raise HTTPException(status_code=409, detail=str(busy)) from busy


@router.get("/games/current")
def current_game(request: Request) -> dict:
    return manager_of(request).snapshot()


@router.get("/games/current/state")
def current_game_state(request: Request):
    """The running world as it stands — the live twin of the archive's state view."""
    state = manager_of(request).latest_state
    if state is None:
        raise HTTPException(status_code=404, detail="no world yet")
    return to_hour_state(state, hour=state.world_time, last_hour=state.world_time)


@router.post("/games/current/stop")
def stop_game(request: Request) -> dict:
    manager = manager_of(request)
    if not manager.running:
        raise HTTPException(status_code=409, detail="nothing is running")
    manager.stop()
    return {"stopping": True}


async def _sse(manager: LiveGameManager, cursor: int):
    while True:
        for item in manager.feed.since(cursor):
            cursor = item.cursor + 1
            yield (
                f"id: {item.cursor}\n"
                f"event: {item.kind}\n"
                f"data: {json.dumps(item.payload)}\n\n"
            )
        if manager.phase in ("finished", "failed") and not manager.feed.since(cursor):
            return
        await asyncio.sleep(0.15)


@router.get("/games/current/stream")
def stream_game(request: Request) -> StreamingResponse:
    last_id = request.headers.get("last-event-id")
    cursor = int(last_id) + 1 if last_id and last_id.isdigit() else 0
    return StreamingResponse(
        _sse(manager_of(request), cursor),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
