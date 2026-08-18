"""Command Pattern implementation for game actions."""
from abc import ABC, abstractmethod
from typing import Any, Tuple, Optional, Dict
from pydantic import BaseModel, Field, ConfigDict

from core.constants import (
    MAX_BERRIES, BUSH_REGENERATION_RATE, 
    HUNGER_PER_HOUR, STARTING_BERRIES,
    DEFAULT_SLEEP_DURATION
)
from core.enums import BodyState, EventType, MessageDirection

from entities.world import WorldState
from entities.events import GameEvent
from entities.bush import BushRules
from entities.character import CharacterRules, reachable_seats
from entities.memory import Role

class Command(BaseModel, ABC):
    """
    Base class for all game commands (immutable).
    
    Commands are deterministic - they store decisions, not queries.
    Each command can be replayed to recreate exact game state.
    
    Generic over StateT (game state) and EventT (event type) to decouple
    from concrete implementations. This allows commands to work with any
    immutable state and event objects.
    
    Commands emit events for observable changes (Event Stream pattern).
    Events are separate from state - they capture what happened for
    logging, UI updates, and debugging.
    
    """
    model_config = ConfigDict(frozen=True)
    
    # Metadata. The engine stamps sequence_number and timestamp when it executes the
    # command, so a caller that supplies them has them overwritten; they default rather
    # than being required, to keep call sites from inventing placeholder values.
    sequence_number: int = Field(default=0, ge=0, description="Global command index in history")
    agent_id: int = Field(..., ge=0, description="Agent executing this command")
    timestamp: int = Field(default=0, ge=0, description="Game time when command issued")
    
    @abstractmethod
    def execute(self, state: WorldState) -> Tuple[WorldState, Tuple[GameEvent, ...]]:
        """
        Execute command on state, return new state and events generated.
        
        Args:
            state: Current game state
            
        Returns:
            Tuple of (new_state, events_tuple)
            
        Note:
            Events are returned as Tuple (immutable) not List.
            Events capture observable changes (harvest, hunger update, death, etc.)
            for logging and UI. State captures final result only.
        """
        raise NotImplementedError("Subclasses must implement execute method")

    @abstractmethod
    def can_execute(self, state: WorldState) -> bool:
        """
        Check if command is valid (optional pre-validation).
        
        Args:
            state: Current game state
            
        Returns:
            True if command can execute
        """
        raise NotImplementedError("Subclasses must implement can_execute method")

# ============================================================================
# META COMMANDS (Game Engine Internal)
# ============================================================================

class ClearPendingMessagesCommand(Command):
    """
    Meta-command: Clear agent's pending message fields at start of turn.
    
    Clears the messages spoken last turn so the agent starts fresh.

    It does NOT touch sleep_duration: that is the rate the agent is currently
    sleeping at, and hunger is charged against it every hour. Resetting it here
    charged every sleeper the waking rate, which quietly made long sleep worthless.
    WakeUpCommand resets it instead, when the sleep it governed is over.
    """
    
    def can_execute(self, state: WorldState) -> bool:
        """Always executable."""
        return True
    
    def execute(self, state: WorldState) -> Tuple[WorldState, Tuple[GameEvent, ...]]:
        """Clear agent's pending messages."""
        new_state = state.with_agent(self.agent_id, pending_messages=())
        
        # No event needed - internal housekeeping
        return new_state, ()


class MarkDeadCommand(Command):
    """
    Meta-command: Mark agent as DEAD due to starvation.
    
    Sets alive=False, body_state=DEAD, records time_of_death.
    """
    
    def can_execute(self, state: WorldState) -> bool:
        """Can only mark living agents as dead."""
        agent = state.agents[self.agent_id]
        return agent.alive
    
    def execute(self, state: WorldState) -> Tuple[WorldState, Tuple[GameEvent, ...]]:
        """Mark agent as dead."""
        agent = state.agents[self.agent_id]
        
        new_state = state.with_agent(
            self.agent_id,
            alive=False,
            body_state=BodyState.DEAD,
            time_of_death=self.timestamp,
            wake_time=None
        )
        
        events = (
            GameEvent(
                sequence_number=self.sequence_number,
                agent_id=self.agent_id,
                event_type=EventType.AGENT_DIED,
                message=f"{agent.name} has died of starvation",
                data={
                    "agent_name": agent.name,
                    "time_of_death": self.timestamp,
                    "final_hunger": agent.hunger
                },
                game_time=self.timestamp
            ),
        )
        
        return new_state, events


