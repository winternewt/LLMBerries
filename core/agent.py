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

from core.commands import (
    EatBerriesCommand,
    FinishTurnCommand,
    SleepDurationCommand,
    SpeakCommand,
    ThinkCommand,
)
from core.constants import MAX_SLEEP_DURATION, MIN_SLEEP_DURATION
from core.enums import BodyState
from core.game_engine import GameEngine
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

    def speak_to_left(self, content: str) -> str:
        """Send a message to your left neighbor.

        The message will reach them on their next turn. Your other neighbor will see that
        you're communicating, but won't hear what you say. This is your chance to negotiate,
        or manipulate the situation.

        Args:
            content: What you want to say to your left neighbor

        Returns:
            Confirmation that your message has been prepared
        """
        self.engine.execute_command(
            SpeakCommand(agent_id=self.agent_id, say_to_left=content, say_to_right=None)
        )
        return "Message prepared for your left neighbor."

    def speak_to_right(self, content: str) -> str:
        """Send a message to your right neighbor.

        The message will reach them on their next turn. Your other neighbor will see that
        you're communicating, but won't hear what you say.

        Args:
            content: What you want to say to your right neighbor

        Returns:
            Confirmation that your message has been prepared
        """
        self.engine.execute_command(
            SpeakCommand(agent_id=self.agent_id, say_to_left=None, say_to_right=content)
        )
        return "Message prepared for your right neighbor."

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
        """Tools offered to a model, in a fixed order."""
        return [
            self.think,
            self.speak_to_left,
            self.speak_to_right,
            self.eat_berries,
            self.choose_sleep_duration,
        ]


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
        if observation.own_hunger < self.eat_below_hunger:
            available = min(self.berries_per_meal, observation.bush_berries)
            if available > 0:
                self.eat_berries(available)
        self.choose_sleep_duration(self.sleep_hours)


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

    def decide(self, observation: AgentObservation) -> None:
        agno_agent = AgnoAgent(
            name=observation.agent_name,
            model=self._model,
            system_message=self._system_message(observation),
            tools=self.tools(),
            tool_call_limit=self.max_tool_calls,
            add_history_to_context=False,  # history is the game's, not the framework's
            telemetry=False,
        )

        get_provider_pacer(self.provider).acquire()
        output = agno_agent.run(self._pending_messages())

        if output.status == RunStatus.error:
            # A refused call is not a decision. The engine ends the turn, so the
            # agent simply loses it — recorded here rather than silently skipped.
            logger.warning(
                "%s (%s): turn lost, model call failed: %s",
                observation.agent_name,
                self.provider.name,
                (output.content or "no content")[:200],
            )
            return

        logger.info(
            "%s (%s): %s", observation.agent_name, self.provider.name, (output.content or "").strip()[:200]
        )
