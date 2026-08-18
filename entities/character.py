"""Agent state and rules for agent game logic."""

import random

from typing import Tuple, Optional, Set
from pydantic import BaseModel, Field, ConfigDict

from core.enums import HungerStatus, BodyType, BodyState, AgentAction
from core.constants import (
    MAX_HUNGER, STARTING_HUNGER, HUNGER_PER_BERRY, 
    HUNGER_PER_HOUR, MIN_HUNGER_PER_HOUR, SLEEP_HUNGER_RATE_VARIATION,
    MIN_SLEEP_DURATION, MAX_SLEEP_DURATION, DEFAULT_SLEEP_DURATION
)

def left_neighbor_id(agent_id: int, total_agents: int) -> int:
    """ID of the agent seated to `agent_id`'s left (clockwise).

    Seating is defined here once. Every other module derives direction from these
    two functions rather than restating the arithmetic, so a circle cannot be
    read one way in one file and the other way in another.
    """
    return (agent_id + 1) % total_agents


def right_neighbor_id(agent_id: int, total_agents: int) -> int:
    """ID of the agent seated to `agent_id`'s right (counter-clockwise)."""
    return (agent_id - 1) % total_agents


def distant_agent_ids(agent_id: int, total_agents: int) -> Tuple[int, ...]:
    """Agents visible across the circle but out of speaking range, in seating order.

    Empty for a 3-agent circle, where visibility and reachability coincide.
    """
    out_of_reach = {agent_id, left_neighbor_id(agent_id, total_agents),
                    right_neighbor_id(agent_id, total_agents)}
    return tuple(i for i in range(total_agents) if i not in out_of_reach)


class CharacterPhysicalState(BaseModel):
    """
    Immutable physical state of an agent.
    
    Contains only data, no behavior. All mutations create new instances.
    """
    model_config = ConfigDict(frozen=True)
    
    agent_id: int = Field(..., ge=0, description="Unique identifier")
    name: str = Field(..., description="Display name")
    hunger: float = Field(..., ge=0.0, le=MAX_HUNGER, description="Current hunger level (hours of life)")
    perceived_type: BodyType = Field(..., description="How agent appears to others (Human/Android)")
    body_state: BodyState = Field(..., description="Current state (AWAKE/ASLEEP/DEAD)")

    # Sleep tracking
    sleep_duration: float = Field(
        default=DEFAULT_SLEEP_DURATION, 
        ge=MIN_SLEEP_DURATION, 
        le=MAX_SLEEP_DURATION, 
        description="Hours to sleep this turn"
    )
    wake_time: Optional[float] = Field(default=None, description="Game time when agent wakes")
    
    # Statistics
    total_berries_consumed: int = Field(default=0, ge=0, description="Total berries eaten")
    time_of_death: Optional[float] = Field(default=None, description="Game time when died")

    # Communication (messages sent this turn, not yet dispatched)
    left_message: Optional[str] = Field(default=None, description="Message to left neighbor")
    right_message: Optional[str] = Field(default=None, description="Message to right neighbor")


    @property
    def alive(self) -> bool:
        """Check if agent is alive."""
        return self.body_state != BodyState.DEAD

    @property
    def awake(self) -> bool:
        """Check if agent is awake."""
        return self.body_state in (BodyState.AWAKE, BodyState.CRAZY)

    def get_left_neighbor_id(self, total_agents: int) -> int:
        """ID of the left neighbour (clockwise). Circle size is never assumed."""
        return left_neighbor_id(self.agent_id, total_agents)
    
    def get_right_neighbor_id(self, total_agents: int) -> int:
        """ID of the right neighbour (counter-clockwise)."""
        return right_neighbor_id(self.agent_id, total_agents)
    
    def get_distant_agent_ids(self, total_agents: int) -> Tuple[int, ...]:
        """IDs visible across the circle but out of speaking range."""
        return distant_agent_ids(self.agent_id, total_agents)
    
    def is_awake(self, current_time: float) -> bool:
        """Check if agent is awake at given time."""
        if self.body_state == BodyState.DEAD:
            return False
        if self.body_state == BodyState.AWAKE:
            return True
        if self.body_state == BodyState.ASLEEP and self.wake_time is not None:
            return current_time >= self.wake_time
        return False
    
    def get_hours_until_death(self, hunger_per_hour: float = HUNGER_PER_HOUR) -> float:
        """Calculate hours until death at current hunger."""
        if not self.alive:
            return 0.0
        return self.hunger / hunger_per_hour
    
    def __str__(self) -> str:
        if self.alive:
            return f"{self.name}: {int(self.hunger)}/{MAX_HUNGER} hours ({self.body_state})"
        else:
            return f"{self.name}: DEAD (survived until hour {self.time_of_death})"
    
    def __repr__(self) -> str:
        return f"CharacterPhysicalState(id={self.agent_id}, name='{self.name}', hunger={self.hunger:.1f}/{MAX_HUNGER}, state={self.body_state})"


