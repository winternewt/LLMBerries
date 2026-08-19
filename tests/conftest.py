"""Shared fixtures.

`recorded_run` plays one scripted game through the real CLI so web tests read the
same artifacts a person's run leaves behind — nothing hand-built, nothing mocked,
and no API calls. Session-scoped: the game is deterministic (seeded), so every
test reads the same recording.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

import main


@pytest.fixture(scope="session")
def recorded_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("runs")
    result = CliRunner().invoke(
        main.app,
        ["--scripted", "--agents", "4", "--max-hours", "16", "--seed", "7", "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    run_dirs = [entry for entry in out.iterdir() if entry.is_dir()]
    assert len(run_dirs) == 1
    return run_dirs[0]
