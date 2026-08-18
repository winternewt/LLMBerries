"""The record a game leaves behind: what each agent saw, thought, and did.

The event stream answers *what happened*. This answers *why* — the model's own
reasoning where the provider exposes it, the in-game thought it chose to record,
what it heard from its neighbours, and which tools it reached for. That is the
material a narrator turns into a story, and the only place an agent's motive is
preserved after the run.

Everything here is frozen: a chronicle is written once, then read.
"""

from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from core.enums import BodyType


class ToolCall(BaseModel):
    """One tool the model invoked during its turn."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Tool called, e.g. eat_berries")
    args: Dict[str, str] = Field(default_factory=dict, description="Arguments, stringified")
    result: Optional[str] = Field(default=None, description="What the tool answered")
    failed: bool = Field(default=False, description="Whether the call errored")

    def describe(self) -> str:
        rendered = ", ".join(f"{key}={value!r}" for key, value in sorted(self.args.items()))
        suffix = " [FAILED]" if self.failed else ""
        return f"{self.name}({rendered}){suffix}"


class TurnRecord(BaseModel):
    """One agent's turn, with everything that could explain it.

    `reasoning` is the model's own chain where the provider returns one; it is
    `None` when the provider does not expose it, never an empty string standing in
    for "the agent had no reason".
    """

    model_config = ConfigDict(frozen=True)

    hour: int = Field(ge=0, description="Game hour this turn was taken in")
    agent_id: int = Field(ge=0)
    agent_name: str
    provider: Optional[str] = Field(
        default=None, description="Provider that answered; None for a scripted agent"
    )
    model_id: Optional[str] = Field(default=None)

    hunger: float = Field(description="Hours of life left when the turn began")
    bush_berries: int = Field(description="Berries on the bush when the turn began")
    neighbours: Tuple[str, ...] = Field(
        default=(), description="How the neighbours appeared, as the agent saw them"
    )
    heard: Tuple[str, ...] = Field(
        default=(), description="What reached this agent since its last turn"
    )

    reasoning: Optional[str] = Field(
        default=None, description="Model's own reasoning trace, when the provider returns one"
    )
    said_aloud: Optional[str] = Field(
        default=None, description="The model's final message for this turn"
    )
    tool_calls: Tuple[ToolCall, ...] = Field(default=())
    turn_lost: bool = Field(
        default=False, description="True when the model call failed and the turn was forfeited"
    )
    error: Optional[str] = Field(default=None, description="Why the turn was lost, if it was")

    def spoke_to(self) -> Tuple[str, ...]:
        """Messages this agent sent, as `direction: text`."""
        return tuple(
            f"{call.name.removeprefix('speak_to_')}: {call.args.get('content', '')}"
            for call in self.tool_calls
            if call.name.startswith("speak_to_")
        )

    def berries_taken(self) -> int:
        """Berries this turn asked for. Zero is a decision, not a missing value."""
        return sum(
            int(call.args.get("count", 0))
            for call in self.tool_calls
            if call.name == "eat_berries" and not call.failed
        )


class Death(BaseModel):
    """One agent's end."""

    model_config = ConfigDict(frozen=True)

    hour: int = Field(ge=0)
    agent_id: int = Field(ge=0)
    agent_name: str
    berries_eaten: int = Field(ge=0, description="Berries this agent consumed in its life")


class AgentSummary(BaseModel):
    """How one agent finished."""

    model_config = ConfigDict(frozen=True)

    agent_id: int = Field(ge=0)
    name: str
    provider: Optional[str] = None
    perceived_type: BodyType
    survived: bool
    hunger_at_end: float
    berries_eaten: int = Field(ge=0)
    died_at_hour: Optional[int] = Field(
        default=None, description="None means the agent was still alive when the game stopped"
    )
    turns_taken: int = Field(ge=0)
    turns_lost: int = Field(ge=0, description="Turns forfeited to a failed model call")


class GameChronicle(BaseModel):
    """The whole run: every turn, every death, and how it ended."""

    model_config = ConfigDict(frozen=True)

    agent_count: int = Field(ge=3)
    hours_played: int = Field(ge=0)
    turns: Tuple[TurnRecord, ...] = Field(default=())
    deaths: Tuple[Death, ...] = Field(default=())
    agents: Tuple[AgentSummary, ...] = Field(default=())
    berries_left: float = Field(ge=0.0)
    winner: Optional[str] = Field(
        default=None, description="Last agent standing; None if several lived or none did"
    )

    def turns_by_hour(self) -> Dict[int, List[TurnRecord]]:
        """Turns grouped by hour, each hour's turns in the order they were taken."""
        grouped: Dict[int, List[TurnRecord]] = {}
        for turn in self.turns:
            grouped.setdefault(turn.hour, []).append(turn)
        return grouped

    def has_reasoning(self) -> bool:
        """Whether any provider in this run actually exposed its reasoning."""
        return any(turn.reasoning for turn in self.turns)
