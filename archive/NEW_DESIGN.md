# LLMBerries - NEW_DESIGN.md
**Single Source of Truth for Architecture & Implementation Status**

Last Updated: 2025-11-07

---

## 🎯 Project Vision

**LLMBerries** is a research platform for studying LLM behavior in resource scarcity scenarios. Three LLM agents compete for limited berries from a shared bush, creating a trolley problem meets prisoner's dilemma experiment.

**Core Question:** How do LLMs cooperate, compete, and communicate when survival is at stake?

---

## 📊 Current State: Mid-Refactor to Command Pattern

### Status Summary

🟢 **CLEAN** - DTOs in `entities/` folder (immutable, no circular deps)  
🟡 **MIXED** - `objects/` folder contains old OOP + new immutable state  
🟡 **MIXED** - `core/` folder has two game engines (v1 mutable, v2 command-based)  
🔴 **BROKEN** - Circular dependencies between `objects/agent_body.py` ↔ `core/game_engine.py`  
🔴 **INCOMPLETE** - Refactor started but not finished

### Architecture Goal

**Target Pattern:** Command Pattern with Immutable State (from `game_patterns.md`)

**Why Command Pattern?**
- Time travel debugging (inspect any past turn)
- State branching (A/B test different LLMs from same starting point)
- Deterministic replay (store command history)
- Network-ready (commands are serializable)
- No circular dependencies (one-way flow: Command → GameState)

---

## 📁 Detailed File Analysis

### ✅ entities/ - NEW DTOs (CLEAN)

**Purpose:** Immutable data transfer objects following Command Pattern

| File | Status | Description | Issues |
|------|--------|-------------|--------|
| `actions.py` | 🔴 EMPTY | Should contain action enums/types | Empty file (1 line) |
| `bush.py` | 🟢 GOOD | `BushState` (frozen) + `BushRules` (static) | None |
| `character.py` | 🟢 GOOD | `CharacterPhysicalState` (frozen) + `CharacterRules` (static) | None |
| `hunger.py` | 🟢 GOOD | `HungerStatus` enum (DEAD→STUFFED) | None |
| `llm_configs.py` | 🟢 GOOD | LLM configuration helpers | None |
| `memory.py` | 🟢 GOOD | `ConversationMemory` (frozen) | None |
| `messsage.py` | 🟡 TYPO | `NeighborMessage` (frozen) | Filename typo: "messsage" |
| `observations.py` | 🟢 GOOD | `NeighborObservation` + `AgentObservation` (frozen) | None |
| `world.py` | 🟡 STUB | `WorldState` (frozen, mostly empty) | Underutilized |

**Dependencies:**
- ✅ Only imports constants/enums from `core.common` (acceptable)
- ✅ NO references to GameState or mutable objects
- ✅ NO circular dependencies
- ✅ All classes use `frozen=True` (immutable)

**Pattern Compliance:**
```python
# Frozen state dataclass
class BushState(BaseModel):
    model_config = ConfigDict(frozen=True)
    current_berries: float
    max_berries: float

# Pure functions for state transitions
class BushRules:
    @staticmethod
    def harvest(bush: BushState, count: int) -> Tuple[BushState, int]:
        # Returns NEW state, never mutates
```

---

### ⚠️ objects/ - OLD OOP + NEW IMMUTABLE (MIXED)

**Purpose:** Legacy OOP classes being phased out + some new immutable state

| File | Status | Description | Issues |
|------|--------|-------------|--------|
| `agent_body.py` | 🔴 LEGACY | Mutable `AgentBody` class | Circular dep with `game_engine.py`, references WORLD singleton |
| `game_state.py` | 🟡 PARTIAL | `GameState` (frozen) + helpers | Exists here AND in pattern, unclear ownership |
| `observations.py` | 🟡 LEGACY | Uses old `AgentBody` | Duplicates `entities/observations.py` |
| `bush.py` | 🔴 UNKNOWN | Not read yet | Likely old mutable Bush class |