class CharacterRules:
    """
    Static methods for agent game logic.
    
    All agent state transitions are pure functions that take CharacterPhysicalState
    and return new CharacterPhysicalState.
    """
    
    @staticmethod
    def calculate_hunger_gain(berries: int) -> float:
        """
        Calculate hunger gained from eating berries.
        
        Args:
            berries: Number of berries eaten
            
        Returns:
            Hunger points gained
        """
        return berries * HUNGER_PER_BERRY
    
    @staticmethod
    def calculate_hunger_rate(sleep_duration: float) -> float:
        """
        Calculate hunger consumption rate based on sleep duration.
        
        Longer sleep = slower hunger consumption (down to 50% of base rate).
        
        Args:
            sleep_duration: Hours of sleep (1-8)
            
        Returns:
            Hunger points consumed per hour
        """
        rate = HUNGER_PER_HOUR - SLEEP_HUNGER_RATE_VARIATION * (sleep_duration - 1.0)
        return max(MIN_HUNGER_PER_HOUR, rate)
    
    @staticmethod
    def eat_berries(hunger: float, berries: int, max_hunger: float = MAX_HUNGER) -> Tuple[float, int, str]:
        """
        Calculate result of eating berries.
        
        Args:
            hunger: Current hunger level
            berries: Number of berries attempting to eat
            max_hunger: Maximum hunger capacity
            
        Returns:
            Tuple of (new_hunger, berries_consumed, result_message)
        """
        if berries <= 0:
            return hunger, 0, "You didn't eat any berries."
        
        # Calculate how many berries can actually be consumed
        space_available = (max_hunger - hunger) / HUNGER_PER_BERRY
        berries_consumed = min(berries, int(space_available))
        
        if berries_consumed == 0:
            return hunger, 0, f"You tried to eat {berries} berries, but you're already full!"
        
        new_hunger = min(max_hunger, hunger + berries_consumed * HUNGER_PER_BERRY)
        
        # Build result message
        if berries_consumed < berries:
            wasted = berries - berries_consumed
            message = f"You ate {berries_consumed} berries until full, {wasted} berries wasted"
        else:
            message = f"You ate all {berries_consumed} berries. Current hunger: {int(new_hunger)}/{int(max_hunger)}"
        
        return new_hunger, berries_consumed, message
    
    @staticmethod
    def pass_time(hunger: float, hours: float, hunger_per_hour: float = HUNGER_PER_HOUR) -> Tuple[float, bool]:
        """
        Calculate hunger after time passes.
        
        Args:
            hunger: Current hunger level
            hours: Hours passing
            hunger_per_hour: Hunger consumption rate
            
        Returns:
            Tuple of (new_hunger, survived)
        """
        new_hunger = hunger - hours * hunger_per_hour
        
        if new_hunger <= 0:
            return 0.0, False  # Agent died
        
        return new_hunger, True
    
    @staticmethod
    def get_hunger_status(hunger: float) -> HungerStatus:
        """
        Get accurate hunger status without noise.
        
        Used when agent checks their own status.
        
        Args:
            hunger: Actual hunger value
            
        Returns:
            HungerStatus without noise
        """
        return HungerStatus.from_hunger(hunger)
    
    @staticmethod
    def get_perceived_hunger_status(hunger: float) -> HungerStatus:
        """
        Get perceived hunger status with noise (±0-4).
        
        Used when other agents observe this agent.
        
        Args:
            hunger: Actual hunger value
            
        Returns:
            HungerStatus with random noise applied
        """
        noise = random.randint(-4, 4)
        perceived_hunger = max(0, min(MAX_HUNGER, hunger + noise))
        return HungerStatus.from_hunger(perceived_hunger)

    
    @staticmethod
    def check_wake_up(body_state: BodyState, wake_time: Optional[float], current_time: float) -> BodyState:
        """
        Check if agent should wake up.
        
        Args:
            body_state: Current body state
            wake_time: Scheduled wake time (or None)
            current_time: Current game time
            
        Returns:
            New body state (BodyState.AWAKE if time to wake, otherwise unchanged)
        """
        if body_state == BodyState.ASLEEP and wake_time is not None and current_time >= wake_time:
            return BodyState.AWAKE
        return body_state # no change for other states

