# LLMBerries Architecture Layers

This document clarifies which transitions go to which layer: Commands, Rules, or GameEngine.

## 🏗️ Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    GAME ENGINE                           │
│  (Turn cycle orchestration)                             │
│  - Phase sequencing                                      │
│  - Clockwise agent processing                           │
│  - Game over detection                                   │
│  - Command history management                           │
└─────────────────────────────────────────────────────────┘
                         ↓ uses
┌─────────────────────────────────────────────────────────┐
│                     COMMANDS                             │
│  (Decision recording + multi-step orchestration)        │
│  - Store LLM decisions                                   │
│  - Coordinate state changes                             │
│  - Generate events                                       │
│  - Call Rules for calculations                          │
└─────────────────────────────────────────────────────────┘
                         ↓ uses
┌─────────────────────────────────────────────────────────┐
│                      RULES                               │
│  (Pure logic, no side effects)                          │
│  - Calculations                                          │
│  - State transitions                                     │
│  - No knowledge of game context                         │
└─────────────────────────────────────────────────────────┘
```

---

## 📋 Decision Tree: Where Does X Go?

### 1. Is it pure calculation with no side effects?
**→ Rules** (entities/*Rules classes)

Examples:
- "How much hunger from 5 berries?" → `CharacterRules.calculate_hunger_gain(5)`
- "Regenerate bush for 1.5 hours" → `BushRules.regenerate(bush, 1.5)`
- "What's hunger rate for 8-hour sleep?" → `CharacterRules.calculate_hunger_rate(8)`
- "Did agent survive hunger decrease?" → `CharacterRules.pass_time(hunger, hours, rate)`

**Rules DON'T:**
- ❌ Know about WorldState
- ❌ Update multiple entities
- ❌ Make turn flow decisions
- ❌ Check game-level conditions

---

### 2. Is it a player/LLM decision or multi-step orchestration?
**→ Commands** (core/commands.py)

Examples:
- "Agent eats 5 berries" → `EatBerriesCommand` (harvest + eat + update)
- "Agent sets messages for neighbors" → `SpeakCommand`
- "Agent finishes turn" → `FinishTurnCommand` (sleep + dispatch messages)
- "Time advances" → `AdvanceTimeCommand` (regen bush + update all agents)

**Commands DO:**
- ✅ Call Rules for calculations
- ✅ Update WorldState immutably
- ✅ Generate events for logging/UI
- ✅ Orchestrate multi-entity updates
- ✅ Validate before executing
- ✅ Handle atomic transactions

**Commands DON'T:**
- ❌ Decide turn flow (that's GameEngine)
- ❌ Process agents in order (that's GameEngine)

---

### 3. Is it turn cycle management or game-level coordination?
**→ GameEngine** (core/game_engine.py)

Examples:
- "Check all agents clockwise for wake-up" → `GameEngine.run_turn_cycle()`
- "Detect game over (≤1 alive)" → `GameEngine.run_turn_cycle()` Phase 3
- "Process awake agents in order" → `GameEngine.run_turn_cycle()` Phase 6
- "Execute 7 phases in sequence" → `GameEngine.run_turn_cycle()`

**GameEngine DOES:**
- ✅ Orchestrate turn phases
- ✅ Process agents clockwise
- ✅ Detect game over
- ✅ Manage command history
- ✅ Decide WHEN to execute commands

**GameEngine DOESN'T:**
- ❌ Contain game logic (that's Rules)
- ❌ Make agent decisions (that's LLM)
- ❌ Calculate hunger/berries (that's Rules)

---

## 🎯 Game Cycle → Layer Mapping

From `commands.py` lines 17-42, here's where each transition goes:

| Game Cycle Step | Layer | Implementation |
|----------------|-------|----------------|
| **Game starts @ turn 0** | GameEngine | `GameEngine.create_new_game()` |
| **Agents ASLEEP, waketime 0** | WorldState | Initial state setup |
| **State cleanup** | GameEngine → Command | Loop agents, execute `ClearPendingMessagesCommand` |
| **Hunger check (0 → DEAD)** | GameEngine → Command | Check hunger, execute `MarkDeadCommand` |
| **Alive check (≤1 → game over)** | GameEngine | Count alive, set `self.game_over` |
| **Waketime check (→ AWAKE)** | GameEngine → Command | Check wake_time, execute `WakeUpCommand` |
| **Set sleep_duration = 1** | Command | `WakeUpCommand` updates sleep_duration |
| **State report** | GameEngine | Emit events for all agents |
| **Observations** | Observation DTOs | `AgentObservation.from_state()` classmethod |
| **ThinkCommand** | Command | Update agent memory |
| **EatBerriesCommand** | Command → Rules | Calls `BushRules.harvest()`, `CharacterRules.eat_berries()` |
| **SpeakCommand** | Command | Set left_message/right_message |
| **SleepDurationCommand** | Command | Set sleep_duration |
| **FinishTurnCommand** | Command → Rules | Calls `CharacterRules.start_sleep()`, dispatches messages |
| **Calculate waketime** | Rules | `CharacterRules.start_sleep(time, duration)` |
| **Dispatch messages** | Command | `FinishTurnCommand` adds to neighbor memories |
| **Advance time** | Command → Rules | `AdvanceTimeCommand` calls `BushRules`, `CharacterRules` |
| **Regenerate bush** | Rules | `BushRules.regenerate(bush, hours)` |
| **Decrease hunger** | Rules | `CharacterRules.pass_time(hunger, hours, rate)` |

---

## 📝 Specific Examples

### Example 1: Agent Eats Berries

```python
# Layer 3: GameEngine decides WHEN
engine.run_turn_cycle()  # Phase 6: Process awake agents
  
  # Layer 2: Command orchestrates WHAT
  cmd = EatBerriesCommand(agent_id=0, count=5)
  cmd.execute(state):
    # Harvest berries
    new_bush, harvested = BushRules.harvest(bush, 5)  # Layer 1: Rules calculate HOW
    
    # Eat berries
    new_hunger, consumed, msg = CharacterRules.eat_berries(hunger, harvested)  # Layer 1
    
    # Update state (Layer 2)
    state = state.with_bush(new_bush).with_agent(0, hunger=new_hunger)
    
    # Generate events (Layer 2)
    return state, events
```

### Example 2: Time Advances

```python
# Layer 3: GameEngine detects all agents asleep
engine.run_turn_cycle()  # Phase 7
  if all_agents_asleep():
    
    # Layer 2: Command orchestrates system update
    cmd = AdvanceTimeCommand(hours=1.0)
    cmd.execute(state):
      # Regenerate bush (Layer 1: Rules)
      new_bush, regen = BushRules.regenerate(bush, 1.0)
      
      # Update each agent (Layer 1: Rules)
      for agent in agents:
        rate = CharacterRules.calculate_hunger_rate(agent.sleep_duration)
        new_hunger, survived = CharacterRules.pass_time(agent.hunger, 1.0, rate)
        
        # Update state (Layer 2)
        state = state.with_agent(agent_id, hunger=new_hunger)
      
      # Generate events (Layer 2)
      return state, events
```

### Example 3: Agent Wakes Up

```python
# Layer 3: GameEngine checks wake times
engine.run_turn_cycle()  # Phase 4: Wake Up Check
  for agent_id in range(TOTAL_AGENTS):
    agent = state.agents[agent_id]
    if agent.wake_time and state.world_time >= agent.wake_time:
      
      # Layer 2: Command updates agent state
      cmd = WakeUpCommand(agent_id=agent_id)
      cmd.execute(state):
        # Layer 2: Direct state update (no Rules needed for enum change)
        state = state.with_agent(
          agent_id,
          body_state=BodyState.AWAKE,
          wake_time=None,
          sleep_duration=1.0
        )
        
        # Generate event (Layer 2)
        return state, events
```

---

## ✅ Design Principles Summary

### Rules (Layer 1)
**Purpose:** Answer "how does X work?"
- Pure functions
- No side effects
- No game context
- Return new values, never mutate

### Commands (Layer 2)
**Purpose:** Record decisions, orchestrate changes
- Store LLM/player decisions
- Call Rules for calculations
- Update state immutably
- Generate events
- Atomic transactions

### GameEngine (Layer 3)
**Purpose:** Orchestrate turn flow
- Execute 7-phase cycle
- Process agents in order
- Detect game over
- Manage history/events
- Decide WHEN, not HOW

---

## 🎮 Integration Point: LLM Agents

```python
# GameEngine orchestrates
engine.run_turn_cycle()  # Phase 6

for agent_id in clockwise_order:
    if agent.body_state == BodyState.AWAKE:
        
         # 1. Generate observation (classmethod on DTO)
         observation = AgentObservation.from_state(state, agent_id)
        
        # 2. LLM decides actions
        agent_interface = AgentInterface(engine=engine, agent_id=agent_id)
        
        # Agent loop (controlled by LLM)
        while not finished:
            # LLM sees observation, decides action
            action = llm.decide(observation)
            
            # Execute via interface
            if action.type == "eat":
                agent_interface.eat_berries(action.count)
            elif action.type == "speak":
                agent_interface.speak(action.left, action.right)
            elif action.type == "finish":
                agent_interface.finish_turn()
                break
```

---

## 📚 Files Reference

| Layer | Files | Purpose |
|-------|-------|---------|
| Rules | `entities/bush.py` | BushRules (harvest, regenerate) |
| Rules | `entities/character.py` | CharacterRules (eat, pass_time, hunger calculations) |
| DTOs | `entities/observations.py` | Observation DTOs with `.from_state()` classmethods |
| Commands | `core/commands.py` | All 8 commands (4 meta, 4 player) |
| Engine | `core/game_engine.py` | GameEngine, turn cycle |
| Interface | `interface/agent_interface.py` | AgentInterface (implements AgentTools) |

---

**Summary:** 
- **Rules** = "HOW" (pure logic)
- **Commands** = "WHAT" (decisions + orchestration)  
- **GameEngine** = "WHEN" (turn flow + coordination)

This separation makes the codebase:
- ✅ Testable (each layer independently)
- ✅ Debuggable (clear responsibilities)
- ✅ Maintainable (changes localized)
- ✅ Extensible (add new commands/rules easily)

