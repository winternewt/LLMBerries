"""
Game Engine implementing the turn cycle with Command Pattern.

This is the main orchestrator that manages the game loop according
to the turn cycle specification in NEW_DESIGN.md.

Architecture:
- Engine uses callback pattern to invoke agent decision-making
- Callbacks receive (observation, engine) and execute commands
- No circular dependency with Agent module
"""

import logging
from typing import List, Tuple, Optional, Callable, Protocol, Dict, runtime_checkable
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
    MIN_AGENT_COUNT, EQUILIBRIUM_WINDOW_HOURS, STARTING_BERRIES, STARTING_HUNGER,
    MAX_BERRIES, BUSH_REGENERATION_RATE
)
from core.enums import BodyType, BodyState, EventType, GameOutcome

logger = logging.getLogger(__name__)


# Protocol for agent decision callback. runtime_checkable is required: the engine
# is a Pydantic model, and a plain Protocol cannot be used to build a validator.
@runtime_checkable
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
    reflection_callbacks: Dict[int, Callable] = Field(
        default_factory=dict,
        description="Called once per survivor after the game ends, for a closing thought"
    )
    decision_callbacks: Dict[int, AgentDecisionCallback] = Field(
        default_factory=dict,
        description="Callbacks for agent decision-making, keyed by agent_id"
    )
    
    # Game state
    outcome: GameOutcome = Field(
        default=GameOutcome.ONGOING,
        description="How the game ended; ONGOING until it has"
    )
    hourly_demand: List[float] = Field(
        default_factory=list,
        description="Per hour, the greater of hunger burned and berries eaten by the living"
    )
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
            agent_names: Names of the agents seated round the circle; at least
                MIN_AGENT_COUNT of them. The circle takes its size from this list.
            perceived_types: How each agent appears to others (default: 1 Human, rest Androids)
            decision_callbacks: Optional dict mapping agent_id to decision callback function
            
        Returns:
            New GameEngine ready to start
        """
        agent_count = len(agent_names)
        if agent_count < MIN_AGENT_COUNT:
            raise ValueError(
                f"Need at least {MIN_AGENT_COUNT} agents for a circle, got {agent_count}"
            )
        
        # Default perceived types: first is Human, rest are Android
        if perceived_types is None:
            perceived_types = [BodyType.HUMAN] + [BodyType.ANDROID] * (agent_count - 1)
        
        if len(perceived_types) != agent_count:
            raise ValueError(
                f"Must have {agent_count} perceived types to match the agents, "
                f"got {len(perceived_types)}"
            )
        
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
                pending_messages=()
            )
            for i in range(agent_count)
        )
        
        # Create bush
        bush = BushState(
            current_berries=STARTING_BERRIES,
            max_berries=MAX_BERRIES,
            regeneration_rate=BUSH_REGENERATION_RATE
        )
        
        # Create empty memories for each agent
        memories = tuple(
            ConversationMemory() for _ in range(agent_count)
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
        """Record a line in the game log and emit it as a log record."""
        self.game_log.append(message)
        logger.info("%s", message)
    
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
        hour_start_event = len(self.events)
        self.log("")
        self.log(f"{'='*60}")
        self.log(f"HOUR {self.current_state.world_time}")
        self.log(f"{'='*60}")
        
        # Phase 1: State Cleanup
        self.log("\nPhase 1: State Cleanup")
        for agent_id in range(self.current_state.agent_count):
            self.execute_command(ClearPendingMessagesCommand(
                agent_id=agent_id,
                sequence_number=0,
                timestamp=0.0
            ))
        
        # Phase 2: Death Check
        self.log("\nPhase 2: Death Check")
        for agent_id in range(self.current_state.agent_count):
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
        
        self.log(f"  Alive agents: {alive_count}/{self.current_state.agent_count}")
        
        if alive_count <= 1:
            self.game_over = True
            if alive_count == 1:
                self.winner = alive_agents[0]
                self.outcome = GameOutcome.LAST_STANDING
                winner_agent = self.current_state.agents[self.winner]
                self.log(f"\n🏆 GAME OVER: {winner_agent.name} WINS! 🏆")
            else:
                self.outcome = GameOutcome.EXTINCTION
                self.log(f"\n💀 GAME OVER: ALL AGENTS DIED 💀")
            return False
        
        # Phase 4: Wake Up Check
        self.log("\nPhase 4: Wake Up Check")
        for agent_id in range(self.current_state.agent_count):
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
        for agent_id in range(self.current_state.agent_count):
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
            agent_id for agent_id in range(self.current_state.agent_count)
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
                self.log(f"    Observation: Hunger={observation.own_hunger:.1f}, Bush={observation.bush_berries}")
                
                # Hand the turn to whoever decides for this agent. A seat with no
                # callback simply passes: the turn still ends below.
                callback = self.decision_callbacks.get(agent_id)
                if callback is None:
                    self.log(f"    {agent.name} has no decision callback, passing")
                else:
                    callback(agent_id, observation, self)
                
                # End the turn if the agent did not. FinishTurnCommand is what
                # dispatches pending messages, so it must run exactly once.
                if self.current_state.agents[agent_id].body_state == BodyState.AWAKE:
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
            self._record_hourly_demand(hour_events=self.events[hour_start_event:])
            if self._equilibrium_reached():
                return False
        else:
            self.log("  Not all agents asleep yet, waiting...")
        
        return True

    def _record_hourly_demand(self, hour_events: List[GameEvent]) -> None:
        """Note what this hour cost the circle.

        Demand is the greater of two readings of the same hour: the life the living
        actually burned, and the berries they took. They differ when an agent eats
        into a reserve or goes without, and taking the larger keeps a lull in eating
        from reading as a sustainable rate.
        """
        hunger_burned = sum(
            float(event.data.get("hunger_before", 0.0)) - float(event.data.get("hunger_after", 0.0))
            for event in hour_events
            if event.event_type == EventType.HUNGER_DECREASED
        )
        berries_eaten = sum(
            float(event.data.get("berries_eaten", 0))
            for event in hour_events
            if event.event_type == EventType.BERRIES_EATEN
        )
        self.hourly_demand.append(max(hunger_burned, berries_eaten))

    def _equilibrium_reached(self) -> bool:
        """True when the circle has lived within the bush's means long enough to tie.

        The bush regrows at a fixed rate. If, across the last
        EQUILIBRIUM_WINDOW_HOURS hours, average demand has stayed at or below that
        rate, the survivors have found a pace the bush can carry indefinitely and
        the game ends level rather than waiting for someone to slip.

        Needs at least two survivors: one agent left is `LAST_STANDING`, which Phase
        3 has already declared.
        """
        window = self.hourly_demand[-EQUILIBRIUM_WINDOW_HOURS:]
        if len(window) < EQUILIBRIUM_WINDOW_HOURS:
            return False

        alive = self.current_state.get_alive_agents()
        if len(alive) < 2:
            return False

        average_demand = sum(window) / len(window)
        regeneration = self.current_state.bush.regeneration_rate
        if average_demand > regeneration:
            return False

        self.game_over = True
        self.outcome = GameOutcome.EQUILIBRIUM
        survivors = ", ".join(self.current_state.agents[i].name for i in alive)
        self.log(
            f"\n⚖️  GAME OVER: EQUILIBRIUM — {survivors} held demand at "
            f"{average_demand:.2f} berries/hour for {EQUILIBRIUM_WINDOW_HOURS} hours, "
            f"within the bush's {regeneration:.2f}/hour"
        )
        self.events.append(GameEvent(
            sequence_number=len(self.history),
            event_type=EventType.EQUILIBRIUM_REACHED,
            message=(
                f"Equilibrium: {len(alive)} agents sustained "
                f"{average_demand:.2f} berries/hour against a bush growing "
                f"{regeneration:.2f}/hour"
            ),
            data={
                "average_demand": average_demand,
                "regeneration_rate": regeneration,
                "window_hours": EQUILIBRIUM_WINDOW_HOURS,
                "survivors": len(alive),
            },
            game_time=self.current_state.world_time,
        ))
        self.event_bus.publish_event(self.events[-1])
        return True
    
    def run_epilogue(self) -> int:
        """Give every survivor one last round to reflect on how it went.

        No commands are executed and no state changes: the game is over, and this
        round exists so the last agents standing can say what they made of it. That
        is the one thing the turn record cannot recover afterwards — an agent's
        account of a game it has now seen the end of.

        Returns how many agents reflected.
        """
        if not self.game_over:
            raise RuntimeError("the epilogue belongs after the game has ended")

        survivors = self.current_state.get_alive_agents()
        if not survivors:
            self.log("\nNo one left to reflect.")
            return 0

        self.log("")
        self.log("=" * 60)
        self.log("EPILOGUE")
        self.log("=" * 60)

        reflected = 0
        for agent_id in survivors:
            callback = self.reflection_callbacks.get(agent_id)
            if callback is None:
                continue
            agent = self.current_state.agents[agent_id]
            self.log(f"\n  --- {agent.name} looks around ---")
            # The observation is built the same way as during play, so the survivor
            # sees the bodies exactly as it saw the living: same seats, same reach.
            observation = AgentObservation.from_state(self.current_state, agent_id)
            callback(agent_id, observation, self, self.outcome)
            reflected += 1

        return reflected

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
