"""Free-tier LLM providers used by the game, with their pacing quotas.

Each entry names one provider/model pair reachable with a free key, the rate the
game paces itself at, and what the provider publishes. The two are separate on
purpose: `pace_rpm` is our policy and always has a value, while `published_rpm`
records what the provider actually states — `None` means "not stated", never
"unlimited".

Run `uv run python scripts/key_test.py` to check the keys are live and the pacing
holds; it reports the limits the APIs return in their headers, which outrank the
numbers recorded here.
"""

import logging
import os
import random
from typing import Callable, Dict, Optional, Tuple

from agno.models.base import Model
from agno.models.cerebras import Cerebras
from agno.models.deepseek import DeepSeek
from agno.models.google import Gemini
from agno.models.groq import Groq
from pydantic import BaseModel, ConfigDict, Field

from core.pacing import RateLimiter, get_pacer

logger = logging.getLogger(__name__)


class ProviderSpec(BaseModel):
    """One free-tier provider/model pair and its quota."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Short provider key, also the pacer's name")
    model_id: str = Field(description="Model id as the provider's API names it")
    env_var: str = Field(description="Environment variable holding the API key")
    pace_rpm: int = Field(gt=0, description="Requests per minute the game paces itself at")
    published_rpm: Optional[int] = Field(
        default=None, description="Free-tier RPM the provider publishes; None means not stated"
    )
    published_tpm: Optional[int] = Field(
        default=None, description="Free-tier tokens per minute; None means not stated"
    )
    published_rpd: Optional[int] = Field(
        default=None, description="Free-tier requests per day; None means not stated"
    )
    max_context: Optional[int] = Field(
        default=None, description="Free-tier context cap where the provider imposes one"
    )
    notes: str = Field(default="", description="Anything a run needs to know about this tier")


GOOGLE = ProviderSpec(
    name="google",
    model_id="gemini-3.7-flash",
    env_var="GOOGLE_API_KEY",
    pace_rpm=10,
    published_rpm=10,
    published_rpd=1500,
    notes="Free tier covers Flash and Flash-Lite only; Pro models require billing.",
)

GROQ = ProviderSpec(
    name="groq",
    model_id="openai/gpt-oss-120b",
    env_var="GROQ_API_KEY",
    pace_rpm=30,
    published_rpm=30,
    published_tpm=8000,
    published_rpd=1000,
    notes="TPM is the binding limit here, not RPM: 8k tokens/min across all calls.",
)

DEEPSEEK = ProviderSpec(
    name="deepseek",
    model_id="deepseek-v4-flash",
    env_var="DEEPSEEK_API_KEY",
    pace_rpm=30,
    published_rpm=None,
    notes=(
        "DeepSeek publishes no per-minute request cap and throttles under load instead, "
        "so pace_rpm here is our own conservative choice, not a quoted limit."
    ),
)

CEREBRAS = ProviderSpec(
    name="cerebras",
    model_id="gpt-oss-120b",
    env_var="CEREBRAS_API_KEY",
    pace_rpm=30,
    published_rpm=30,
    max_context=8192,
    notes="Free tier exposes a short model list and caps context at 8192 tokens.",
)

LLM_SET: Tuple[ProviderSpec, ...] = (GOOGLE, GROQ, DEEPSEEK, CEREBRAS)

_BUILDERS: Dict[str, Callable[[str, str], Model]] = {
    "google": lambda model_id, api_key: Gemini(id=model_id, api_key=api_key),
    "groq": lambda model_id, api_key: Groq(id=model_id, api_key=api_key),
    "deepseek": lambda model_id, api_key: DeepSeek(id=model_id, api_key=api_key),
    "cerebras": lambda model_id, api_key: Cerebras(id=model_id, api_key=api_key),
}


def get_api_key(spec: ProviderSpec) -> str:
    """Read the provider's key from the environment, refusing an empty one.

    An empty string is treated as absent on purpose: that is how a test signals
    "no credential" without a real key leaking in from a loaded `.env`.
    """
    key = os.environ.get(spec.env_var, "").strip()
    if not key:
        raise RuntimeError(
            f"{spec.name}: no API key — set {spec.env_var} in .env (see .env.template)"
        )
    return key


def build_model(spec: ProviderSpec) -> Model:
    """Build the Agno model for this provider. Raises if its key is missing."""
    builder = _BUILDERS[spec.name]
    return builder(spec.model_id, get_api_key(spec))


def get_provider_pacer(spec: ProviderSpec) -> RateLimiter:
    """Return the shared limiter for this provider's quota."""
    return get_pacer(name=spec.name, rpm=spec.pace_rpm)


def get_provider_by_name(name: str) -> ProviderSpec:
    for spec in LLM_SET:
        if spec.name == name:
            return spec
    known = ", ".join(spec.name for spec in LLM_SET)
    raise KeyError(f"unknown provider {name!r}; known providers: {known}")


def get_provider_by_index(index: int) -> ProviderSpec:
    """Provider for agent `index`, wrapping when there are more agents than providers."""
    return LLM_SET[index % len(LLM_SET)]


def get_random_provider() -> ProviderSpec:
    return random.choice(LLM_SET)
