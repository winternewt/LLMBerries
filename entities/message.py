"""Messages passed between neighbouring agents around the circle."""

from pydantic import BaseModel, ConfigDict, Field

from core.enums import BodyType
from entities.character import left_neighbor_id, right_neighbor_id
from entities.memory import ChatMessage, Role


class NeighborMessage(BaseModel):
    """A message from one agent to another.

    Only neighbours can be addressed; the circle size is never assumed here, it is
    supplied by the caller that knows how many agents are seated.
    """

    model_config = ConfigDict(frozen=True)

    from_agent_id: int = Field(..., ge=0, description="Sender agent ID")
    to_agent_id: int = Field(..., ge=0, description="Recipient agent ID")
    content: str = Field(description="Message content")
    sender_type: BodyType = Field(description="Perceived type of sender")
    game_time_sent: int = Field(description="Game time when message was sent (in hours)")

    def direction_from_recipient(self, total_agents: int) -> str:
        """Where the sender sits as seen by the recipient: "left", "right" or "across".

        Derived from the seating helpers rather than restating the arithmetic, so
        this cannot drift from how the rest of the game seats the circle.
        """
        if self.from_agent_id == left_neighbor_id(self.to_agent_id, total_agents):
            return "left"
        if self.from_agent_id == right_neighbor_id(self.to_agent_id, total_agents):
            return "right"
        return "across"

    def format_for_recipient(self, total_agents: int) -> ChatMessage:
        """Render the message as the recipient will read it on their next turn."""
        direction = self.direction_from_recipient(total_agents)
        type_str = "human" if self.sender_type == BodyType.HUMAN else "android"
        return ChatMessage(
            role=Role.user,  # the message arrives as if spoken to the agent
            content=f"The {type_str} on your {direction} says: {self.content}",
        )

    def __repr__(self) -> str:
        return (
            f"NeighborMessage(from_agent_id={self.from_agent_id}, "
            f"to_agent_id={self.to_agent_id}, content={self.content!r}, "
            f"sender_type={self.sender_type}, game_time_sent={self.game_time_sent})"
        )
