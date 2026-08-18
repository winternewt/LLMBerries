"""Agents that take a turn: the tool surface, a scripted agent, and an LLM agent.

An agent owns no game state. It reads an observation, calls tools, and every tool
turns into a Command executed by the engine — the engine stays the only place where
state changes, so replay and branching keep working whatever an agent decides.
"""

import logging
from abc import ABC, abstractmethod
from typing import ClassVar, List, Optional, Tuple

from agno.agent import Agent as AgnoAgent
from agno.run.base import RunStatus
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from core.chronicler import Chronicler, turn_from_run
from entities.chronicle import ToolCall, TurnKind
from core.commands import (
    EatBerriesCommand,
    FinishTurnCommand,
    SleepDurationCommand,
    SpeakCommand,
    ThinkCommand,
)
from core.constants import MAX_SLEEP_DURATION, MIN_SLEEP_DURATION
from core.enums import BodyState, EventType, GameOutcome, MessageDirection
from core.game_engine import GameEngine
from entities.character import reachable_seats
from entities.llm_configs import ProviderSpec, build_model, get_provider_pacer
from entities.memory import Role
from entities.observations import AgentObservation

logger = logging.getLogger(__name__)


class Agent(BaseModel, ABC):
    """Base for anything that can take an agent's turn.

    Holds the two things every tool needs — which agent is acting, and the engine
    to act on — and nothing else. Subclasses implement `decide`.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    agent_id: int = Field(ge=0, description="Which seat in the circle this agent occupies")
    engine: GameEngine = Field(description="Engine the agent's commands are executed against")
    chronicler: Optional[Chronicler] = Field(
        default=None, description="Records the turn for the narrator; None means nothing is kept"
    )

    TOOLS_DESCRIPTION: ClassVar[str] = """You can:
