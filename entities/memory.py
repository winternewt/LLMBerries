"""Per-agent conversation history, owned by the game rather than by the agent framework.

Memory lives inside `WorldState` on purpose. The engine branches a game from any past
turn, and a branch is only meaningful if what each agent remembers forks with it — a
framework-side session store would keep one history across both branches and quietly
leak the road not taken.
"""

from enum import Enum
from typing import Dict, Self, Tuple

from pydantic import BaseModel, ConfigDict, Field


class Role(str, Enum):
    """Message roles, matching the wire vocabulary every provider uses.

    Subclasses `str` so a role compares and serialises as the plain string the
    provider APIs expect.
    """

    system = "system"
    user = "user"
    assistant = "assistant"


class ChatMessage(BaseModel):
    """One turn of conversation."""

    model_config = ConfigDict(frozen=True)

    role: Role = Field(description="Who produced this message")
    content: str = Field(description="Message text")

    def as_dict(self) -> Dict[str, str]:
        """Provider-shaped mapping, for handing history to a model."""
        return {"role": self.role.value, "content": self.content}


class ConversationMemory(BaseModel):
    """Immutable conversation history for one agent."""

    model_config = ConfigDict(frozen=True)

    messages: Tuple[ChatMessage, ...] = Field(
        default=(), description="Conversation so far, oldest first"
    )

    def with_message(self, role: Role, content: str) -> Self:
        """Return a new memory with one message appended."""
        return self.model_copy(
            update={"messages": self.messages + (ChatMessage(role=role, content=content),)}
        )

    def as_dicts(self) -> Tuple[Dict[str, str], ...]:
        """History as provider-shaped mappings, oldest first."""
        return tuple(message.as_dict() for message in self.messages)

    def __len__(self) -> int:
        return len(self.messages)