class WakeUpCommand(Command):
    """
    Meta-command: Wake up agent from sleep.
    
    Sets body_state=AWAKE, clears wake_time, sets sleep_duration to 1 hour.
    """
    
    def can_execute(self, state: WorldState) -> bool:
        """Can only wake sleeping agents."""
        agent = state.agents[self.agent_id]
        return agent.body_state == BodyState.ASLEEP and agent.alive
    
    def execute(self, state: WorldState) -> Tuple[WorldState, Tuple[GameEvent, ...]]:
        """Wake up agent, and reset the sleep rate now that the sleep is over."""
        agent = state.agents[self.agent_id]
        
        new_state = state.with_agent(
            self.agent_id,
            body_state=BodyState.AWAKE,
            wake_time=None,
            sleep_duration=DEFAULT_SLEEP_DURATION
        )
        
        events = (
            GameEvent(
                sequence_number=self.sequence_number,
                agent_id=self.agent_id,
                event_type=EventType.AGENT_WOKE,
                message=f"{agent.name} woke up",
                data={
                    "agent_name": agent.name,
                    "hunger": agent.hunger
                },
                game_time=self.timestamp
            ),
        )
        
        return new_state, events


class AdvanceTimeCommand(Command):
    """
    Meta-command: Advance game clock and update all systems.
    
    This handles:
    - Time progression (world_time += hours)
    - Bush regeneration
    - Agent hunger decrease
    - Agent deaths
    """
    
    hours: float = Field(default=1.0, ge=0.0, description="Hours to advance")
    
    def can_execute(self, state: WorldState) -> bool:
        """Always executable."""
        return True
    
    def execute(self, state: WorldState) -> Tuple[WorldState, Tuple[GameEvent, ...]]:
        """Advance time and update all systems."""
        events_list = []
        
        # 1. Regenerate bush
        old_berries = state.bush.current_berries
        new_bush, regen_amount = BushRules.regenerate(state.bush, self.hours)
        state = state.with_bush(new_bush)
        
        if regen_amount > 0:
            events_list.append(GameEvent(
                sequence_number=self.sequence_number,
                agent_id=None,
                event_type=EventType.BUSH_REGENERATED,
                message=f"Bush regenerated {regen_amount:.2f} berries ({old_berries:.1f} -> {new_bush.current_berries:.1f})",
                data={
                    "berries_before": old_berries,
                    "berries_after": new_bush.current_berries,
                    "regenerated": regen_amount
                },
                game_time=self.timestamp
            ))
        
        # 2. Update all agents
        deaths = []
        
        for i, agent in enumerate(state.agents):
            if not agent.alive:
                continue
            
            # Calculate hunger rate (based on sleep duration)
            hunger_rate = CharacterRules.calculate_hunger_rate(agent.sleep_duration)
            
            # Apply time passage
            old_hunger = agent.hunger
            new_hunger, survived = CharacterRules.pass_time(agent.hunger, self.hours, hunger_rate)
            
            updates: Dict[str, Any] = {"hunger": new_hunger}
            
            if not survived:
                # Agent died
                updates["alive"] = False
                updates["body_state"] = BodyState.DEAD
                updates["time_of_death"] = self.timestamp + self.hours
                updates["wake_time"] = None
                deaths.append(agent.name)
                
                events_list.append(GameEvent(
                    sequence_number=self.sequence_number,
                    agent_id=i,
                    event_type=EventType.AGENT_DIED,
                    message=f"{agent.name} died of starvation",
                    data={
                        "agent_name": agent.name,
                        "time_of_death": self.timestamp + self.hours
                    },
                    game_time=self.timestamp + self.hours
                ))
            else:
                # Agent survived - emit hunger update if changed
                if abs(new_hunger - old_hunger) > 0.01:
                    events_list.append(GameEvent(
                        sequence_number=self.sequence_number,
                        agent_id=i,
                        event_type=EventType.HUNGER_DECREASED,
                        message=f"{agent.name}'s hunger decreased: {old_hunger:.1f} -> {new_hunger:.1f}",
                        data={
                            "agent_name": agent.name,
                            "hunger_before": old_hunger,
                            "hunger_after": new_hunger,
                            "hunger_rate": hunger_rate
                        },
                        game_time=self.timestamp + self.hours
                    ))
            
            state = state.with_agent(i, **updates)
        
        # 3. Advance clock
        new_time = state.world_time + self.hours
        state = state.with_time_advanced()
        
        # 4. Time advancement event
        events_list.insert(0, GameEvent(
            sequence_number=self.sequence_number,
            agent_id=None,
            event_type=EventType.TIME_ADVANCED,
            message=f"Time advanced by {self.hours} hour(s) to hour {new_time}",
            data={
                "hours": self.hours,
                "new_time": new_time,
                "deaths": deaths
            },
            game_time=self.timestamp + self.hours
        ))
        
        return state, tuple(events_list)