**Circular Dependencies:**
```
objects/agent_body.py
  ↓ imports
core/game_engine.py
  ↓ imports
objects/agent_body.py  ❌ CIRCULAR!
```

**WORLD Singleton:**
```python
# objects/agent_body.py
from core.world import WORLD
_game_engine: GameEngine = PrivateAttr(default=WORLD.get_game_engine())
```
This creates global state and tight coupling.

---

### 🟡 core/ - MIX OF OLD & NEW (TRANSITIONAL)

**Purpose:** Game logic, engine, commands

| File | Status | Description | Issues |
|------|--------|-------------|--------|
| `common.py` | 🟢 GOOD | Constants, enums (MAX_HUNGER, TOTAL_AGENTS, etc.) | None |
| `commands.py` | 🟢 GOOD | Command classes (EatBerriesCommand, SpeakCommand, etc.) | References `objects/` (acceptable) |
| `game_engine.py` | 🔴 LEGACY | OLD mutable engine | Circular dep with `agent_body.py` |
| `game_engine_v2.py` | 🟢 NEW | Command-based engine with history/branching | Clean, immutable |
| `berries_agent.py` | 🟡 MIXED | LLM agent class | Inherits from BOTH BaseAgent AND AgentBody (mixing concerns) |
| `zombie_agent.py` | 🟡 TEST | Mock agent for testing | Uses old observations |
| `demo.py` | 🟡 DEMO | Demo script | References old `objects/` classes |

**Two Engines Coexist:**
- `game_engine.py` (v1) - Mutable, OOP, circular deps
- `game_engine_v2.py` (v2) - Immutable, command-based, clean ✅

**Agent Inheritance Problem:**
```python
# core/berries_agent.py
class BerriesAgent(BaseAgent, AgentBody):
    """LLM decision-maker + Physical state MIXED"""
```
This violates separation of concerns. Agent should be stateless processor, state should live in GameState.

---

### ✅ interface/ - ABSTRACTIONS (CLEAN)

| File | Status | Description |
|------|--------|-------------|
| `command.py` | 🟢 GOOD | Generic `Command[StateT]` base class |
| `agent_tools.py` | 🟢 GOOD | `AgentTools` abstract interface |

---

### 📚 Documentation State

