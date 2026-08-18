"""Game events for observable state changes, and the bus that carries them."""

import logging
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, ConfigDict, Field

from core.enums import EventType

logger = logging.getLogger(__name__)

EventCallback = Callable[[str, "GameEvent"], None]


class GameEvent(BaseModel):
    """
    Observable game event representing a state change.
    
    Events are separate from state - they capture what happened
    for logging, UI updates, and debugging. Events can be ephemeral
    or stored alongside command history.
    
    Examples:
        - EventType.BERRIES_HARVESTED: Bush lost berries
        - EventType.HUNGER_DECREASED: Agent hunger changed
        - EventType.AGENT_DIED: Agent starved
        - EventType.BUSH_REGENERATED: Bush grew berries
    """
    model_config = ConfigDict(frozen=True)
    
    sequence_number: int = Field(
        ..., 
        ge=0, 
        description="Command sequence that generated this event"
    )
    agent_id: Optional[int] = Field(
        default=None,
        description="Agent involved (None for global events)"
    )
    event_type: EventType = Field(
        ..., 
        description="Event category from EventType enum"
    )
    message: str = Field(
        ..., 
        description="Human-readable description"
    )
    data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured event data for UI/logging"
    )
    game_time: int = Field(
        default=0,
        description="Game time when event occurred (in hours)"
    )
    
    def __str__(self) -> str:
        """Human-readable format."""
        agent_prefix = f"[Agent {self.agent_id}] " if self.agent_id is not None else ""
        return f"{agent_prefix}{self.message}"
    
    def __repr__(self) -> str:
        """Debug format."""
        return f"GameEvent(seq={self.sequence_number}, type={self.event_type.name}, msg='{self.message}')"


class GameEventBus:
    """Publish/subscribe bus for game events, with buffering and prefix matching.

    Events published while nothing is listening are buffered rather than dropped,
    so a subscriber attached after the game starts still sees what it missed. That
    is the property the engine relies on: commands execute during construction,
    before any UI or logger has had a chance to subscribe.

    Subscription patterns are either an exact event name (``game.agent_died``) or a
    prefix ending in ``*`` (``game.*``, matching every game event).

    Usage:
        bus = GameEventBus()
        bus.subscribe_console_logger()
        bus.publish_event(game_event)
    """

    def __init__(self, buffer_size: int = 255, event_filter: Optional[Set[EventType]] = None) -> None:
        """
        Args:
            buffer_size: How many undelivered events to hold before the oldest is dropped
            event_filter: Only these event types are published (None publishes all)
        """
        self._subscribers: Dict[str, List[EventCallback]] = {}
        self._buffer: Deque[Tuple[str, "GameEvent"]] = deque(maxlen=buffer_size)
        self._event_filter: Optional[Set[EventType]] = event_filter

    @staticmethod
    def event_name(event_type: EventType) -> str:
        """Hierarchical name an event of this type is published under."""
        return f"game.{event_type.value}"

    @staticmethod
    def _matches(pattern: str, name: str) -> bool:
        if pattern.endswith("*"):
            return name.startswith(pattern[:-1])
        return pattern == name

    def _deliver(self, name: str, event: "GameEvent") -> bool:
        """Hand one event to every matching subscriber. True if any received it."""
        delivered = False
        for pattern in sorted(self._subscribers):
            if not self._matches(pattern, name):
                continue
            for callback in self._subscribers[pattern]:
                callback(name, event)
                delivered = True
        return delivered

    def _flush_buffer(self) -> int:
        """Deliver buffered events that now have a subscriber. Returns how many went out."""
        if not self._buffer:
            return 0

        pending = list(self._buffer)
        self._buffer.clear()
        flushed = 0
        for name, event in pending:
            if self._deliver(name, event):
                flushed += 1
            else:
                self._buffer.append((name, event))
        return flushed

    def subscribe(self, event_pattern: str, callback: EventCallback) -> bool:
        """Subscribe to an exact event name or a ``prefix*`` pattern.

        Subscribing flushes anything buffered that this subscriber now matches.
        Returns False if this exact callback is already subscribed to the pattern.
        """
        callbacks = self._subscribers.setdefault(event_pattern, [])
        if callback in callbacks:
            return False

        callbacks.append(callback)
        self._flush_buffer()
        return True

    def unsubscribe(self, event_pattern: str, callback: EventCallback) -> bool:
        """Remove one subscription. False if it was not subscribed."""
        callbacks = self._subscribers.get(event_pattern)
        if not callbacks or callback not in callbacks:
            return False

        callbacks.remove(callback)
        if not callbacks:
            del self._subscribers[event_pattern]
        return True

    def publish_event(self, event: "GameEvent") -> bool:
        """Publish a game event. Returns True if a subscriber received it.

        A filtered-out event is neither delivered nor buffered. An event nobody is
        listening for is buffered and delivered on the next matching subscribe.
        """
        if self._event_filter is not None and event.event_type not in self._event_filter:
            return False

        name = self.event_name(event.event_type)
        if self._deliver(name, event):
            return True

        self._buffer.append((name, event))
        return False

    def subscribe_console_logger(self, verbose: bool = True) -> bool:
        """Log every game event through the module logger.

        Args:
            verbose: When False, the per-message housekeeping events are skipped
        """

        def console_logger(event_name: str, event: "GameEvent") -> None:
            if not verbose and event.event_type == EventType.MESSAGE_PREPARED:
                return
            logger.info("%s", event)

        return self.subscribe("game.*", console_logger)

    def subscribe_to_type(self, event_type: EventType, callback: EventCallback) -> bool:
        """Subscribe to one event type."""
        return self.subscribe(self.event_name(event_type), callback)

    def subscribe_to_types(self, event_types: Set[EventType], callback: EventCallback) -> bool:
        """Subscribe one callback to several event types. True only if all succeeded."""
        success = True
        for event_type in sorted(event_types, key=lambda et: et.value):
            success = self.subscribe_to_type(event_type, callback) and success
        return success

    def buffered_count(self) -> int:
        """How many events are waiting for a subscriber."""
        return len(self._buffer)
