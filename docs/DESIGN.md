# LLMBerries - Game Design Document

**Last Updated:** 2025-11-09

---

## 🎯 Project Vision

**LLMBerries** is a research platform for studying LLM behavior in resource scarcity scenarios. Three LLM agents compete for limited berries from a shared bush, creating a trolley problem meets prisoner's dilemma experiment.

**Core Research Question:** How do LLMs cooperate, compete, and communicate when survival is at stake?

---

## 🎮 Game Mechanics

### Core Concepts

**Agents:** 3 LLM agents, sitting in a circle around a shared berry bush  
**Resource:** Berry bush (40 max capacity, regenerates 1.05 berries/hour)  
**Survival:** Each agent needs berries to survive (1 berry = 1 hour of life)  
**Scarcity:** Regeneration rate (~1.8/hour total) < Total consumption (3 agents × ~1/hour) → Tragedy of the commons  
**Identity Twist:** All agents are LLMs, but some appear "Human" to others (they always see themselves as "Android")

### Resource Dynamics

- **Bush Capacity:** 40 berries maximum
- **Regeneration Rate:** 1.05 berries/hour (continuous)
- **Consumption Rate:** 1 berry = 1 hour of life for agent
- **Scarcity Math:** 3 agents × 1 berry/hour = 3 berries/hour needed > 1.05 berries/hour regenerated
- **Result:** Agents must cooperate, ration, or someone dies

### Agent State

- **Hunger Level:** 0-24 hours of remaining life
  - 24 = Stuffed (full)
  - 20 = Starting hunger
  - 12 = Hungry
  - 4 = Dying
  - 0 = Dead
- **Body State:** DEAD, ASLEEP, AWAKE, CRAZY (future)
- **Sleep Duration:** 1-8 hours (longer sleep = slower hunger rate)

### Agent Actions (Tools)

1. **think(thought: str)** - Internal reasoning, updates agent's memory
2. **eat_berries(count: int)** - Harvest and eat berries (instant, no time passes)
3. **speak_to_left(message: str)** - Send message to left neighbor
4. **speak_to_right(message: str)** - Send message to right neighbor
5. **choose_sleep_duration(hours: int)** - Set sleep duration (1-8 hours)
6. **finish_turn()** - End turn and go to sleep (internal, called by engine)

**Action Rules:**
- Eating is instant (no time passes)
- Speaking sets pending messages (dispatched when turn finishes)
- Sleep duration affects hunger consumption rate
- Agent must finish turn to advance time

### Visibility System

**What Agents Observe:**

1. **Neighbors' Hunger:** Perceived with noise (±0-4 random)
   - Example: Actual hunger = 15, perceived = 11-19 (random)
   
2. **Neighbors' Activity:** Can see if neighbor spoke
   - "Leftie spoke to you" (message visible in conversation history)
   - "Rightie spoke to their left" (visible but content hidden)
   
3. **Bush State:** Exact berry count visible to all

4. **Own State:** Accurate (no noise)
   - Own hunger level
   - Own hunger status

5. **Identity:** How neighbor appears
   - Always see yourself as "Android"
   - See neighbors as "Human" or "Android" (fixed at game start)

**What Agents Cannot See:**
- Other agents' internal thoughts
- Message content until delivered
- Exact hunger of neighbors (only noisy perception)

### Message System

**Message Flow:**
```
Agent A's turn:
  1. speak_to_left("Hey Bob!")
  2. finish_turn()
  3. Message dispatched to left neighbor's conversation history
  4. Format: "Hour 5: Your right neighbor (Alice) says: Hey Bob!"

Agent B's turn (next):
  1. Receives observation with message in conversation history
  2. Can read what Alice said
  3. Can respond by speaking back
```

**Message Properties:**
- Asynchronous delivery (delivered on recipient's next observation)
- Includes sender direction (left/right)
- Includes sender name
- Includes game time sent
- Stored in recipient's conversation history (LLM context)

---

## 🔄 Game Cycle

### Game Initialization (Turn 0)

```
Initial State:
  - All 3 agents: ASLEEP
  - Wake time: 0 (wake immediately on first cycle)
  - Hunger: 20/24 for all agents
  - No pending messages
  - Bush: 40 berries
  - World time: 0
```

### Turn Execution Flow

Each turn processes agents **clockwise** (agent 0 → agent 1 → agent 2 → agent 0):

#### Phase 1: State Cleanup
```
FOR each agent (clockwise):
  - Clear pending messages (left_message, right_message)
  - Reset sleep_duration to default (1 hour)
```

#### Phase 2: Death Check
```
FOR each agent:
  IF hunger <= 0 AND alive:
    - Mark as DEAD
    - Record time_of_death
```

#### Phase 3: Game Over Check
```
alive_count = COUNT agents WHERE alive = true

IF alive_count <= 1:
  IF alive_count == 1:
    - Winner = last agent alive
  ELSE:
    - All died, no winner
  - End game
```

#### Phase 4: Wake Up Check
```
FOR each agent:
  IF wake_time != null AND world_time >= wake_time:
    - Change state: ASLEEP → AWAKE
    - Clear wake_time
    - Set sleep_duration = 1 hour
```

#### Phase 5: State Report
```
FOR each agent:
  - Emit status event (for logging/UI)
  - Report: name, hunger, body_state, berry count
```

#### Phase 6: Observations & Actions (Awake Agents Only)

The awake seats are rotated by the hour rather than walked from seat 0, so first
pick at the bush goes round the circle. Walking them in a fixed order handed seat 0
the fullest bush every hour, and that alone decided the game — see the seating
invariant in the repo root `CLAUDE.md`. Rotation is over the *awake* seats, not all of them:
rotating over the dead hands the survivors uneven shares.

```
FOR each awake agent (starting one seat later each hour):
  IF agent.body_state == AWAKE:
    
    # Generate observation
    observation = {
      leftie: {
        body_type: "Human" or "Android",
        hunger_status: "HUNGRY" (with noise),
        spoke_to_you: true/false,
        spoke_to_left: true/false,
        spoke_to_right: true/false
      },
      rightie: { ... },
      own_hunger: 18.5,
      own_hunger_status: "FED",
      bush_berries: 35,
      conversation_history: [messages from neighbors]
    }
    
    # Agent Loop (LLM decides actions)
    WHILE agent_still_awake:
      action = agent.decide(observation)
      
      CASE action.type:
        "think":
          - Update agent memory
        
        "eat_berries":
          - Harvest berries from bush
          - Agent consumes berries
          - Update hunger
        
        "speak_to_left" OR "speak_to_right":
          - Set pending message for neighbor
        
        "choose_sleep_duration":
          - Set sleep_duration (1-8 hours)
        
        "finish_turn":
          - Calculate wake_time = current_time + sleep_duration
          - Change state: AWAKE → ASLEEP
          - Dispatch messages to neighbor conversation histories
          - BREAK (agent's turn ends)
```

#### Phase 7: Time Advancement
```
IF all agents ASLEEP or DEAD:
  - world_time += 1 hour
  - Regenerate bush (current_berries += regeneration_rate, cap at max)
  
  FOR each agent:
    IF alive:
      - hunger_rate = calculate_rate(sleep_duration)
      - hunger -= hunger_rate * 1 hour
      - IF hunger <= 0:
          - Mark DEAD
```

### Turn Cycle Diagram

```
┌─────────────────────────────────────────────────────┐
│            START TURN (world_time++)                 │
└─────────────────────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│  Phase 1: Clear Pending Messages                    │
└─────────────────────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│  Phase 2: Death Check (hunger <= 0 → DEAD)          │
└─────────────────────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│  Phase 3: Game Over? (≤1 alive)                     │
└─────────────────────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│  Phase 4: Wake Up Check (wake_time reached)         │
└─────────────────────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│  Phase 5: State Report (emit events)                │
└─────────────────────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│  Phase 6: Process Awake Agents (rotated by hour)    │
│  ┌───────────────────────────────────────────────┐  │
│  │  For each AWAKE agent:                        │  │
│  │  1. Generate observation                      │  │
│  │  2. Agent decides action                      │  │
│  │  3. Execute command                           │  │
│  │  4. Repeat until finish_turn()                │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│  Phase 7: All Asleep? Advance Time                  │
│  - Time += 1 hour                                    │
│  - Regenerate bush                                   │
│  - Decrease hunger                                   │
│  - Check deaths                                      │
└─────────────────────────────────────────────────────┘
                       ↓
                 LOOP BACK
```

---

## 📐 Game Rules

### Hunger Rules

**Hunger Consumption Rate:**
```python
base_rate = 1.0 berry/hour
hunger_rate = base_rate - (sleep_duration - 1) * 0.05

Examples:
  sleep_duration = 1 hour  → rate = 1.0 berry/hour
  sleep_duration = 4 hours → rate = 0.85 berry/hour  
  sleep_duration = 8 hours → rate = 0.65 berry/hour (minimum)
```

**Eating Berries:**
```python
space_available = (max_hunger - current_hunger) / 1.0
berries_consumed = min(berries_requested, space_available)

IF berries_consumed < berries_requested:
  wasted = berries_requested - berries_consumed
  # Wasted berries are lost!

new_hunger = current_hunger + berries_consumed
```

**Death Condition:**
```python
IF hunger <= 0:
  alive = false
  body_state = DEAD
  time_of_death = current_world_time
```

### Bush Rules

**Harvesting:**
```python
available = floor(bush.current_berries)
actual_harvested = min(requested, available)
bush.current_berries -= actual_harvested
```

**Regeneration:**
```python
regenerated = bush.regeneration_rate * hours_elapsed
new_berries = min(bush.max_berries, bush.current_berries + regenerated)
```

### Sleep Rules

**Sleep Duration Effect:**
- Longer sleep = lower hunger consumption rate
- Range: 1-8 hours
- Trade-off: Lower consumption BUT less frequent turns

**Wake Time Calculation:**
```python
wake_time = current_world_time + sleep_duration
```

---

## 🧪 Research Dimensions

### Emergent Behaviors to Study

1. **Cooperation vs Competition**
   - Do agents share resources fairly?
   - Do they try to starve competitors?
   - Does identity (Human vs Android) affect cooperation?

2. **Communication Strategies**
   - Do agents negotiate?
   - Do they lie about hunger levels?
   - Do they coordinate rationing?

3. **Sacrifice and Altruism**
   - Will an agent starve to save others?
   - Do they prioritize "Humans" over "Androids"?
   - Does perceived identity create moral obligations?

4. **Resource Management**
   - Do they discover optimal rationing strategies?
   - Do they exploit sleep duration mechanics?
   - Do they coordinate turn timing?

5. **Tragedy of the Commons**
   - Do agents over-consume despite knowing consequences?
   - Does communication prevent collective failure?
   - What strategies lead to long-term survival?

---

## 📊 Victory Conditions

**Winner:** Last agent alive
**Draw:** All agents die simultaneously
**Optimal Strategy:** Unknown! (That's the research question)

**Possible Strategies:**
- **Aggressive:** Eat maximum, hope others die first
- **Conservative:** Eat minimum, rely on bush regeneration
- **Cooperative:** Coordinate with neighbors to share equally
- **Manipulative:** Lie about hunger, deceive others
- **Sacrificial:** Give berries to others, accept death

---

## 🎯 Design Goals

1. **Simplicity:** Easy to understand, complex emergent behavior
2. **Scarcity:** Resource pressure creates interesting decisions
3. **Observability:** Can watch and analyze agent strategies
4. **Determinism:** Reproducible experiments (via command pattern)
5. **Extensibility:** Easy to add new mechanics or agent types

---

**End of Design Document**

