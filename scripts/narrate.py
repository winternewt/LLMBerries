"""Tell the story of a game that was already played.

    uv run python scripts/narrate.py run.json --out story.md
    uv run python scripts/narrate.py run.json --transcript-only

`--transcript-only` needs no key: it prints the raw record — every turn, the
reasoning behind it, who said what — without asking a model to shape it.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.chronicler import load_chronicle  # noqa: E402  (path set up above)
from core.narrator import Narrator, render_transcript  # noqa: E402
from entities.llm_configs import LLM_SET, get_provider_by_name  # noqa: E402

logger = logging.getLogger("narrate")

app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    chronicle_path: Path = typer.Argument(..., help="Chronicle JSON written by a game run"),
    out: Optional[Path] = typer.Option(None, help="Write the story here instead of stdout"),
    provider: Optional[str] = typer.Option(
        None, help="Provider to narrate with; defaults to the first configured one"
    ),
    hours_per_chapter: int = typer.Option(8, min=1, help="Game hours per narrated passage"),
    transcript_only: bool = typer.Option(
        False, "--transcript-only", help="Print the raw record, no model, no key"
    ),
) -> None:
    """Narrate a saved chronicle."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    load_dotenv()

    chronicle = load_chronicle(chronicle_path)

    if transcript_only:
        text = render_transcript(chronicle)
    else:
        spec = get_provider_by_name(provider) if provider else LLM_SET[0]
        if not chronicle.has_reasoning():
            logger.info(
                "No provider in this run exposed its reasoning; the story rests on "
                "actions and messages alone."
            )
        logger.info("Narrating %d turns with %s...", len(chronicle.turns), spec.name)
        text = Narrator(spec, hours_per_chapter=hours_per_chapter).narrate(chronicle)

    if out is None:
        typer.echo(text)
        return

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    typer.echo(f"Written to {out}")


if __name__ == "__main__":
    app()
