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


# ----------------------------------------------------------------------------
# /api/runs/{stamp}
# ----------------------------------------------------------------------------


def test_run_detail_carries_the_chronicle_and_the_seed(archive: Path, recorded_run: Path) -> None:
    detail = client_for(archive).get(f"/api/runs/{recorded_run.name}").json()

    assert detail["complete"] is True
    assert detail["seed"] == 7
    assert detail["chronicle"]["agent_count"] == 4
    assert detail["chronicle"]["turns"], "a played game has turns"
    assert set(detail["artifacts"]) >= {"session.log", "transcript.txt", "chronicle.json", "replay.json"}


def test_an_unknown_stamp_is_404(archive: Path) -> None:
    assert client_for(archive).get("/api/runs/20990101T000000Z").status_code == 404


def test_a_stamp_that_is_not_a_stamp_is_404_not_a_path(archive: Path) -> None:
    client = client_for(archive)

    assert client.get("/api/runs/..").status_code == 404
    assert client.get("/api/runs/%2e%2e%2fsecrets").status_code == 404
    assert client.get("/api/runs/not-a-stamp").status_code == 404


# ----------------------------------------------------------------------------
# /api/runs/{stamp}/state
# ----------------------------------------------------------------------------


def test_hour_state_is_rebuilt_from_the_replay(archive: Path, recorded_run: Path) -> None:
    client = client_for(archive)

    start = client.get(f"/api/runs/{recorded_run.name}/state", params={"hour": 0}).json()
    assert start["hour"] == 0
    assert len(start["agents"]) == 4
    assert start["bush"]["max"] == 40
    for seat in start["agents"]:
        assert seat["body_state"] in {"dead", "unconscious", "asleep", "awake", "crazy"}

    end = client.get(
        f"/api/runs/{recorded_run.name}/state", params={"hour": start["last_hour"]}
    ).json()
    assert end["hour"] == end["last_hour"]


def test_an_hour_the_run_never_reached_is_404(archive: Path, recorded_run: Path) -> None:
    response = client_for(archive).get(
        f"/api/runs/{recorded_run.name}/state", params={"hour": 9999}
    )

    assert response.status_code == 404
    assert "9999" in response.json()["detail"]


def test_the_second_look_at_a_run_does_not_rebuild(
    archive: Path, recorded_run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import web.runs as web_runs

    loads = []
    real_load = web_runs.load_replay
    monkeypatch.setattr(web_runs, "load_replay", lambda p: loads.append(p) or real_load(p))

    client = client_for(archive)
    client.get(f"/api/runs/{recorded_run.name}/state", params={"hour": 1})
    client.get(f"/api/runs/{recorded_run.name}/state", params={"hour": 2})

    assert len(loads) == 1
