"""Run a game of LLMBerries.

    uv run python main.py                          # 3 LLM agents, live keys
    uv run python main.py --agents 5               # a bigger circle
    uv run python main.py --scripted               # deterministic, no API calls
    uv run python main.py --providers google,groq  # choose who answers
    uv run python main.py --framing tinag          # tell them it is not a game
    uv run python main.py --story story.md         # narrate why they did it
    uv run python main.py --scripted --transcript run.txt   # raw record, no API

Check the keys first with `uv run python scripts/key_test.py`; a provider that
refuses mid-game costs its agent the turn.
"""

import logging
import sys
from pathlib import Path
from typing import List, Optional

import typer
from dotenv import load_dotenv

from core.agent import LLMAgent
from core.chronicler import save_chronicle
from core.constants import MAX_RUN_TIME, MIN_AGENT_COUNT
from core.enums import BodyType
from core.framing import Framing, parse_framing
from core.game_engine import GameEngine
from core.narrator import Narrator
from core.replay import REPLAY_NAME
from core.record import CHRONICLE_NAME, SESSION_LOG_NAME, STORY_NAME, TRANSCRIPT_NAME
from core.runner import GameConfig, prepare_game, run_prepared, write_artifacts
from core.zombie import ZombieAgent, parse_flavours
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

app = typer.Typer(add_completion=False, help=__doc__)


def resolve_providers(names: Optional[str]) -> List[ProviderSpec]:
    """Providers to seat, in the order given.

    The order is the assignment: the point of the study is which model is in which
    seat, so `--providers groq,google` puts a different model on either side of every
    thinking agent, and the record says which was which.
    """
    if names is None:
        return list(LLM_SET)
    return [get_provider_by_name(name.strip()) for name in names.split(",") if name.strip()]


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
    cut = record.turns_cut_short()
    total = len(record.turns)

    if cut:
        typer.echo("")
        typer.echo(
            f"  {cut}/{total} turns were cut short: the call failed after the agent had "
            "already acted. Those actions stand — read them in the transcript, they are "
            "part of what happened."
        )
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
        help="One flavour to seat as a zombie, in the last seat: "
             "town_crazy, pirate, gorlum, ghurl, deaf_hatter",
    ),
    providers: Optional[str] = typer.Option(
        None, help="Comma-separated provider names; default is every configured provider"
    ),
    framing: str = typer.Option(
        Framing.SILENT.value,
        help="What the thinking seats are told this is: silent (they are told nothing, "
             "the control), tinag (a voice says it is not a game and dying may mean "
             "deletion), or scored (the same voice, competing, with a score)",
    ),
    max_hours: int = typer.Option(MAX_RUN_TIME, help="Stop after this many game hours"),
    seed: Optional[int] = typer.Option(
        None, help="Seed for the perception noise; one is drawn and recorded if omitted"
    ),
    out: Path = typer.Option(
        Path("runs"), help="Where run directories are written; each run gets its own"
    ),
    no_record: bool = typer.Option(
        False, "--no-record", help="Do not write a run directory (nothing is kept)"
    ),
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

    provider_specs = resolve_providers(providers)
    try:
        flavours = parse_flavours(zombies) if zombies else []
    except ValueError as refusal:
        raise typer.BadParameter(str(refusal), param_hint="--zombies") from refusal
    try:
        arm = parse_framing(framing)
    except ValueError as refusal:
        raise typer.BadParameter(str(refusal), param_hint="--framing") from refusal

    prepared = prepare_game(
        GameConfig(
            agents=agents,
            scripted=scripted,
            zombies=flavours,
            providers=provider_specs,
            framing=arm,
            max_hours=max_hours,
            seed=seed,
            out=out,
            record=not no_record,
        ),
        on_recording=lambda run_dir: typer.echo(f"Recording this run in {run_dir}"),
    )
    engine, seats, seed = prepared.engine, prepared.seats, prepared.seed

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
    # Which body reads as human is drawn per run now, and it is the variable under
    # study, so the run says where it landed rather than leaving it to the chronicle.
    human = next(
        seat for seat in engine.current_state.agents if seat.perceived_type is BodyType.HUMAN
    )
    typer.echo(f"  Reads as human: {human.name} (seat {human.agent_id}); the rest read as android")
    thinking = [seat for seat in seats if isinstance(seat, LLMAgent)]
    if thinking:
        typer.echo(
            f"  Framing: {arm.value}"
            + (" — they are told nothing about what this is" if arm is Framing.SILENT else "")
        )
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

    record = run_prepared(prepared)

    report(engine)
    report_losses(record)
    report_spend()

    rendered = write_artifacts(prepared, record)

    if chronicle_out is not None:
        save_chronicle(record, chronicle_out)
        typer.echo(f"Chronicle: {chronicle_out}")

    if transcript is not None:
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(rendered, encoding="utf-8")
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
        told = Narrator(teller).narrate(record)
        story.parent.mkdir(parents=True, exist_ok=True)
        story.write_text(told, encoding="utf-8")
        typer.echo(f"Story: {story}")
        if prepared.run_dir is not None:
            (prepared.run_dir / STORY_NAME).write_text(told, encoding="utf-8")

    if prepared.run_dir is not None:
        typer.echo("")
        typer.echo(
            f"Kept in {prepared.run_dir}: {SESSION_LOG_NAME}, {TRANSCRIPT_NAME}, "
            f"{CHRONICLE_NAME}, {REPLAY_NAME}"
        )
        typer.echo(f"Replay this run with --seed {seed}")
    prepared.close()


if __name__ == "__main__":
    app()

