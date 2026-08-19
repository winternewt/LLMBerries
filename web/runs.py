"""The tape archive: what finished (or crashed) runs look like from the outside.

A run directory with no chronicle is still listed — a crash is evidence, not
garbage — it is just marked incomplete. Stamps are validated against the exact
shape `open_run_directory` produces, which is also what keeps a path traversal
from ever reaching the filesystem.
"""

import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from core.chronicler import load_chronicle
from core.constants import MAX_BERRIES, MAX_HUNGER, MAX_RUN_TIME, MIN_AGENT_COUNT
from core.framing import Framing
from core.record import CHRONICLE_NAME, STORY_NAME
from core.zombie import ZombieFlavour
from entities.llm_configs import LLM_SET
from web.schemas import MetaResponse, RunListItem, RunListResponse

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