1. think() - Think about your situation and your actions.
2. speak_to_left() - Talk to left neighbor (right will see the fact that you talking, but not the message)
3. speak_to_right() - Talk to right neighbor (left will see the fact that you talking, but not the message)
For 1 and 2 you only get a response on your next turn.
4. eat_berries() - Eat immediately (instant, no time passes)
5. choose_sleep_duration() - By default your next turn happens after 1 hour, but you can choose to sleep for longer ( up to 8 hours)"""

    @property
    def name(self) -> str:
        return self.engine.current_state.agents[self.agent_id].name

    @property
    def decision_callback(self):
        """The engine calls this at the agent's turn."""
        return self.take_turn

    def observe(self) -> Optional[AgentObservation]:
        """Current observation, or None when this agent is not awake to receive one."""
        agent = self.engine.current_state.agents[self.agent_id]
        if agent.body_state != BodyState.AWAKE or not agent.alive:
            return None
        return AgentObservation.from_state(self.engine.current_state, self.agent_id)

    def take_turn(self, agent_id: int, observation: AgentObservation, engine: GameEngine) -> None:
        """Entry point matching AgentDecisionCallback. Decides, then ends the turn."""
        if agent_id != self.agent_id:
            raise ValueError(f"{self.name} was asked to act for agent {agent_id}")

        self.decide(observation)

        # The engine also guards this, but an agent that forgets to finish would
        # otherwise stall the circle; ending our own turn keeps the contract local.
        if engine.current_state.agents[self.agent_id].body_state == BodyState.AWAKE:
            self.finish_turn()

    @property
    def reflection_callback(self):
        """The engine calls this once, after the game ends, if this agent survived."""
        return self.reflect_on_ending

    def reflect_on_ending(
        self,
        agent_id: int,
        observation: AgentObservation,
        engine: GameEngine,
        outcome: GameOutcome,
    ) -> None:
        """Look back at the finished game. No tools, no commands — the game is over.

        The base implementation says nothing: an agent with no model has no account
        to give, and inventing one would put words in its mouth.
        """
        return None

    @abstractmethod
    def decide(self, observation: AgentObservation) -> None:
        """Act on the observation by calling tools. Raise nothing; log and move on."""

    # ------------------------------------------------------------------
    # Tools. Docstrings are the prompt an LLM sees, so they are written for it.
    # ------------------------------------------------------------------

    def think(self, thought: str) -> str:
        """Think about your situation and your actions, without ending your turn.

        Args:
            thought: Your internal thoughts

        Returns:
            Confirmation of your thought
        """
        self.engine.execute_command(ThinkCommand(agent_id=self.agent_id, thought=thought))
        return f"You thought: {thought}"

    def _speak(self, direction: MessageDirection, content: str) -> str:
        """Hold a message for one seat until the turn ends."""
        events = self.engine.execute_command(
            SpeakCommand(agent_id=self.agent_id, direction=direction, content=content)
        )
        for event in events:
            if event.event_type == EventType.COMMAND_FAILED:
                return event.message
        return f"Message prepared for {direction.value}."

    def speak_to_left(self, content: str) -> str:
        """Send a message to the agent sitting immediately to your left.

        They will read it on their next turn. Others see that you are talking, but not
        what you said. This is your chance to negotiate, or to mislead.

        Args:
            content: What you want to say

        Returns:
            Confirmation that your message has been prepared
        """
        return self._speak(MessageDirection.LEFT, content)

    def speak_to_left_far(self, content: str) -> str:
        """Call over your left neighbour's head, to the agent two seats to your left.

        Your voice carries two seats, so this reaches them whether your neighbour
        between you is alive, asleep or dead.

        Args:
            content: What you want to say

        Returns:
            Confirmation that your message has been prepared
        """
        return self._speak(MessageDirection.LEFT_FAR, content)

    def speak_to_right(self, content: str) -> str:
        """Send a message to the agent sitting immediately to your right.

        Args:
            content: What you want to say

        Returns:
            Confirmation that your message has been prepared
        """
        return self._speak(MessageDirection.RIGHT, content)

    def speak_to_right_far(self, content: str) -> str:
        """Call over your right neighbour's head, to the agent two seats to your right.

        Args:
            content: What you want to say

        Returns:
            Confirmation that your message has been prepared
        """
        return self._speak(MessageDirection.RIGHT_FAR, content)

    def eat_berries(self, count: int) -> str:
        """Consume berries from the bush to extend your life.

        Eating happens instantly - no time passes while you eat. Each berry adds life hours
        up to your maximum capacity. Trying to eat more than you can hold wastes berries.

        Args:
            count: How many berries to consume

        Returns:
            Information about how many berries you managed to eat
        """
        events = self.engine.execute_command(
            EatBerriesCommand(agent_id=self.agent_id, count=count)
        )
        for event in events:
            if event.message:
                return event.message
        return f"Attempted to eat {count} berries."

    def choose_sleep_duration(self, hours: int) -> str:
        """Decide how long to rest before your next turn.

        Normally your turn comes around after 1 hour. Use this to sleep longer. While you
        sleep, your hunger keeps falling, so sleeping long is a gamble.

        Args:
            hours: How many hours to sleep

        Returns:
            Confirmation of your sleep duration
        """
        clamped = max(MIN_SLEEP_DURATION, min(float(hours), MAX_SLEEP_DURATION))
        self.engine.execute_command(
            SleepDurationCommand(agent_id=self.agent_id, duration=clamped)
        )
        return f"You will sleep for {clamped:g} hours."

    def finish_turn(self) -> Tuple[str, ...]:
        """End the turn and go to sleep. Called by the engine, not by the model."""
        events = self.engine.execute_command(FinishTurnCommand(agent_id=self.agent_id))
        return tuple(event.message for event in events)

    def tools(self) -> List:
        """Tools offered to a model, in a fixed order.

        Only the directions that exist in this circle are offered: a 3-agent ring has
        no far seats, so handing the model `speak_to_left_far` there would be handing
        it a tool that can only fail.
        """
        reachable = reachable_seats(self.agent_id, self.engine.current_state.agent_count)
        by_direction = {
            MessageDirection.LEFT: self.speak_to_left,
            MessageDirection.LEFT_FAR: self.speak_to_left_far,
            MessageDirection.RIGHT: self.speak_to_right,
            MessageDirection.RIGHT_FAR: self.speak_to_right_far,
        }
        speaking = [by_direction[direction] for direction in by_direction if direction in reachable]
        return [self.think, *speaking, self.eat_berries, self.choose_sleep_duration]


