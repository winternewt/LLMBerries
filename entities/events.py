"""Game events for observable state changes."""

from typing import Any, Optional, Dict, Set
from pydantic import BaseModel, Field, ConfigDict
from just_agents.just_bus import BufferedEventBus
from core.enums import EventType


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


class GameEventBus(BufferedEventBus):
    """
    Event bus for game events with optional filtering.
    
    This bus extends BufferedEventBus to provide:
    - Event buffering when no subscribers exist
    - Optional event filtering by type (not used yet, but available)
    - Console logging subscriber for debugging
    
    Usage:
        bus = GameEventBus()
        bus.subscribe_console_logger()
        bus.publish_event(game_event)
    """
    
    def __init__(self, buffer_size: int = 255, event_filter: Optional[Set[EventType]] = None) -> None:
        """
        Initialize the game event bus.
        
        Args:
            buffer_size: Maximum number of events to buffer
            event_filter: Optional set of event types to filter (None = all events)
        """
        super().__init__(buffer_size=buffer_size)
        self._event_filter = event_filter
    
    def publish_event(self, event: GameEvent) -> bool:
        """
        Publish a game event to all subscribers.
        
        Args:
            event: The GameEvent to publish
            
        Returns:
            True if event was delivered to any subscriber
        """
        # Apply filter if set
        if self._event_filter is not None and event.event_type not in self._event_filter:
            return False
        
        # Publish event with hierarchical naming: "game.{event_type}"
        event_name = f"game.{event.event_type.value}"
        return self.publish(event_name, event)
    
    def subscribe_console_logger(self, verbose: bool = True) -> bool:
        """
        Subscribe a console logger to all game events.
        
        Args:
            verbose: If True, log all event details; if False, only log important events
            
        Returns:
            True if subscription successful
        """
        def console_logger(event_name: str, event: GameEvent) -> None:
            """Log event to console."""
            # Filter out internal housekeeping events in non-verbose mode
            if not verbose and event.event_type == EventType.MESSAGE_PREPARED:
                return
            
            print(f"[EVENT] {event}")
        
        # Subscribe to all game events using wildcard pattern
        return self.subscribe("game.*", console_logger)
    
    def subscribe_to_type(self, event_type: EventType, callback: Any) -> bool:
        """
        Subscribe to a specific event type.
        
        Args:
            event_type: The EventType to subscribe to
            callback: Callback function (event_name: str, event: GameEvent) -> None
            
        Returns:
            True if subscription successful
        """
        event_name = f"game.{event_type.value}"
        return self.subscribe(event_name, callback)
    
    def subscribe_to_types(self, event_types: Set[EventType], callback: Any) -> bool:
        """
        Subscribe to multiple event types with the same callback.
        
        Args:
            event_types: Set of EventTypes to subscribe to
            callback: Callback function (event_name: str, event: GameEvent) -> None
            
        Returns:
            True if all subscriptions successful
        """
        success = True
        for event_type in event_types:
            success = success and self.subscribe_to_type(event_type, callback)
        return success