# ============================================================================
# PLAYER COMMANDS (LLM Agent Actions)
# ============================================================================

class ThinkCommand(Command):
    """
    Agent updates internal reasoning/memory.
    
    This command allows the LLM to add a thought to its conversation
    history without taking any game action. Useful for internal reasoning.
    """
    
    thought: str = Field(..., min_length=1, description="Agent's internal thought")
    
    def can_execute(self, state: WorldState) -> bool:
        """Agent must be alive and awake."""
        agent = state.agents[self.agent_id]
        return agent.alive and agent.body_state == BodyState.AWAKE
    
    def execute(self, state: WorldState) -> Tuple[WorldState, Tuple[GameEvent, ...]]:
        """Add thought to agent's memory."""
        agent = state.agents[self.agent_id]
        
        if not self.can_execute(state):
            return state, (
                GameEvent(
                    sequence_number=self.sequence_number,
                    agent_id=self.agent_id,
                    event_type=EventType.COMMAND_FAILED,
                    message=f"{agent.name} cannot think (dead or asleep)",
                    data={"reason": "dead_or_asleep"},
                    game_time=self.timestamp
                ),
            )
        
        # Update memory with thought
        old_memory = state.agent_memories[self.agent_id]
        new_memory = old_memory.with_message(Role.assistant, f"Internal thought: {self.thought}")
        state = state.with_agent_memory(self.agent_id, new_memory)
        
        events = (
            GameEvent(
                sequence_number=self.sequence_number,
                agent_id=self.agent_id,
                event_type=EventType.AGENT_THOUGHT,
                message=f"{agent.name} is thinking",
                data={
                    "agent_name": agent.name,
                    "thought_length": len(self.thought)
                },
                game_time=self.timestamp
            ),
        )
        
        return state, events


class EatBerriesCommand(Command):
    """
    Agent harvests berries from bush and eats them.
    
    Atomic operation: harvest from bush → eat berries → update hunger.
    If bush doesn't have enough, only available berries are harvested.
    If agent is full, excess berries are wasted.
    """
    
    count: int = Field(..., ge=1, le=10, description="Berries to eat")
    
    def can_execute(self, state: WorldState) -> bool:
        """Agent must be alive and awake."""
        agent = state.agents[self.agent_id]
        return agent.alive and agent.body_state == BodyState.AWAKE
    
    def execute(self, state: WorldState) -> Tuple[WorldState, Tuple[GameEvent, ...]]:
        """Execute eating berries."""
        agent = state.agents[self.agent_id]
        events_list = []
        
        # Validate
        if not self.can_execute(state):
            return state, (
                GameEvent(
                    sequence_number=self.sequence_number,
                    agent_id=self.agent_id,
                    event_type=EventType.COMMAND_FAILED,
                    message=f"{agent.name} cannot eat (dead or asleep)",
                    data={"reason": "dead_or_asleep"},
                    game_time=self.timestamp
                ),
            )
        
        # 1. Harvest from bush
        old_bush_berries = state.bush.current_berries
        new_bush, harvested = BushRules.harvest(state.bush, self.count)
        state = state.with_bush(new_bush)
        
        events_list.append(GameEvent(
            sequence_number=self.sequence_number,
            agent_id=self.agent_id,
            event_type=EventType.BERRIES_HARVESTED,
            message=f"{agent.name} harvested {harvested} berries from bush",
            data={
                "agent_name": agent.name,
                "requested": self.count,
                "harvested": harvested,
                "bush_before": old_bush_berries,
                "bush_after": new_bush.current_berries
            },
            game_time=self.timestamp
        ))
        
        if harvested < self.count:
            events_list.append(GameEvent(
                sequence_number=self.sequence_number,
                agent_id=self.agent_id,
                event_type=EventType.HARVEST_PARTIAL,
                message=f"Only {harvested}/{self.count} berries available",
                data={
                    "requested": self.count,
                    "available": harvested
                },
                game_time=self.timestamp
            ))
        
        if harvested == 0:
            return state, tuple(events_list)
        
        # 2. Agent eats berries
        old_hunger = agent.hunger
        new_hunger, consumed, eat_message = CharacterRules.eat_berries(
            agent.hunger, harvested, max_hunger=24.0
        )
        
        # Update agent state
        state = state.with_agent(
            self.agent_id,
            hunger=new_hunger,
            total_berries_consumed=agent.total_berries_consumed + consumed
        )
        
        events_list.append(GameEvent(
            sequence_number=self.sequence_number,
            agent_id=self.agent_id,
            event_type=EventType.BERRIES_EATEN,
            message=f"{agent.name}: {eat_message}",
            data={
                "agent_name": agent.name,
                "berries_eaten": consumed,
                "berries_wasted": harvested - consumed,
                "hunger_before": old_hunger,
                "hunger_after": new_hunger
            },
            game_time=self.timestamp
        ))
        
        return state, tuple(events_list)


