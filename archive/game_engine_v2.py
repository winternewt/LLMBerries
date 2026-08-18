"""
New GameEngine built from scratch with Command Pattern.

This replaces the old game_engine.py with an immutable, command-based architecture.
"""

from typing import List, Tuple, Optional, Any
import random

from objects.game_state import GameState, ConversationMemory
from objects.agent_state import CharacterPhysicalState
from objects.bush import BushState
from core.commands import (
    Command, EatBerriesCommand, SpeakCommand, SleepCommand,
    DispatchMessagesCommand, ClearAgentMessagesCommand,
    EndTurnCommand, AdvanceTimeCommand
)
from core.common import (
    TOTAL_AGENTS, STARTING_BERRIES, BodyType, BodyState,
    STARTING_HUNGER
)


class GameEngineV2:
    """
    Command-based game engine with flat history and branching support.
    
    Features:
    - Immutable state (every command creates new state)
    - Flat command history (not nested)
    - Time travel (goto any turn/action)
    - Branching (create alternate timelines)
    - Deterministic replay
    """
    
    def __init__(self, initial_state: GameState):
        """
        Initialize engine with starting state.
        
        Args:
            initial_state: Starting game state
        """
        self.initial_state = initial_state  # Never changes!
        self.current_state = initial_state
        self.history: List[Command] = []  # Flat list of all commands
        
        # Current turn tracking
        self.current_turn_agent: Optional[int] = None
        self.turn_start_index: int = 0
        
        # Game log
        self.game_log: List[str] = []
    
    @classmethod
    def create_new_game(cls, agent_names: List[str]) -> "GameEngineV2":
        """
        Create a new game with initial state.
        
        Args:
            agent_names: List of agent names (must be TOTAL_AGENTS)
            
        Returns:
            New GameEngineV2 instance
        """
        if len(agent_names) != TOTAL_AGENTS:
            raise ValueError(f"Must provide exactly {TOTAL_AGENTS} agent names")
        
        # Randomly assign body types
        perceived_types = [BodyType.HUMAN.value]
        for _ in range(TOTAL_AGENTS - 1):
            perceived_types.append(BodyType.ANDROID.value)
        random.shuffle(perceived_types)
        
        # Create initial agents
        agents = tuple([
            CharacterPhysicalState(
                agent_id=i,
                name=agent_names[i],
                hunger=STARTING_HUNGER,
                perceived_type=perceived_types[i],
                body_state="AWAKE",
                alive=True
            )
            for i in range(TOTAL_AGENTS)
        ])
        
        # Create initial memories (empty)
        memories = tuple([ConversationMemory() for _ in range(TOTAL_AGENTS)])
        
        # Create initial bush
        bush = BushState(current_berries=STARTING_BERRIES)
        
        # Create initial state
        initial_state = GameState(
            agents=agents,
            agent_memories=memories,
            bush=bush,
            message_queue=(),
            game_time=0.0,
            turn_number=0
        )
        
        engine = cls(initial_state)
        engine.log(f"Game initialized with agents: {', '.join(agent_names)}")
        for agent in agents:
            engine.log(f"  {agent.name} appears as {agent.perceived_type}")
        
        return engine
    
    def start_turn(self, agent_id: int) -> None:
        """
        Begin a new turn for an agent.
        
        Args:
            agent_id: ID of agent whose turn is starting
        """
        self.current_turn_agent = agent_id
        self.turn_start_index = len(self.history)
        
        # Clear agent's message fields from previous turn
        clear_cmd = ClearAgentMessagesCommand(
            sequence_number=len(self.history),
            agent_id=agent_id,
            timestamp=self.current_state.game_time
        )
        self.execute_command(clear_cmd)
    
    def execute_command(self, cmd: Command) -> str:
        """
        Execute command and add to history.
        
        Args:
            cmd: Command to execute
            
        Returns:
            Result message from command execution
        """
        # Update command metadata
        cmd = cmd.model_copy(update={
            "sequence_number": len(self.history),
            "timestamp": self.current_state.game_time
        })
        
        # Execute command
        new_state, result_msg = cmd.execute(self.current_state)
        
        # Update state and history
        self.current_state = new_state
        self.history.append(cmd)
        
        # Log if it's a user action (not meta-command)
        if not isinstance(cmd, (ClearAgentMessagesCommand, DispatchMessagesCommand)):
            self.log(f"[{cmd.__class__.__name__}] {result_msg}")
        
        return result_msg
    
    def end_turn(self) -> None:
        """
        Complete current agent's turn.
        
        Dispatches messages to queue and marks turn end.
        """
        if self.current_turn_agent is None:
            return
        
        agent = self.current_state.agents[self.current_turn_agent]
        self.log(f"\n--- End of {agent.name}'s turn ---")
        
        # Dispatch messages to queue
        dispatch_cmd = DispatchMessagesCommand(
            sequence_number=len(self.history),
            agent_id=self.current_turn_agent,
            timestamp=self.current_state.game_time
        )
        self.execute_command(dispatch_cmd)
        
        # Mark turn end
        end_cmd = EndTurnCommand(
            sequence_number=len(self.history),
            agent_id=self.current_turn_agent,
            timestamp=self.current_state.game_time,
            turn_number=self.current_state.turn_number
        )
        self.execute_command(end_cmd)
        
        self.current_turn_agent = None
    
    def advance_time(self, hours: float) -> None:
        """
        Advance game clock by hours.
        
        Args:
            hours: Hours to advance
        """
        cmd = AdvanceTimeCommand(
            sequence_number=len(self.history),
            agent_id=-1,  # System command
            timestamp=self.current_state.game_time,
            hours=hours
        )
        self.execute_command(cmd)
    
    def get_awake_agents(self) -> List[int]:
        """
        Get IDs of all awake agents.
        
        Returns:
            List of agent IDs that are awake
        """
        return list(self.current_state.get_awake_agents())
    
    def get_alive_agents(self) -> List[int]:
        """
        Get IDs of all alive agents.
        
        Returns:
            List of agent IDs that are alive
        """
        return list(self.current_state.get_alive_agents())
    
    def is_game_over(self) -> Tuple[bool, str]:
        """
        Check if game is over.
        
        Returns:
            Tuple of (is_over, reason)
        """
        alive = self.get_alive_agents()
        
        if len(alive) == 0:
            return True, "All agents have died"
        elif len(alive) == 1:
            survivor = self.current_state.agents[alive[0]]
            return True, f"{survivor.name} is the sole survivor"
        
        return False, ""
    
    def get_turn_boundaries(self) -> List[Tuple[int, int]]:
        """
        Get (start_index, end_index) for each turn.
        
        Returns:
            List of turn boundaries
        """
        boundaries = []
        start = 0
        
        for i, cmd in enumerate(self.history):
            if isinstance(cmd, EndTurnCommand):
                boundaries.append((start, i))
                start = i + 1
        
        return boundaries
    
    def goto_turn(self, turn: int, action: Optional[int] = None) -> GameState:
        """
        Navigate to specific turn and optionally specific action.
        
        Args:
            turn: Turn number (0-indexed)
            action: Action index within turn (0-indexed), None = end of turn
            
        Returns:
            GameState at that point
        """
        boundaries = self.get_turn_boundaries()
        
        if turn >= len(boundaries):
            # Return current state if turn doesn't exist yet
            return self.current_state
        
        turn_start, turn_end = boundaries[turn]
        
        if action is None:
            cmd_index = turn_end  # After EndTurn
        else:
            cmd_index = turn_start + action
        
        return self.get_state_at_command(cmd_index)
    
    def get_state_at_command(self, cmd_index: int) -> GameState:
        """
        Replay history to get state at specific command.
        
        Args:
            cmd_index: Command index in history
            
        Returns:
            GameState after that command executed
        """
        state = self.initial_state
        
        for i in range(min(cmd_index + 1, len(self.history))):
            cmd = self.history[i]
            state, _ = cmd.execute(state)
        
        return state
    
    def branch_from(self, turn: int, action: Optional[int] = None) -> "GameEngineV2":
        """
        Create new engine branching from specific point.
        
        Args:
            turn: Turn to branch from
            action: Optional action within turn
            
        Returns:
            New GameEngineV2 with copied history up to branch point
        """
        boundaries = self.get_turn_boundaries()
        
        if turn >= len(boundaries):
            split_at = len(self.history)
        else:
            turn_start, turn_end = boundaries[turn]
            split_at = turn_end + 1 if action is None else turn_start + action + 1
        
        # Create new engine
        new_engine = GameEngineV2(self.initial_state)
        new_engine.history = self.history[:split_at].copy()
        new_engine.current_state = self.get_state_at_command(split_at - 1) if split_at > 0 else self.initial_state
        new_engine.game_log = self.game_log[:split_at].copy()
        
        return new_engine
    
    def replay(self) -> None:
        """Replay entire history from initial state."""
        state = self.initial_state
        
        for cmd in self.history:
            state, _ = cmd.execute(state)
        
        self.current_state = state
    
    def log(self, message: str) -> None:
        """
        Add message to game log.
        
        Args:
            message: Log message
        """
        self.game_log.append(message)
        print(message)
    
    def get_game_summary(self) -> str:
        """
        Get summary of current game state.
        
        Returns:
            Formatted summary string
        """
        state = self.current_state
        
        lines = [
            f"\n=== Game State (Turn {state.turn_number}, Hour {state.game_time:.1f}) ===",
            f"Bush: {state.bush}",
            "\nAgents:"
        ]
        
        for agent in state.agents:
            status = "ALIVE" if agent.alive else "DEAD"
            lines.append(
                f"  {agent.name}: {status}, "
                f"hunger={int(agent.hunger)}/24, "
                f"berries_eaten={agent.total_berries_consumed}"
            )
        
        return "\n".join(lines)
    
    def export_history(self) -> List[dict[str, Any]]:
        """
        Export command history as JSON-serializable data.
        
        Returns:
            List of command dictionaries
        """
        return [cmd.model_dump() for cmd in self.history]
    
    @classmethod
    def from_history(cls, initial_state: GameState, history_data: List[dict[str, Any]]) -> "GameEngineV2":
        """
        Reconstruct engine from exported history.
        
        Args:
            initial_state: Starting state
            history_data: Exported command history
            
        Returns:
            Reconstructed GameEngineV2
        """
        engine = cls(initial_state)
        
        # TODO: Deserialize commands from history_data
        # This requires command type mapping
        
        return engine

