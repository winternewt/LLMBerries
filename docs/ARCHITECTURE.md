# LLMBerries - Architecture Document

**Last Updated:** 2025-11-09

---

## 🏗️ Architecture Pattern

**Primary Pattern:** Command Pattern with Immutable State

**Supporting Patterns:**
- Event Stream (for observability)
- Rules Engine (for pure game logic)
- Factory Pattern (for observations)

---

## 🎯 Why Command Pattern?

### Requirements That Led to This Choice

1. **Time Travel Debugging**
   - Need to inspect any past turn
   - Requirement: Store complete decision history
   - Solution: Commands are decisions (not queries)

2. **State Branching (A/B Testing)**
   - Compare different LLMs from same starting point
   - Requirement: Fork game state at any turn
   - Solution: Replay commands from fork point

3. **Deterministic Replay**
   - Reproduce experiments exactly
   - Requirement: Store command history → recreate state
   - Solution: Commands are pure (no side effects)

4. **Network-Ready**
   - Future: Distributed agents
   - Requirement: Serialize decisions over network
   - Solution: Commands are JSON-serializable

5. **No Circular Dependencies**
   - Clean separation of concerns
   - Requirement: One-way data flow
   - Solution: Command → State (never State → Command)

### Alternative Patterns Considered

| Pattern | Pros | Cons | Why Not? |
|---------|------|------|----------|
| **Event Sourcing** | Complete audit trail | Over-engineered for our scale | Too complex for 3-agent game |
| **Service Layer** | Simpler to implement | No time travel, no branching | Doesn't meet research requirements |
| **Actor Model** | Natural for agents | Hard to replay, non-deterministic | Can't reproduce experiments |
| **State Machine** | Clear state transitions | Limited history, no branching | Doesn't support A/B testing |

**Verdict:** Command Pattern best fits our research needs (time travel + branching + determinism).

---

## 📊 Three-Layer Architecture

```
┌─────────────────────────────────────────────────────┐
│                  GAME ENGINE                         │
│  (Turn cycle orchestration)                         │
│  - Phase sequencing                                  │
│  - Clockwise agent processing                       │
│  - Game over detection                               │
│  - Command history management                       │
└─────────────────────────────────────────────────────┘
                       ↓ uses
┌─────────────────────────────────────────────────────┐
│                   COMMANDS                           │
│  (Decision recording + multi-step orchestration)    │
│  - Store LLM decisions                               │
│  - Coordinate state changes                         │
│  - Generate events                                   │
│  - Call Rules for calculations                      │
└─────────────────────────────────────────────────────┘
                       ↓ uses
┌─────────────────────────────────────────────────────┐
│                    RULES                             │
│  (Pure logic, no side effects)                      │
│  - Calculations                                      │
│  - State transitions                                 │
│  - No knowledge of game context                     │
└─────────────────────────────────────────────────────┘
```

### Layer Responsibilities

#### **Layer 1: Rules** (entities/bush.py, entities/character.py)

**Responsibility:** Answer "HOW does X work?"

**Characteristics:**
- Pure functions (no side effects)
- Static methods only
- No knowledge of WorldState
- No knowledge of other agents
- Easily testable in isolation

**Examples:**
```python
# BushRules
harvest(bush, count) → (new_bush, actual_harvested)
regenerate(bush, hours) → (new_bush, regenerated_amount)

# CharacterRules
eat_berries(hunger, berries) → (new_hunger, consumed, message)
pass_time(hunger, hours, rate) → (new_hunger, survived)
calculate_hunger_rate(sleep_duration) → rate
```

**Rules DON'T:**
- ❌ Update multiple entities
- ❌ Make turn flow decisions
- ❌ Check game-level conditions
- ❌ Know about GameEngine

---

#### **Layer 2: Commands** (core/commands.py)

**Responsibility:** Record decisions + orchestrate multi-step actions

**Characteristics:**
- Immutable (Pydantic frozen models)
- Store LLM decisions (not queries)
- Call Rules for calculations
- Update WorldState immutably
- Generate events for observability
- Atomic transactions (validate → execute → emit)

**Examples:**
```python
# Meta Commands (engine-internal)
ClearPendingMessagesCommand  # Phase 1
MarkDeadCommand              # Phase 2
WakeUpCommand                # Phase 4
AdvanceTimeCommand           # Phase 7

# Player Commands (LLM actions)
ThinkCommand                 # Internal reasoning
EatBerriesCommand            # Harvest + eat (atomic)
SpeakCommand                 # Set messages
SleepDurationCommand         # Set sleep time
FinishTurnCommand            # End turn + dispatch messages
```

**Commands DO:**
- ✅ Validate before executing (`can_execute()`)
- ✅ Call Rules for calculations
- ✅ Update WorldState via `model_copy()`
- ✅ Generate events for logging/UI
- ✅ Handle multi-entity updates
- ✅ Ensure atomicity (all-or-nothing)

**Commands DON'T:**
- ❌ Decide turn flow (that's GameEngine)
- ❌ Process agents in order (that's GameEngine)
- ❌ Query external systems (store decisions)

---

#### **Layer 3: GameEngine** (core/game_engine.py)

**Responsibility:** Orchestrate turn cycle + manage history

**Characteristics:**
- Executes 7-phase turn cycle
- Processes agents clockwise
- Detects game over
- Manages command history (for replay)
- Collects event stream (for observability)
- Provides time travel features

**GameEngine DOES:**
- ✅ Run turn phases in order
- ✅ Check when to execute commands
- ✅ Detect game-over conditions
- ✅ Store history + events
- ✅ Provide replay/branching

**GameEngine DOESN'T:**
- ❌ Contain game logic (that's Rules)
- ❌ Make agent decisions (that's LLM)
- ❌ Calculate hunger/berries (that's Rules)

---

## 🔄 Data Flow (One-Way)

```
User Input (LLM decision)
  ↓
BerriesAgent (stateless processor)
  ↓ returns
Command (EatBerriesCommand, SpeakCommand, etc.)
  ↓ executed by
GameEngine
  ↓ calls
Command.execute(state: WorldState)
  ↓ uses
BushRules / CharacterRules (pure functions)
  ↓ returns
New WorldState (immutable)
  ↓
GameEngine stores in history
```

**✅ No circular dependencies!**  
**✅ All state mutations via commands**  
**✅ Pure functions, easy to test**

---

## 🎬 Event Stream Pattern

### Why Event Stream?

**Problem:** Commands produce multiple observable changes, but state only captures final result.

```python
# One EatBerriesCommand execution:
  → Harvest 5 berries from bush  # Observable event 1
  → Agent gains 5 hunger          # Observable event 2  
  → Hunger now 18/24              # Observable event 3
  → Final state: {bush: 35, agent.hunger: 18}
```

**Where do the intermediate observations go?**

### Solution: Events Separate from State

```
┌─────────────────────────────────────────────────────┐
│                   Game Engine                        │
├─────────────────────────────────────────────────────┤
│  history: List[Command]  ← For replay/branching     │
│  events: List[GameEvent]  ← For observation/logging │
│  current_state: WorldState ← Pure game data         │
└─────────────────────────────────────────────────────┘
```

### Three Storage Layers

```python
Layer 1: Command History (stored, for replay)
  └─ [EatBerriesCommand(seq=42), SleepCommand(seq=43), ...]
  └─ Purpose: Time travel, branching, deterministic replay

Layer 2: WorldState (stored/reconstructable)
  └─ WorldState(turn=5, agents=(...), bush=...)
  └─ Purpose: Current game state, can save/restore

Layer 3: Event Stream (ephemeral or stored separately)
  └─ [GameEvent("berries_harvested"), GameEvent("hunger_updated"), ...]
  └─ Purpose: Logging, UI updates, debugging, analytics
```

### Command Implementation Pattern

```python
class EatBerriesCommand(Command[WorldState]):
    count: int = Field(..., ge=1, le=10)
    
    def can_execute(self, state: WorldState) -> bool:
        """Pre-validate command."""
        agent = state.agents[self.agent_id]
        return agent.alive and state.bush.has_berries(self.count)
    
    def execute(self, state: WorldState) -> Tuple[WorldState, Tuple[GameEvent, ...]]:
        """Execute and emit events."""
        events_list = []
        
        # Validate first (no changes yet)
        if not self.can_execute(state):
            events_list.append(GameEvent(event_type="eat_failed", ...))
            return state, tuple(events_list)  # Unchanged state
        
        # Atomic transaction: harvest + eat
        new_bush, harvested = BushRules.harvest(state.bush, self.count)
        events_list.append(GameEvent(event_type="berries_harvested", ...))
        
        agent = state.agents[self.agent_id]
        new_hunger, consumed, msg = CharacterRules.eat_berries(agent.hunger, harvested)
        events_list.append(GameEvent(event_type="hunger_updated", ...))
        
        # Update state atomically
        new_state = state.with_bush(new_bush).with_agent(self.agent_id, hunger=new_hunger)
        
        return new_state, tuple(events_list)
```

### Event Benefits

**✅ Separation of Concerns:**
- State = "what is" (game data)
- Commands = "what happened" (history)
- Events = "how it happened" (observation)

**✅ Multiple Consumers:**
```python
# UI subscribes to events
for event in engine.events[-N:]:
    ui.display(event.message)

# Analytics tracks events
deaths = [e for e in engine.events if e.event_type == "agent_died"]

# Debug logs detailed changes
for event in engine.events:
    logger.debug(f"{event.game_time}: {event.message}")
```

**✅ Replay with Events:**
```python
# Replay commands AND regenerate events
engine = GameEngine(initial_state)
for cmd in saved_history:
    new_state, events = cmd.execute(engine.current_state)
    engine.current_state = new_state
    for event in events:
        print(f"[Replay] {event.message}")
```

---

## 🔒 Immutability Principles

### Core Tenet

**All state is immutable.** Mutations create new instances.

### Implementation

1. **Frozen Pydantic Models**
```python
class BushState(BaseModel):
    model_config = ConfigDict(frozen=True)
    current_berries: float
```

2. **Tuples Instead of Lists**
```python
agents: Tuple[CharacterPhysicalState, ...]  # ✅
agents: List[CharacterPhysicalState]        # ❌
```

3. **Immutable Updates**
```python
# ❌ BAD: Mutation
state.bush.current_berries -= 5

# ✅ GOOD: Copy with updates
new_bush = bush.model_copy(update={"current_berries": bush.current_berries - 5})
new_state = state.with_bush(new_bush)
```

### Benefits

- **Thread-Safe:** Immutable state can be shared safely
- **Easy Undo:** Just go back to previous state
- **No Hidden Mutations:** All changes explicit
- **Time Travel:** Can keep all historical states

---

## 💡 Design Principles

### 1. Immutability First
All state uses `frozen=True`, Tuples instead of Lists

### 2. Pure Functions
Rules classes contain only static methods with no side effects

### 3. One-Way Flow
Commands → WorldState (no back-references)

### 4. Separation of Concerns
Data (entities/), Logic (Rules), Orchestration (Commands), Coordination (GameEngine)

### 5. Determinism
Commands store decisions, not how to query LLMs again

### 6. Event Stream
Observable changes separate from state (logging, UI, debug)

---

## ❌ Anti-Patterns to Avoid

❌ Mutable state (no `list`, `dict`, `set` in WorldState)  
❌ Circular dependencies (module A imports B, B imports A)  
❌ Global singletons (no WORLD)  
❌ Mixed concerns (Agent = LLM processor, NOT physical state)  
❌ Direct mutations (use Commands + Rules instead)  
❌ Floating variables (validate first, then transact atomically)  
❌ Messages in state (use Event Stream instead)

---

## 🎯 Architectural Trade-offs

### What We Gained

✅ **Time Travel:** Inspect any past turn  
✅ **Branching:** A/B test from same point  
✅ **Determinism:** Reproducible experiments  
✅ **Testability:** Each layer tests independently  
✅ **Debuggability:** Full event log of changes  
✅ **Network-Ready:** Commands are serializable  

### What We Sacrificed

❌ **Simplicity:** More complex than mutable OOP  
❌ **Performance:** More object creation overhead  
❌ **Learning Curve:** Command Pattern less familiar  

**Verdict:** Trade-offs worth it for research requirements.

---

## 🔧 Architecture Decisions Log

### Decision 1: Command Pattern over Event Sourcing
**Why:** Event Sourcing is overkill for 3-agent game. Command Pattern gives us time travel + branching without complexity of event store infrastructure.

### Decision 2: Rules in Same File as State
**Why:** High cohesion. `BushRules` are the behavior of `BushState`. Moving to separate file adds no decoupling (Rules need State imports anyway).

### Decision 3: Event Stream Separate from Command History
**Why:** Commands = replay (essential), Events = observability (optional). Can store events ephemerally, rotating buffer, or permanently depending on needs.

### Decision 4: Agents are Stateless
**Why:** Agent physical state (hunger, alive) lives in WorldState. Agent class is just decision processor (LLM interface). Separates concerns: data vs behavior.

### Decision 5: Tuple Return from Commands
**Why:** `Tuple[GameEvent, ...]` is immutable, enforces no modifications after return. Consistent with immutability principle.

---

**End of Architecture Document**

