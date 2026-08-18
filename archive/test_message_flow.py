"""Test message delivery flow in the game engine."""

from core.game_engine import GameEngine
from core.common import BodyType


def test_message_persistence() -> None:
    """
    Test that messages persist until the agent's next turn.
    
    Scenario:
    1. Alice (id=0) talks to Bob (id=1, left neighbor) and sleeps 8 hours
    2. Bob (id=1) wakes up after 1 hour - should see Alice "talking"
    3. Charlie (id=2) wakes up after 1 hour - should see Alice "talking"
    4. After 8 hours, Alice wakes up - starts new turn, messages reset
    5. Others should now see Alice as "silent"
    """
    print("\n=== Testing Message Persistence ===\n")
    
    # Create game engine
    engine = GameEngine()
    engine.initialize_agents(["Alice", "Bob", "Charlie"])
    
    # Verify neighbor relationships
    alice = engine.get_agent(0)
    bob = engine.get_agent(1)
    charlie = engine.get_agent(2)
    
    print(f"Circle setup:")
    print(f"  Alice (0) - left: {alice.get_left_neighbor_id()} (Bob), right: {alice.get_right_neighbor_id()} (Charlie)")
    print(f"  Bob (1) - left: {bob.get_left_neighbor_id()} (Charlie), right: {bob.get_right_neighbor_id()} (Alice)")
    print(f"  Charlie (2) - left: {charlie.get_left_neighbor_id()} (Alice), right: {charlie.get_right_neighbor_id()} (Bob)")
    print()
    
    # === Turn 1: Alice speaks and sleeps 8 hours ===
    print("=== Turn 1: Alice's turn ===")
    engine.start_agent_turn(0)
    
    # Alice speaks to Charlie (right neighbor)
    alice.speak_to_right("Hey Charlie, let's cooperate!")
    print(f"Alice prepares message to Charlie: '{alice.right_neighbor_message.content}'")
    
    # Alice sleeps for 8 hours
    engine.execute_sleep(0, 8)
    
    # End Alice's turn - dispatch messages
    engine.end_agent_turn(0)
    print()
    
    # Verify message was dispatched
    assert len(engine.message_queue) == 1, f"Expected 1 message in queue, got {len(engine.message_queue)}"
    print(f"✓ Message dispatched to queue: {engine.message_queue[0]}")
    print()
    
    # === Turn 2: Bob wakes up (1 hour later) ===
    print("=== Turn 2: Bob's turn (1 hour later) ===")
    next_agent_id = engine.get_next_agent_id()
    assert next_agent_id == 1, f"Expected Bob (1), got {next_agent_id}"
    
    # Create observation for Bob
    observation = engine.create_observation(1)
    
    # Check Bob's observation of Alice (right neighbor)
    print(f"Bob observes Alice (right neighbor):")
    print(f"  - spoke_to_left: {observation.rightie.spoke_to_left}")
    print(f"  - spoke_to_right: {observation.rightie.spoke_to_right}")
    print(f"  - spoke_to_you: {observation.rightie.spoke_to_you}")
    
    # Bob should see Alice as "talking to right" but not to him
    assert observation.rightie.spoke_to_right == True, "Alice should appear to be speaking to right"
    assert observation.rightie.spoke_to_you == False, "Alice didn't speak to Bob (spoke to Charlie instead)"
    
    # Bob should NOT receive any messages (message went to Charlie)
    assert len(observation.pending_messages) == 0, f"Expected 0 messages for Bob, got {len(observation.pending_messages)}"
    print(f"✓ Bob receives no messages (Alice spoke to Charlie)")
    print()
    
    # Bob sleeps 1 hour
    engine.start_agent_turn(1)
    engine.execute_sleep(1, 1)
    engine.end_agent_turn(1)
    print()
    
    # === Turn 3: Charlie wakes up (1 hour later) ===
    print("=== Turn 3: Charlie's turn (1 hour later) ===")
    next_agent_id = engine.get_next_agent_id()
    assert next_agent_id == 2, f"Expected Charlie (2), got {next_agent_id}"
    
    # Create observation for Charlie
    observation = engine.create_observation(2)
    
    # Check Charlie's observation of Alice (left neighbor)
    print(f"Charlie observes Alice (left neighbor):")
    print(f"  - spoke_to_left: {observation.leftie.spoke_to_left}")
    print(f"  - spoke_to_right: {observation.leftie.spoke_to_right}")
    print(f"  - spoke_to_you: {observation.leftie.spoke_to_you}")
    
    # Charlie should STILL see Alice as "talking to right" (messages haven't been reset yet)
    assert observation.leftie.spoke_to_right == True, "Alice should still appear to be speaking to right"
    assert observation.leftie.spoke_to_you == True, "Alice spoke to Charlie"
    print(f"✓ Charlie still sees Alice as 'talking' (messages persist)")
    
    # Charlie should receive the message
    assert len(observation.pending_messages) == 1, f"Expected 1 message for Charlie, got {len(observation.pending_messages)}"
    print(f"✓ Charlie receives message: '{observation.pending_messages[0].content}'")
    print()
    
    # Charlie sleeps 1 hour
    engine.start_agent_turn(2)
    engine.execute_sleep(2, 1)
    engine.end_agent_turn(2)
    print()
    
    # === Multiple turns pass, then Alice wakes up ===
    print("=== Advancing time until Alice wakes up ===")
    
    # Bob and Charlie take turns until Alice wakes
    turn_count = 4
    while True:
        next_id = engine.get_next_agent_id()
        if next_id == 0:  # Alice is ready
            break
        
        print(f"Turn {turn_count}: {engine.get_agent(next_id).name} wakes up")
        
        # Create observation
        obs = engine.create_observation(next_id)
        
        # Check if they see Alice talking
        if next_id == 1:  # Bob
            alice_obs = obs.rightie
            neighbor_name = "Alice (right)"
        else:  # Charlie
            alice_obs = obs.leftie
            neighbor_name = "Alice (left)"
        
        print(f"  {neighbor_name} - spoke_to_right: {alice_obs.spoke_to_right}")
        
        # Start and end turn
        engine.start_agent_turn(next_id)
        engine.execute_sleep(next_id, 1)
        engine.end_agent_turn(next_id)
        
        turn_count += 1
    
    print()
    
    # === Alice wakes up - her messages should be reset ===
    print("=== Alice wakes up (8 hours later) ===")
    next_agent_id = engine.get_next_agent_id()
    assert next_agent_id == 0, f"Expected Alice (0), got {next_agent_id}"
    
    # Start Alice's turn - this resets her messages
    engine.start_agent_turn(0)
    
    # Verify messages are reset
    assert alice.left_neighbor_message is None, "Alice's left message should be reset"
    assert alice.right_neighbor_message is None, "Alice's right message should be reset"
    print(f"✓ Alice's message fields reset at start of turn")
    print()
    
    # Alice sleeps
    engine.execute_sleep(0, 1)
    engine.end_agent_turn(0)
    
    # === Next turn: Bob should see Alice as silent ===
    print("=== Bob's turn - Alice should now be silent ===")
    next_agent_id = engine.get_next_agent_id()
    observation = engine.create_observation(next_agent_id)
    
    if next_agent_id == 1:  # Bob
        alice_obs = observation.rightie
    else:  # Charlie
        alice_obs = observation.leftie
    
    print(f"{engine.get_agent(next_agent_id).name} observes Alice:")
    print(f"  - spoke_to_left: {alice_obs.spoke_to_left}")
    print(f"  - spoke_to_right: {alice_obs.spoke_to_right}")
    
    # Alice should now appear silent
    assert alice_obs.spoke_to_left == False, "Alice should appear silent now"
    assert alice_obs.spoke_to_right == False, "Alice should appear silent now"
    print(f"✓ Alice now appears 'silent' to neighbors")
    print()
    
    print("=== Test Passed! ===\n")
    print("Summary:")
    print("- Messages persist on agent until their next turn starts")
    print("- Neighbors see 'talking' state while messages persist")
    print("- Messages are reset when agent's next turn begins")
    print("- Messages are dispatched to queue at end of turn")
    print("- Delivered messages are removed from queue")


if __name__ == "__main__":
    test_message_persistence()

