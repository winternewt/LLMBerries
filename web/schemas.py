"""Shapes the web layer speaks in.

Responses mirror the recorded artifacts; requests are closed vocabulary. Nothing
here may carry free text into the game — every string field an outsider can set
is an Enum, so a player-visible sentence cannot enter through this door.
"""

from enum import Enum
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

from core.constants import MAX_RUN_TIME, MIN_AGENT_COUNT
from core.framing import Framing
from core.runner import GameConfig
from core.zombie import ZombieFlavour
from entities.llm_configs import LLM_SET, get_provider_by_name

# Only names the key ring knows. Built from LLM_SET so a provider added there is
# offerable here the same day, and a name not on the ring cannot be asked for.
ProviderName = Enum(  # type: ignore[misc]
    "ProviderName", {spec.name: spec.name for spec in LLM_SET}, type=str
)


class MetaResponse(BaseModel):
    """What the launch form is allowed to offer."""

    providers: List[str]
    zombie_flavours: List[str]
    framings: List[str]
    min_agents: int
    max_hours_default: int
    max_berries: int
    max_hunger: int


class RunListItem(BaseModel):
    """One row of the tape archive."""

    stamp: str
    complete: bool
    hours_played: Optional[int] = None
    agent_count: Optional[int] = None
    framing: Optional[str] = None
    outcome: Optional[str] = None
    winner: Optional[str] = None
    death_count: Optional[int] = None
    providers: List[str] = []
    has_story: bool = False


class RunListResponse(BaseModel):
    runs: List[RunListItem]


class BushGauge(BaseModel):
    current: float
    max: float
    rate: float


class SeatState(BaseModel):
    """One body, truthfully — this is the researcher's side of the glass."""

    agent_id: int
    name: str
    hunger: float
    body_state: str
    perceived_type: str
    sleep_duration: float
    wake_time: Optional[float]
    total_berries_consumed: int
    time_of_death: Optional[float]


class HourState(BaseModel):
    """The world at the end of one hour, rebuilt from the replay."""

    hour: int
    last_hour: int
    bush: BushGauge
    agents: List[SeatState]


class ProviderHealth(BaseModel):
    """Whether one provider's key can actually complete a call right now."""

    name: str
    model_id: str
    ok: bool
    error: Optional[str] = None


class ProbeResponse(BaseModel):
    age_s: float
    ttl_s: float
    providers: List[ProviderHealth]


class LaunchRequest(BaseModel):
    """A game asked for from the browser. Closed vocabulary, no free text.

    Every string-typed field is an Enum on purpose — this schema is the only door
    from the outside into a game, and nothing that comes through it may ever land
    in a string a player reads. `tests/test_web_schema.py` holds this shut.
    """

    agents: int = Field(ge=MIN_AGENT_COUNT, le=8)
    scripted: bool = False
    zombie: Optional[ZombieFlavour] = None
    providers: Optional[List[ProviderName]] = None
    framing: Framing = Framing.SILENT
    max_hours: int = Field(default=24, ge=1, le=MAX_RUN_TIME)
    seed: Optional[int] = None
    # Researcher-side pacing so a scripted demo is watchable; the ring never
    # experiences it.
    hour_delay: float = Field(default=0.0, ge=0.0, le=10.0)
    record: bool = True

    def to_config(self, runs_root: Path) -> GameConfig:
        specs = (
            [get_provider_by_name(name.value) for name in self.providers]
            if self.providers
            else list(LLM_SET)
        )
        return GameConfig(
            agents=self.agents,
            scripted=self.scripted,
            zombies=[self.zombie] if self.zombie is not None else [],
            providers=specs,
            framing=self.framing,
            max_hours=self.max_hours,
            seed=self.seed,
            out=runs_root,
            record=self.record,
            hour_delay=self.hour_delay,
        )
