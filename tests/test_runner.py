"""Tests for the extracted game runner.

`main.py` and the web layer both drive games through `core/runner.py`; these pin
that the mechanics are the CLI's mechanics — same artifacts, same replayability —
and that a cooperative stop still seals a valid record.
"""

import threading
from pathlib import Path

import pytest

from core.enums import EventType
from core.record import CHRONICLE_NAME, SESSION_LOG_NAME, TRANSCRIPT_NAME
from core.replay import REPLAY_NAME, load_replay, rebuild
from core.runner import GameConfig, prepare_game, run_prepared, write_artifacts


def scripted_config(tmp_path: Path, **overrides) -> GameConfig:
    values = dict(agents=4, scripted=True, max_hours=8, seed=11, out=tmp_path)
    values.update(overrides)
    return GameConfig(**values)


def test_a_prepared_game_leaves_the_full_artifact_set(tmp_path: Path) -> None:
    prepared = prepare_game(scripted_config(tmp_path))
    record = run_prepared(prepared)
    write_artifacts(prepared, record)
    prepared.close()

    assert prepared.run_dir is not None
    names = {entry.name for entry in prepared.run_dir.iterdir()}
    assert names == {SESSION_LOG_NAME, TRANSCRIPT_NAME, CHRONICLE_NAME, REPLAY_NAME}
    assert record.hours_played == 8
    assert record.agent_count == 4


def test_the_run_replays_to_the_same_world(tmp_path: Path) -> None:
    prepared = prepare_game(scripted_config(tmp_path))
    record = run_prepared(prepared)
    write_artifacts(prepared, record)
    prepared.close()

    rebuilt = rebuild(load_replay(prepared.run_dir / REPLAY_NAME))

    assert rebuilt.current_state == prepared.engine.current_state


def test_a_stop_event_ends_the_game_between_hours(tmp_path: Path) -> None:
    prepared = prepare_game(scripted_config(tmp_path, max_hours=50))
    stop = threading.Event()
    prepared.engine.event_bus.subscribe_to_type(
        EventType.TIME_ADVANCED,
        lambda name, event: stop.set() if event.game_time >= 3 else None,
    )

    record = run_prepared(prepared, stop=stop)
    write_artifacts(prepared, record)
    prepared.close()

    assert record.hours_played < 50
    # A stopped run is still a whole recording: it replays to the world it left.
    rebuilt = rebuild(load_replay(prepared.run_dir / REPLAY_NAME))
    assert rebuilt.current_state == prepared.engine.current_state


def test_a_missing_seed_is_drawn_and_recorded(tmp_path: Path) -> None:
    prepared = prepare_game(scripted_config(tmp_path, seed=None))
    record = run_prepared(prepared)
    write_artifacts(prepared, record)
    prepared.close()

    assert isinstance(prepared.seed, int)
    assert load_replay(prepared.run_dir / REPLAY_NAME).seed == prepared.seed


def test_an_unrecorded_game_touches_no_disk(tmp_path: Path) -> None:
    prepared = prepare_game(scripted_config(tmp_path, record=False))
    record = run_prepared(prepared)
    rendered = write_artifacts(prepared, record)
    prepared.close()

    assert prepared.run_dir is None
    assert list(tmp_path.iterdir()) == []
    assert rendered, "the transcript still renders; it is just not kept"