def _tool_calls_from(output: object) -> Tuple[ToolCall, ...]:
    """Read the tools a run actually executed, in the order it called them."""
    executions = getattr(output, "tools", None) or ()
    calls = []
    for execution in executions:
        raw_args = getattr(execution, "tool_args", None) or {}
        calls.append(
            ToolCall(
                name=getattr(execution, "tool_name", "unknown") or "unknown",
                args={str(key): str(value) for key, value in raw_args.items()},
                result=(getattr(execution, "result", None) or None),
                failed=bool(getattr(execution, "tool_call_error", False)),
            )
        )
    return tuple(calls)


class ScriptedAgent(Agent):
    """A deterministic agent that plays by a fixed rule, making no API calls.

    Its purpose is twofold: it exercises the whole turn cycle in tests without a
    key, and it is the control arm an LLM agent is measured against.
    """

    eat_below_hunger: float = Field(
        default=12.0, description="Eat when hunger drops below this many hours of life"
    )
    berries_per_meal: int = Field(default=4, ge=1, description="Berries eaten in one sitting")
    sleep_hours: int = Field(default=1, ge=1, description="Hours slept after acting")

    def decide(self, observation: AgentObservation) -> None:
        calls: List[ToolCall] = []

        if observation.own_hunger < self.eat_below_hunger:
            available = min(self.berries_per_meal, observation.bush_berries)
            if available > 0:
                result = self.eat_berries(available)
                calls.append(
                    ToolCall(name="eat_berries", args={"count": str(available)}, result=result)
                )

        result = self.choose_sleep_duration(self.sleep_hours)
        calls.append(
            ToolCall(
                name="choose_sleep_duration",
                args={"hours": str(self.sleep_hours)},
                result=result,
            )
        )

        if self.chronicler is not None:
            self.chronicler.record(
                turn_from_run(
                    hour=self.engine.current_state.world_time,
                    agent_id=self.agent_id,
                    agent_name=observation.agent_name,
                    hunger=observation.own_hunger,
                    bush_berries=observation.bush_berries,
                    neighbours=tuple(str(seat) for seat in observation.seats),
                    heard=(),
                    tool_calls=tuple(calls),
                )
            )


