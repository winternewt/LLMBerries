"""
Game Engine implementing the turn cycle with Command Pattern.

This is the main orchestrator that manages the game loop according
to the turn cycle specification in NEW_DESIGN.md.

Architecture:
- Engine uses callback pattern to invoke agent decision-making
- Callbacks receive (observation, engine) and execute commands
- No circular dependency with Agent module
"""

from typing import List, Tuple, Optional, Callable, Protocol, Dict
from pydantic import BaseModel, Field, ConfigDict
from entities.world import WorldState
from entities.character import CharacterPhysicalState
from entities.bush import BushState
from entities.memory import ConversationMemory
from entities.events import GameEvent, GameEventBus
from core.commands import (
    Command, ClearPendingMessagesCommand, MarkDeadCommand, WakeUpCommand,
    AdvanceTimeCommand, ThinkCommand, EatBerriesCommand, SpeakCommand,
    SleepDurationCommand, FinishTurnCommand
)
from entities.observations import AgentObservation
from core.constants import (
    TOTAL_AGENTS, STARTING_BERRIES, STARTING_HUNGER,
    MAX_BERRIES, BUSH_REGENERATION_RATE
)
from core.enums import BodyType, BodyState, EventType


# Protocol for agent decision callback (for type hints only, no class needed)
class AgentDecisionCallback(Protocol):
    """
    Protocol defining the signature for agent decision callbacks.
    
    Args:
        agent_id: The agent making the decision
        observation: Current observation of the world
        engine: GameEngine instance to execute commands on
    """
    def __call__(self, agent_id: int, observation: AgentObservation, engine: "GameEngine") -> None:
        ...


#
# Game Cycle Specification:
#  - Game starts @ turn 0, agents are in ASLEEP state with waketime 0, all have 20/24 hunger, no messages. 
#  - Turn starts, agents are checked clockwise:
#   - State cleanup: pending messages cleared
#   - Hunger check: if agents are at 0 hunger, change state to DEAD
#   - Alive check: if only one or less agents are alive, game over, end game.  
#   - Waketime check: if agent waketime is reached, change state to AWAKE, sleep duration is set to 1 hour.
#   - State report: all agents are checked and their state is reported to events
#   - Observations check, if any agent is AWAKE,
#     - they receive observations based on their neighbors states at this moment.
#     - they receive complete observation of the world at this moment plus the above.
#   - Actions check (clockwise), if any agent is AWAKE, they can take any number of the below actions:
#     - ThinkCommand: updates agent's internal memory
#     - EatBerriesCommand: harvest, eat
#     - SpeakCommand: sets messages for neighbors
#     - SleepDurationCommand: sets sleep duration
#     - FinishTurnCommand: end turn, agent goes to sleep: 
#       - waketime is set to current time + sleep duration
#       - messages are dispatched to neighbor conversation histories with prefix (eg, hour X: left speaks to you:...)
#   - Once no agents left awake, advance time (AdvanceTimeCommand):
#     - Advance time by 1 hour
#     - Regenerate bush
#     - Agent's hunger is decreased depending on their rate.
#     


