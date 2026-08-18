"""Bush state and rules for berry resources."""

from typing import Tuple
from pydantic import BaseModel, ConfigDict, Field
from core.constants import MAX_BERRIES, BUSH_REGENERATION_RATE, STARTING_BERRIES


class BushState(BaseModel):
    """
    Immutable bush state.
    """
    model_config = ConfigDict(frozen=True)
    max_berries: float = Field(
        default=MAX_BERRIES, ge=1.0, 
        description="Maximum berry capacity"
    )
    current_berries: float = Field(
        default=STARTING_BERRIES, 
        ge=0.0, 
        description="Current number of berries"
    )
    regeneration_rate: float = Field(
        default=BUSH_REGENERATION_RATE, 
        description="Berries regenerated per hour"
    )
    
    def get_berry_count(self) -> int:
        """Get current berry count (rounded down)."""
        return int(self.current_berries)
    
    def has_berries(self, count: int) -> bool:
        """Check if bush has at least count berries."""
        return self.current_berries >= count
    
    def __str__(self) -> str:
        return f"{self.get_berry_count()}/{int(self.max_berries)} berries"
    
    def __repr__(self) -> str:
        return f"BushState(berries={self.get_berry_count()}/{int(self.max_berries)}, rate={self.regeneration_rate}/hr)"


class BushRules:
    """
    Static methods for bush game logic.
    
    All bush state transitions are pure functions that take BushState
    and return new BushState.
    """
    
    @staticmethod
    def harvest(bush: BushState, count: int) -> Tuple[BushState, int]:
        """
        Harvest berries from bush immutably.
        
        Args:
            bush: Current bush state
            count: Number of berries to harvest
            
        Returns:
            Tuple of (new_bush_state, actual_harvested)
        """
        if count <= 0:
            return bush, 0
        
        available = int(bush.current_berries)
        actual = min(count, available)
        new_berries = bush.current_berries - actual
        
        new_bush = bush.model_copy(update={"current_berries": new_berries})
        return new_bush, actual
    
    @staticmethod
    def regenerate(bush: BushState, hours: float) -> Tuple[BushState, float]:
        """
        Regenerate berries immutably.
        
        Args:
            bush: Current bush state
            hours: Hours passed
            
        Returns:
            Tuple of (new_bush_state, actual_regenerated)
        """
        regenerated = bush.regeneration_rate * hours
        new_berries = min(bush.max_berries, bush.current_berries + regenerated)
        actual_regenerated = new_berries - bush.current_berries
        
        new_bush = bush.model_copy(update={"current_berries": new_berries})
        return new_bush, actual_regenerated