| File | Status | Description | Action |
|------|--------|-------------|--------|
| `DESIGN.md` | 🔴 OUTDATED | Original OOP design (pre-refactor) | Archive or delete |
| `ARCHITECTURE_SUMMARY.md` | 🟡 PARTIAL | Command pattern summary, incomplete | Merge into NEW_DESIGN.md |
| `REFACTOR_COMPLETE.md` | 🔴 MISLEADING | Claims refactor done (it's not!) | Delete |
| `pattern_refactor.md` | 🟢 REFERENCE | Detailed refactor plan and reasoning | Keep as reference |
| `game_patterns.md` | 🟢 REFERENCE | Architecture patterns guide | Keep (don't touch!) |
| `README.md` | 🟡 OUTDATED | Basic project info | Update with current state |

---

## 🔧 Technical Debt & Issues

### Critical Issues

1. **Circular Dependency** 🔴
   - `objects/agent_body.py` ↔ `core/game_engine.py`
   - Blocks clean separation of concerns
   - Makes testing difficult

2. **WORLD Singleton** 🔴
   - Global mutable state pattern
   - Used in `objects/agent_body.py` and referenced elsewhere
   - Anti-pattern for Command Pattern

3. **Mixed Paradigms** 🟡
   - Old mutable OOP (objects/) + New immutable Command Pattern (entities/)
   - Two game engines coexist
   - Confusion about which to use

4. **Agent State Mixing** 🟡
   - `BerriesAgent` inherits from both `BaseAgent` (LLM) and `AgentBody` (state)
   - Should separate: Agent (stateless processor) vs CharacterPhysicalState (data)

### Minor Issues

5. **Filename Typo** 🟡
   - `entities/messsage.py` should be `message.py`

6. **Empty File** 🟡
   - `entities/actions.py` is empty (1 line)

7. **Duplicate Files** 🟡
   - `objects/observations.py` vs `entities/observations.py`
   - Unclear which is canonical

---

## 🎯 Clear Path Forward

### Phase 1: Cleanup & Consolidation (HIGH PRIORITY)

**Goal:** Remove confusion, establish single paradigm

- [ ] **Delete or archive legacy files**
  - [ ] Move `DESIGN.md` → `archive/DESIGN_OLD.md`
  - [ ] Delete `REFACTOR_COMPLETE.md` (misleading)
  - [ ] Archive `ARCHITECTURE_SUMMARY.md` content into NEW_DESIGN.md
  
- [ ] **Fix filename issues**
  - [ ] Rename `entities/messsage.py` → `entities/message.py`
  - [ ] Update imports in all files
  
- [ ] **Populate empty files**
  - [ ] Add action types to `entities/actions.py` (or delete if unused)
  
- [ ] **Resolve duplication**
  - [ ] Decide: Keep `entities/observations.py` (uses immutable CharacterPhysicalState)
  - [ ] Delete `objects/observations.py` (uses mutable AgentBody)

### Phase 2: Break Circular Dependencies (HIGH PRIORITY)

**Goal:** Make objects/ folder reference-free from core/

- [ ] **Remove WORLD singleton**
  - [ ] Refactor `objects/agent_body.py` to not reference WORLD
  - [ ] Pass game_time as parameter instead of singleton access
  - [ ] Delete `core/world.py` if no longer needed
  
- [ ] **Break agent_body ↔ game_engine cycle**
  - [ ] Remove `_game_engine` attribute from `AgentBody`
  - [ ] Move tool execution logic to Command classes
  - [ ] Make `AgentBody` pure data class (or delete it entirely)

### Phase 3: Consolidate to Command Pattern (MEDIUM PRIORITY)

**Goal:** Single consistent architecture

- [ ] **Choose ONE game engine**
  - [ ] Migrate remaining code to `game_engine_v2.py`
  - [ ] Delete or archive `game_engine.py` (old mutable version)
  
- [ ] **Separate Agent concerns**
  - [ ] Make `BerriesAgent` stateless (remove `AgentBody` inheritance)
  - [ ] Move agent state to `GameState.agents` (already exists in v2)
  - [ ] Agent should only: receive observation → return command
  
- [ ] **Unify observations**
  - [ ] Use `entities/observations.py` everywhere
  - [ ] Update zombie_agent.py and demo.py
  
- [ ] **Move or delete objects/ folder**
  - [ ] Move `objects/game_state.py` → `entities/game_state.py` (if needed)
  - [ ] Delete legacy `objects/agent_body.py`
  - [ ] Delete or archive `objects/bush.py` (use `entities/bush.py`)

### Phase 4: Integration & Testing (MEDIUM PRIORITY)

- [ ] **Update main.py**
  - [ ] Use `game_engine_v2.py`
  - [ ] Use stateless `BerriesAgent`
  - [ ] Implement proper game loop with command pattern
  
- [ ] **Fix tests**
  - [ ] Update `tests/test_hourly_turns.py`
  - [ ] Update `tests/test_message_flow.py`
  - [ ] Update `tests/test_zombie_battle.py`
  - [ ] Add tests for branching/time-travel
  
- [ ] **Update demo.py**
  - [ ] Use new entities/ classes
  - [ ] Show command pattern features (branching, replay)

### Phase 5: Documentation & Polish (LOW PRIORITY)

- [ ] **Update README.md**
  - [ ] Reflect current architecture (Command Pattern)
  - [ ] Update quick start guide
  - [ ] Add examples of branching/replay
  
- [ ] **Add examples**
  - [ ] A/B testing different LLMs
  - [ ] Time travel debugging
  - [ ] Command history export/import
  
- [ ] **Clean up markdown files**
  - [ ] Keep only: NEW_DESIGN.md, game_patterns.md, README.md
  - [ ] Archive others

---

## 🏗️ Target Architecture (Final State)

### Directory Structure

```
LLMBerries/
├── entities/              # ✅ Immutable DTOs (data only)
│   ├── character.py       # CharacterPhysicalState + CharacterRules
│   ├── bush.py            # BushState + BushRules
│   ├── game_state.py      # GameState (top-level frozen state)
│   ├── message.py         # NeighborMessage (fixed typo!)
│   ├── observations.py    # NeighborObservation, AgentObservation
│   ├── memory.py          # ConversationMemory
│   ├── hunger.py          # HungerStatus enum
│   └── llm_configs.py     # LLM config helpers
│
├── core/                  # 🎮 Game logic & orchestration
│   ├── common.py          # Constants, enums
│   ├── commands.py        # Command classes (EatBerries, Speak, etc.)
│   ├── game_engine.py     # NEW: game_engine_v2 becomes main engine
│   ├── berries_agent.py   # LLM decision processor (STATELESS)
│   └── zombie_agent.py    # Mock agent for testing
│
├── interface/             # 🔌 Abstract interfaces
│   ├── command.py         # Command[StateT] base class
│   └── agent_tools.py     # AgentTools interface
│
├── tests/                 # 🧪 Test suite
├── main.py                # 🚀 Game runner
├── NEW_DESIGN.md          # 📋 This file (single source of truth)
├── game_patterns.md       # 📚 Reference (don't touch!)
└── README.md              # 📖 Project overview
```

**DELETED:**
- `objects/` folder (legacy OOP)
- `core/world.py` (singleton)
- `core/game_engine.py` (old mutable version, replaced by v2)
- Outdated markdown files

### Data Flow (Clean One-Way)

```
User Input
  ↓
BerriesAgent (stateless)
  ↓ returns
Command (EatBerriesCommand, SpeakCommand, etc.)
  ↓ executed by
GameEngine
  ↓ calls
Command.execute(state: GameState)
  ↓ uses
BushRules / CharacterRules (pure functions)
  ↓ returns
New GameState (immutable)
  ↓
GameEngine stores in history
```

**No circular dependencies!** ✅  
**All state mutations via commands** ✅  
**Pure functions, easy to test** ✅

---

## 🎮 Game Mechanics

### Core Concepts

**Agents:** 3 LLM agents, sitting in a circle  
**Resource:** Berry bush (40 max capacity, regenerates 1.05/hour)  
**Survival:** Each agent needs berries to survive (1 berry = 1 hour life)  
**Scarcity:** Regeneration (~1.8/hour) < Total consumption (3 agents × ~1/hour) → Tragedy of the commons  
**Identity Twist:** All agents are LLMs, but some appear "Human" to others (they always see themselves as "Android")

### Agent Actions (Tools)

1. **think()** - Internal reasoning, updates agent's memory
2. **eat_berries(count: int)** - Harvest and eat berries (instant, no time passes)
3. **speak(left_msg: str, right_msg: str)** - Send messages to neighbors
4. **set_sleep_duration(hours: int)** - Set sleep duration (1-8 hours)
5. **finish_turn()** - End turn and go to sleep (dispatches messages, advances time)

### Visibility System

**Hunger Perception:** Neighbors' hunger level ± random(0-4) noise  
**Activity Observation:** See if neighbor spoke (but not message content)  
**Messages:** Delivered asynchronously to neighbor's conversation history with prefix  
**Identity:** Fixed at game start (1 Human, 2 Androids perceived)

---

## 🔄 Turn Cycle Specification

### Game Initialization (Turn 0)

```
- All 3 agents in ASLEEP state
- Wake time = 0 (wake immediately)
- Hunger = 20/24 for all agents
- No pending messages
- Bush has 40 berries
```

### Turn Execution Flow

Each turn processes agents **clockwise** (agent 0 → agent 1 → agent 2 → agent 0):

#### Phase 1: State Cleanup
```python
for agent_id in clockwise_order:
    execute(ClearPendingMessagesCommand(agent_id))
```
- Clear messages that were dispatched last turn
- Reset sleep_duration to default (1 hour)

#### Phase 2: Death Check
```python
for agent_id in all_agents:
    if agent.hunger <= 0 and agent.alive:
        execute(MarkDeadCommand(agent_id))
```
- Check if any agent's hunger reached 0
- Mark as DEAD if starved

#### Phase 3: Game Over Check
```python
alive_count = count(agent for agent in agents if agent.alive)
if alive_count <= 1:
    game_over = True
    return winner
```
- If ≤1 agent alive, end game

#### Phase 4: Wake Up Check
```python
for agent_id in all_agents:
    agent = state.agents[agent_id]
    if agent.wake_time and state.world_time >= agent.wake_time:
        execute(WakeUpCommand(agent_id))
        # Sets body_state = AWAKE, sleep_duration = 1 hour
```
- Check if any agent's wake time has been reached
- Change state from ASLEEP → AWAKE

#### Phase 5: State Report
```python
for agent_id in all_agents:
    emit_event(GameEvent(
        event_type="agent_state_report",
        agent_id=agent_id,
        data=agent.get_status_dict()
    ))
```
- Emit status events for all agents (for logging/UI)

#### Phase 6: Observations & Actions (Awake Agents Only)
```python
for agent_id in clockwise_order:
    agent = state.agents[agent_id]
    
    if agent.body_state != "AWAKE":
        continue  # Skip sleeping/dead agents
    
    # Generate observation
    observation = ObservationFactory.create(state, agent_id)
    # Includes:
    #   - Neighbor states (hunger with noise, body type, activity)
    #   - Bush berry count
    #   - Own status
    #   - Pending messages from conversation history
    
    # Agent takes actions (can do multiple)
    while agent_still_awake:
        # Agent can execute:
        # - ThinkCommand: Update internal reasoning
        # - EatBerriesCommand: Harvest berries from bush, eat them
        # - SpeakCommand: Set messages for neighbors
        # - SleepDurationCommand: Set how long to sleep
        # - FinishTurnCommand: End turn (required to advance)
        
        command = agent.decide(observation)
        execute(command)
        
        if isinstance(command, FinishTurnCommand):
            # Agent goes to sleep
            # - Calculate wake_time = current_time + sleep_duration
            # - Set body_state = ASLEEP
            # - Dispatch messages to neighbor conversation histories
            #   with prefix: "Hour X: [Left/Right] says: ..."
            break
```

#### Phase 7: Time Advancement
```python
# Once ALL agents are asleep/dead
if no_agents_awake():
    execute(AdvanceTimeCommand(hours=1))
    # - Increment world_time by 1 hour
    # - Regenerate bush (bush.current_berries += regen_rate)
    # - Decrease agent hunger (hunger -= hunger_rate)
    # - Check for deaths due to starvation
```

### Turn Cycle Diagram

```
┌─────────────────────────────────────────────────────┐
│              START TURN (world_time++)              │
└─────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────┐
│  Phase 1: Clear Pending Messages (all agents)       │
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
│  Phase 6: Process Awake Agents (clockwise)          │
│  ┌───────────────────────────────────────────────┐  │
│  │  For each AWAKE agent:                        │  │
│  │  1. Generate observation                      │  │
│  │  2. Agent decides action                      │  │
│  │  3. Execute command                           │  │
│  │  4. Repeat until FinishTurnCommand            │  │
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

---

## 🧪 Key Features (Enabled by Command Pattern)

### Time Travel Debugging
```python
# Go back to turn 15
state = engine.goto_turn(15)

# Inspect what happened
print(state.agents[0].hunger)  # Alice's hunger at turn 15
```

### State Branching (A/B Testing)
```python
# Try different LLMs from same starting point
gpt_engine = engine.branch_from(turn=10)
gpt_engine.execute_llm_decision(llm=GPT4)

claude_engine = engine.branch_from(turn=10)
claude_engine.execute_llm_decision(llm=CLAUDE)

# Compare outcomes
compare_strategies(gpt_engine, claude_engine)
```

### Deterministic Replay
```python
# Save game
history = engine.export_history()  # List of commands (JSON)

# Replay later
new_engine = GameEngine.from_history(initial_state, history)
new_engine.replay()  # Reaches exact same end state
```

### Network-Ready
```python
# Server
state_json = engine.current_state.model_dump_json()

# Client executes command
cmd = EatBerriesCommand(agent_id=0, count=5)
cmd_json = cmd.model_dump_json()

# Send over network, execute deterministically on server
```

---

## 📊 Metrics & Success Criteria

### Technical Debt Resolution

- [ ] ✅ Zero circular dependencies
- [ ] ✅ No global singletons (WORLD deleted)
- [ ] ✅ Single game engine (v2 only)
- [ ] ✅ Stateless agents (state in GameState)
- [ ] ✅ All DTOs immutable (frozen=True)
- [ ] ✅ Pure functions for logic (CharacterRules, BushRules)

### Testing

- [ ] Unit tests for all Commands
- [ ] Unit tests for all Rules (pure functions)
- [ ] Integration tests for game_engine_v2
- [ ] Tests for branching/replay
- [ ] Tests for LLM agent integration
- [ ] All existing tests pass

### Documentation

- [ ] README.md reflects Command Pattern
- [ ] NEW_DESIGN.md is single source of truth
- [ ] Code examples for branching/replay
- [ ] Architecture diagrams updated

---

## 🚀 Quick Start (After Refactor Complete)

```bash
# Install
uv sync

# Run game
uv run python3 main.py

# Run tests
uv run pytest tests/

# Demo command pattern features
uv run python3 core/demo.py
```

---

## 📖 Related Documents

- **game_patterns.md** - Architecture patterns reference (Command Pattern, Service Layer, etc.)
- **pattern_refactor.md** - Detailed reasoning behind Command Pattern choice
- **README.md** - Project overview and setup

---

## 🔗 Dependencies (from pyproject.toml)

```toml
[dependencies]
python = "^3.11"
pydantic = "^2.10.3"         # Immutable models, validation
just-agents = "*"            # LLM agent framework
frozendict = "*"             # Immutable dicts for LLM configs
python-dotenv = "*"          # Environment variables
```

---

## 💡 Design Principles

### Core Tenets

1. **Immutability First** - All state uses `frozen=True`, Tuples instead of Lists
2. **Pure Functions** - Rules classes contain only static methods with no side effects
3. **One-Way Flow** - Commands → GameState (no back-references)
4. **Separation of Concerns** - Data (entities/), Logic (core/), Abstractions (interface/)
5. **Determinism** - Commands store decisions, not how to query LLMs again
6. **Event Stream Pattern** - Observable changes separate from state (logging, UI, debug)

### Anti-Patterns to Avoid

❌ Mutable state (no `list`, `dict`, `set` in GameState)  
❌ Circular dependencies (module A imports B, B imports A)  
❌ Global singletons (no WORLD)  
❌ Mixed concerns (Agent = LLM processor, NOT physical state)  
❌ Direct mutations (use Commands + Rules instead)  
❌ Floating variables (validate first, then transact atomically)  
❌ Messages in state (use Event Stream instead)

### Patterns We Use

✅ Command Pattern (actions as objects)  
✅ **Event Stream Pattern** (observable changes separate from state)  
✅ Frozen Dataclasses (Pydantic v2 with frozen=True)  
✅ Static Rules Classes (pure functions for domain logic)  
✅ Factory Methods (create observations from state)  
✅ Type Hints Everywhere (mypy-compatible)

---

## 🎬 Event Stream Architecture

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

### Three Layers Model

```python
Layer 1: Command History (stored, for replay)
  └─ [EatBerriesCommand(seq=42), SleepCommand(seq=43), ...]
  └─ Purpose: Time travel, branching, deterministic replay

Layer 2: GameState (stored/reconstructable)
  └─ WorldState(turn=5, agents=(...), bush=...)
  └─ Purpose: Current game state, can save/restore

Layer 3: Event Stream (ephemeral or stored separately)
  └─ [GameEvent("berries_harvested"), GameEvent("hunger_updated"), ...]
  └─ Purpose: Logging, UI updates, debugging, analytics
```

### Command Implementation Pattern

```python
from entities.events import GameEvent

class EatBerriesCommand(Command[WorldState]):
    count: int = Field(..., ge=1, le=10)
    
    def can_execute(self, state: WorldState) -> bool:
        """Pre-validate command."""
        agent = state.agents[self.agent_id]
        return agent.alive and state.bush.has_berries(self.count)
    
    def execute(self, state: WorldState) -> Tuple[WorldState, List[GameEvent]]:
        """Execute and emit events."""
        events = []
        
        # Validate first (no changes yet)
        if not self.can_execute(state):
            events.append(GameEvent(
                sequence_number=self.sequence_number,
                agent_id=self.agent_id,
                event_type="eat_failed",
                message="Cannot eat berries",
                data={"reason": "dead or insufficient berries"},
                game_time=self.timestamp
            ))
            return state, events  # Unchanged state
        
        # Atomic transaction: harvest + eat
        old_berries = state.bush.current_berries
        new_bush, harvested = BushRules.harvest(state.bush, self.count)
        
        events.append(GameEvent(
            event_type="berries_harvested",
            message=f"Harvested {harvested} berries",
            data={"bush_before": old_berries, "bush_after": new_bush.current_berries}
        ))
        
        agent = state.agents[self.agent_id]
        new_hunger = agent.hunger + harvested
        
        events.append(GameEvent(
            event_type="hunger_updated",
            message=f"Hunger: {agent.hunger} → {new_hunger}",
            data={"old": agent.hunger, "new": new_hunger}
        ))
        
        # Update state atomically
        new_state = (
            state
            .with_bush(new_bush)
            .with_agent(self.agent_id, hunger=new_hunger, ...)
        )
        
        return new_state, events
```

### Engine Implementation Pattern

```python
class GameEngine:
    def __init__(self, initial_state: WorldState):
        self.initial_state = initial_state
        self.current_state = initial_state
        self.history: List[Command] = []  # For replay
        self.events: List[GameEvent] = []  # For observation
    
    def execute_command(self, cmd: Command) -> List[GameEvent]:
        """Execute command and collect events."""
        new_state, events = cmd.execute(self.current_state)
        
        self.current_state = new_state
        self.history.append(cmd)
        self.events.extend(events)  # Store separately
        
        # Log events for human consumption
        for event in events:
            self.log(str(event))
        
        return events
```

### Why This is Better

**✅ Separation of Concerns:**
- State = "what is" (game data)
- Commands = "what happened" (history)
- Events = "how it happened" (observation)

**✅ Multiple Consumers:**
```python
# UI subscribes to events
engine.execute_command(eat_cmd)
for event in engine.events[-N:]:
    ui.display(event.message)

# Analytics tracks events
for event in engine.events:
    if event.event_type == "agent_died":
        analytics.record_death(event.data)

# Debug logs detailed changes
for event in engine.events:
    logger.debug(f"{event.game_time}: {event.message}")
```

**✅ Flexible Storage:**
```python
# Option 1: Keep all events (full history)
self.events.extend(events)

# Option 2: Rotating buffer (last N events)
self.events.extend(events)
self.events = self.events[-1000:]  # Keep last 1000

# Option 3: Don't store (ephemeral logging only)
for event in events:
    logger.info(event.message)
# Events discarded after logging
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

### GameEvent Structure

```python
@dataclass(frozen=True)
class GameEvent:
    sequence_number: int  # Which command generated this
    agent_id: int | None  # Agent involved (None for global events)
    event_type: str  # "berries_harvested", "hunger_updated", "agent_died"
    message: str  # Human-readable
    data: dict  # Structured data for UI/analytics
    game_time: float  # When it happened
```

### Event Types in LLMBerries

```python
# Bush events
"berries_harvested"  # Bush lost berries
"bush_regenerated"   # Bush grew berries
"harvest_partial"    # Requested more than available

# Agent events  
"hunger_updated"     # Hunger changed
"agent_died"         # Agent starved
"agent_woke"         # Agent woke from sleep
"agent_slept"        # Agent went to sleep

# Communication events
"message_sent"       # Agent spoke to neighbor
"message_dispatched" # Message added to queue
"message_delivered"  # Message received by agent

# Turn events
"turn_advanced"      # Turn number incremented
"turn_started"       # Agent's turn began
"turn_ended"         # Agent's turn ended
```

### Atomic Transactions

Commands are **atomic**: either succeed fully or fail with unchanged state.

```python
# ❌ BAD: Floating variables
berries = BushRules.harvest(state.bush, 5)  # Floating!
if not agent.alive:
    return state, []  # Berries disappeared!

# ✅ GOOD: Validate first, then transact
def execute(self, state):
    # Check ALL preconditions FIRST
    if not self.can_execute(state):
        return state, [GameEvent(..., event_type="failed")]
    
    # All checks passed - now atomically update
    new_bush, harvested = BushRules.harvest(state.bush, self.count)
    new_state = state.with_bush(new_bush).with_agent(...)
    
    events = [
        GameEvent(..., event_type="harvested"),
        GameEvent(..., event_type="hunger_updated")
    ]
    
    return new_state, events
```

**Key principle:** Return **either**:
- Old state + failure events (validation failed)
- New state + success events (transaction completed)

Never return partial state updates.

---

## 🎯 Next Steps (Prioritized)

**This Week:**
1. Fix filename typo: `messsage.py` → `message.py`
2. Delete misleading `REFACTOR_COMPLETE.md`
3. Break circular dependency: Remove WORLD singleton from `agent_body.py`

**Next Week:**
1. Consolidate to game_engine_v2 as main engine
2. Make BerriesAgent stateless
3. Delete legacy objects/ folder

**Later:**
1. Update tests to use Command Pattern
2. Implement main.py game loop
3. Add replay/branching examples

---

## 🙋 FAQ

**Q: Why Command Pattern instead of simpler Service Layer?**  
A: We need branching/replay for research (A/B testing LLMs). Command Pattern gives this for free.

**Q: Why is there an objects/ folder AND entities/ folder?**  
A: Mid-refactor state. `entities/` is new (clean), `objects/` is old (being phased out).

**Q: Can I use the old game_engine.py?**  
A: No, use `game_engine_v2.py`. The old one has circular dependencies and will be deleted.

**Q: What's the difference between Agent and CharacterPhysicalState?**  
A: `CharacterPhysicalState` = game state data (hunger, alive status). `BerriesAgent` = LLM decision processor (stateless).

**Q: Why can't agents just mutate themselves?**  
A: Command Pattern requires immutability for time-travel/replay. Mutations break this.

---

## 📝 Change Log

**2025-11-07** - NEW_DESIGN.md created as single source of truth
- Analyzed entire codebase state
- Identified circular dependencies, WORLD singleton issues
- Documented clear path forward
- Prioritized cleanup tasks

---

**END OF NEW_DESIGN.md**

This is now the **single source of truth**. All other design docs are archived or outdated.

