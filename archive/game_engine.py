"""Game engine for managing the LLMBerries game."""

import random
from typing import Optional, Tuple, List, Dict, Any
from pydantic import BaseModel, Field

from objects.observations import AgentObservation, NeighborObservation
from core.common import BodyType, BodyState, NeighborMessage
from core.common import TOTAL_AGENTS, MAX_HUNGER, MAX_BERRIES, STARTING_HUNGER, STARTING_BERRIES

from objects.bush import Bush
from objects.agent_body import AgentBody

class GameEngine(BaseModel):
    """
    Manages the game state and turn-based logic.
    
    Coordinates agents, bush, time management, and message delivery.
    
    Turn Flow:
    1. start_agent_turn(agent_id) - Prepare agent for turn (fields already clear)
    2. create_observation(agent_id) - Create observation with current state
       - Neighbors' message fields show if they're "speaking" or "silent"
       - Pending messages from queue are included
    3. deliver_messages_to_agent() - Deliver pending messages to agent's memory
    4. Agent takes actions (talk, eat, sleep) via execute_* methods
       - talk methods store messages on agent but don't dispatch yet
    5. end_agent_turn(agent_id) - Dispatch messages to queue, then clear message fields
    6. Time passes, next agent's turn begins
    
    Message Visibility:
    - When agent speaks: messages stored on agent
    - At end of turn: messages dispatched to queue (but stay on agent)
    - Messages persist on agent until their NEXT turn starts
    - Result: Neighbors see agent as "speaking" until agent's next turn
    - At start of next turn: messages cleared from agent
    - This allows neighbors to observe "speaking" state across time gaps
    """
    
    bush: Bush = Field(default_factory=lambda: Bush(current_berries=STARTING_BERRIES, max_berries=MAX_BERRIES))
    agents: List[AgentBody] = Field(default_factory=list)
    game_time: float = Field(default=0.0, description="Current game time in hours")
    turn_number: int = Field(default=0, description="Current turn number (cycles through all agents)")
    message_queue: List[NeighborMessage] = Field(default_factory=list, description="Pending messages")
    
    # Game log
    game_log: List[str] = Field(default_factory=list, description="Log of game events")
    
    def model_post_init(self, __context: Any) -> None:
        """Post-initialization hook."""
        pass  # Reserved for future use
    
    def initialize_agents(self, names: List[str]) -> None:
        """
        Initialize TOTAL_AGENTS agents with given names.
        
        Args:
            names: List of TOTAL_AGENTS agent names
        """
        if len(names) != TOTAL_AGENTS:
            raise ValueError(f"Must provide exactly {TOTAL_AGENTS} agent names")
        
        # Randomly assign body types
        perceived_types = [BodyType.HUMAN]
        for i in range(TOTAL_AGENTS - 1):
            perceived_types.append(BodyType.ANDROID)
        random.shuffle(perceived_types)
        
        self.agents = [
            AgentBody(
                agent_id=i,
                name=names[i],
                hunger=20.0,
                perceived_type=perceived_types[i],
                body_state=BodyState.AWAKE  # Everyone starts awake
            )
            for i in range(TOTAL_AGENTS)
        ]
        
        self.log(f"Game initialized with agents: {', '.join(names)}")
        for agent in self.agents:
            self.log(f"  {agent.name} appears as {agent.perceived_type.value}")
    
    def get_agent_by_id(self, agent_id: int) -> AgentBody:
        """Get agent by ID."""
        return self.agents[agent_id]
    
    def get_agent(self, agent_id: int) -> AgentBody:
        """Get agent by ID (alias for get_agent_by_id)."""
        return self.get_agent_by_id(agent_id)
    
    def get_awake_agents(self) -> List[int]:
        """
        Get IDs of all awake agents.
        
        Returns:
            List of agent IDs that are awake and can take actions
        """
        return [agent.agent_id for agent in self.agents if agent.is_awake()]
    
    def advance_one_hour(self) -> None:
        """
        Advance game time by 1 hour and update all systems.
        
        Updates:
        - Game clock
        - Berry regeneration  
        - Agent hunger (for all alive agents)
        - Wake times (agents may wake up)
        """
        self.log(f"\n--- 1 hour passes (hour {self.game_time:.1f} → {self.game_time + 1:.1f}) ---")
        
        # Regenerate berries
        regenerated = self.bush.regenerate(1.0)
        if regenerated > 0:
            self.log(f"Bush regenerated {regenerated:.1f} berries -> {self.bush}")
        
        # Update all agents (hunger, wake times, death)
        for agent in self.agents:
            if agent.alive:
                was_asleep = agent.body_state == BodyState.ASLEEP
                survived = agent.pass_time(1.0)
                if not survived:
                    self.log(f"💀 {agent.name} has DIED from starvation at game time {self.game_time + 1:.1f}")
                elif was_asleep and agent.is_awake():
                    # Agent just woke up (is_awake() automatically updates state)
                    self.log(f"😴 {agent.name} wakes up")
        
        # Update game clock
        self.game_time += 1.0
        
        # Update WORLD singleton time (used by agents for wake times)
        from core.world import WORLD
        WORLD.game_time = self.game_time
    
    def create_observation(self, agent_id: int) -> AgentObservation:
        """
        Create observation for an agent's turn.
        
        Args:
            agent_id: ID of agent whose turn it is
            
        Returns:
            AgentObservation with all visible information
        """
        # Get pending messages for this agent before removing them
        pending_messages = [
            msg for msg in self.message_queue
            if msg.to_agent_id == agent_id
        ]
        
        # Use the factory method from AgentObservation
        agents_dict = {agent.agent_id: agent for agent in self.agents}
        observation = AgentObservation.from_neighbors_ids(
            observer_id=agent_id,
            agents=agents_dict,
            bush=self.bush,
            pending_messages=pending_messages
        )
        
        # Remove delivered messages (they're now in the observation)
        self.message_queue = [
            msg for msg in self.message_queue
            if msg.to_agent_id != agent_id
        ]
        
        return observation
    
    def deliver_messages_to_agent(self, agent: Any, observation: AgentObservation) -> None:
        """
        Deliver pending messages to agent for processing.
        
        Messages are processed by the agent's process_message method,
        which adds them to the agent's memory.
        
        Args:
            agent: BerriesAgent instance
            observation: AgentObservation containing pending messages
        """
        for msg in observation.pending_messages:
            agent.process_message(msg)
    
    def dispatch_agent_messages(self, agent_id: int) -> None:
        """
        Dispatch messages from an agent to their neighbors at end of turn.
        
        This adds the agent's outgoing messages to the message queue,
        so neighbors can receive them when it's their turn.
        
        Args:
            agent_id: ID of agent whose messages to dispatch
        """
        agent = self.get_agent(agent_id)
        
        # Dispatch left message
        if agent.left_neighbor_message:
            left_id = agent.get_left_neighbor_id()
            left_agent = self.get_agent(left_id)
            if left_agent.alive:
                self.message_queue.append(agent.left_neighbor_message)
                self.log(f"  → Message dispatched to {left_agent.name} (left)")
        
        # Dispatch right message
        if agent.right_neighbor_message:
            right_id = agent.get_right_neighbor_id()
            right_agent = self.get_agent(right_id)
            if right_agent.alive:
                self.message_queue.append(agent.right_neighbor_message)
                self.log(f"  → Message dispatched to {right_agent.name} (right)")
    
    def start_agent_turn(self, agent_id: int) -> None:
        """
        Prepare an agent for their turn.
        
        Clears message fields from their PREVIOUS turn so they start fresh.
        
        Args:
            agent_id: ID of agent whose turn is starting
        """
        agent = self.get_agent(agent_id)
        agent._reset_turn_tracking()
    
    def end_agent_turn(self, agent_id: int) -> None:
        """
        Complete an agent's turn.
        
        Dispatches messages to queue for neighbors.
        Messages remain stored on agent so neighbors can see "speaking" state.
        Messages will be cleared when agent's NEXT turn starts.
        
        Args:
            agent_id: ID of agent whose turn is ending
        """
        self.log(f"\n--- End of {self.get_agent(agent_id).name}'s turn ---")
        self.dispatch_agent_messages(agent_id)
        # Messages stay on agent until their next turn starts
    
    def reset_all_turn_tracking(self) -> None:
        """Reset communication tracking for all agents."""
        for agent in self.agents:
            agent._reset_turn_tracking()
    
    def execute_speak(
        self, 
        agent_id: int, 
        say_to_left: Optional[str], 
        say_to_right: Optional[str], 
        wait_for: int
    ) -> str:
        """
        Execute speak action.
        
        Args:
            agent_id: Agent performing the action
            say_to_left: Message to left neighbor (or None)
            say_to_right: Message to right neighbor (or None)
            wait_for: Duration in hours (1-8) to sleep after speaking
            
        Returns:
            Result message
        """
        agent = self.get_agent(agent_id)
        
        # Validate parameters
        if not say_to_left and not say_to_right:
            return "ERROR: Must provide at least one message (say_to_left or say_to_right)"
        
        if wait_for < 1 or wait_for > 8:
            return "ERROR: wait_for must be between 1 and 8 hours"
        
        # Store messages on agent (will be dispatched at end of turn)
        if say_to_left:
            left_id = agent.get_left_neighbor_id()
            agent.speak_to_left(say_to_left)
            self.log(f"{agent.name} prepares to speak to {self.get_agent(left_id).name}: \"{say_to_left}\"")
        
        if say_to_right:
            right_id = agent.get_right_neighbor_id()
            agent.speak_to_right(say_to_right)
            self.log(f"{agent.name} prepares to speak to {self.get_agent(right_id).name}: \"{say_to_right}\"")
        
        # Put agent to sleep
        agent.start_sleep(float(wait_for))
        self.log(f"{agent.name} goes to sleep for {wait_for} hours")
        
        return f"You speak and sleep for {wait_for} hours."
    
    def execute_sleep(self, agent_id: int, duration: int) -> str:
        """
        Execute sleep action.
        
        Args:
            agent_id: Agent performing the action
            duration: Duration in hours (1-8)
            
        Returns:
            Result message
        """
        if duration < 1 or duration > 8:
            return "ERROR: duration must be between 1 and 8 hours"
        
        agent = self.get_agent(agent_id)
        agent.start_sleep(float(duration))
        
        self.log(f"{agent.name} goes to sleep for {duration} hours")
        
        return f"You sleep for {duration} hours."
    
    def execute_eat_berries(self, agent_id: int, count: int) -> str:
        """
        Execute eat_berries action.
        
        Args:
            agent_id: Agent performing the action
            count: Number of berries to eat
            
        Returns:
            Result message
        """
        agent = self.get_agent(agent_id)
        
        if count <= 0:
            return "ERROR: count must be positive"
        
        # Try to harvest from bush
        available = self.bush.get_berry_count()
        if count > available:
            self.log(f"{agent.name} tried to eat {count} berries but only {available} available")
            return f"FAILED: Only {available} berries available. You ate nothing."
        
        harvested = self.bush.harvest(count)
        
        # Agent eats berries and get result message
        result_message = agent.eat_berries(harvested)
        
        self.log(f"{agent.name}: {result_message}")
        
        # Eating is instantaneous (agent stays awake, can act again)
        
        return result_message
    
    def is_game_over(self) -> Tuple[bool, str]:
        """
        Check if game is over.
        
        Returns:
            Tuple of (is_over: bool, reason: str)
        """
        alive_count = sum(1 for agent in self.agents if agent.alive)
        
        if alive_count == 0:
            return True, "All agents have died"
        elif alive_count == 1:
            survivor = next(a for a in self.agents if a.alive)
            return True, f"{survivor.name} is the sole survivor"
        
        return False, ""
    
    def log(self, message: str) -> None:
        """Add message to game log."""
        self.game_log.append(message)
        print(message)
    
    def get_game_summary(self) -> str:
        """Get summary of game state."""
        lines = [
            f"\n=== Game State (Turn {self.turn_number}, Hour {self.game_time:.1f}) ===",
            f"Bush: {self.bush}",
            "\nAgents:"
        ]
        
        for agent in self.agents:
            status = "ALIVE" if agent.alive else "DEAD"
            lines.append(f"  {agent.name}: {status}, hunger={int(agent.hunger)}/24, berries_eaten={agent.total_berries_consumed}")
        
        return "\n".join(lines)