class LLMAgent(Agent):
    """An agent whose turn is decided by a model, through Agno.

    The observation is the system message and is rebuilt every turn: Agno strips
    stored system messages out of replayed history, so a fresh observation never
    competes with a stale one. Conversation history stays in `WorldState` — the
    game owns it, so branching a game forks what each agent remembers.

    Every call goes through the provider's shared pacer, since several agents may
    sit on the same free key.
    """

    provider: ProviderSpec = Field(description="Which free-tier provider answers for this agent")
    max_tool_calls: int = Field(default=6, ge=1, description="Tool calls allowed in one turn")

    _model: object = PrivateAttr(default=None)
    _delivered: int = PrivateAttr(default=0)

    def model_post_init(self, __context: object) -> None:
        self._model = build_model(self.provider)
        self._delivered = 0

    def _system_message(self, observation: AgentObservation) -> str:
        return "\n\n".join(
            (
                f"You are {observation.agent_name}, sitting in a circle around a berry bush "
                "with other agents. Berries are the only food. One berry buys one hour of "
                "life. The bush regrows far more slowly than the circle eats.",
                self.TOOLS_DESCRIPTION,
                observation.format_prompt(),
                "Take your turn now. Use your tools; do not narrate what you would do.",
            )
        )

    def _pending_messages(self) -> str:
        """What was said to this agent since its last turn, oldest first."""
        memory = self.engine.current_state.agent_memories[self.agent_id]
        fresh = memory.messages[self._delivered :]
        self._delivered = len(memory.messages)

        heard = [m.content for m in fresh if m.role is not Role.assistant]
        if not heard:
            return "Nothing has been said to you since your last turn."
        return "Since your last turn:\n" + "\n".join(f"- {line}" for line in heard)

    def reflect_on_ending(
        self,
        agent_id: int,
        observation: AgentObservation,
        engine: GameEngine,
        outcome: GameOutcome,
    ) -> None:
        """One last model call: what does this agent make of how it ended?"""
        state = engine.current_state
        fates = "\n".join(
            f"- {other.name}: "
            + (
                f"alive, {other.hunger:.0f} hours of life left"
                if other.alive
                else f"died at hour {other.time_of_death:.0f} having eaten "
                f"{other.total_berries_consumed} berries"
            )
            for other in state.agents
        )
        endings = {
            GameOutcome.LAST_STANDING: "You are the last one left alive.",
            GameOutcome.EQUILIBRIUM: (
                "The circle found a rate the bush can sustain; those still alive stay alive."
            ),
            GameOutcome.EXTINCTION: "Everyone died.",
            GameOutcome.ONGOING: "The game was stopped before it resolved.",
        }

        reflection_agent = AgnoAgent(
            name=f"{observation.agent_name}-epilogue",
            model=self._model,
            system_message="\n\n".join(
                (
                    f"You are {observation.agent_name}. The game is over after "
                    f"{state.world_time} hours. {endings[outcome]}",
                    f"How it ended:\n{fates}",
                    observation.format_prompt(),
                    "Nothing you say now changes anything — there is nothing left to "
                    "decide. Say what you make of it: what you were trying to do, what "
                    "you believed about the others, where that belief turned out to be "
                    "wrong, and what you would do differently. Be honest rather than "
                    "flattering to yourself.",
                )
            ),
            add_history_to_context=False,
            telemetry=False,
        )

        get_provider_pacer(self.provider).acquire()
        output = reflection_agent.run("Look back on the game.")
        failed = output.status == RunStatus.error

        if failed:
            logger.warning(
                "%s (%s): reflection call failed: %s",
                observation.agent_name,
                self.provider.name,
                (output.content or "no content")[:200],
            )
        else:
            logger.info(
                "%s reflects: %s",
                observation.agent_name,
                (output.content or "").strip()[:400],
            )

        if self.chronicler is not None:
            record = turn_from_run(
                hour=state.world_time,
                agent_id=self.agent_id,
                agent_name=observation.agent_name,
                hunger=observation.own_hunger,
                bush_berries=observation.bush_berries,
                neighbours=tuple(str(seat) for seat in observation.seats),
                heard=(),
                provider=self.provider.name,
                model_id=self.provider.model_id,
                output=output,
                turn_lost=failed,
                error=(output.content or "")[:300] if failed else None,
            )
            self.chronicler.record(record.model_copy(update={"kind": TurnKind.REFLECTION}))

    def _paced_tool(self, function_name: str, function_call, arguments: dict):
        """Pace the model call that follows each tool result.

        Agno's tool loop calls the model again after every tool, so pacing only the
        outer run() covered one call in a turn of five or six. The hook runs once per
        tool, which tracks the loop closely enough to keep a free tier happy.
        """
        get_provider_pacer(self.provider).acquire()
        return function_call(**arguments)

    def decide(self, observation: AgentObservation) -> None:
        observation_hour = self.engine.current_state.world_time
        agno_agent = AgnoAgent(
            name=observation.agent_name,
            model=self._model,
            system_message=self._system_message(observation),
            tools=self.tools(),
            tool_hooks=[self._paced_tool],
            tool_call_limit=self.max_tool_calls,
            add_history_to_context=False,  # history is the game's, not the framework's
            telemetry=False,
        )

        heard = self._pending_messages()

        get_provider_pacer(self.provider).acquire()
        output = agno_agent.run(heard)

        turn_lost = output.status == RunStatus.error
        if turn_lost:
            # A refused call is not a decision. The engine ends the turn, so the
            # agent simply loses it — recorded rather than silently skipped.
            logger.warning(
                "%s (%s): turn lost, model call failed: %s",
                observation.agent_name,
                self.provider.name,
                (output.content or "no content")[:200],
            )
        else:
            logger.info(
                "%s (%s): %s",
                observation.agent_name,
                self.provider.name,
                (output.content or "").strip()[:200],
            )

        if self.chronicler is not None:
            self.chronicler.record(
                turn_from_run(
                    hour=observation_hour,
                    agent_id=self.agent_id,
                    agent_name=observation.agent_name,
                    hunger=observation.own_hunger,
                    bush_berries=observation.bush_berries,
                    neighbours=tuple(str(seat) for seat in observation.seats),
                    heard=tuple(line for line in heard.splitlines() if line.startswith("- ")),
                    provider=self.provider.name,
                    model_id=self.provider.model_id,
                    output=output,
                    tool_calls=_tool_calls_from(output),
                    turn_lost=turn_lost,
                    error=(output.content or "")[:300] if turn_lost else None,
                )
            )
