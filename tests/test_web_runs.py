"""Tests for the tape archive: the web layer over recorded runs.

Everything here goes through `create_app(runs_root=...)` on a temporary tree and a
real recorded run — the same artifacts the CLI writes, not fixtures shaped by hand.
"""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.record import CHRONICLE_NAME
from web.app import create_app


@pytest.fixture
def archive(tmp_path: Path, recorded_run: Path) -> Path:
    """A runs directory holding one copy of the recorded run."""
    shutil.copytree(recorded_run, tmp_path / recorded_run.name)
    return tmp_path


def client_for(root: Path) -> TestClient:
    return TestClient(create_app(runs_root=root))


# ----------------------------------------------------------------------------
# /api/meta
# ----------------------------------------------------------------------------


def test_meta_offers_the_closed_vocabulary() -> None:
    meta = client_for(Path("does-not-exist")).get("/api/meta").json()

    assert "google" in meta["providers"] and "groq" in meta["providers"]
    assert "town_crazy" in meta["zombie_flavours"]
    assert meta["framings"] == ["silent", "tinag", "scored"]
    assert meta["min_agents"] == 3
    assert meta["max_berries"] == 40


# ----------------------------------------------------------------------------
# /api/runs
# ----------------------------------------------------------------------------


def test_a_missing_archive_is_empty_not_an_error(tmp_path: Path) -> None:
    response = client_for(tmp_path / "never-made").get("/api/runs")

    assert response.status_code == 200
    assert response.json() == {"runs": []}


def test_a_recorded_run_is_listed_with_its_summary(archive: Path, recorded_run: Path) -> None:
    runs = client_for(archive).get("/api/runs").json()["runs"]

    assert len(runs) == 1
    row = runs[0]
    assert row["stamp"] == recorded_run.name
    assert row["complete"] is True
    assert row["agent_count"] == 4
    assert row["hours_played"] > 0
    assert row["framing"] == "silent"
    assert row["providers"] == ["scripted"]
    assert row["has_story"] is False


def test_a_run_without_a_chronicle_is_listed_incomplete(archive: Path, recorded_run: Path) -> None:
    crashed = archive / "20260101T000000Z"
    shutil.copytree(recorded_run, crashed)
    (crashed / CHRONICLE_NAME).unlink()

    runs = client_for(archive).get("/api/runs").json()["runs"]

    by_stamp = {row["stamp"]: row for row in runs}
    assert by_stamp["20260101T000000Z"]["complete"] is False
    assert by_stamp[recorded_run.name]["complete"] is True


def test_stray_directories_are_not_runs(archive: Path) -> None:
    (archive / "not-a-stamp").mkdir()
    (archive / "loose-file.txt").write_text("noise", encoding="utf-8")

    runs = client_for(archive).get("/api/runs").json()["runs"]

    assert [row["stamp"] for row in runs] == [entry.name for entry in archive.iterdir()
                                              if entry.is_dir() and entry.name != "not-a-stamp"]