class SpeakCommand(Command):
    """
    Agent addresses one seat within reach.

    The message is held on the speaker's state until FinishTurnCommand dispatches
    it, so a listener hears it on their next turn rather than mid-turn. Speaking
    again in the same direction in one turn adds a second message; both are
    delivered, in the order they were spoken.
    """

    direction: MessageDirection = Field(description="Seat addressed, relative to the speaker")
    content: str = Field(min_length=1, description="What the agent says")

    def can_execute(self, state: WorldState) -> bool:
        """Agent must be alive, awake, and the direction must land on another seat."""
        agent = state.agents[self.agent_id]
        if not (agent.alive and agent.body_state == BodyState.AWAKE):
            return False
        return self.direction in reachable_seats(self.agent_id, state.agent_count)

    def execute(self, state: WorldState) -> Tuple[WorldState, Tuple[GameEvent, ...]]:
        """Hold the message on the speaker until the turn ends."""
        agent = state.agents[self.agent_id]

        if not self.can_execute(state):
            reachable = reachable_seats(self.agent_id, state.agent_count)
            reason = (
                "dead_or_asleep"
                if not (agent.alive and agent.body_state == BodyState.AWAKE)
                else "no_such_seat"
            )
            detail = (
                f"{agent.name} cannot speak (dead or asleep)"
                if reason == "dead_or_asleep"
                else (
                    f"{agent.name} has no seat to their {self.direction.value} in a circle "
                    f"of {state.agent_count}; reachable: "
                    f"{', '.join(sorted(d.value for d in reachable))}"
                )
            )
            return state, (
                GameEvent(
                    sequence_number=self.sequence_number,
                    agent_id=self.agent_id,
                    event_type=EventType.COMMAND_FAILED,
                    message=detail,
                    data={"reason": reason, "direction": self.direction.value},
                    game_time=self.timestamp
                ),
            )

        speaker = agent.with_message(self.direction, self.content)
        state = state.with_agent(self.agent_id, pending_messages=speaker.pending_messages)

        events = (
            GameEvent(
                sequence_number=self.sequence_number,
                agent_id=self.agent_id,
                event_type=EventType.MESSAGE_PREPARED,
                message=f"{agent.name} prepared a message for {self.direction.value}",
                data={
                    "agent_name": agent.name,
                    "direction": self.direction.value,
                    "message_length": len(self.content)
                },
                game_time=self.timestamp
            ),
        )

        return state, events


class SleepDurationCommand(Command):
    """
    Agent sets sleep duration for when they finish their turn.
    
    Duration must be between 1-8 hours. Longer sleep = slower hunger rate.
    """
    
    duration: float = Field(..., ge=1.0, le=8.0, description="Sleep duration in hours")
    
    def can_execute(self, state: WorldState) -> bool:
        """Agent must be alive and awake."""
        agent = state.agents[self.agent_id]
        return agent.alive and agent.body_state == BodyState.AWAKE
    
    def execute(self, state: WorldState) -> Tuple[WorldState, Tuple[GameEvent, ...]]:
        """Set sleep duration."""
        agent = state.agents[self.agent_id]
        
        if not self.can_execute(state):
            return state, (
                GameEvent(
                    sequence_number=self.sequence_number,
                    agent_id=self.agent_id,
                    event_type=EventType.COMMAND_FAILED,
                    message=f"{agent.name} cannot set sleep duration (dead or asleep)",
                    data={"reason": "dead_or_asleep"},
                    game_time=self.timestamp
                ),
            )
        
        state = state.with_agent(self.agent_id, sleep_duration=self.duration)
        
        events = (
            GameEvent(
                sequence_number=self.sequence_number,
                agent_id=self.agent_id,
                event_type=EventType.SLEEP_DURATION_SET,
                message=f"{agent.name} will sleep for {self.duration} hours",
                data={
                    "agent_name": agent.name,
                    "duration": self.duration,
                    "hunger_rate": CharacterRules.calculate_hunger_rate(self.duration)
                },
                game_time=self.timestamp
            ),
        )
        
        return state, events


