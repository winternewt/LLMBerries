"""Run a game of LLMBerries.

    uv run python main.py                          # 3 LLM agents, live keys
    uv run python main.py --agents 5               # a bigger circle
    uv run python main.py --scripted               # deterministic, no API calls
    uv run python main.py --providers google,groq  # choose who answers
    uv run python main.py --story story.md         # narrate why they did it
    uv run python main.py --scripted --transcript run.txt   # raw record, no API

Check the keys first with `uv run python scripts/key_test.py`; a provider that
refuses mid-game costs its agent the turn.
"""

import logging
import random
import sys
from pathlib import Path
from typing import List, Optional

import typer
from dotenv import load_dotenv

from core.agent import Agent, LLMAgent, ScriptedAgent
from core.chronicler import Chronicler, save_chronicle
from core.constants import MAX_RUN_TIME, MIN_AGENT_COUNT
from core.game_engine import GameEngine
from core.narrator import Narrator, render_transcript
from entities.llm_configs import LLM_SET, ProviderSpec, get_provider_by_name

logger = logging.getLogger("llmberries")

DEFAULT_NAMES: tuple[str, ...] = (
    "Alice", "Bob", "Charlie", "Dana", "Eli", "Fen", "Gus", "Hana",
)

app = typer.Typer(add_completion=False, help=__doc__)


def agent_names(count: int) -> List[str]:
    """Names for `count` agents, extending past the built-in list if asked."""
    if count <= len(DEFAULT_NAMES):
        return list(DEFAULT_NAMES[:count])
    extra = [f"Agent{i}" for i in range(len(DEFAULT_NAMES), count)]
    return list(DEFAULT_NAMES) + extra


def resolve_providers(names: Optional[str]) -> List[ProviderSpec]:
    if names is None:
        return list(LLM_SET)
    return [get_provider_by_name(name.strip()) for name in names.split(",") if name.strip()]


def build_agents(
    engine: GameEngine,
    scripted: bool,
    providers: List[ProviderSpec],
    chronicler: Chronicler,
) -> List[Agent]:
    """One agent per seat. LLM agents take providers round-robin."""
    count = engine.current_state.agent_count
    if scripted:
        return [
            ScriptedAgent(agent_id=i, engine=engine, chronicler=chronicler)
            for i in range(count)
        ]
    return [
        LLMAgent(
            agent_id=i,
            engine=engine,
            chronicler=chronicler,
            provider=providers[i % len(providers)],
        )
        for i in range(count)
    ]


def report_losses(record) -> None:
    """Say plainly when a run was decided by refused calls rather than by choices."""
    lost = record.turns_lost()
    total = len(record.turns)
    if lost == 0:
        return

    share = lost / total if total else 0.0
    typer.echo("")
    typer.echo(f"  WARNING: {lost}/{total} turns were lost to refused model calls.")
    for summary in record.agents:
        if summary.turns_lost:
            typer.echo(
                f"    {summary.name} ({summary.provider or 'scripted'}): "
                f"{summary.turns_lost}/{summary.turns_taken} lost"
            )
    if share >= 0.25:
        typer.echo(
            "    Most of this game was decided by calls that never happened, not by "
            "anything the agents chose. Read the outcome as a quota failure."
        )


def report(engine: GameEngine) -> None:
    state = engine.current_state
    survivors = [agent for agent in state.agents if agent.alive]

    typer.echo("")
    typer.echo("=" * 60)
    typer.echo(f"GAME OVER after {state.world_time} hours")
    typer.echo("=" * 60)
    for agent in state.agents:
        fate = (
            f"alive, hunger {agent.hunger:.1f}"
            if agent.alive
            else f"died at hour {agent.time_of_death:.0f}"
        )
        typer.echo(f"  {agent.name:<10} ate {agent.total_berries_consumed:>3} berries — {fate}")
    typer.echo(f"  Bush: {state.bush.current_berries:.1f}/{state.bush.max_berries:.0f} berries left")
    typer.echo(f"  Survivors: {len(survivors)}/{state.agent_count}")
    typer.echo(f"  Outcome: {engine.outcome.value}")
    typer.echo(f"  Commands: {len(engine.history)}, events: {len(engine.events)}")


@app.command()
def play(
    agents: int = typer.Option(MIN_AGENT_COUNT, min=MIN_AGENT_COUNT, help="Agents in the circle"),
    scripted: bool = typer.Option(False, "--scripted", help="Rule-based agents, no API calls"),
    providers: Optional[str] = typer.Option(
        None, help="Comma-separated provider names; default is every configured provider"
    ),
    max_hours: int = typer.Option(MAX_RUN_TIME, help="Stop after this many game hours"),
    seed: Optional[int] = typer.Option(None, help="Seed for the perception noise"),
    verbose: bool = typer.Option(False, "--verbose", help="Log every engine event"),
    story: Optional[Path] = typer.Option(
        None, help="Write the narrated story here (needs a live provider)"
    ),
    narrator: Optional[str] = typer.Option(
        None, help="Provider that tells the story; defaults to the first one playing"
    ),
    transcript: Optional[Path] = typer.Option(
        None, help="Write the raw reasoning transcript here — no API calls"
    ),
    chronicle_out: Optional[Path] = typer.Option(
        None, "--chronicle", help="Write the chronicle as JSON for narrating later"
    ),
) -> None:
    """Play one game and report how it ended."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        stream=sys.stdout,
    )
    load_dotenv()

    if seed is not None:
        random.seed(seed)

    provider_specs = resolve_providers(providers)
    engine = GameEngine.create_new_game(agent_names=agent_names(agents))
    chronicler = Chronicler(engine)
    seats = build_agents(
        engine, scripted=scripted, providers=provider_specs, chronicler=chronicler
    )

    for seat in seats:
        engine.decision_callbacks[seat.agent_id] = seat.decision_callback
        engine.reflection_callbacks[seat.agent_id] = seat.reflection_callback

    if scripted:
        typer.echo(f"Playing {agents} scripted agents (no API calls).")
    else:
        assignments = ", ".join(
            f"{seat.name}={seat.provider.name}" for seat in seats if isinstance(seat, LLMAgent)
        )
        typer.echo(f"Playing {agents} LLM agents — {assignments}")

    hours = 0
    while hours < max_hours and engine.run_turn_cycle():
        hours += 1

    if engine.game_over:
        engine.run_epilogue()

    report(engine)
    record = chronicler.seal()
    report_losses(record)

    if chronicle_out is not None:
        save_chronicle(record, chronicle_out)
        typer.echo(f"Chronicle: {chronicle_out}")

    if transcript is not None:
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(render_transcript(record), encoding="utf-8")
        typer.echo(f"Transcript: {transcript}")

    if story is not None:
        teller = get_provider_by_name(narrator) if narrator else provider_specs[0]
        if not record.has_reasoning():
            typer.echo(
                f"Note: no provider in this run exposed its reasoning, so the story is "
                f"built from actions and messages only."
            )
        typer.echo(f"Narrating with {teller.name}...")
        story.parent.mkdir(parents=True, exist_ok=True)
        story.write_text(Narrator(teller).narrate(record), encoding="utf-8")
        typer.echo(f"Story: {story}")


if __name__ == "__main__":
    app()
