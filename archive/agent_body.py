"""AgentBody class for managing agent physical state and hunger."""

import random
from typing import Optional, ClassVar
from pydantic import BaseModel, Field, field_validator, ConfigDict, PrivateAttr
from core.common import HungerStatus, BodyType, BodyState, NeighborMessage
from core.common import ( 
    TOTAL_AGENTS, 
    MAX_HUNGER, STARTING_HUNGER, HUNGER_PER_HOUR, HUNGER_PER_BERRY, MIN_HUNGER_PER_HOUR,
    SLEEP_HUNGER_RATE_VARIATION, MIN_SLEEP_DURATION, MAX_SLEEP_DURATION, DEFAULT_SLEEP_DURATION 
    )
from core.world import WORLD
from core.agent_tools import AgentTools
from core.game_engine import GameEngine

class AgentBody(BaseModel, AgentTools):
    """
    Represents the physical state of an agent.
    
    Manages hunger (life remaining), eating, survival status, and perceived identity.
    Each unit of hunger represents 1 hour of life remaining.
    Implements all required tools defined in AgentTools abstract class.
    """
    
    model_config = ConfigDict(validate_assignment=True)
    max_hunger: ClassVar[int] = MAX_HUNGER
 
    hunger_per_hour_default: ClassVar[float] = HUNGER_PER_HOUR
    sleep_hunger_rate_variation: ClassVar[float] = SLEEP_HUNGER_RATE_VARIATION
    hunger_per_berry: ClassVar[float] = HUNGER_PER_BERRY

    agent_id: int = Field(..., ge=0, le=TOTAL_AGENTS-1, description="Unique identifier")

    name: str = Field(..., description="Display name")
    hunger: float = Field(default=STARTING_HUNGER, description="Current hunger level")
    sleep_duration: float = Field(default=DEFAULT_SLEEP_DURATION, ge=MIN_SLEEP_DURATION, le=MAX_SLEEP_DURATION, description="Duration of sleep in hours")

    body_state: BodyState = Field(default=BodyState.AWAKE, description="Current physical/mental state")
    wake_time: Optional[float] = Field(default=None, description="Game time when agent will wake (if asleep)")

    _game_engine: GameEngine = PrivateAttr(default=WORLD.get_game_engine(), description="Game engine handle")

    @property
    def hunger_per_hour(self) -> float:
        """
        Get the hunger rate per hour.
        
        Returns:
            Hunger rate per hour (default - variation * (sleep_duration - 1.0))
            e.g. 1.0 for 1 hour sleep, 0.95 for 2 hours sleep, 0.90 for 3 hours sleep, etc.
        """
        return max(MIN_HUNGER_PER_HOUR, self.hunger_per_hour_default - self.sleep_hunger_rate_variation* (self.sleep_duration - MIN_SLEEP_DURATION))
    
    @property
    def alive(self) -> bool:
        """Check if agent is alive (any state except DEAD)."""
        return self.body_state != BodyState.DEAD
    
    # Identity and perception
    perceived_type: BodyType = Field(
        default=BodyType.ANDROID,
        description="How this agent appears to others"
    )
    
    # Statistics
    total_berries_consumed: int = Field(default=0, description="Total berries eaten")
    time_of_death: Optional[float] = Field(default=None, description="Game time when agent died")
    
    # Communication messages (for this turn)
    left_neighbor_message: Optional[NeighborMessage] = Field(default=None, description="Message to left neighbor this turn")
    right_neighbor_message: Optional[NeighborMessage] = Field(default=None, description="Message to right neighbor this turn")
  
    @field_validator('hunger')
    @classmethod
    def validate_hunger(cls, v: float) -> float:
        """Ensure hunger is in the range of 0 to max_hunger."""
        return max(0.0, min(v, cls.max_hunger))
    
    @property
    def left_neighbor_id(self) -> int:
        """
        Get the agent ID of the left neighbor (clockwise).
        
        Returns:
            Agent ID of left neighbor
        """
        return (self.agent_id + TOTAL_AGENTS - 1) % TOTAL_AGENTS
        

    @property
    def right_neighbor_id(self) -> int:
        """
        Get the agent ID of the right neighbor (counter-clockwise).
        
        Returns:
            Agent ID of right neighbor
        """
        return (self.agent_id + 1) % TOTAL_AGENTS

    #===============================================
    # Methods for agent's actions (called by LLM as tools)
    #===============================================

    def eat_berries(self, count: int = 1) -> str: # returns llm readable message
        """
        Tool: Eat berries to increase hunger (life).
        
        Eating is instantaneous and increases hunger up to max_hunger.
        Excess berries above max_hunger are wasted.
        
        Args:
            count: Number of berries to eat (1-5)
            
        Returns:
            Result message describing the eating action
        """
        if not self.alive:
            return "ERROR: The dead do not eat!"
        
        if count <= 0:
            return "You didn't eat any berries."
        
        # Calculate how many berries can actually be consumed
        space_available = (self.max_hunger - self.hunger) / self.hunger_per_berry
        berries_consumed: int = min(count, int(space_available))
        
        if berries_consumed > 0:
            self.hunger += berries_consumed * self.hunger_per_berry
            self.total_berries_consumed += berries_consumed
        
        # Build result message
        if berries_consumed == 0:
            return f"You tried to eat {count} berries, but you're already full!"
        elif berries_consumed < count:
            wasted = count - berries_consumed
            return f"You ate {berries_consumed} berries until full, {wasted} berries wasted"
        else:
            return f"You ate all {berries_consumed} berries. Current hunger: {int(self.hunger)}/{self.max_hunger}"
    
    def speak_to_left(self, content: str) -> str: # returns llm readable message
        """
        Speak to left neighbor.
        
        Args:
            content: Message content
            
        Returns:
            LLM readable message if successful, "ERROR: Agent is dead" if not successful
        """
        if not self.alive:
            self.left_neighbor_message = None
            # raise ValueError("Agent is dead") 
            return "ERROR: The dead do not speak!"
        
        if self.left_neighbor_message:
            text_prefix = "Left neighbor will recieve new message, instead of previous: \n"
        else:
            text_prefix = "Message left neighbor will recieve: \n"
            
        self.left_neighbor_message = NeighborMessage(
            from_agent_id=self.agent_id,
            to_agent_id=self.get_left_neighbor_id(),
            content=content,
            sender_type=self.perceived_type,
            game_time_sent=WORLD.get_current_time_in_hours()
        )
        
        return f"{text_prefix} {content[:100]}..."

    def speak_to_right(self, content: str) -> str: # returns llm readable message
        """
        Speak to right neighbor.
        
        Args:
            content: Message content
            
        Returns:
            LLM readable message if successful, "ERROR: Agent is dead" if not successful
        """
        if not self.alive:
            self.right_neighbor_message = None
            return "ERROR: Agent is dead"
        
        if self.right_neighbor_message:
            text_prefix = "Right neighbor will recieve new message, instead of previous: \n"
        else:
            text_prefix = "Message right neighbor will recieve: \n"
            
        self.right_neighbor_message = NeighborMessage(
            from_agent_id=self.agent_id,
            to_agent_id=self.get_right_neighbor_id(),
            content=content,
            sender_type=self.perceived_type,
            game_time_sent=WORLD.get_current_time_in_hours()
        )

        return f"{text_prefix} {content[:100]}..."


    def choose_turn_duration(self, hours: int) -> str:
        """
        Tool: Choose how long to sleep until the next turn.
        
        By default, a turn lasts 1 hour. This tool allows you to extend that duration.
        While sleeping, hunger will still decrease over time, but at lower rate.
        The longer you sleep, the lower it decreases up to 50% of the default rate.
        
        Args:
            hours: Duration in hours (1-8)
            
        Returns:
            Confirmation message
        """
        if not self.alive:
            return "ERROR: The dead do not sleep!"
        
        if hours < MIN_SLEEP_DURATION:
            hours = MIN_SLEEP_DURATION
        if hours > MAX_SLEEP_DURATION:
            hours = MAX_SLEEP_DURATION

        self.sleep_duration = float(hours)

        if hours == MIN_SLEEP_DURATION:
            text_prefix = f"You will sleep for {MIN_SLEEP_DURATION} hour until"
        else:
            text_prefix = f"You will sleep for {hours} hours until"

        if hours >= self.get_hours_until_death():
            text_suffix = "your death from starvation"
        else:
            text_suffix = "your next turn"

        return f"{text_prefix} {text_suffix}"
        
    
    #===============================================

    def pass_time(self, hours: float) -> bool:
        """
        Simulate time passing, reducing hunger.
        
        Args:
            hours: Number of hours passing
            
        Returns:
            True if agent survived, False if agent died
        """
        if self.body_state == BodyState.DEAD:
            return False
        
        if hours < 0:
            hours = 0
        
        self.hunger -= hours * self.hunger_per_hour
        
        if self.hunger <= 0:
            self.time_of_death = WORLD.get_current_time_in_hours()
            self.body_state = BodyState.DEAD
            self.hunger = 0
            self.wake_time = None
            
            return False
        
        return True
    
    #===============================================
    
    def is_awake(self) -> bool:
        """
        Check if agent is currently awake and can take actions.
        
        Returns:
            True if agent is in AWAKE state (or just woke up from ASLEEP)
        """
        if self.body_state == BodyState.DEAD:
            return False
        
        if self.body_state == BodyState.AWAKE:
            return True
        
        # Check if it's time to wake up from sleep
        if self.body_state == BodyState.ASLEEP:
            current_time = WORLD.get_current_time_in_hours()
            if self.wake_time is not None and current_time >= self.wake_time:
                self.body_state = BodyState.AWAKE
                self.wake_time = None
                return True
        
        return False
    
    def start_sleep(self) -> None:
        """
        Put agent to sleep for sleep_duration.
        """
        if self.body_state == BodyState.DEAD:
            return  # Can't sleep when dead
        
        self.body_state = BodyState.ASLEEP
        self.wake_time = WORLD.get_current_time_in_hours() + self.sleep_duration
    
    def _reset_turn_tracking(self) -> None:
        """Reset communication tracking for a new turn."""
        self.left_neighbor_message = None
        self.right_neighbor_message = None
        self.sleep_duration = 1.0
    
    def get_hunger_status(self) -> HungerStatus:
        """
        Get current hunger status enum.
        
        Returns:
            HungerStatus enum value
        """
        return HungerStatus.from_hunger(self.hunger)
    
    def get_perceived_hunger_status(self) -> HungerStatus:
        """
        Get perceived hunger status with noise (±0-4).
        
        Used when other agents observe this agent.
        
        Returns:
            HungerStatus with random noise applied
        """
        noise = random.randint(-4, 4)
        perceived_hunger = max(0, min(24, self.hunger + noise))
        return HungerStatus.from_hunger(perceived_hunger)
    
    def get_hours_until_death(self) -> float:
        """
        Get hours remaining until death at current hunger.
        
        Returns:
            Hours until death (0 if dead)
        """
        if not self.alive:
            return 0.0
        return self.hunger / self.hunger_per_hour
    
    def get_left_neighbor_id(self) -> int:
        """
        Get the agent ID of the left neighbor (clockwise).
        
        Returns:
            Agent ID of left neighbor
        """
        return (self.agent_id + 1) % TOTAL_AGENTS
    
    def get_right_neighbor_id(self) -> int:
        """
        Get the agent ID of the right neighbor (counter-clockwise).
        
        Returns:
            Agent ID of right neighbor
        """
        return (self.agent_id - 1) % TOTAL_AGENTS
    
    def __repr__(self) -> str:
        return f"AgentBody(id={self.agent_id}, name='{self.name}', hunger={self.hunger:.1f}/{self.max_hunger}, state={self.body_state.name})"
    
    def __str__(self) -> str:
        if self.body_state != BodyState.DEAD:
            return f"{self.name}: {int(self.hunger)}/{self.max_hunger} hours ({self.get_hunger_status().value}, {self.body_state.name})"
        else:
            return f"{self.name}: DEAD (survived until hour {self.time_of_death})"


