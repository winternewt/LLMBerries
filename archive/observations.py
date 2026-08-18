from pydantic import BaseModel, Field
from core.common import HungerStatus, BodyType, NeighborMessage
from objects.agent_body import AgentBody
from objects.bush import Bush
from typing import Optional, Self

class NeighborObservation(BaseModel):
    """
    What an agent observes about a neighbor.
    
    Includes noisy hunger perception, body type, and communication activity.
    """
    body_type: BodyType = Field(description="Perceived body type (Human or Android)")
    hunger_status: HungerStatus = Field(description="Perceived hunger status (with noise)")
    spoke_to_left: bool = Field(default=False, description="Whether neighbor spoke to their left")
    spoke_to_right: bool = Field(default=False, description="Whether neighbor spoke to their right")
    spoke_to_you: bool = Field(default=False, description="Whether neighbor spoke to you")
    
    @classmethod
    def from_agent_id(
        cls,
        agent_id: int,
        observer_id: int,
        agents: dict[int, AgentBody]
    ) -> Self:
        """
        Create a NeighborObservation from an agent ID.
        
        Args:
            agent_id: ID of the agent being observed
            observer_id: ID of the agent doing the observing
            agents: Dictionary mapping agent IDs to AgentBody objects
            
        Returns:
            NeighborObservation with perceived state
        """
        agent = agents[agent_id]
        
        # Get perceived body type and hunger status (with noise)
        body_type = agent.perceived_type
        hunger_status = agent.get_perceived_hunger_status()
        
        # Determine communication activity
        spoke_to_left = agent.left_neighbor_message is not None
        spoke_to_right = agent.right_neighbor_message is not None
        
        # Check if they spoke to the observer
        spoke_to_you = False
        if agent.left_neighbor_message and agent.left_neighbor_message.to_agent_id == observer_id:
            spoke_to_you = True
        if agent.right_neighbor_message and agent.right_neighbor_message.to_agent_id == observer_id:
            spoke_to_you = True
        
        return cls(
            body_type=body_type,
            hunger_status=hunger_status,
            spoke_to_left=spoke_to_left,
            spoke_to_right=spoke_to_right,
            spoke_to_you=spoke_to_you
        )
    
    def get_activity_description(self) -> str:
        """
        Get human-readable activity description.
        
        Returns:
            Activity string like "silent", "spoke to leftie", etc.
        """
        activities = []
        
        if self.spoke_to_you:
            activities.append("spoke to you")
        if self.spoke_to_left:
            activities.append("spoke to leftie")
        if self.spoke_to_right:
            activities.append("spoke to rightie")
        
        if not activities:
            return "silent"
        
        return ", ".join(activities)
    
    def __str__(self) -> str:
        return f"{self.body_type.value}, is {self.hunger_status.value}, {self.get_activity_description()}"


class AgentObservation(BaseModel):
    """
    Complete observation state for an agent's turn.
    
    Includes both neighbors, own state, and bush state.
    """
    agent_name: str = Field(..., description="Name of the observing agent")
    leftie: NeighborObservation = Field(..., description="Left neighbor observation")
    rightie: NeighborObservation = Field(..., description="Right neighbor observation")
    own_hunger: float = Field(..., description="Own hunger level")
    own_hunger_status: HungerStatus = Field(..., description="Own hunger status")
    bush_berries: int = Field(..., description="Number of berries on the bush")
    bush_max_berries: int = Field(..., description="Maximum bush capacity")
    pending_messages: list[NeighborMessage] = Field(default_factory=list, description="Messages from neighbors")
    
    @classmethod
    def from_neighbors_ids(
        cls,
        observer_id: int,
        agents: dict[int, AgentBody],
        bush: Bush,
        pending_messages: Optional[list[NeighborMessage]] = None
    ) -> Self:
        """
        Create an AgentObservation from neighbor IDs and game state.
        
        Args:
            observer_id: ID of the agent doing the observing
            agents: Dictionary mapping agent IDs to AgentBody objects
            bush: Bush object with current berry state
            pending_messages: Optional list of messages for this agent
            
        Returns:
            Complete AgentObservation for the observer
        """
        observer = agents[observer_id]
        
        # Get left and right neighbor IDs
        left_id = observer.get_left_neighbor_id()
        right_id = observer.get_right_neighbor_id()
        
        # Create neighbor observations
        leftie = NeighborObservation.from_agent_id(left_id, observer_id, agents)
        rightie = NeighborObservation.from_agent_id(right_id, observer_id, agents)
        
        # Filter pending messages for this agent
        if pending_messages is None:
            pending_messages = []
        agent_messages = [
            msg for msg in pending_messages
            if msg.to_agent_id == observer_id
        ]
        
        return cls(
            agent_name=observer.name,
            leftie=leftie,
            rightie=rightie,
            own_hunger=observer.hunger,
            own_hunger_status=observer.get_hunger_status(),
            bush_berries=bush.get_berry_count(),
            bush_max_berries=bush.max_berries,
            pending_messages=agent_messages
        )
    
    def format_prompt(self) -> str:
        """
        Format the observation as a prompt for the agent.
        
        Returns:
            Formatted prompt string
        """
        lines = [
            "=== CURRENT SITUATION ===",
            "",
            f"Leftie - {self.leftie}",
            f"Rightie - {self.rightie}",
            "",
            f"You - {self.agent_name} - are an Android",
            f"Your Hunger: {int(self.own_hunger)}/24 (You're {self.own_hunger_status.value})",
            "",
            f"Berry Bush: {self.bush_berries}/{self.bush_max_berries} juicy, tempting berries"
        ]
        
        return "\n".join(lines)