from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Any, Tuple
from entities.character import CharacterPhysicalState
from entities.bush import BushState
from entities.memory import ConversationMemory

from core.constants import MIN_AGENT_COUNT

def check_immutable(obj: Any, path: str = "root") -> None:
    """
    Validate no mutable collections exist in state tree.
    
    Args:
        obj: Object to validate
        path: Current path for error reporting
        
    Raises:
        ValueError: If mutable collection found
    """
    if isinstance(obj, (list, dict, set)):
        raise ValueError(
            f"Mutable {type(obj).__name__} at {path}. Use Tuple/FrozenSet."
        )
    if isinstance(obj, BaseModel):
        for name in obj.__class__.model_fields:
            check_immutable(getattr(obj, name), f"{path}.{name}")
    elif isinstance(obj, tuple):
        for i, item in enumerate(obj):
            check_immutable(item, f"{path}[{i}]")

class WorldState(BaseModel):
    """
    Immutable snapshot of entire game state.
    
    All game data in one frozen structure. Updates create new instances.
    """
    model_config = ConfigDict(frozen=True)

    world_time: int = Field(default=0, ge=0, description="Current world time in hours")
    active_agent_id: int = Field(default=0, ge=0, description="ID of active agent")

    agents: Tuple[CharacterPhysicalState, ...] = Field(..., description="All agent states")
    bush: BushState = Field(..., description="Bush state")
    agent_memories: Tuple[ConversationMemory, ...] = Field(..., description="LLM conversation histories")

    @model_validator(mode='after')
    def validate_immutability(self) -> "WorldState":
        """Ensure no mutable collections in state tree."""
        check_immutable(self)
        return self

    @model_validator(mode='after')
    def validate_agent_count(self) -> "WorldState":
        """The circle sizes itself from `agents`; everything else is checked against it.

        Bounds are derived here rather than restated on each field, so a state with
        four agents cannot be built with validators still assuming three.
        """
        count = len(self.agents)
        if count < MIN_AGENT_COUNT:
            raise ValueError(
                f"a circle needs at least {MIN_AGENT_COUNT} agents, got {count}: with fewer, "
                "an agent's left and right neighbour are the same agent"
            )
        if len(self.agent_memories) != count:
            raise ValueError(
                f"{count} agents but {len(self.agent_memories)} memories — they must match"
            )
        if self.active_agent_id >= count:
            raise ValueError(
                f"active_agent_id {self.active_agent_id} is outside a circle of {count}"
            )
        return self

    @property
    def agent_count(self) -> int:
        """Number of agents in the circle. The single source of truth for its size."""
        return len(self.agents)

    def with_agent(self, agent_id: int, **fields: Any) -> "WorldState":
        """
        Create new state with updated agent fields.
        
        Args:
            agent_id: ID of agent to update
            **fields: Fields to update on agent
            
        Returns:
            New WorldState with updated agent
        """
        old_agent = self.agents[agent_id]
        new_agent = old_agent.model_copy(update=fields)
        new_agents = self.agents[:agent_id] + (new_agent,) + self.agents[agent_id+1:]
        return self.model_copy(update={"agents": new_agents})
    
    def with_agent_memory(self, agent_id: int, memory: ConversationMemory) -> "WorldState":
        """Create new state with updated agent memory."""
        new_memories = self.agent_memories[:agent_id] + (memory,) + self.agent_memories[agent_id+1:]
        return self.model_copy(update={"agent_memories": new_memories})
    
    def with_bush(self, bush: "BushState") -> "WorldState":
        """Create new state with updated bush."""
        return self.model_copy(update={"bush": bush})

    def with_time_advanced(self) -> "WorldState":
        """Create new state with time advanced by 1 hour."""
        return self.model_copy(update={"world_time": self.world_time + 1})
    
    def get_alive_agents(self) -> Tuple[int, ...]:
        """Get tuple of alive agent IDs."""
        return tuple(agent.agent_id for agent in self.agents if agent.alive)
    
    def get_awake_agents(self) -> Tuple[int, ...]:
        """Get tuple of awake agent IDs."""
        return tuple(
            agent.agent_id 
            for agent in self.agents 
            if agent.is_awake(self.world_time)
        )