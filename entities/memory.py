from just_agents.base_memory import BaseMemory
from pydantic import BaseModel, Field, ConfigDict
from typing import Tuple, Self
from just_agents.data_classes import Message, Role

class ConversationMemory(BaseMemory):
    model_config = ConfigDict(frozen=True)
    messages: Tuple[dict[str, str], ...] = Field(
        default=(),
        description="Tuple of message dicts with 'role' and 'content'"
    )
    
    def with_message(self, role: Role, content: str) -> Self:
        new_msg = Message(role=role, content=content)
        return self.model_copy(update={"messages": self.messages + (new_msg,)})
    
