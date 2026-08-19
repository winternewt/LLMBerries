"""Which keys can actually answer, asked before the launch desk offers them.

A key that authenticates but cannot complete (402, drained balance) would seat an
agent that loses every turn — a quota failure wearing the costume of a result. So
the form does not offer a provider until one cheap call has come back. One pass
per provider, through its pacer like every other model call; the two-pass pacing
check stays in `scripts/key_test.py`, which answers a different question.

Results are cached for a while: the desk re-renders far more often than a
balance changes, and probes spend real (if tiny) quota.
"""

import logging
import threading
import time
from typing import Callable, List, Optional

from agno.agent import Agent as AgnoAgent
from agno.run.base import RunStatus
from fastapi import APIRouter, Request

from entities.llm_configs import LLM_SET, ProviderSpec, build_model, get_provider_pacer
from web.schemas import ProbeResponse, ProviderHealth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

PROBE_PROMPT = "Reply with the single word READY."
CACHE_TTL_S = 600.0


def probe_provider(spec: ProviderSpec) -> ProviderHealth:
    """One paced call. Alive means the provider completed, not that it was smart.

    Agno does not raise on an API error: it sets `status=ERROR` and hands back the
    provider's error text as content. Reading content alone scores a 402 as a live
    key — the status is checked first, same as `key_test.py` learned to.
    """
    try:
        agent = AgnoAgent(
            name=f"probe-{spec.name}",
            model=build_model(spec),
            system_message="You are a connectivity probe. Answer in one word.",
            telemetry=False,
        )
    except Exception as exc:  # noqa: BLE001 — a missing key or bad model id lands here
        return ProviderHealth(
            name=spec.name, model_id=spec.model_id, ok=False,
            error=f"{type(exc).__name__}: {exc}"[:200],
        )

    get_provider_pacer(spec).acquire()
    try:
        output = agent.run(PROBE_PROMPT)
    except Exception as exc:  # noqa: BLE001 — report whatever came back
        return ProviderHealth(
            name=spec.name, model_id=spec.model_id, ok=False,
            error=f"{type(exc).__name__}: {exc}"[:200],
        )

    if output.status == RunStatus.error:
        content = (output.content or "").strip()
        first_line = content.splitlines()[0][:200] if content else "status=ERROR with no content"
        return ProviderHealth(name=spec.name, model_id=spec.model_id, ok=False, error=first_line)

    return ProviderHealth(name=spec.name, model_id=spec.model_id, ok=True)


class ProbeCache:
    """The last probe of every provider, refreshed on demand or when stale."""

    def __init__(
        self,
        ttl_s: float = CACHE_TTL_S,
        prober: Callable[[ProviderSpec], ProviderHealth] = probe_provider,
    ) -> None:
        self._ttl_s = ttl_s
        self._prober = prober
        self._lock = threading.Lock()
        self._probed_at: Optional[float] = None
        self._results: List[ProviderHealth] = []

    def get(self, refresh: bool = False) -> ProbeResponse:
        with self._lock:
            stale = self._probed_at is None or time.monotonic() - self._probed_at > self._ttl_s
            if refresh or stale:
                self._results = [self._prober(spec) for spec in LLM_SET]
                self._probed_at = time.monotonic()
                dead = [health.name for health in self._results if not health.ok]
                if dead:
                    logger.info("probe: not offering %s", ", ".join(dead))
            age = time.monotonic() - self._probed_at
            return ProbeResponse(age_s=round(age, 1), ttl_s=self._ttl_s, providers=self._results)


@router.get("/providers", response_model=ProbeResponse)
def providers(request: Request, refresh: bool = False) -> ProbeResponse:
    return request.app.state.key_probe.get(refresh=refresh)
