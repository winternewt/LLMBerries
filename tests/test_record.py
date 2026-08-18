"""Tests for what a run leaves behind.

The failure these pin was found in a real run and is the worst kind: the world
changed and the record said nothing had happened. Agno executes tools one at a
time and re-calls the model between them, so a turn can eat twenty berries and
then hit the daily token cap. `RunOutput.tools` comes back empty on a failed run,
so the chronicle showed `turn_lost` with no actions — while half the bush was gone
and the next agent's observation could not explain why.

The second half is about keeping any record at all: artifacts used to be written
only when asked for, to a path the caller named, so an unasked run left nothing
and a second run under the same name destroyed the first.
"""

import logging
from pathlib import Path

import pytest

from core.agent import LLMAgent
from core.game_engine import GameEngine
from core.record import SessionLog, open_run_directory
from entities.chronicle import GameChronicle, ToolCall, TurnRecord
from entities.llm_configs import GROQ
from core.keydrum import reset_drums
from core.narrator import render_transcript


@pytest.fixture
def engine() -> GameEngine:
    return GameEngine.create_new_game(agent_names=["Alice", "Bob", "Charlie"])


@pytest.fixture
def agent(engine: GameEngine, monkeypatch: pytest.MonkeyPatch) -> LLMAgent:
    """A real LLMAgent on a fake key. Nothing here reaches the network."""
    reset_drums()
    monkeypatch.setenv("GROQ_API_KEY", "not-a-real-key")
    seated = LLMAgent(agent_id=0, engine=engine, provider=GROQ)
    yield seated
    reset_drums()


# ----------------------------------------------------------------------------
# A turn records what it did, at the moment it does it
# ----------------------------------------------------------------------------


def test_a_tool_is_recorded_when_it_runs(agent: LLMAgent) -> None:
    result = agent._paced_tool("eat_berries", lambda count: f"harvested {count}", {"count": 5})

    assert result == "harvested 5"
    assert len(agent._executed) == 1
    call = agent._executed[0]
    assert call.name == "eat_berries"
    assert call.args == {"count": "5"}
    assert call.result == "harvested 5"
    assert call.failed is False


def test_a_tool_that_raises_is_recorded_and_the_failure_still_propagates(
    agent: LLMAgent,
) -> None:
    def refuses(**_: object) -> str:
        raise RuntimeError("bush is empty")

    with pytest.raises(RuntimeError, match="bush is empty"):
        agent._paced_tool("eat_berries", refuses, {"count": 1})

    assert agent._executed[0].failed is True, "the record keeps the attempt"
    assert "bush is empty" in (agent._executed[0].result or "")


def test_actions_survive_a_failure_that_arrives_after_them(agent: LLMAgent) -> None:
    """The exact shape of the real bug: three tools ran, then the provider refused."""
    for count in (5, 5, 10):
        agent._paced_tool("eat_berries", lambda count: f"harvested {count}", {"count": count})

    record = TurnRecord(
        hour=0,
        agent_id=0,
        agent_name="Bob",
        hunger=20.0,
        bush_berries=35,
        tool_calls=tuple(agent._executed),
        error="Rate limit reached ... tokens per day (TPD): Limit 200000",
    )

    assert record.turn_lost is False, "twenty berries left the bush; that is not a lost turn"
    assert record.turn_cut_short is True
    assert record.berries_taken() == 20


# ----------------------------------------------------------------------------
# Lost and cut short are different things and the record says which
# ----------------------------------------------------------------------------


def a_turn(**fields: object) -> TurnRecord:
    base = dict(hour=0, agent_id=0, agent_name="Bob", hunger=20.0, bush_berries=35)
    base.update(fields)
    return TurnRecord(**base)


def test_a_call_that_failed_before_anything_ran_is_a_lost_turn() -> None:
    record = a_turn(error="402 payment required")

    assert record.turn_lost is True
    assert record.turn_cut_short is False


def test_a_turn_with_no_error_is_neither() -> None:
    record = a_turn(tool_calls=(ToolCall(name="think", args={"thought": "hm"}),))

    assert record.turn_lost is False
    assert record.turn_cut_short is False


def test_the_chronicle_counts_the_two_separately() -> None:
    chronicle = GameChronicle(
        agent_count=3,
        hours_played=1,
        turns=(
            a_turn(error="refused"),
            a_turn(tool_calls=(ToolCall(name="eat_berries", args={"count": "5"}),), error="refused"),
        ),
        agents=(),
        berries_left=1.0,
    )

    assert chronicle.turns_lost() == 1
    assert chronicle.turns_cut_short() == 1


