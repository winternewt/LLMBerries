"""The tape archive: what finished (or crashed) runs look like from the outside.

A run directory with no chronicle is still listed — a crash is evidence, not
garbage — it is just marked incomplete. Stamps are validated against the exact
shape `open_run_directory` produces, which is also what keeps a path traversal
from ever reaching the filesystem.
"""

import logging
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, HTTPException, Request

from core.chronicler import load_chronicle
from core.constants import MAX_BERRIES, MAX_HUNGER, MAX_RUN_TIME, MIN_AGENT_COUNT
from core.framing import Framing
from core.record import CHRONICLE_NAME, SESSION_LOG_NAME, STORY_NAME, TRANSCRIPT_NAME
from core.replay import REPLAY_NAME, load_replay, rebuild
from core.zombie import ZombieFlavour
from entities.llm_configs import LLM_SET
from entities.world import WorldState
from web.schemas import BushGauge, HourState, MetaResponse, RunListItem, RunListResponse, SeatState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Exactly what open_run_directory writes: UTC second stamp, optional collision suffix.
STAMP_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}Z(-[0-9]+)?$")


def runs_root(request: Request) -> Path:
    return request.app.state.runs_root


def run_dir_for(request: Request, stamp: str) -> Path:
    """Resolve a stamp to its directory, refusing anything that is not a stamp."""
    if not STAMP_PATTERN.match(stamp):
        raise HTTPException(status_code=404, detail=f"no run named {stamp!r}")
    candidate = runs_root(request) / stamp
    if not candidate.is_dir():
        raise HTTPException(status_code=404, detail=f"no run named {stamp!r}")
    return candidate


@router.get("/meta", response_model=MetaResponse)
def meta() -> MetaResponse:
    return MetaResponse(
        providers=[spec.name for spec in LLM_SET],
        zombie_flavours=[flavour.value for flavour in ZombieFlavour],
        framings=[arm.value for arm in Framing],
        min_agents=MIN_AGENT_COUNT,
        max_hours_default=MAX_RUN_TIME,
        max_berries=MAX_BERRIES,
        max_hunger=MAX_HUNGER,
    )


@router.get("/runs", response_model=RunListResponse)
def list_runs(request: Request) -> RunListResponse:
    root = runs_root(request)
    if not root.is_dir():
        return RunListResponse(runs=[])

    items = []
    for entry in sorted(root.iterdir(), reverse=True):
        if not entry.is_dir() or not STAMP_PATTERN.match(entry.name):
            continue
        items.append(_list_item(entry))
    return RunListResponse(runs=items)


def _list_item(run_dir: Path) -> RunListItem:
    chronicle_path = run_dir / CHRONICLE_NAME
    if not chronicle_path.is_file():
        return RunListItem(stamp=run_dir.name, complete=False)
    try:
        chronicle = load_chronicle(chronicle_path)
    except (ValueError, OSError):
        logger.warning("unreadable chronicle in %s", run_dir, exc_info=True)
        return RunListItem(stamp=run_dir.name, complete=False)

    providers: list[str] = []
    for summary in chronicle.agents:
        label = summary.provider or "scripted"
        if label not in providers:
            providers.append(label)
    return RunListItem(
        stamp=run_dir.name,
        complete=True,
        hours_played=chronicle.hours_played,
        agent_count=chronicle.agent_count,
        framing=chronicle.framing,
        outcome=chronicle.outcome,
        winner=chronicle.winner,
        death_count=len(chronicle.deaths),
        providers=providers,
        has_story=(run_dir / STORY_NAME).is_file(),
    )


ARTIFACT_NAMES = (SESSION_LOG_NAME, TRANSCRIPT_NAME, CHRONICLE_NAME, REPLAY_NAME, STORY_NAME)


@router.get("/runs/{stamp}")
def run_detail(request: Request, stamp: str) -> dict:
    """The whole chronicle, plus what else the directory holds.

    A crashed run answers too — chronicle `null`, `complete` false — because the
    archive lists it and a listing you cannot open is a dead link.
    """
    run_dir = run_dir_for(request, stamp)
    chronicle_path = run_dir / CHRONICLE_NAME
    chronicle = None
    if chronicle_path.is_file():
        try:
            chronicle = load_chronicle(chronicle_path).model_dump(mode="json")
        except (ValueError, OSError):
            logger.warning("unreadable chronicle in %s", run_dir, exc_info=True)

    seed = None
    replay_path = run_dir / REPLAY_NAME
    if replay_path.is_file():
        try:
            seed = load_replay(replay_path).seed
        except (ValueError, OSError):
            logger.warning("unreadable replay in %s", run_dir, exc_info=True)

    return {
        "stamp": stamp,
        "complete": chronicle is not None,
        "chronicle": chronicle,
        "seed": seed,
        "artifacts": [name for name in ARTIFACT_NAMES if (run_dir / name).is_file()],
    }


class SnapshotCache:
    """End-of-hour world states per run, from one instrumented rebuild each.

    Keyed by the run directory itself, holding the last few runs anyone looked at.
    A run directory is never rewritten (`open_run_directory` refuses to reuse a
    name), so a cached rebuild never goes stale.
    """

    def __init__(self, keep: int = 4) -> None:
        self._keep = keep
        self._lock = threading.Lock()
        self._snapshots: OrderedDict[Path, Dict[int, WorldState]] = OrderedDict()

    def for_run(self, run_dir: Path) -> Dict[int, WorldState]:
        with self._lock:
            cached = self._snapshots.get(run_dir)
            if cached is not None:
                self._snapshots.move_to_end(run_dir)
                return cached

        replay = load_replay(run_dir / REPLAY_NAME)
        snapshots: Dict[int, WorldState] = {0: replay.initial_state}

        def keep_latest(engine) -> None:
            snapshots[engine.current_state.world_time] = engine.current_state

        # The last write for each hour is the world just before time advances —
        # the end-of-hour view a scrubber wants.
        rebuild(replay, observer=keep_latest)

        with self._lock:
            self._snapshots[run_dir] = snapshots
            while len(self._snapshots) > self._keep:
                self._snapshots.popitem(last=False)
        return snapshots


@router.get("/runs/{stamp}/state", response_model=HourState)
def run_state(request: Request, stamp: str, hour: int = 0) -> HourState:
    run_dir = run_dir_for(request, stamp)
    if not (run_dir / REPLAY_NAME).is_file():
        raise HTTPException(status_code=404, detail=f"{stamp} has no replay to rebuild from")

    snapshots = request.app.state.snapshots.for_run(run_dir)
    last_hour = max(snapshots)
    if hour not in snapshots:
        raise HTTPException(
            status_code=404, detail=f"{stamp} has hours 0..{last_hour}, not {hour}"
        )

    state = snapshots[hour]
    return HourState(
        hour=hour,
        last_hour=last_hour,
        bush=BushGauge(
            current=state.bush.current_berries,
            max=state.bush.max_berries,
            rate=state.bush.regeneration_rate,
        ),
        agents=[
            SeatState(
                agent_id=agent.agent_id,
                name=agent.name,
                hunger=agent.hunger,
                body_state=agent.body_state.name.lower(),
                perceived_type=agent.perceived_type.value,
                sleep_duration=agent.sleep_duration,
                wake_time=agent.wake_time,
                total_berries_consumed=agent.total_berries_consumed,
                time_of_death=agent.time_of_death,
            )
            for agent in state.agents
        ],
    )
