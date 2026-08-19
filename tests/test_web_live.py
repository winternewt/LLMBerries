"""Tests for the live bridge: launching, watching and stopping a game over HTTP.

Everything runs scripted — the worker thread plays a real game through the real
runner, in-process, with no keys — and the feed is checked against the sealed
chronicle, because a live stream that disagrees with the record is worse than no
stream at all.
"""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from web.app import create_app

LAUNCH = {"agents": 4, "scripted": True, "max_hours": 6, "seed": 5}


def wait_for_finish(client: TestClient, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = client.get("/api/games/current").json()
        if snapshot["phase"] in ("finished", "failed"):
            return snapshot
        time.sleep(0.05)
    pytest.fail("the game never finished")


def sse_items(body: str) -> list[tuple[str, str]]:
    """(event, data) pairs out of a raw SSE body."""
    items = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            items.append((lines["event"], lines.get("data", "")))
    return items


def test_a_launched_game_plays_out_and_lands_in_the_archive(tmp_path: Path) -> None:
    client = TestClient(create_app(runs_root=tmp_path))

    born = client.post("/api/games", json=LAUNCH)
    assert born.status_code == 201
    stamp = born.json()["stamp"]
    assert born.json()["seed"] == 5

    ended = wait_for_finish(client)
    assert ended["phase"] == "finished"

    listed = client.get("/api/runs").json()["runs"]
    assert [row["stamp"] for row in listed] == [stamp]
    assert listed[0]["complete"] is True


def test_the_feed_from_zero_matches_the_sealed_chronicle(tmp_path: Path) -> None:
    client = TestClient(create_app(runs_root=tmp_path))
    stamp = client.post("/api/games", json=LAUNCH).json()["stamp"]
    wait_for_finish(client)

    # The stream terminates once the game is over and the feed is drained, so a
    # plain GET returns the whole run — which is exactly the catch-up path a
    # client connecting mid-game uses.
    items = sse_items(client.get("/api/games/current/stream").text)
    turn_count = sum(1 for kind, _ in items if kind == "turn")

    chronicle = client.get(f"/api/runs/{stamp}").json()["chronicle"]
    assert turn_count == len(chronicle["turns"])
    assert items[-1][0] == "status"
    assert any(kind == "event" for kind, _ in items)


def test_a_second_launch_is_refused_while_one_runs(tmp_path: Path) -> None:
    client = TestClient(create_app(runs_root=tmp_path))
    slow = dict(LAUNCH, max_hours=50, hour_delay=0.2)
    assert client.post("/api/games", json=slow).status_code == 201

    refused = client.post("/api/games", json=LAUNCH)
    assert refused.status_code == 409

    assert client.post("/api/games/current/stop").json() == {"stopping": True}
    wait_for_finish(client)


def test_a_stopped_game_still_seals_its_artifacts(tmp_path: Path) -> None:
    client = TestClient(create_app(runs_root=tmp_path))
    stamp = client.post("/api/games", json=dict(LAUNCH, max_hours=50, hour_delay=0.2)).json()[
        "stamp"
    ]
    client.post("/api/games/current/stop")
    ended = wait_for_finish(client)

    assert ended["phase"] == "finished"
    detail = client.get(f"/api/runs/{stamp}").json()
    assert detail["complete"] is True
    assert "replay.json" in detail["artifacts"]
    # And it can be scrubbed like any archived run.
    assert client.get(f"/api/runs/{stamp}/state", params={"hour": 0}).status_code == 200


def test_stopping_nothing_is_a_409(tmp_path: Path) -> None:
    client = TestClient(create_app(runs_root=tmp_path))
    assert client.post("/api/games/current/stop").status_code == 409


def test_free_text_cannot_ride_the_launch_request(tmp_path: Path) -> None:
    client = TestClient(create_app(runs_root=tmp_path))

    refused = client.post("/api/games", json=dict(LAUNCH, zombie="a made up thing"))
    assert refused.status_code == 422
    refused = client.post("/api/games", json=dict(LAUNCH, providers=["not a provider"]))
    assert refused.status_code == 422
