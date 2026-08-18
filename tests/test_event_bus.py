"""Tests for the game event bus: delivery, filtering, buffering, unsubscribe."""

from typing import List, Tuple

from core.enums import EventType
from core.game_engine import GameEngine
from entities.events import GameEvent, GameEventBus


def make_event(sequence_number: int, event_type: EventType) -> GameEvent:
    return GameEvent(
        sequence_number=sequence_number,
        event_type=event_type,
        message=f"{event_type.value} #{sequence_number}",
    )


def test_wildcard_subscriber_receives_published_events() -> None:
    bus = GameEventBus()
    received: List[Tuple[str, GameEvent]] = []

    assert bus.subscribe("game.*", lambda name, event: received.append((name, event))) is True

    published = [make_event(i, EventType.TIME_ADVANCED) for i in range(3)]
    for event in published:
        assert bus.publish_event(event) is True

    assert [event for _name, event in received] == published
    assert {name for name, _event in received} == {"game.time_advanced"}


def test_duplicate_subscription_is_refused() -> None:
    bus = GameEventBus()

    def callback(name: str, event: GameEvent) -> None:
        return None

    assert bus.subscribe("game.*", callback) is True
    assert bus.subscribe("game.*", callback) is False


def test_unsubscribe_stops_delivery() -> None:
    bus = GameEventBus()
    received: List[GameEvent] = []

    def callback(name: str, event: GameEvent) -> None:
        received.append(event)

    bus.subscribe("game.*", callback)
    bus.publish_event(make_event(1, EventType.TIME_ADVANCED))
    assert bus.unsubscribe("game.*", callback) is True
    bus.publish_event(make_event(2, EventType.TIME_ADVANCED))

    assert len(received) == 1, "an unsubscribed callback must not keep receiving events"
    assert bus.unsubscribe("game.*", callback) is False


def test_type_subscriber_only_receives_its_type() -> None:
    bus = GameEventBus()
    deaths: List[GameEvent] = []

    bus.subscribe_to_type(EventType.AGENT_DIED, lambda name, event: deaths.append(event))

    death = make_event(1, EventType.AGENT_DIED)
    bus.publish_event(death)
    bus.publish_event(make_event(2, EventType.TIME_ADVANCED))

    assert deaths == [death]


def test_filtered_bus_drops_unlisted_types() -> None:
    bus = GameEventBus(event_filter={EventType.AGENT_DIED})
    received: List[GameEvent] = []
    bus.subscribe("game.*", lambda name, event: received.append(event))

    death = make_event(1, EventType.AGENT_DIED)
    assert bus.publish_event(death) is True
    assert bus.publish_event(make_event(2, EventType.TIME_ADVANCED)) is False

    assert received == [death], "a filtered-out event must not be delivered"
    assert bus.buffered_count() == 0, "a filtered-out event must not be buffered either"


def test_events_published_without_subscribers_are_buffered_then_flushed() -> None:
    bus = GameEventBus()
    published = [make_event(i, EventType.TIME_ADVANCED) for i in range(4)]

    for event in published:
        assert bus.publish_event(event) is False
    assert bus.buffered_count() == len(published)

    received: List[GameEvent] = []
    bus.subscribe("game.*", lambda name, event: received.append(event))

    assert received == published, "subscribing must flush the buffer in publication order"
    assert bus.buffered_count() == 0


def test_engine_events_reach_a_late_subscriber() -> None:
    """The engine executes commands during construction, before anything subscribes."""
    engine = GameEngine.create_new_game(agent_names=["Alice", "Bob", "Charlie"])
    for _ in range(3):
        if not engine.run_turn_cycle():
            break

    received: List[GameEvent] = []
    engine.event_bus.subscribe("game.*", lambda name, event: received.append(event))

    assert len(engine.events) > 0, "three turn cycles must generate events"
    assert [event.sequence_number for event in received] == [
        event.sequence_number for event in engine.events
    ], "every event the engine recorded must reach a subscriber that arrives late"
