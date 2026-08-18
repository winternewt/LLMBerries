"""Test hourly turn system with proper message visibility."""

from core.game_engine import GameEngine
from core.common import BodyType, BodyState


def test_hourly_turn_system() -> None:
    """
    Test that all agents get processed every hour, with proper message visibility.
    
    Scenario:
    Hour 0: Alice speaks to both neighbors and sleeps for 3 hours
    Hour 1: Bob and Charlie see Alice silent, receive messages, reply
    Hour 2: Alice still sleeping, Bob/Charlie see her silent, can send more messages
    Hour 3: Alice wakes up, sees backlog of messages from Bob and Charlie
    """
    print("\n=== Testing Hourly Turn System ===\n")
    
    # Create game engine
    engine = GameEngine()
    engine.initialize_agents(["Alice", "Bob", "Charlie"])
    
    alice = engine.get_agent(0)
    bob = engine.get_agent(1)
    charlie = engine.get_agent(2)
    
    print(f"Circle setup:")
    print(f"  Alice (0) - left: Bob (1), right: Charlie (2)")
    print(f"  Bob (1) - left: Charlie (2), right: Alice (0)")
    print(f"  Charlie (2) - left: Alice (0), right: Bob (1)")
    print()
    
    # === Hour 0: Alice's turn ===
    print(f"=== Hour {engine.game_time:.0f}: Alice speaks and sleeps ===")
    
    # Alice is awake, can take actions
    assert alice.is_awake() == True, "Alice should be awake"
    
    # Start Alice's turn
    engine.start_agent_turn(0)
    
    # Alice speaks to both neighbors
    alice.speak_to_left("Hey Bob!")
    alice.speak_to_right("Hey Charlie!")
    
    # Alice sleeps for 3 hours
    engine.execute_sleep(0, 3)
    
    # End Alice's turn - messages dispatched and cleared
    engine.end_agent_turn(0)
    
    # Verify Alice is asleep and messages NOT cleared (persist until next turn)
    assert alice.body_state == BodyState.ASLEEP, "Alice should be asleep"
    assert alice.left_neighbor_message is not None, "Alice's messages should persist"
    assert alice.right_neighbor_message is not None, "Alice's messages should persist"
    
    # Verify messages in queue
    assert len(engine.message_queue) == 2, f"Should have 2 messages in queue, got {len(engine.message_queue)}"
    print(f"✓ Alice asleep, messages dispatched (and still on Alice)")
    print()
    
    # === Advance to Hour 1 ===
    print(f"=== Advancing to Hour 1 ===")
    engine.advance_one_hour()
    
    # Alice should still be asleep
    assert alice.is_awake() == False, "Alice should still be asleep"
    assert alice.hunger < 20.0, "Alice's hunger should have decreased"
    print(f"✓ Alice still sleeping, hunger: {alice.hunger:.1f}")
    
    # === Hour 1: Alice's background turn (asleep) ===
    print(f"\n=== Hour {engine.game_time:.0f}: Alice's turn (asleep, background only) ===")
    
    # Alice gets a turn for background processing
    engine.start_agent_turn(0)
    # Messages should NOW be cleared
    assert alice.left_neighbor_message is None, "Alice's messages should be cleared at turn start"
    assert alice.right_neighbor_message is None, "Alice's messages should be cleared at turn start"
    print(f"✓ Alice's messages cleared at start of turn")
    
    # Alice is asleep, no actions, just end turn
    engine.end_agent_turn(0)
    print()
    
    # === Hour 1: Bob's turn ===
    print(f"=== Hour {engine.game_time:.0f}: Bob's turn ===")
    
    # Bob is awake
    assert bob.is_awake() == True, "Bob should be awake"
    
    # Create observation for Bob
    obs = engine.create_observation(1)
    
    # Bob sees Alice as SILENT (her turn started this hour, messages cleared)
    print(f"Bob observes Alice (right neighbor):")
    print(f"  - spoke_to_left: {obs.rightie.spoke_to_left}")
    print(f"  - spoke_to_right: {obs.rightie.spoke_to_right}")
    print(f"  - spoke_to_you: {obs.rightie.spoke_to_you}")
    
    assert obs.rightie.spoke_to_left == False, "Alice should appear silent (messages cleared at her turn start)"
    assert obs.rightie.spoke_to_right == False, "Alice should appear silent (messages cleared at her turn start)"
    
    # But Bob RECEIVED Alice's message
    assert len(obs.pending_messages) == 1, f"Bob should have 1 message, got {len(obs.pending_messages)}"
    assert obs.pending_messages[0].content == "Hey Bob!", "Bob should receive Alice's message"
    print(f"✓ Bob sees Alice as silent but received her message: '{obs.pending_messages[0].content}'")
    
    # Bob replies
    engine.start_agent_turn(1)
    bob.speak_to_right("Hi Alice, I got your message!")
    engine.execute_sleep(1, 1)
    engine.end_agent_turn(1)
    print()
    
    # === Hour 1: Charlie's turn ===
    print(f"=== Hour {engine.game_time:.0f}: Charlie's turn ===")
    
    # Charlie is awake
    assert charlie.is_awake() == True, "Charlie should be awake"
    
    # Create observation for Charlie
    obs = engine.create_observation(2)
    
    # Charlie also sees Alice as SILENT
    print(f"Charlie observes Alice (left neighbor):")
    print(f"  - spoke_to_left: {obs.leftie.spoke_to_left}")
    print(f"  - spoke_to_right: {obs.leftie.spoke_to_right}")
    
    assert obs.leftie.spoke_to_right == False, "Alice should appear silent"
    
    # Charlie RECEIVED Alice's message
    assert len(obs.pending_messages) == 1, f"Charlie should have 1 message"
    assert obs.pending_messages[0].content == "Hey Charlie!", "Charlie should receive Alice's message"
    print(f"✓ Charlie sees Alice as silent but received her message: '{obs.pending_messages[0].content}'")
    
    # Charlie replies
    engine.start_agent_turn(2)
    charlie.speak_to_left("Hi Alice, got it!")
    engine.execute_sleep(2, 1)
    engine.end_agent_turn(2)
    print()
    
    # === Advance to Hour 2 ===
    print(f"=== Advancing to Hour 2 ===")
    engine.advance_one_hour()
    
    # Alice still asleep
    assert alice.is_awake() == False, "Alice should still be asleep"
    print(f"✓ Alice still sleeping (wakes at hour {alice.wake_time:.0f})")
    print()
    
    # === Hour 2: Bob and Charlie see Alice still silent ===
    print(f"=== Hour {engine.game_time:.0f}: Bob and Charlie's turns ===")
    
    # Bob's turn
    obs = engine.create_observation(1)
    assert obs.rightie.spoke_to_right == False, "Alice still appears silent"
    # Bob receives Charlie's reply from hour 1
    assert len(obs.pending_messages) == 0, "Bob has no new messages"
    
    engine.start_agent_turn(1)
    bob.speak_to_right("Alice, are you there?")
    engine.execute_sleep(1, 1)
    engine.end_agent_turn(1)
    
    # Charlie's turn
    obs = engine.create_observation(2)
    assert obs.leftie.spoke_to_right == False, "Alice still appears silent"
    # Charlie receives Bob's reply
    assert len(obs.pending_messages) == 0, "Charlie has no new messages from Alice"
    
    engine.start_agent_turn(2)
    charlie.speak_to_left("Alice, hello?")
    engine.execute_sleep(2, 1)
    engine.end_agent_turn(2)
    
    print(f"✓ Bob and Charlie see Alice as silent (uncertainty: sleeping or ignoring?)")
    print()
    
    # === Advance to Hour 3 ===
    print(f"=== Advancing to Hour 3 ===")
    engine.advance_one_hour()
    
    # Alice should wake up
    assert alice.is_awake() == True, "Alice should be awake now"
    print(f"✓ Alice wakes up!")
    print()
    
    # === Hour 3: Alice's turn - sees message backlog ===
    print(f"=== Hour {engine.game_time:.0f}: Alice wakes and sees backlog ===")
    
    obs = engine.create_observation(0)
    
    # Alice should have received multiple messages
    print(f"Alice has {len(obs.pending_messages)} messages:")
    for msg in obs.pending_messages:
        print(f"  - {msg.content}")
    
    # Alice should have received Bob's first reply, Charlie's first reply,
    # Bob's second message, Charlie's second message
    assert len(obs.pending_messages) == 4, f"Alice should have 4 messages, got {len(obs.pending_messages)}"
    
    print(f"✓ Alice sees full backlog from while she was asleep")
    print()
    
    print("=== Test Passed! ===\n")
    print("Summary:")
    print("- All agents processed every hour (no time skipping)")
    print("- Sleeping agents get hunger/message updates but can't act")
    print("- Awake agents can take actions")
    print("- Messages visible ONLY during sender's turn, then cleared")
    print("- Creates uncertainty: can't tell if neighbor is sleeping or ignoring")
    print("- Message backlog accumulates while sleeping")


if __name__ == "__main__":
    test_hourly_turn_system()

