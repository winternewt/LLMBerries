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
from core.zombie import ZombieAgent, ZombieFlavour, parse_flavours
from core.keydrum import LEDGER
from entities.llm_configs import (
    LLM_SET,
    ProviderSpec,
    get_drum_for,
    get_provider_by_name,
    pick_narrator,
    remaining_budget,
)

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
    """Providers to seat, in the order given.

    The order is the assignment: the point of the study is which model is in which
    seat, so `--providers groq,google` puts a different model on either side of every
    thinking agent, and the record says which was which.
    """
    if names is None:
        return list(LLM_SET)
    return [get_provider_by_name(name.strip()) for name in names.split(",") if name.strip()]


def build_agents(
    engine: GameEngine,
    scripted: bool,
    providers: List[ProviderSpec],
    chronicler: Chronicler,
    zombies: Optional[List[ZombieFlavour]] = None,
    seed: Optional[int] = None,
) -> List[Agent]:
    """One agent per seat.

    Zombies take the last seats, so the thinking ones sit together and each has at
    least one babbling neighbour. Everyone else gets a provider round-robin, or is
    scripted when no keys are being spent.
    """
    count = engine.current_state.agent_count
    zombies = zombies or []
    if len(zombies) > count:
        raise ValueError(f"{len(zombies)} zombies asked for but only {count} seats")

    first_zombie_seat = count - len(zombies)
    seats: List[Agent] = []

    for seat_id in range(count):
        if seat_id >= first_zombie_seat:
            seats.append(
                ZombieAgent(
                    agent_id=seat_id,
                    engine=engine,
                    chronicler=chronicler,
                    flavour=zombies[seat_id - first_zombie_seat],
                    seed=seed if seed is not None else 0,
                )
            )
        elif scripted:
            seats.append(ScriptedAgent(agent_id=seat_id, engine=engine, chronicler=chronicler))
        else:
            seats.append(
                LLMAgent(
                    agent_id=seat_id,
                    engine=engine,
                    chronicler=chronicler,
                    provider=providers[seat_id % len(providers)],
                )
            )
    return seats


def report_spend() -> None:
    """What this run actually cost each provider."""
    spend = LEDGER.summary()
    if not spend:
        return
    typer.echo("")
    typer.echo("  Spent this run:")
    for provider, calls, tokens in spend:
        typer.echo(f"    {provider}: {calls} calls, {tokens:,} tokens")


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
    zombies: Optional[str] = typer.Option(
        None,
        help="Comma-separated flavours to seat as zombies, last seats first: "
             "town_crazy, pirate, gorlum, ghurl, deaf_hatter",
    ),
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
    flavours = parse_flavours(zombies) if zombies else []
    engine = GameEngine.create_new_game(agent_names=agent_names(agents))
    chronicler = Chronicler(engine)
    seats = build_agents(
        engine,
        scripted=scripted,
        providers=provider_specs,
        chronicler=chronicler,
        zombies=flavours,
        seed=seed,
    )

    for seat in seats:
        engine.decision_callbacks[seat.agent_id] = seat.decision_callback
        engine.reflection_callbacks[seat.agent_id] = seat.reflection_callback

    described = ", ".join(
        f"{seat.name}="
        + (
            f"zombie/{seat.flavour.value}"
            if isinstance(seat, ZombieAgent)
            else seat.provider.name
            if isinstance(seat, LLMAgent)
            else "scripted"
        )
        for seat in seats
    )
    typer.echo(f"Seated {agents} — {described}")
    thinking = [seat for seat in seats if isinstance(seat, LLMAgent)]
    if thinking:
        distinct = {seat.provider.name for seat in thinking}
        if len(distinct) == 1 and len(thinking) > 1:
            typer.echo(
                f"  Note: all {len(thinking)} thinking seats are {distinct.pop()}. Nothing "
                "here compares one model against another; pass --providers a,b to mix them."
            )
        for spec in sorted({seat.provider.name: seat.provider for seat in thinking}.values(),
                           key=lambda spec: spec.name):
            drum = get_drum_for(spec)
            budget = remaining_budget(spec)
            headroom = f"{budget:,} tokens left today" if budget is not None else "budget not stated"
            held_by = ", ".join(
                seat.name for seat in thinking if seat.provider.name == spec.name
            )
            typer.echo(
                f"  {spec.name}: {spec.model_id}, {drum.chambers} key(s), {headroom} — {held_by}"
            )

    hours = 0
    while hours < max_hours and engine.run_turn_cycle():
        hours += 1

    if engine.game_over:
        engine.run_epilogue()

    report(engine)
    record = chronicler.seal()
    report_losses(record)
    report_spend()

    if chronicle_out is not None:
        save_chronicle(record, chronicle_out)
        typer.echo(f"Chronicle: {chronicle_out}")

    if transcript is not None:
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(render_transcript(record), encoding="utf-8")
        typer.echo(f"Transcript: {transcript}")

    if story is not None:
        # Whoever has the most left. The narrator reads the whole transcript in one
        # go, so taking it out of the budget that just played the game is how a run
        # ends with a story it cannot afford to tell.
        teller = get_provider_by_name(narrator) if narrator else pick_narrator()
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