def test_the_transcript_shows_the_actions_of_a_cut_short_turn() -> None:
    chronicle = GameChronicle(
        agent_count=3,
        hours_played=1,
        turns=(
            a_turn(
                tool_calls=(ToolCall(name="eat_berries", args={"count": "10"}, result="took 10"),),
                error="tokens per day (TPD): Limit 200000",
            ),
        ),
        agents=(),
        berries_left=1.0,
    )

    text = render_transcript(chronicle)

    assert "eat_berries" in text, "the ten berries really left the bush"
    assert "CUT SHORT" in text
    assert "TURN LOST" not in text
    assert "tokens per day" in text


# ----------------------------------------------------------------------------
# The run directory
# ----------------------------------------------------------------------------


def test_a_run_directory_is_new_and_empty(tmp_path: Path) -> None:
    made = open_run_directory(tmp_path)

    assert made.is_dir()
    assert list(made.iterdir()) == []
    assert made.parent == tmp_path


def test_two_runs_in_the_same_second_do_not_share_a_directory(tmp_path: Path) -> None:
    """Overwriting an earlier run's evidence is the failure this prevents."""
    first = open_run_directory(tmp_path)
    second = open_run_directory(tmp_path)

    assert first != second
    assert first.exists() and second.exists()


def test_the_session_log_reaches_disk(tmp_path: Path) -> None:
    log = SessionLog(tmp_path / "session.log").attach("command: uv run python main.py")
    logging.getLogger("llmberries.test").info("Alice harvested 5 berries")
    log.detach()

    written = (tmp_path / "session.log").read_text(encoding="utf-8")
    assert "command: uv run python main.py" in written
    assert "Alice harvested 5 berries" in written


def test_the_session_log_refuses_to_write_over_an_existing_one(tmp_path: Path) -> None:
    (tmp_path / "session.log").write_text("an earlier run", encoding="utf-8")

    with pytest.raises(FileExistsError):
        SessionLog(tmp_path / "session.log").attach()

    assert (tmp_path / "session.log").read_text(encoding="utf-8") == "an earlier run"


def test_keeping_a_debug_log_does_not_make_the_console_shout(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """The file wants everything; the terminal wants what it asked for."""
    root = logging.getLogger()
    console = logging.StreamHandler()
    root.addHandler(console)
    previous = root.level
    root.setLevel(logging.INFO)
    try:
        log = SessionLog(tmp_path / "session.log").attach()
        logging.getLogger("llmberries.quiet").debug("pacer waited 2.1s")
        log.detach()
    finally:
        root.removeHandler(console)
        root.setLevel(previous)

    assert "pacer waited 2.1s" in (tmp_path / "session.log").read_text(encoding="utf-8")
    assert "pacer waited 2.1s" not in capsys.readouterr().err


# ----------------------------------------------------------------------------
# What a run actually leaves behind, through the CLI
# ----------------------------------------------------------------------------


def test_a_plain_run_records_itself_without_being_asked(tmp_path: Path) -> None:
    """Nobody passed --transcript. The evidence exists anyway; that is the point."""
    from typer.testing import CliRunner

    from core.record import CHRONICLE_NAME, SESSION_LOG_NAME, TRANSCRIPT_NAME
    from core.replay import REPLAY_NAME
    from main import app

    result = CliRunner().invoke(
        app, ["--scripted", "--agents", "3", "--seed", "5", "--out", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output

    made = [child for child in tmp_path.iterdir() if child.is_dir()]
    assert len(made) == 1, "one run, one directory"
    kept = {child.name for child in made[0].iterdir()}
    assert kept == {SESSION_LOG_NAME, TRANSCRIPT_NAME, CHRONICLE_NAME, REPLAY_NAME}


def test_the_replay_beside_the_transcript_rebuilds_the_same_game(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from core.replay import REPLAY_NAME, load_replay, rebuild
    from main import app

    result = CliRunner().invoke(
        app, ["--scripted", "--agents", "4", "--seed", "5", "--out", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    run_dir = next(child for child in tmp_path.iterdir() if child.is_dir())

    replayed = rebuild(load_replay(run_dir / REPLAY_NAME))

    assert f"Bush: {replayed.current_state.bush.current_berries:.1f}" in result.output
    for agent in replayed.current_state.agents:
        assert f"ate {agent.total_berries_consumed:>3} berries" in result.output


def test_two_runs_keep_both_records(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from main import app

    runner = CliRunner()
    for _ in range(2):
        assert (
            runner.invoke(app, ["--scripted", "--agents", "3", "--out", str(tmp_path)]).exit_code
            == 0
        )

    assert len([child for child in tmp_path.iterdir() if child.is_dir()]) == 2


def test_a_run_told_not_to_record_leaves_nothing(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from main import app

    result = CliRunner().invoke(
        app, ["--scripted", "--agents", "3", "--no-record", "--out", str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []
