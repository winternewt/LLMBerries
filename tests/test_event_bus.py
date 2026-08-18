"""Test script to demonstrate GameEventBus with console subscriber."""

import sys

# Fix encoding for Windows
if sys.platform == 'win32':
    # Force UTF-8 encoding for stdout/stderr
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    if sys.stderr.encoding != 'utf-8':
        sys.stderr.reconfigure(encoding='utf-8')

from core.game_engine import GameEngine
from core.enums import EventType


def test_event_bus_console_subscriber():
    """Test that event bus publishes events and console subscriber receives them."""
    print("\n" + "=" * 60)
    print("TESTING EVENT BUS WITH CONSOLE SUBSCRIBER")
    print("=" * 60 + "\n")
    
    # Create a new game
    engine = GameEngine.create_new_game(
        agent_names=["Alice", "Bob", "Charlie"]
    )
    
    # Define console logger callback so we can unsubscribe later
    def console_logger(event_name: str, event) -> None:
        """Log event to console."""
        from core.enums import EventType
        if event.event_type != EventType.MESSAGE_PREPARED:
            print(f"[EVENT] {event}")
    
    # Subscribe console logger to event bus
    print("Subscribing console logger to event bus...\n")
    engine.event_bus.subscribe("game.*", console_logger)
    
    # Run a few turn cycles to generate events
    print("Running 3 turn cycles to generate events...\n")
    for i in range(3):
        if not engine.run_turn_cycle():
            break
    
    # Unsubscribe console logger
    print("\nUnsubscribing console logger...\n")
    engine.event_bus.unsubscribe("game.*", console_logger)
    
    # Print summary
    print("=" * 60)
    print("EVENT BUS TEST SUMMARY")
    print("=" * 60)
    print(f"Total events generated: {len(engine.events)}")
    print(f"Total commands executed: {len(engine.history)}")
    print(f"Event types observed:")
    
    event_type_counts = {}
    for event in engine.events:
        event_type_counts[event.event_type] = event_type_counts.get(event.event_type, 0) + 1
    
    for event_type, count in sorted(event_type_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  - {event_type.name}: {count}")
    
    print("\n" + "=" * 60 + "\n")


def test_event_bus_specific_type_subscriber():
    """Test subscribing to specific event types."""
    print("\n" + "=" * 60)
    print("TESTING SPECIFIC EVENT TYPE SUBSCRIPTION")
    print("=" * 60 + "\n")
    
    # Create a new game
    engine = GameEngine.create_new_game(
        agent_names=["Alice", "Bob", "Charlie"]
    )
    
    # Track agent deaths
    deaths = []
    
    def death_tracker(event_name: str, event) -> None:
        """Track agent deaths."""
        deaths.append({
            "agent": event.agent_id,
            "time": event.game_time,
            "message": event.message
        })
        print(f"💀 DEATH TRACKED: {event.message}")
    
    # Subscribe to agent death events only
    print("Subscribing death tracker to AGENT_DIED events...\n")
    engine.event_bus.subscribe_to_type(EventType.AGENT_DIED, death_tracker)
    
    # Run game until game over or max turns (no console logging this time)
    print("Running game until game over (no console logging)...\n")
    max_turns = 50
    for i in range(max_turns):
        if not engine.run_turn_cycle():
            break
    
    # Unsubscribe death tracker
    death_event_name = f"game.{EventType.AGENT_DIED.value}"
    engine.event_bus.unsubscribe(death_event_name, death_tracker)
    
    # Print summary
    print("\n" + "=" * 60)
    print("DEATH TRACKER SUMMARY")
    print("=" * 60)
    print(f"Total deaths tracked: {len(deaths)}")
    for death in deaths:
        print(f"  - Agent {death['agent']} at hour {death['time']}: {death['message']}")
    print("\n" + "=" * 60 + "\n")


def test_event_bus_filtering():
    """Test event filtering by type."""
    print("\n" + "=" * 60)
    print("TESTING EVENT BUS WITH FILTERING")
    print("=" * 60 + "\n")
    
    # Create game with event bus that filters to only show critical events
    engine = GameEngine.create_new_game(
        agent_names=["Alice", "Bob", "Charlie"]
    )
    
    # Replace event bus with filtered one (only critical events)
    from entities.events import GameEventBus
    critical_events = {
        EventType.AGENT_DIED,
        EventType.BERRIES_EATEN,
        EventType.TIME_ADVANCED
    }
    
    filtered_bus = GameEventBus(event_filter=critical_events)
    
    # Define console logger so we can unsubscribe it
    def filtered_console_logger(event_name: str, event) -> None:
        print(f"[FILTERED EVENT] {event}")
    
    filtered_bus.subscribe("game.*", filtered_console_logger)
    engine.event_bus = filtered_bus
    
    print(f"Event bus configured to only publish: {[e.name for e in critical_events]}\n")
    
    # Run a few turns
    print("Running 3 turn cycles with filtered event bus...\n")
    for i in range(3):
        if not engine.run_turn_cycle():
            break
    
    # Unsubscribe
    filtered_bus.unsubscribe("game.*", filtered_console_logger)
    
    print("\n" + "=" * 60)
    print("NOTE: Only filtered events (TIME_ADVANCED) appeared above")
    print("=" * 60 + "\n")


def test_event_bus_buffering():
    """Test event buffering - subscribe AFTER game runs to see buffered events."""
    print("\n" + "=" * 60)
    print("TESTING EVENT BUS BUFFERING")
    print("=" * 60 + "\n")
    
    # Create a new game with a fresh event bus
    from entities.events import GameEventBus
    engine = GameEngine.create_new_game(
        agent_names=["Alice", "Bob", "Charlie"]
    )
    
    # Replace with a fresh bus to avoid singleton issues
    engine.event_bus = GameEventBus(buffer_size=100)
    
    print("Running 2 turn cycles WITHOUT any subscribers...\n")
    print("Events will be buffered until a subscriber appears.\n")
    
    # Run game without any subscribers - events should be buffered
    for i in range(2):
        if not engine.run_turn_cycle():
            break
    
    print("=" * 60)
    print(f"Game generated {len(engine.events)} events with no subscribers.")
    print("Now subscribing to event bus to receive buffered events...\n")
    print("=" * 60 + "\n")
    
    # Now subscribe - should receive all buffered events
    buffered_events = []
    
    def buffer_receiver(event_name: str, event) -> None:
        """Receive buffered events."""
        buffered_events.append(event)
        from core.enums import EventType
        if event.event_type != EventType.MESSAGE_PREPARED:
            print(f"[BUFFERED] {event}")
    
    engine.event_bus.subscribe("game.*", buffer_receiver)
    
    # Print summary
    print("\n" + "=" * 60)
    print("BUFFERING TEST SUMMARY")
    print("=" * 60)
    print(f"Total events generated: {len(engine.events)}")
    print(f"Buffered events received: {len(buffered_events)}")
    print(f"Buffering efficiency: {len(buffered_events)}/{len(engine.events)} events recovered")
    
    # Unsubscribe
    engine.event_bus.unsubscribe("game.*", buffer_receiver)
    
    print("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    # Run all tests
    test_event_bus_console_subscriber()
    test_event_bus_specific_type_subscriber()
    test_event_bus_filtering()
    test_event_bus_buffering()
    
    print("\n✅ All event bus tests completed!")

