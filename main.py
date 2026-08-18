"""Run a game of LLMBerries.

    uv run python main.py                          # 3 LLM agents, live keys
    uv run python main.py --agents 5               # a bigger circle
    uv run python main.py --scripted               # deterministic, no API calls
    uv run python main.py --providers google,groq  # choose who answers

Check the keys first with `uv run python scripts/key_test.py`; a provider that
refuses mid-game costs its agent the turn.
"""

import logging
import random
import sys
from typing import Dict, List, Optional

import typer
from dotenv import load_dotenv

from core.agent import Agent, LLMAgent, ScriptedAgent
from core.constants import MAX_RUN_TIME, MIN_AGENT_COUNT
from core.game_engine import GameEngine
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
    engine: GameEngine, scripted: bool, providers: List[ProviderSpec]
) -> List[Agent]:
    """One agent per seat. LLM agents take providers round-robin."""
    count = engine.current_state.agent_count
    if scripted:
        return [ScriptedAgent(agent_id=i, engine=engine) for i in range(count)]
    return [
        LLMAgent(agent_id=i, engine=engine, provider=providers[i % len(providers)])
        for i in range(count)
    ]


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
    seats = build_agents(engine, scripted=scripted, providers=provider_specs)

    callbacks: Dict[int, object] = engine.decision_callbacks
    for seat in seats:
        callbacks[seat.agent_id] = seat.decision_callback

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

    report(engine)


if __name__ == "__main__":
    app()
