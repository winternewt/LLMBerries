"""Check the free-tier keys are live and that pacing survives a second call.

Two passes per provider, back to back. The first proves the key works and the
model id exists; the second proves the pacer spaces requests widely enough that
the provider does not refuse the follow-up. A second call that comes back 429 is
the failure this script exists to catch — the game fires one request per awake
agent per turn, which is exactly that shape.

    uv run python scripts/key_test.py
    uv run python scripts/key_test.py --provider groq --json
"""

import json
import logging
import sys
import time
from pathlib import Path
from typing import List, Optional

import typer
from agno.agent import Agent
from agno.run.base import RunStatus
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from entities.llm_configs import (  # noqa: E402  (path set up above)
    LLM_SET,
    ProviderSpec,
    build_model,
    get_provider_by_name,
    get_provider_pacer,
)

logger = logging.getLogger("key_test")

PROMPT: str = "Reply with the single word READY."

# Deliberately excludes the bare word "quota": a 402 "payment required" names a quota
# param and would otherwise be mislabelled as pacing failure, which is a different
# problem with a different fix.
RATE_LIMIT_MARKERS: tuple[str, ...] = (
    "429",
    "rate limit",
    "rate_limit",
    "resource_exhausted",
    "resource exhausted",
    "quota exceeded",
    "too many requests",
)

app = typer.Typer(add_completion=False, help=__doc__)


class PassResult(BaseModel):
    """Outcome of one live call."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    paced_wait_s: float = Field(description="Seconds the pacer held the request back")
    latency_s: Optional[float] = Field(default=None, description="Round-trip time when it ran")
    reply: Optional[str] = Field(default=None, description="First line of the model's reply")
    error: Optional[str] = Field(default=None)
    rate_limited: Optional[bool] = Field(
        default=None, description="True/False once a call ran; None when it never ran"
    )


class ProviderResult(BaseModel):
    """Both passes for one provider."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model_id: str
    pace_rpm: int
    min_spacing_s: float
    first: PassResult
    second: PassResult

    @property
    def passed(self) -> bool:
        return self.first.ok and self.second.ok


def _is_rate_limit(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in RATE_LIMIT_MARKERS)


def _run_once(spec: ProviderSpec, agent: Agent) -> PassResult:
    """Pace, then make one live call."""
    pacer = get_provider_pacer(spec)
    waited = pacer.acquire()

    started = time.monotonic()
    try:
        output = agent.run(PROMPT)
    except Exception as exc:  # noqa: BLE001 - the point is to report whatever came back
        message = f"{type(exc).__name__}: {exc}"
        logger.debug("%s: call failed: %s", spec.name, message)
        return PassResult(
            ok=False,
            paced_wait_s=round(waited, 2),
            latency_s=round(time.monotonic() - started, 2),
            error=message[:300],
            rate_limited=_is_rate_limit(message),
        )

    latency = round(time.monotonic() - started, 2)
    content = (output.content or "").strip()
    first_line = content.splitlines()[0][:120] if content else ""

    # Agno does not raise on an API error: it logs, sets status=ERROR and hands back
    # a RunOutput whose content is the provider's error text. Reading content alone
    # would score a 402 as a live key, so the status is checked first and the reply
    # is then required to actually answer the prompt.
    if output.status == RunStatus.error:
        return PassResult(
            ok=False,
            paced_wait_s=round(waited, 2),
            latency_s=latency,
            error=first_line or "run returned status=ERROR with no content",
            rate_limited=_is_rate_limit(content),
        )

    if "ready" not in content.lower():
        return PassResult(
            ok=False,
            paced_wait_s=round(waited, 2),
            latency_s=latency,
            reply=first_line,
            error=f"reply did not answer the probe: {first_line!r}",
            rate_limited=_is_rate_limit(content),
        )

    return PassResult(
        ok=True,
        paced_wait_s=round(waited, 2),
        latency_s=latency,
        reply=first_line[:80],
        rate_limited=False,
    )


def check_provider(spec: ProviderSpec) -> ProviderResult:
    """Two passes against one provider, with the pacer between them."""
    pacer = get_provider_pacer(spec)

    try:
        agent = Agent(
            name=f"keytest-{spec.name}",
            model=build_model(spec),
            system_message="You are a connectivity probe. Answer in one word.",
            telemetry=False,
        )
    except Exception as exc:  # noqa: BLE001 - a missing key or bad model id lands here
        failure = PassResult(
            ok=False, paced_wait_s=0.0, error=f"{type(exc).__name__}: {exc}"[:300]
        )
        return ProviderResult(
            provider=spec.name,
            model_id=spec.model_id,
            pace_rpm=spec.pace_rpm,
            min_spacing_s=round(pacer.min_spacing, 2),
            first=failure,
            second=failure,
        )

    first = _run_once(spec, agent)
    second = _run_once(spec, agent)

    return ProviderResult(
        provider=spec.name,
        model_id=spec.model_id,
        pace_rpm=spec.pace_rpm,
        min_spacing_s=round(pacer.min_spacing, 2),
        first=first,
        second=second,
    )


def _report(result: ProviderResult) -> None:
    mark = "PASS" if result.passed else "FAIL"
    typer.echo(
        f"[{mark}] {result.provider:<9} {result.model_id:<22} "
        f"pace={result.pace_rpm}/min (>= {result.min_spacing_s}s apart)"
    )
    for label, outcome in (("  pass 1", result.first), ("  pass 2", result.second)):
        if outcome.ok:
            typer.echo(
                f"{label}: ok   waited {outcome.paced_wait_s}s, "
                f"replied in {outcome.latency_s}s: {outcome.reply!r}"
            )
        else:
            flag = " RATE-LIMITED" if outcome.rate_limited else ""
            typer.echo(f"{label}: FAIL{flag}  waited {outcome.paced_wait_s}s — {outcome.error}")


@app.command()
def main(
    provider: Optional[str] = typer.Option(
        None, help="Check one provider only (google, groq, deepseek, cerebras)"
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit results as JSON"),
    verbose: bool = typer.Option(False, "--verbose", help="Debug logging, including pacer waits"),
) -> None:
    """Verify every configured free-tier key with a paced two-pass call."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    load_dotenv()

    specs: List[ProviderSpec] = (
        [get_provider_by_name(provider)] if provider is not None else list(LLM_SET)
    )

    results: List[ProviderResult] = []
    for spec in specs:
        result = check_provider(spec)
        results.append(result)
        if not as_json:
            _report(result)

    if as_json:
        typer.echo(json.dumps([r.model_dump() for r in results], indent=2))

    failed = [r.provider for r in results if not r.passed]
    if failed:
        typer.echo(f"\n{len(failed)}/{len(results)} providers failed: {', '.join(failed)}")
        raise typer.Exit(code=1)

    typer.echo(f"\nAll {len(results)} providers live, no rate-limit refusal on the second call.")


if __name__ == "__main__":
    app()
