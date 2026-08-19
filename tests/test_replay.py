"""Tests for saving and replaying a game.

The engine is a command pattern over frozen state, so a run is fully described by
its initial state and its commands. These pin that the claim is true in practice
and not only in the design document: a saved run rebuilds the identical world,
down to hunger and berries, and a rebuild that lands anywhere else is an error
rather than a warning.
"""

from pathlib import Path

import pytest

from core.agent import ScriptedAgent
from core.commands import EatBerriesCommand
from core.game_engine import GameEngine
from core.replay import Replay, load_replay, rebuild, save_replay


def played_game(hours: int = 6, names: tuple = ("Alice", "Bob", "Charlie")) -> GameEngine:
    """A real game, played by the scripted arm — no keys, no network."""
    engine = GameEngine.create_new_game(agent_names=list(names))
    for seat_id in range(len(names)):
        seat = ScriptedAgent(agent_id=seat_id, engine=engine)
        engine.decision_callbacks[seat_id] = seat.decision_callback
    for _ in range(hours):
        if not engine.run_turn_cycle():
            break
    return engine


def test_a_replay_rebuilds_the_identical_world(tmp_path: Path) -> None:
    played = played_game()
    save_replay(played, seed=7, path=tmp_path / "replay.json")

    rebuilt = rebuild(load_replay(tmp_path / "replay.json"))

    assert rebuilt.current_state == played.current_state
    assert rebuilt.current_state.world_time == played.current_state.world_time
    assert rebuilt.current_state.bush.current_berries == played.current_state.bush.current_berries
    assert [a.hunger for a in rebuilt.current_state.agents] == [
        a.hunger for a in played.current_state.agents
    ]


def test_every_command_survives_the_round_trip(tmp_path: Path) -> None:
    played = played_game()
    save_replay(played, seed=7, path=tmp_path / "replay.json")

    loaded = load_replay(tmp_path / "replay.json")

    assert len(loaded.commands) == len(played.history)
    assert [c.type for c in loaded.commands] == [type(c).__name__ for c in played.history]
    assert rebuild(loaded).history == played.history


def test_the_seating_and_seed_are_kept_with_the_commands(tmp_path: Path) -> None:
    """A replay that cannot say which seed it ran on cannot reproduce its perception."""
    played = played_game(names=("Alice", "Bob", "Charlie", "Dana"))
    save_replay(played, seed=4242, path=tmp_path / "replay.json")

    loaded = load_replay(tmp_path / "replay.json")

    assert loaded.seed == 4242
    assert loaded.agent_names == ("Alice", "Bob", "Charlie", "Dana")


def test_stopping_part_way_leaves_a_real_world(tmp_path: Path) -> None:
    played = played_game(hours=10)
    save_replay(played, seed=1, path=tmp_path / "replay.json")

    partial = rebuild(load_replay(tmp_path / "replay.json"), stop_at_hour=4)

    assert partial.current_state.world_time == 4
    assert len(partial.history) < len(played.history)
    assert all(agent.hunger > 0 for agent in partial.current_state.agents)


def test_a_replay_that_lands_somewhere_else_is_an_error(tmp_path: Path) -> None:
    """Silence here would mean drawing conclusions about a game that never happened."""
    played = played_game()
    save_replay(played, seed=1, path=tmp_path / "replay.json")
    loaded = load_replay(tmp_path / "replay.json")

    tampered = loaded.model_copy(
        update={
            "final_state": loaded.final_state.model_copy(
                update={"bush": loaded.final_state.bush.model_copy(update={"current_berries": 39.0})}
            )
        }
    )

    with pytest.raises(ValueError, match="diverged"):
        rebuild(tampered)


def test_a_command_this_build_does_not_know_is_refused(tmp_path: Path) -> None:
    """A replay missing a command is not shorter, it is a different game."""
    played = played_game()
    save_replay(played, seed=1, path=tmp_path / "replay.json")
    loaded = load_replay(tmp_path / "replay.json")

    unknown = loaded.commands[0].model_copy(update={"type": "SacrificeCommand"})
    broken = loaded.model_copy(update={"commands": (unknown,) + loaded.commands[1:]})

    with pytest.raises(ValueError, match="SacrificeCommand"):
        rebuild(broken)


def test_a_file_from_another_format_is_refused(tmp_path: Path) -> None:
    played = played_game(hours=2)
    save_replay(played, seed=1, path=tmp_path / "replay.json")
    text = (tmp_path / "replay.json").read_text(encoding="utf-8")
    (tmp_path / "old.json").write_text(text.replace('"format": 1', '"format": 0'), encoding="utf-8")

    with pytest.raises(ValueError, match="format"):
        load_replay(tmp_path / "old.json")


def test_a_command_added_later_is_replayable_without_registering_it() -> None:
    """The registry is walked from the base class, not maintained by hand."""
    from core.replay import _command_types

    known = _command_types()

    assert "EatBerriesCommand" in known
    assert known["EatBerriesCommand"] is EatBerriesCommand
    assert "Command" not in known, "the abstract base is not a command anyone can replay"


def test_an_observer_sees_every_command_pass(tmp_path: Path) -> None:
    """One instrumented rebuild can snapshot the whole run — that is what the web
    scrubber leans on instead of rebuilding once per hour."""
    played = played_game()
    save_replay(played, seed=7, path=tmp_path / "replay.json")
    replay = load_replay(tmp_path / "replay.json")

    seen: list[int] = []
    snapshots = {0: replay.initial_state}

    def watch(engine: GameEngine) -> None:
        seen.append(engine.current_state.world_time)
        snapshots[engine.current_state.world_time] = engine.current_state

    rebuilt = rebuild(replay, observer=watch)

    assert len(seen) == len(replay.commands)
    assert snapshots[max(snapshots)] == rebuilt.current_state
    # The last write per hour is the world just before time advanced.
    assert sorted(snapshots) == list(range(max(snapshots) + 1))