class GameEngine(BaseModel):
    """
    Command-based game engine implementing the full turn cycle.
    
    Features:
    - Immutable state (every command creates new state)
    - Flat command history (for replay/time-travel)
    - Event stream (for logging/UI updates)
    - Turn cycle phases (cleanup → checks → actions → time advance)
    
    Turn Cycle (from NEW_DESIGN.md):
    1. State cleanup (clear pending messages)
    2. Death check (hunger <= 0 → DEAD)
    3. Game over check (≤1 alive → end game)
    4. Wake up check (wake_time reached → AWAKE)
    5. State report (emit events)
    6. Observations & actions (for AWAKE agents)
    7. Time advancement (once all asleep)
    """
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    # Core state
    initial_state: WorldState = Field(
        description="Initial game state, never changes (for replay)"
    )
    current_state: WorldState = Field(
        description="Current game state"
    )
    
    # History and events
    history: List[Command] = Field(
        default_factory=list,
        description="Flat list of all commands executed"
    )
    events: List[GameEvent] = Field(
        default_factory=list,
        description="All events generated during the game"
    )
    
    # Event bus for real-time event publishing
    event_bus: GameEventBus = Field(
        default_factory=GameEventBus,
        description="Event bus for publishing events to subscribers"
    )
    
    # Agent decision callbacks (callback pattern to avoid circular dependency)
    decision_callbacks: Dict[int, AgentDecisionCallback] = Field(
        default_factory=dict,
        description="Callbacks for agent decision-making, keyed by agent_id"
    )
    
    # Game state
    game_over: bool = Field(
        default=False,
        description="Whether the game has ended"
    )
    winner: Optional[int] = Field(
        default=None,
        description="Agent ID of the winner, if any"
    )
    game_log: List[str] = Field(
        default_factory=list,
        description="Game log messages"
    )
    
    @classmethod
    def create_new_game(
        cls, 
        agent_names: List[str],
        perceived_types: Optional[List[BodyType]] = None,
        decision_callbacks: Optional[Dict[int, AgentDecisionCallback]] = None
    ) -> "GameEngine":
        """
        Create a new game with specified agents.
        
        Args:
            agent_names: List of agent names (must be 3)
            perceived_types: How each agent appears to others (default: 1 Human, 2 Androids)
            decision_callbacks: Optional dict mapping agent_id to decision callback function
            
        Returns:
            New GameEngine ready to start
        """
        if len(agent_names) != TOTAL_AGENTS:
            raise ValueError(f"Must have exactly {TOTAL_AGENTS} agents, got {len(agent_names)}")
        
        # Default perceived types: first is Human, rest are Android
        if perceived_types is None:
            perceived_types = [BodyType.HUMAN] + [BodyType.ANDROID] * (TOTAL_AGENTS - 1)
        
        if len(perceived_types) != TOTAL_AGENTS:
            raise ValueError(f"Must have {TOTAL_AGENTS} perceived types, got {len(perceived_types)}")
        
        # Create agents (all start ASLEEP with wake_time=0, will wake immediately)
        agents = tuple(
            CharacterPhysicalState(
                agent_id=i,
                name=agent_names[i],
                hunger=STARTING_HUNGER,
                perceived_type=perceived_types[i],
                body_state=BodyState.ASLEEP,
                alive=True,
                wake_time=0.0,  # Wake immediately on first turn
                sleep_duration=1.0,
                total_berries_consumed=0,
                time_of_death=None,
                left_message=None,
                right_message=None
            )
            for i in range(TOTAL_AGENTS)
        )
        
        # Create bush
        bush = BushState(
            current_berries=STARTING_BERRIES,
            max_berries=MAX_BERRIES,
            regeneration_rate=BUSH_REGENERATION_RATE
        )
        
        # Create empty memories for each agent
        memories = tuple(
            ConversationMemory() for _ in range(TOTAL_AGENTS)
        )
        
        # Create initial world state
        initial_state = WorldState(
            world_time=0,
            active_agent_id=0,
            agents=agents,
            bush=bush,
            agent_memories=memories
        )
        
        # Create event bus
        event_bus = GameEventBus()
        
        engine = cls(
            initial_state=initial_state,
            current_state=initial_state,
            event_bus=event_bus
        )
        
        # Log game start
        engine.log("=" * 60)
        engine.log("GAME START")
        engine.log("=" * 60)
        for agent in agents:
            engine.log(f"  {agent.name}: Hunger={agent.hunger}/24, Type={agent.perceived_type}")
        engine.log(f"  Bush: {bush.current_berries}/{bush.max_berries} berries")
        engine.log("")
        
        return engine
    
    def log(self, message: str) -> None:
        """Add message to game log."""
        self.game_log.append(message)
        print(message)
    
    def execute_command(self, cmd: Command) -> Tuple[GameEvent, ...]:
        """
        Execute command and add to history.
        
        Args:
            cmd: Command to execute
            
        Returns:
            Tuple of events generated
        """
        # Update command metadata
        cmd = cmd.model_copy(update={
            "sequence_number": len(self.history),
            "timestamp": float(self.current_state.world_time)
        })
        
        # Execute command
        new_state, events = cmd.execute(self.current_state)
        
        # Update state and history
        self.current_state = new_state
        self.history.append(cmd)
        self.events.extend(events)
        
        # Publish events to event bus
        for event in events:
            self.event_bus.publish_event(event)
        
        # Log events
        for event in events:
            # Only log important events (filter out internal housekeeping)
            if event.event_type != EventType.MESSAGE_PREPARED:
                self.log(f"  [{event.event_type.name}] {event.message}")
        
        return events
    
    def run_turn_cycle(self) -> bool:
        """
        Execute one complete turn cycle.
        
        Returns:
            True if game continues, False if game over
        """
        self.log("")
        self.log(f"{'='*60}")
        self.log(f"HOUR {self.current_state.world_time}")
        self.log(f"{'='*60}")
        
        # Phase 1: State Cleanup
        self.log("\nPhase 1: State Cleanup")
        for agent_id in range(TOTAL_AGENTS):
            self.execute_command(ClearPendingMessagesCommand(
                agent_id=agent_id,
                sequence_number=0,
                timestamp=0.0
            ))
        
        # Phase 2: Death Check
        self.log("\nPhase 2: Death Check")
        for agent_id in range(TOTAL_AGENTS):
            agent = self.current_state.agents[agent_id]
            if agent.hunger <= 0 and agent.alive:
                self.execute_command(MarkDeadCommand(
                    agent_id=agent_id,
                    sequence_number=0,
                    timestamp=0.0
                ))
        
        # Phase 3: Game Over Check
        self.log("\nPhase 3: Game Over Check")
        alive_agents = self.current_state.get_alive_agents()
        alive_count = len(alive_agents)
        
        self.log(f"  Alive agents: {alive_count}/{TOTAL_AGENTS}")
        
        if alive_count <= 1:
            self.game_over = True
            if alive_count == 1:
                self.winner = alive_agents[0]
                winner_agent = self.current_state.agents[self.winner]
                self.log(f"\n🏆 GAME OVER: {winner_agent.name} WINS! 🏆")
            else:
                self.log(f"\n💀 GAME OVER: ALL AGENTS DIED 💀")
            return False
        
        # Phase 4: Wake Up Check
        self.log("\nPhase 4: Wake Up Check")
        for agent_id in range(TOTAL_AGENTS):
            agent = self.current_state.agents[agent_id]
            if agent.wake_time is not None and self.current_state.world_time >= agent.wake_time:
                if agent.body_state == BodyState.ASLEEP and agent.alive:
                    self.execute_command(WakeUpCommand(
                        agent_id=agent_id,
                        sequence_number=0,
                        timestamp=0.0
                    ))
        
        # Phase 5: State Report
        self.log("\nPhase 5: State Report")
        for agent_id in range(TOTAL_AGENTS):
            agent = self.current_state.agents[agent_id]
            if agent.alive:
                status = f"  {agent.name}: Hunger={agent.hunger:.1f}/24, State={agent.body_state.name}"
                self.log(status)
            else:
                self.log(f"  {agent.name}: DEAD")
        self.log(f"  Bush: {int(self.current_state.bush.current_berries)}/{int(MAX_BERRIES)} berries")
        
        # Phase 6: Observations & Actions (for AWAKE agents)
        self.log("\nPhase 6: Agent Actions")
        awake_agents = [
            agent_id for agent_id in range(TOTAL_AGENTS)
            if self.current_state.agents[agent_id].body_state == BodyState.AWAKE
        ]
        
        if not awake_agents:
            self.log("  No agents awake")
        else:
            for agent_id in awake_agents:
                agent = self.current_state.agents[agent_id]
                self.log(f"\n  --- {agent.name}'s Turn ---")
                
                # Generate observation
                observation = AgentObservation.from_state(self.current_state, agent_id)
                
                # NOTE: This is where LLM agent would decide actions
                # For now, this is just the engine infrastructure
                # The actual agent decision-making will be plugged in here
                
                # The agent would call:
                # - agent.decide(observation) → returns list of commands
                # - engine.execute_command(cmd) for each command
                # - until FinishTurnCommand is issued
                
                self.log(f"    Waiting for {agent.name} to act...")
                self.log(f"    Observation: Hunger={observation.own_hunger:.1f}, Bush={observation.bush_berries}")
                
                # For now, we'll just have agents finish their turn immediately
                # In real game, this would be agent.decide() loop
                self.execute_command(FinishTurnCommand(
                    agent_id=agent_id,
                    sequence_number=0,
                    timestamp=0.0
                ))
        
        # Phase 7: Time Advancement
        self.log("\nPhase 7: Time Advancement")
        all_asleep = all(
            agent.body_state != BodyState.AWAKE
            for agent in self.current_state.agents
            if agent.alive
        )
        
        if all_asleep:
            self.execute_command(AdvanceTimeCommand(
                agent_id=0,  # Global command, agent_id doesn't matter
                hours=1.0,
                sequence_number=0,
                timestamp=0.0
            ))
        else:
            self.log("  Not all agents asleep yet, waiting...")
        
        return True
    
    def run_game(self, max_hours: int = 100) -> None:
        """
        Run complete game until game over or max hours reached.
        
        Args:
            max_hours: Maximum hours to run before stopping
        """
        while not self.game_over and self.current_state.world_time < max_hours:
            should_continue = self.run_turn_cycle()
            if not should_continue:
                break
        
        # Final report
        self.log("")
        self.log("=" * 60)
        self.log("FINAL STATS")
        self.log("=" * 60)
        for agent in self.current_state.agents:
            if agent.alive:
                self.log(f"  {agent.name}: ALIVE, Hunger={agent.hunger:.1f}/24, Berries eaten={agent.total_berries_consumed}")
            else:
                self.log(f"  {agent.name}: DEAD at hour {agent.time_of_death}, Berries eaten={agent.total_berries_consumed}")
        self.log(f"  Total commands executed: {len(self.history)}")
        self.log(f"  Total events generated: {len(self.events)}")
        self.log("")
    
    def get_state(self) -> WorldState:
        """Get current world state."""
        return self.current_state
    
    def get_history(self) -> List[Command]:
        """Get command history."""
        return self.history.copy()
    
    def get_events(self) -> List[GameEvent]:
        """Get all events."""
        return self.events.copy()
    
    def get_events_by_type(self, event_type: str) -> List[GameEvent]:
        """Get all events of specific type."""
        return [e for e in self.events if e.event_type == event_type]
    
    def get_events_by_agent(self, agent_id: int) -> List[GameEvent]:
        """Get all events for specific agent."""
        return [e for e in self.events if e.agent_id == agent_id]
    
    def replay(self) -> "GameEngine":
        """
        Replay entire game from history.
        
        Returns:
            New engine with same final state
        """
        new_engine = GameEngine(
            initial_state=self.initial_state,
            current_state=self.initial_state
        )
        for cmd in self.history:
            new_engine.execute_command(cmd)
        return new_engine
    
    def branch_from(self, turn: int) -> "GameEngine":
        """
        Create new engine from historical point.
        
        Args:
            turn: Turn number to branch from
            
        Returns:
            New engine at that point in history
        """
        commands = self.history[:turn]
        new_engine = GameEngine(
            initial_state=self.initial_state,
            current_state=self.initial_state
        )
        for cmd in commands:
            new_engine.execute_command(cmd)
        return new_engine
