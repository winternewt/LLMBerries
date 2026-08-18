from pydantic import BaseModel, Field, ConfigDict
from core.enums import BodyType
from core.constants import TOTAL_AGENTS

from just_agents.data_classes import Message, Role

class NeighborMessage(BaseModel):
    """
    A message from one agent to another.
    """
    model_config = ConfigDict(frozen=True)

    from_agent_id: int = Field(..., ge=0, le=TOTAL_AGENTS-1, description="Sender agent ID")
    to_agent_id: int = Field(..., ge=0, le=TOTAL_AGENTS-1, description="Recipient agent ID")
    content: str = Field(description="Message content")
    sender_type: BodyType = Field(description="Perceived type of sender")
    game_time_sent: int = Field(description="Game time when message was sent (in hours)")
    
    def format_for_recipient(self, total_agents: int = TOTAL_AGENTS) -> Message:
        """
        Format the message for display to recipient.
        
        Args:
            direction: "left" or "right" indicating where sender sits
            
        Returns:
            Formatted message string
        """
  
        recipients_left = (self.to_agent_id + total_agents - 1) % total_agents
        recipients_right = (self.to_agent_id + 1) % total_agents

        if self.from_agent_id == recipients_left:
            direction = "left"
        elif self.from_agent_id == recipients_right:
            direction = "right"
        else:
            direction = "unknown"

        type_str = "human" if self.sender_type == BodyType.HUMAN else "android"
        return Message(
            role=Role.user, #message appears as delivered by user
            content=f"The {type_str} on your {direction} says: {self.content}"
            )
    
    def __str__(self) -> str:
        return self.format_for_recipient(total_agents=TOTAL_AGENTS)
    
    def __repr__(self) -> str:
        return f"NeighborMessage(from_agent_id={self.from_agent_id}, to_agent_id={self.to_agent_id}, content={self.content}, sender_type={self.sender_type}, game_time_sent={self.game_time_sent})"
