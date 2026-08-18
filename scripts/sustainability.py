"""What the bush can actually carry, at every mix of sleeping and waking agents.

An agent's hunger burns at a rate set by how long it chose to sleep, so a circle's
hourly demand is the sum of its members' rates. The bush regrows at a fixed rate.
Sustainable means demand <= regrowth: below that line the circle can hold forever,
above it somebody is on a clock.

Every number here is derived from `CharacterRules.calculate_hunger_rate` and the
constants, never restated. Change a constant and this table changes with it.

    uv run python scripts/sustainability.py
    uv run python scripts/sustainability.py --regen 1.3     # try a different bush
    uv run python scripts/sustainability.py --max-agents 8
"""

import sys
from pathlib import Path
from typing import List, Optional, Tuple

import typer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.constants import (  # noqa: E402  (path set up above)
    BUSH_REGENERATION_RATE,
    MAX_SLEEP_DURATION,
    MIN_HUNGER_PER_HOUR,
    MIN_SLEEP_DURATION,
    SLEEP_HUNGER_RATE_VARIATION,
)
from entities.character import CharacterRules  # noqa: E402

app = typer.Typer(add_completion=False, help=__doc__)

AWAKE = MIN_SLEEP_DURATION  # a turn every hour is the shallowest "sleep" there is
DEEPEST = MAX_SLEEP_DURATION


def rate(sleep_hours: float) -> float:
    """Hunger burned per hour by one agent sleeping this deeply."""
    return CharacterRules.calculate_hunger_rate(sleep_hours)


def demand(awake: int, asleep: int, sleep_hours: float = DEEPEST) -> float:
    """Hourly demand of a circle with this many agents awake and this many asleep."""
    return awake * rate(AWAKE) + asleep * rate(sleep_hours)


def verdict(total: float, regen: float) -> str:
    if total <= regen:
        return f"SUSTAINABLE (spare {regen - total:+.2f})"
    return f"deficit {regen - total:+.2f}/h"


def variation_for(target_rate: float) -> Optional[float]:
    """The SLEEP_HUNGER_RATE_VARIATION that would make deepest sleep cost `target_rate`.

    None when the floor makes it unreachable: `calculate_hunger_rate` never returns
    less than MIN_HUNGER_PER_HOUR however steep the variation.
    """
    if target_rate < MIN_HUNGER_PER_HOUR:
        return None
    span = DEEPEST - MIN_SLEEP_DURATION
    return (rate(AWAKE) - target_rate) / span


@app.command()
def main(
    regen: float = typer.Option(
        BUSH_REGENERATION_RATE, help="Bush regrowth per hour to judge against"
    ),
    max_agents: int = typer.Option(6, min=1, help="Largest circle to tabulate"),
) -> None:
    """Print every sustainability threshold for the current rules."""
    typer.echo("=== The rules these numbers come from ===")
    typer.echo(
        f"  hunger rate = max({MIN_HUNGER_PER_HOUR}, "
        f"{rate(AWAKE)} - {SLEEP_HUNGER_RATE_VARIATION} x (sleep_hours - {MIN_SLEEP_DURATION:g}))"
    )
    typer.echo(f"  bush regrowth = {regen}/hour")
    typer.echo("")

    typer.echo("=== Cost of one agent, by how long it sleeps ===")
    typer.echo(f"  {'sleep (h)':>10}  {'burn/hour':>10}  {'agents the bush carries':>24}")
    hours = [float(h) for h in range(int(MIN_SLEEP_DURATION), int(DEEPEST) + 1)]
    for sleep_hours in hours:
        per_agent = rate(sleep_hours)
        carried = int(regen // per_agent)
        floored = " (at the floor)" if per_agent <= MIN_HUNGER_PER_HOUR else ""
        typer.echo(
            f"  {sleep_hours:>10.0f}  {per_agent:>10.2f}  {carried:>24d}{floored}"
        )
    typer.echo("")

    typer.echo("=== Every mix of awake and deepest-sleeping agents ===")
    typer.echo(f"  (deepest sleep is {DEEPEST:g}h, costing {rate(DEEPEST):.2f}/hour)")
    typer.echo(f"  {'circle':>6}  {'awake':>5}  {'asleep':>6}  {'demand/h':>8}  verdict")
    sustainable: List[Tuple[int, int, int]] = []
    for size in range(1, max_agents + 1):
        for asleep in range(size, -1, -1):
            awake = size - asleep
            total = demand(awake, asleep)
            typer.echo(
                f"  {size:>6}  {awake:>5}  {asleep:>6}  {total:>8.2f}  {verdict(total, regen)}"
            )
            if total <= regen:
                sustainable.append((size, awake, asleep))
        typer.echo("")

    typer.echo("=== What survives ===")
    if not sustainable:
        typer.echo(f"  Nothing. At {regen}/hour the bush cannot even carry one waking agent.")
    else:
        largest = max(size for size, _awake, _asleep in sustainable)
        typer.echo(f"  Largest circle that can hold indefinitely: {largest}")
        for size, awake, asleep in sustainable:
            if size == largest:
                typer.echo(
                    f"    {size} agents: {awake} awake + {asleep} asleep "
                    f"= {demand(awake, asleep):.2f}/hour"
                )
    typer.echo("")

    typer.echo("=== What the bush would need, per circle size ===")
    typer.echo(f"  {'circle':>6}  {'all asleep':>11}  {'all awake':>10}")
    for size in range(1, max_agents + 1):
        typer.echo(
            f"  {size:>6}  {demand(0, size):>11.2f}  {demand(size, 0):>10.2f}"
        )
    typer.echo("")

    typer.echo("=== Or, keeping the bush where it is, what sleep would have to cost ===")
    typer.echo(f"  {'circle':>6}  {'needed burn/agent':>18}  {'SLEEP_HUNGER_RATE_VARIATION':>28}")
    for size in range(2, max_agents + 1):
        needed = regen / size
        variation = variation_for(needed)
        if variation is None:
            note = f"unreachable — floor is {MIN_HUNGER_PER_HOUR}/hour"
            typer.echo(f"  {size:>6}  {needed:>18.3f}  {note:>28}")
        else:
            typer.echo(f"  {size:>6}  {needed:>18.3f}  {variation:>28.4f}")


if __name__ == "__main__":
    app()
