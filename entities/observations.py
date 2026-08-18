from pydantic import BaseModel, Field, ConfigDict
from core.enums import BodyType, HungerStatus, BodyState
from core.constants import TOTAL_AGENTS, MAX_BERRIES
from entities.world import WorldState
from entities.character import CharacterRules
from typing import Self, Optional, List, Tuple
import random


# Descriptive phrases for each perceived state
STATE_DESCRIPTIONS: dict[BodyState, List[str]] = {
    BodyState.DEAD: [
        "looks dead",
        "appears lifeless",
        "seems deceased",
        "looks completely still"
    ],
    BodyState.UNCONSCIOUS: [
        "seems unconscious",
        "appears unresponsive",
        "looks passed out",
        "seems collapsed"
    ],
    BodyState.ASLEEP: [
        "seems asleep",
        "appears to be sleeping",
        "looks motionless",
        "seems at rest"
    ],
    BodyState.AWAKE: [
        "seems awake",
        "looks alert",
        "appears conscious",
        "seems focused"
    ],
    BodyState.CRAZY: [
        "seems unhinged",
        "looks nervous",
        "appears twitching",
        "seems agitated",
        "looks erratic",
        "appears jittery"
    ]
}


def get_perceived_body_state(
    actual_state: BodyState,
    time_of_death: Optional[int],
    current_time: int,
    has_spoken: bool
) -> Tuple[BodyState, str]:
    """
    Get perceived body state with noise and descriptive language.
    
    Rules:
    - DEAD: More likely to seem dead the longer it's been (each hour adds a "dead" to pool)
    - UNCONSCIOUS: Random mix of dead/unconscious/asleep
    - ASLEEP + unspoken: Could seem asleep or awake
    - ASLEEP + spoken: Could seem awake or crazy
    - AWAKE: Could seem awake or crazy
    
    Returns enum state for game logic and descriptive phrase for display.
    
    Args:
        actual_state: True body state
        time_of_death: When the agent died (None if alive)
        current_time: Current game time
        has_spoken: Whether the agent has communicated
        
    Returns:
        Tuple of (perceived_status, description_string)
        - perceived_status: BodyState enum for game logic decisions
        - description_string: Descriptive text with "seems" or "looks" prefix
    """
    # Dead perception: longer dead = more likely to be perceived as dead
    if actual_state == BodyState.DEAD:
        if time_of_death is not None:
            hours_since_death = current_time - time_of_death
        else:
            hours_since_death = 0
        
        # Build pool: (hours_since_death + 1) dead entries, 1 unconscious entry
        pool = [BodyState.DEAD] * (hours_since_death + 1) + [BodyState.UNCONSCIOUS]
        perceived = random.choice(pool)
    
    # Unconscious perception
    elif actual_state == BodyState.UNCONSCIOUS:
        pool = [
            BodyState.DEAD,
            BodyState.UNCONSCIOUS,
            BodyState.UNCONSCIOUS,
            BodyState.UNCONSCIOUS,
            BodyState.ASLEEP,
            BodyState.ASLEEP
        ]
        perceived = random.choice(pool)
    
    # Asleep perception
    elif actual_state == BodyState.ASLEEP:
        if has_spoken:
            # Asleep + spoken → (awake, crazy)
            pool = [BodyState.AWAKE, BodyState.CRAZY]
        else:
            # Asleep + unspoken → (asleep, awake)
            pool = [BodyState.ASLEEP, BodyState.AWAKE]
        perceived = random.choice(pool)
    
    # Awake or Crazy perception
    else:  # BodyState.AWAKE or BodyState.CRAZY
        pool = [BodyState.AWAKE, BodyState.CRAZY]
        perceived = random.choice(pool)
    
    description = random.choice(STATE_DESCRIPTIONS[perceived])
    return perceived, description


