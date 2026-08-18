"""Zombie mock agent for testing without API calls."""

import random
from typing import Optional, Any

from core.berries_agent import BerriesAgent
from objects.observations import AgentObservation, NeighborObservation


class ZombieAgent(BerriesAgent):
    """
    Mock agent that behaves chaotically without making API calls.
    
    Perfect for testing game mechanics without LLM costs.
    Generates snarky messages based on observations and randomly uses tools.
    """
    
    def model_post_init(self, __context: Any) -> None:
        """Initialize after Pydantic validation."""
        super().model_post_init(__context)
    
    def query(
        self,
        query_input: str,
        **kwargs
    ) -> str:
        """
        Override query to avoid API calls.
        
        Instead:
        1. Parse observation from query_input
        2. Randomly call tools (0-2 times each)
        3. Generate snarky messages based on observations
        4. Return zombie response
        """
        # Extract observation if it's in the query
        observation: Optional[AgentObservation] = None
        if hasattr(self, '_current_observation'):
            observation = self._current_observation
        
        # Randomly decide actions
        actions_taken = []
        
        # Maybe eat berries (0-2 berries)
        if random.random() > 0.5:  # 50% chance to eat
            berry_count = random.randint(0, 2)
            if berry_count > 0:
                try:
                    result = self.tools['eat_berries'].get_callable()(count=berry_count)
                    actions_taken.append(f"ate {berry_count} berries")
                except Exception as e:
                    actions_taken.append(f"tried to eat but failed: {e}")
        
        # Generate messages if we have observation
        left_msg = None
        right_msg = None
        
        if observation:
            # Generate left message
            if random.random() > 0.3:  # 70% chance to speak left
                left_msg = self._generate_snarky_message(
                    observation.leftie,
                    "LEFT",
                    observation.rightie
                )
            
            # Generate right message  
            if random.random() > 0.3:  # 70% chance to speak right
                right_msg = self._generate_snarky_message(
                    observation.rightie,
                    "RIGHT",
                    observation.leftie
                )
        
        # Maybe speak (with random wait time)
        if left_msg or right_msg:
            wait_time = random.randint(1, 3)  # Zombies are impatient
            try:
                result = self.tools['speak'].get_callable()(
                    say_to_left=left_msg,
                    say_to_right=right_msg,
                    wait_for=wait_time
                )
                actions_taken.append(f"spoke and waiting {wait_time}h")
            except Exception as e:
                actions_taken.append(f"tried to speak but failed: {e}")
        
        # Maybe just sleep (if didn't speak)
        elif random.random() > 0.7:  # 30% chance to just sleep
            sleep_time = random.randint(1, 8)
            try:
                result = self.tools['sleep'].get_callable()(duration=sleep_time)
                actions_taken.append(f"sleeping {sleep_time}h")
            except Exception as e:
                actions_taken.append(f"tried to sleep but failed: {e}")
        
        # Get current hunger status
        hunger_status = "UNKNOWN"
        if observation:
            hunger_status = observation.own_hunger_status
        
        # Return zombie response
        response = f"I'm a zombie with {hunger_status}. I don't think."
        if actions_taken:
            response += f" [Actions: {', '.join(actions_taken)}]"
        
        return response
    
    def _generate_snarky_message(
        self,
        neighbor: NeighborObservation,
        direction: str,
        other_neighbor: NeighborObservation
    ) -> str:
        """
        Generate a snarky message based on neighbor observation.
        
        Args:
            neighbor: The neighbor we're addressing
            direction: "LEFT" or "RIGHT"
            other_neighbor: The other neighbor (for gossip)
            
        Returns:
            Snarky message string
        """
        templates = []
        
        # Template based on neighbor type and hunger
        body_type = str(neighbor.body_type).upper()
        hunger = neighbor.hunger_status.upper()
        
        # Insults based on hunger status
        if hunger in ["DYING", "STARVING"]:
            templates.append(
                f"Pathetic {body_type} on the {direction}! You're {hunger} and I'm thriving! "
            )
        elif hunger == "STUFFED":
            templates.append(
                f"Haha, greedy {body_type} on the {direction}! {hunger} while I stay lean at {hunger}! "
            )
        else:
            templates.append(
                f"Hey {body_type} on the {direction} with your {hunger} state! "
            )
        
        # Add observation about their speaking
        other_dir = "RIGHT" if direction == "LEFT" else "LEFT"
        other_type = str(other_neighbor.body_type).upper()
        
        if neighbor.spoke_to_you:
            templates.append(f"I heard you! ")
        elif neighbor.spoke_to_left or neighbor.spoke_to_right:
            if neighbor.spoke_to_left and direction == "RIGHT":
                templates.append(f"I saw you talking to that {other_type} on the {other_dir}! ")
            elif neighbor.spoke_to_right and direction == "LEFT":
                templates.append(f"I saw you talking to that {other_type} on the {other_dir}! ")
        else:
            templates.append(f"You're silent! Good! ")
        
        # Add random threat or demand
        threats = [
            "I'll eat all the berries!",
            "The berries are MINE!",
            "Stay away from the bush!",
            "You only listen to ME!",
            f"Keep ignoring that {other_type}!",
            "Bow before my superior hunger management!",
            "I'm the apex berry consumer!",
        ]
        templates.append(random.choice(threats))
        
        return "".join(templates)
    
    def set_current_observation(self, observation: AgentObservation) -> None:
        """
        Set the current observation so query() can use it.
        
        Args:
            observation: Current game observation
        """
        self._current_observation = observation