class FinishTurnCommand(Command):
    """
    Agent finishes turn and goes to sleep.
    
    This command:
    1. Sets body_state = ASLEEP
    2. Calculates wake_time = current_time + sleep_duration
    3. Dispatches pending messages to neighbor conversation histories
    """
    
    def can_execute(self, state: WorldState) -> bool:
        """Agent must be alive and awake."""
        agent = state.agents[self.agent_id]
        return agent.alive and agent.body_state == BodyState.AWAKE
    
    def execute(self, state: WorldState) -> Tuple[WorldState, Tuple[GameEvent, ...]]:
        """Finish turn and go to sleep."""
        agent = state.agents[self.agent_id]
        events_list = []
        
        if not self.can_execute(state):
            return state, (
                GameEvent(
                    sequence_number=self.sequence_number,
                    agent_id=self.agent_id,
                    event_type=EventType.COMMAND_FAILED,
                    message=f"{agent.name} cannot finish turn (dead or asleep)",
                    data={"reason": "dead_or_asleep"},
                    game_time=self.timestamp
                ),
            )
        
        # 1. Calculate wake time
        wake_time = self.timestamp + agent.sleep_duration
        
        # 2. Dispatch messages to neighbor conversation histories
        messages_dispatched = 0
        
        for pending in agent.pending_messages:
            seats = reachable_seats(self.agent_id, state.agent_count)
            target_id = seats.get(pending.direction)
            if target_id is None:
                # The seat vanished between speaking and finishing — only possible if
                # the circle changed size, which it cannot. Recorded rather than lost.
                events_list.append(GameEvent(
                    sequence_number=self.sequence_number,
                    agent_id=self.agent_id,
                    event_type=EventType.MESSAGE_UNDELIVERED,
                    message=f"{agent.name}'s message to {pending.direction.value} had no seat",
                    data={"from_agent": agent.name, "direction": pending.direction.value,
                          "reason": "no_such_seat"},
                    game_time=self.timestamp
                ))
                continue

            target = state.agents[target_id]
            if not target.alive:
                # The dead do not listen. The speaker is told, so silence is not
                # mistaken for a neighbour choosing not to answer.
                events_list.append(GameEvent(
                    sequence_number=self.sequence_number,
                    agent_id=self.agent_id,
                    event_type=EventType.MESSAGE_UNDELIVERED,
                    message=f"{agent.name} spoke to {target.name}, who is dead",
                    data={"from_agent": agent.name, "to_agent": target.name,
                          "direction": pending.direction.value, "reason": "recipient_dead"},
                    game_time=self.timestamp
                ))
                continue

            heard_from = pending.direction.label
            message_text = (
                f"About {int(self.timestamp)} hours in, {heard_from} ({agent.name}) "
                f"said: {pending.content}"
            )
            state = state.with_agent_memory(
                target_id, state.agent_memories[target_id].with_message(Role.system, message_text)
            )
            messages_dispatched += 1

            events_list.append(GameEvent(
                sequence_number=self.sequence_number,
                agent_id=self.agent_id,
                event_type=EventType.MESSAGE_DISPATCHED,
                message=f"{agent.name} sent a message {pending.direction.value} to {target.name}",
                data={
                    "from_agent": agent.name,
                    "to_agent": target.name,
                    "direction": pending.direction.value
                },
                game_time=self.timestamp
            ))

        # 3. Put agent to sleep
        state = state.with_agent(
            self.agent_id,
            body_state=BodyState.ASLEEP,
            wake_time=wake_time
        )
        
        events_list.append(GameEvent(
            sequence_number=self.sequence_number,
            agent_id=self.agent_id,
            event_type=EventType.AGENT_SLEPT,
            message=f"{agent.name} went to sleep for {agent.sleep_duration} hours (wake at hour {int(wake_time)})",
            data={
                "agent_name": agent.name,
                "sleep_duration": agent.sleep_duration,
                "wake_time": wake_time,
                "messages_dispatched": messages_dispatched
            },
            game_time=self.timestamp
        ))
        
        return state, tuple(events_list)