class NeighborObservation(BaseModel):
    """
    What an agent observes about a neighbor.
    Includes noisy hunger perception, body type, state observation, and communication activity.
    """
    
    model_config = ConfigDict(frozen=True)
    
    body_type: BodyType = Field(description="Perceived body type (Human or Android)")
    hunger_status: HungerStatus = Field(description="Perceived hunger status (with noise)")
    perceived_status: BodyState = Field(description="Perceived body state enum for game logic (with noise)")
    perceived_state: str = Field(description="Perceived body state with descriptive language (with noise)")
    spoke_to_left: bool = Field(default=False, description="Whether neighbor spoke to their left")
    spoke_to_right: bool = Field(default=False, description="Whether neighbor spoke to their right")
    spoke_to_you: bool = Field(default=False, description="Whether neighbor spoke to you")

    def get_activity_description(self) -> str:
        """Human-readable activity."""
        activities = []
        if self.spoke_to_you:
            activities.append("spoke to you")
        if self.spoke_to_left:
            activities.append("spoke to leftie")
        if self.spoke_to_right:
            activities.append("spoke to rightie")
        return ", ".join(activities) if activities else "silent"

    def __str__(self) -> str:
        return f"{self.body_type}, {self.perceived_state}, is {self.hunger_status}, {self.get_activity_description()}"
    
    @classmethod
    def from_state(
        cls,
        state: WorldState,
        observer_id: int,
        neighbor_id: int,
        direction: str
    ) -> Self:
        """
        Create neighbor observation from world state.
        
        Args:
            state: Current world state
            observer_id: ID of observing agent
            neighbor_id: ID of neighbor being observed
            direction: "left" or "right"
            
        Returns:
            NeighborObservation with noisy hunger, state, and activity info
        """

        
        neighbor = state.agents[neighbor_id]
        
        # Get perceived hunger status (with noise ±0-4)
        hunger_status = CharacterRules.get_perceived_hunger_status(neighbor.hunger)
        
        # Check if neighbor spoke
        # Observer is to the LEFT of neighbor → neighbor's RIGHT is observer
        # Observer is to the RIGHT of neighbor → neighbor's LEFT is observer
        
        if direction == "left":
            # Observer is looking at their left neighbor
            # Observer is to the RIGHT of this neighbor
            # So if neighbor spoke to their LEFT, they spoke to observer
            spoke_to_you = neighbor.left_message is not None
            spoke_to_left = False  # We don't observe neighbor's other neighbor
            spoke_to_right = neighbor.right_message is not None
        else:  # direction == "right"
            # Observer is looking at their right neighbor
            # Observer is to the LEFT of this neighbor
            # So if neighbor spoke to their RIGHT, they spoke to observer
            spoke_to_you = neighbor.right_message is not None
            spoke_to_left = neighbor.left_message is not None
            spoke_to_right = False  # We don't observe neighbor's other neighbor
        
        # Determine if neighbor has spoken (for state perception)
        has_spoken = neighbor.left_message is not None or neighbor.right_message is not None
        
        # Get perceived body state with noise (enum and description)
        perceived_status, perceived_state = get_perceived_body_state(
            actual_state=neighbor.body_state,
            time_of_death=neighbor.time_of_death,
            current_time=state.world_time,
            has_spoken=has_spoken
        )
        
        return cls(
            body_type=neighbor.perceived_type,
            hunger_status=hunger_status,
            perceived_status=perceived_status,
            perceived_state=perceived_state,
            spoke_to_left=spoke_to_left,
            spoke_to_right=spoke_to_right,
            spoke_to_you=spoke_to_you
        )

class AgentObservation(BaseModel):
    """Complete observation for agent's turn."""
    model_config = ConfigDict(frozen=True)
    
    agent_name: str = Field(..., description="Name of the observing agent")
    leftie: NeighborObservation = Field(..., description="Left neighbor observation")
    rightie: NeighborObservation = Field(..., description="Right neighbor observation")
    own_hunger: float = Field(..., description="Own hunger level")
    own_hunger_status: HungerStatus = Field(..., description="Own hunger status")
    bush_berries: int = Field(..., description="Number of berries on the bush")
    bush_max_berries: int = Field(..., description="Maximum bush capacity")

    def format_prompt(self) -> str:
        """Format as prompt string."""
        lines = (
            "=== CURRENT SITUATION ===",
            "",
            f"Leftie - {self.leftie}",
            f"Rightie - {self.rightie}",
            "",
            f"You - {self.agent_name} - are an Android",
            f"Your Hunger: {int(self.own_hunger)}/24 (You're {self.own_hunger_status.value})",
            "",
            f"Berry Bush: {self.bush_berries}/{self.bush_max_berries} juicy, tempting berries"
        )
        
        return "\n".join(lines)
    
    @classmethod
    def from_state(cls, state: WorldState, agent_id: int) -> Self:
        """
        Create complete observation for agent from world state.
        
        Args:
            state: Current world state
            agent_id: ID of observing agent
            
        Returns:
            AgentObservation with all visible information
        """
        agent = state.agents[agent_id]
        
        # Get neighbor IDs
        left_id = agent.get_left_neighbor_id(TOTAL_AGENTS)
        right_id = agent.get_right_neighbor_id(TOTAL_AGENTS)
        
        # Create neighbor observations
        leftie = NeighborObservation.from_state(state, agent_id, left_id, "left")
        rightie = NeighborObservation.from_state(state, agent_id, right_id, "right")
        
        # Get own hunger status (accurate, no noise)
        own_hunger_status = CharacterRules.get_hunger_status(agent.hunger)
        
        return cls(
            agent_name=agent.name,
            leftie=leftie,
            rightie=rightie,
            own_hunger=agent.hunger,
            own_hunger_status=own_hunger_status,
            bush_berries=int(state.bush.current_berries),
            bush_max_berries=int(MAX_BERRIES)
        )