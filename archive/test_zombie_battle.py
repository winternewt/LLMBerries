"""Test zombie battle - full game run without API calls."""

import sys

# Fix encoding for Windows
if sys.platform == 'win32':
    # Force UTF-8 encoding for stdout/stderr
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    if sys.stderr.encoding != 'utf-8':
        sys.stderr.reconfigure(encoding='utf-8')

from core.game_engine import GameEngine
from core.zombie_agent import ZombieAgent
from core.common import BodyState, LLM_SET
from objects.observations import AgentObservation


def test_zombie_battle() -> None:
    """
    Run a full zombie battle with mock agents.
    
    This demonstrates the game mechanics without making any API calls.
    Zombies will randomly eat, speak snarky messages, and sleep.
    """
    print("\n=== 🧟 ZOMBIE BERRY BATTLE 🧟 ===\n")
    
    # Create game engine
    engine = GameEngine()
    engine.initialize_agents(["Zed", "Zara", "Zeke"])
    
    # Create zombie agents
    zombies = []
    for i, agent_state in enumerate(engine.agents):
        zombie = ZombieAgent(
            llm_options=LLM_SET[i % len(LLM_SET)],  # Just for initialization
            agent_id=agent_state.agent_id,
            name=agent_state.name,
            hunger=agent_state.hunger,
            body_state=agent_state.body_state,
            perceived_type=agent_state.perceived_type,
        )
        # Set game engine reference after initialization
        zombie._game_engine = engine
        zombies.append(zombie)
        print(f"🧟 {zombie.name} spawned as {zombie.perceived_type}")
    
    print(f"\nStarting conditions:")
    print(f"  Bush: {engine.bush}")
    print(f"  Each zombie: {int(engine.agents[0].hunger)}/24 hunger\n")
    
    print("=" * 60)
    
    # Run game for N hours
    max_hours = 30
    
    for hour in range(max_hours):
        print(f"\n{'='*60}")
        print(f"HOUR {hour} - Game Time: {engine.game_time:.1f}")
        print(f"Bush: {engine.bush}")
        print(f"{'='*60}\n")
        
        # Check game over
        is_over, reason = engine.is_game_over()
        if is_over:
            print(f"\n🎮 GAME OVER: {reason}")
            break
        
        # Advance time by 1 hour (updates hunger, wake times, bush)
        if hour > 0:
            engine.advance_one_hour()
        
        # Process each agent's turn
        for i, (agent_state, zombie) in enumerate(zip(engine.agents, zombies)):
            if not agent_state.alive:
                continue
            
            print(f"\n--- {agent_state.name}'s turn ---")
            print(f"State: {agent_state.body_state.name}, Hunger: {int(agent_state.hunger)}/24")
            
            # Start turn (clears old messages)
            engine.start_agent_turn(i)
            
            # If awake, zombie can take actions
            if agent_state.is_awake():
                # Create observation
                obs = engine.create_observation(i)
                
                # Show what zombie sees
                print(f"\n{agent_state.name} observes:")
                print(f"  Left: {obs.leftie.body_type}, "
                      f"{obs.leftie.hunger_status}, "
                      f"spoke_to_you={obs.leftie.spoke_to_you}")
                print(f"  Right: {obs.rightie.body_type}, "
                      f"{obs.rightie.hunger_status}, "
                      f"spoke_to_you={obs.rightie.spoke_to_you}")
                
                # Show received messages
                if obs.pending_messages:
                    print(f"\n📨 Messages received:")
                    for msg in obs.pending_messages:
                        print(f"  • {msg.format_for_recipient()}")
                
                # Let zombie decide what to do
                zombie.set_current_observation(obs)
                response = zombie.query("Your turn")
                
                print(f"\n💭 {agent_state.name}'s inner monologue: {response}")
            else:
                print(f"  (Asleep until hour {agent_state.wake_time:.0f})")
            
            # End turn (dispatches messages)
            engine.end_agent_turn(i)
        
        # Show status summary
        print(f"\n{'─'*60}")
        print(f"Status after hour {hour}:")
        for agent in engine.agents:
            if agent.alive:
                print(f"  {agent.name}: {agent.body_state.name}, "
                      f"Hunger {int(agent.hunger)}/24 ({agent.get_hunger_status().value})")
            else:
                print(f"  {agent.name}: 💀 DEAD")
        print(f"{'─'*60}")
    
    # Final summary
    print(f"\n\n{'='*60}")
    print("FINAL RESULTS")
    print(f"{'='*60}")
    
    for agent in engine.agents:
        if agent.alive:
            print(f"🧟 {agent.name}: SURVIVED with {int(agent.hunger)}/24 hunger, "
                  f"ate {agent.total_berries_consumed} berries")
        else:
            print(f"💀 {agent.name}: DIED at hour {agent.time_of_death:.1f}, "
                  f"ate {agent.total_berries_consumed} berries total")
    
    print(f"\nBush final state: {engine.bush}")
    print(f"Total game hours: {engine.game_time:.1f}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    test_zombie_battle()

