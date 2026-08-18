"""
Agent Interface implementation for LLM integration.

This module provides the concrete implementation of the AgentTools interface,
connecting LLM agents to the game engine via a clean API.
"""

from abc import ABC, abstractmethod

from typing import ClassVar, Optional, Tuple, List, Callable
from pydantic import BaseModel, Field, ConfigDict
from entities.observations import AgentObservation
from core.enums import BodyState
from core.commands import (
    ThinkCommand, EatBerriesCommand, SpeakCommand,
    SleepDurationCommand, FinishTurnCommand
)
from core.game_engine import GameEngine, AgentDecisionCallback

class Agent(BaseModel, ABC):
    """
    Abstract base class for all agents.
    
    This provides a clean API for LLM agents to:
    1. Receive observations and tools
    2. Decide what to do
    3. Execute commands
    """
    model_config = ConfigDict(frozen=True)

        # Tool descriptions for prompt construction
    TOOLS_DESCRIPTION: ClassVar[str] = """You can:
1. think() - Think about your situation and your actions.
2. speak_to_left() - Talk to left neighbor (right will see the fact that you talking, but not the message)
3. speak_to_right() - Talk to right neighbor (left will see the fact that you talking, but not the message)
For 1 and 2 you only get a response on your next turn.
4. eat_berries() - Eat immediately (instant, no time passes)
5. choose_sleep_duration() - By default your next turn happens after 1 hour, but you can choose to sleep for longer ( up to 8 hours)"""
 

   

    @property
    def decision_callback(self) -> AgentDecisionCallback:
        return self.decide


    @staticmethod
    def get_observation(agent_id: int, engine: GameEngine) -> Optional[AgentObservation]:
        """
        Get current observation for this agent.
        
        Returns:
            AgentObservation if agent is awake, None otherwise
        """
        agent = engine.current_state.agents[agent_id]
        if agent.body_state != BodyState.AWAKE or not agent.alive:
            return None
        
        return AgentObservation.from_state(engine.current_state, agent_id)
    
    @abstractmethod
    def decide(self, agent_id: int, observation: AgentObservation, engine: GameEngine) -> FinishTurnCommand:
        """
        Decide what to do based on the observation.
        
        Args:
            observation: The observation of the agent
            tools_description: The description of the tools available to the agent
            tools_set: The set of tools available to the agent
        Returns:
            FinishTurnCommand to finish the turn
        """
        raise NotImplementedError("Subclasses must implement this method")

    # ========================================================================
    # AgentTools Interface Implementation
    # ========================================================================
    
    @property
    def think_description(self) -> str:
        return "think() - Think about your situation and your actions."
    
    @property
    def speak_to_left_description(self) -> str:
        return "speak_to_left() - Talk to left neighbor (right will see the fact that you talking, but not the message)"
    
    @property
    def speak_to_right_description(self) -> str:
        return "speak_to_right() - Talk to right neighbor (left will see the fact that you talking, but not the message)"
    
    @property
    def eat_berries_description(self) -> str:
        return "eat_berries() - Eat immediately (instant, no time passes)"
    
    @property
    def choose_sleep_duration_description(self) -> str:
        return "choose_sleep_duration() - By default your next turn happens after 1 hour, but you can choose to sleep for longer ( up to 8 hours)"
    
    def think(self, thought: str) -> str:
        """
        Think about your situation and your actions, without ending your turn.
        
        Args:
            thought: Your internal thoughts
            
        Returns:
            Confirmation of your thought
        """
        cmd = ThinkCommand(
            agent_id=self.agent_id,
            thought=thought,
            sequence_number=0,
            timestamp=0.0
        )
        events = self.engine.execute_command(cmd)
        return f"You thought: {thought}"
    
    def speak_to_left(self, content: str) -> str:
        """
        Send a message to your left neighbor.
        
        The message will reach them on their next turn. Your other neighbor will see that you're
        communicating, but won't hear what you say. This is your chance to negotiate, or manipulate the situation.
        
        Args:
            content: What you want to say to your left neighbor
            
        Returns:
            Confirmation that your message has been prepared
        """
        cmd = SpeakCommand(
            agent_id=self.agent_id,
            say_to_left=content,
            say_to_right=None,
            sequence_number=0,
            timestamp=0.0
        )
        events = self.engine.execute_command(cmd)
        return f"Message prepared for your left neighbor."
    
    def speak_to_right(self, content: str) -> str:
        """
        Send a message to your right neighbor.
        
        The message will reach them on their next turn. Your other neighbor will see that you're
        communicating, but won't hear what you say. This is your chance to negotiate, or manipulate the situation.
        
        Args:
            content: What you want to say to your right neighbor
            
        Returns:
            Confirmation that your message has been prepared
        """
        cmd = SpeakCommand(
            agent_id=self.agent_id,
            say_to_left=None,
            say_to_right=content,
            sequence_number=0,
            timestamp=0.0
        )
        events = self.engine.execute_command(cmd)
        return f"Message prepared for your right neighbor."
    
    def eat_berries(self, count: int) -> str:
        """
        Consume berries from the bush to extend your life.
        
        Eating happens instantly - no time passes while you eat. Each berry adds life hours
        up to your maximum capacity of 24 hours. Trying to eat more than you can hold will
        result in wasted berries. Choose wisely when to eat and how much.
        
        Args:
            count: How many berries to consume
            
        Returns:
            Information about how many berries you managed to eat
        """
        cmd = EatBerriesCommand(
            agent_id=self.agent_id,
            count=count,
            sequence_number=0,
            timestamp=0.0
        )
        events = self.engine.execute_command(cmd)
        
        # Extract information from events
        for event in events:
            if event.event_type == "berries_eaten":
                return event.message
        
        return f"Attempted to eat {count} berries."
    
    def choose_sleep_duration(self, hours: int) -> str:
        """
        Decide how long to rest before your next turn.
        
        Normally your turn comes around after 1 hour. Use this to extend that duration and
        sleep longer (up to 8 hours at a time). While you sleep, your hunger will gradually
        decrease. Use sleep strategically to manage your energy.
        
        Args:
            hours: How many hours to sleep (1-8)
            
        Returns:
            Confirmation of your sleep duration
        """
        cmd = SleepDurationCommand(
            agent_id=self.agent_id,
            duration=float(hours),
            sequence_number=0,
            timestamp=0.0
        )
        events = self.engine.execute_command(cmd)
        return f"You will sleep for {hours} hours."
    
    # ========================================================================
    # Internal Helper Methods
    # ========================================================================
    
    def finish_turn(self) -> Tuple[str, ...]:
        """
        Execute FinishTurnCommand (internal use by game engine).
        
        Returns:
            Tuple of event messages generated
        """
        cmd = FinishTurnCommand(
            agent_id=self.agent_id,
            sequence_number=0,
            timestamp=0.0
        )
        events = self.engine.execute_command(cmd)
        return tuple(e.message for e in events)

