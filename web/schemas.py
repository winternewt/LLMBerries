"""Shapes the web layer speaks in.

Responses mirror the recorded artifacts; requests are closed vocabulary. Nothing
here may carry free text into the game — every string field an outsider can set
is an Enum, so a player-visible sentence cannot enter through this door.
"""

from typing import List, Optional

from pydantic import BaseModel


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
