"""Play a finished game back from its commands.

    uv run python scripts/replay.py runs/20260819T012345Z
    uv run python scripts/replay.py runs/20260819T012345Z/replay.json --verbose
    uv run python scripts/replay.py runs/20260819T012345Z --at 12

No model is called and no key is spent. The run is rebuilt from what it actually
did rather than asked again what it would do, so the world it lands in is the same
world down to the last berry — and if it is not, that is an error and says so.

`--at HOUR` stops the rebuild at the start of an hour, which is what a branch is
made from: the state is real and the rest of history has not happened yet.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

import typer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.replay import REPLAY_NAME, load_replay, rebuild  # noqa: E402  (path set up above)

logger = logging.getLogger("replay")

app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    run: Path = typer.Argument(..., help="A run directory, or the replay.json inside one"),
    at: Optional[int] = typer.Option(
        None, help="Stop at the start of this game hour instead of replaying the whole run"
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Log every command as it replays"),
) -> None:
    """Rebuild the game and report where it lands."""
    # The engine narrates itself at INFO while it runs, which on a replay is the
    # same wall of events twice. Quiet unless asked.
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(message)s",
        stream=sys.stdout,
    )

    path = run / REPLAY_NAME if run.is_dir() else run
    if not path.exists():
        raise typer.BadParameter(f"no replay at {path}")

    loaded = load_replay(path)
    typer.echo(
        f"Replaying {len(loaded.commands)} commands over {len(loaded.agent_names)} seats "
        f"(seed {loaded.seed}): {', '.join(loaded.agent_names)}"
    )

    engine = rebuild(loaded, stop_at_hour=at)
    state = engine.current_state

    if at is None:
        typer.echo("Replay matches the recorded ending, command for command.")
    else:
        typer.echo(f"Stopped at hour {state.world_time}, {len(engine.history)} commands in.")

    typer.echo("")
    typer.echo(f"  Hour {state.world_time}, bush at {state.bush.current_berries:.1f}")
    for agent in state.agents:
        standing = f"hunger {agent.hunger:.1f}" if agent.alive else "gone"
        typer.echo(
            f"  {agent.name:<10} {standing}, ate {agent.total_berries_consumed} berries"
        )


if __name__ == "__main__":
    app()
