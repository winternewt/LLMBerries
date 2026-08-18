# LLMBerries: Pattern Refactor Plan

Documentation of architectural decisions and refactoring plan for transitioning to Command Pattern.

---

## Lessons Learned

### The Problem Discovery

Starting with a hybrid OOP approach, we encountered several architectural pain points:

#### 1. **Circular Dependencies**
```python
# Current problematic structure
from core.game_engine import GameEngine  # in agent_body.py
from objects.agent_body import AgentBody  # in game_engine.py

class AgentBody:
    _game_engine: GameEngine = PrivateAttr(default=WORLD.get_game_engine())
```

**The issue:** `AgentBody` needs `GameEngine` to perform actions, `GameEngine` needs `AgentBody` to manage state. This creates a circular reference that's hard to maintain and test.

#### 2. **Split Brain Problem**
```python
# In AgentBody (objects/agent_body.py)
def eat_berries(self, count: int) -> str:
    # Agent calculates hunger changes
    self.hunger += count * HUNGER_PER_BERRY
    
# In GameEngine (core/game_engine.py)
def execute_eat_berries(self, agent_id: int, count: int) -> str:
    # Engine handles bush interaction
    harvested = self.bush.harvest(count)
    agent.eat_berries(harvested)
```

**The issue:** Logic is split between agent and engine. Who is responsible for what? Where do bugs live? This violates single responsibility principle.

#### 3. **Global Singleton Dependency**
```python
# In core/world.py
WORLD = World()

# Used everywhere via import
from core.world import WORLD
time = WORLD.get_current_time_in_hours()
```

**The issue:** Hidden dependencies make testing difficult and coupling tight. Changes to WORLD affect entire codebase.

#### 4. **Mixed Concerns in Agent Classes**
```python
class BerriesAgent(BaseAgent, AgentBody):
    """Inherits from both LLM agent AND game state."""
    pass
```

**The issue:** LLM agent (decision-maker) is merged with physical state (game data). This makes it impossible to:
- Test game logic without LLM
- Swap LLMs without touching game state
- Branch game state while preserving agent memory
- Separate player from character

### The Core Insight

> **"Everything more than two entities is COMPLEXITY"**

With 3 agents + bush + messages + time coordination, we have:
- 6 agent-agent relationships
- 3 agent-bush relationships  
- 3 agent-message relationships
- Turn coordination
- Time management

That's **12+ interaction points**. Without proper architecture, this becomes unmaintainable quickly.

### Key Realizations

1. **Backward references are a code smell** - If you need object A to reference object B and B to reference A, your ownership hierarchy is wrong.

2. **Domain separation isn't optional** - When the agent "digests berries itself but asks engine for harvest transaction," you've lost domain boundaries.

3. **Small projects need architecture too** - Even 6 entities (3 agents + bush + 2 neighbors) need thought-out patterns.

4. **Architecture before implementation** - Building MVP first revealed the pain points, but choosing architecture upfront would have saved refactoring time.

---

## Reasoning Behind Command Pattern

### Why Command Pattern?

Service Layer would work for simple needs, but Command Pattern gives us critical capabilities for research:

```python
# Branch from any point in history to test variations
state_at_turn_10 = engine.goto_turn(10)

# Try with GPT-4
engine_a = engine.branch_from(turn=10)
engine_a.play_with_llm(agent_id=0, llm=GPT4)

# Try with Claude from SAME starting point
engine_b = engine.branch_from(turn=10)
engine_b.play_with_llm(agent_id=0, llm=CLAUDE)

# Compare outcomes deterministically
compare_strategies(engine_a, engine_b)
```

This requires immutable state + command history.

### Why Command Pattern Fits

#### 1. **Research/Experiment Focus**
This is a trolley problem + prisoner's dilemma experiment for LLMs:
- Need to reproduce specific scenarios
- Need to vary LLM models at specific turns
- Need to compare different prompt strategies
- Need to analyze decision trees

Command Pattern gives us **free state branching**.

#### 2. **Debugging Complex Interactions**
With 3 LLM agents making decisions:
- "What was the game state when Alice decided to hoard?"
- "If we replay from turn 5, does Bob still betray?"
- "What if we change Carol's prompt at turn 8?"

Command Pattern gives us **time travel debugging**.

#### 3. **Future Network Support**
If this becomes popular, imagine:
- Server runs the game simulation
- Client provides their own LLM (API key)
- Server sends game state
- Client sends back commands

Command Pattern makes this **trivial** - commands are already serializable data.

#### 4. **Reproducibility**
For academic/research purposes:
- Store command history
- Anyone can replay exact same game
- Deterministic results

Command Pattern gives us **perfect replay**.

### The Trade-off: Memory for Clarity

```python
# Memory cost analysis
agents = 3 × ~100 bytes = 300 bytes
bush = 2 floats = 16 bytes  
messages = ~10 × 200 bytes = 2KB
agent_memories = 3 × (20 messages × 500 bytes) = 30KB

Total per snapshot: ~32KB
100 snapshots (100 turns): 3.2MB
```

On a modern machine with 8GB+ RAM, **3.2MB is 0.04% of available memory**. The cognitive clarity is worth the negligible memory cost.

---

## Implementation Decisions

### Immutability: Pydantic + Frozen (Not pyrsistent)

**Decision:** Use Pydantic v2 with `frozen=True` + Tuple-only collections.

**Rationale:**
- ✅ Pydantic validation catches bugs at creation time
- ✅ `frozen=True` prevents accidental mutations
- ✅ `model_copy(update={...})` provides clean update API
- ✅ No additional dependencies (pyrsistent not needed)
- ✅ Type hints work naturally (`Tuple[Agent, ...]`)
- ⚠️ Must use Tuples exclusively (no Lists/Dicts in state)

**Rejected Alternative:** `pyrsistent` library (PVector, PMap)
- ❌ Additional dependency
- ❌ Incompatible with Pydantic validation
- ❌ Overkill for 3-agent game
- ❌ Learning curve not worth it for this scale

```python
# FINAL APPROACH
from pydantic import BaseModel
from typing import Tuple

class GameState(BaseModel):
    model_config = {"frozen": True}
    agents: Tuple[CharacterPhysicalState, ...]  # Immutable tuple
    message_queue: Tuple[NeighborMessage, ...]
    
    def with_agent(self, agent_id: int, **fields) -> "GameState":
        """Update agent fields immutably."""
        old_agent = self.agents[agent_id]
        new_agent = old_agent.model_copy(update=fields)
        new_agents = self.agents[:agent_id] + (new_agent,) + self.agents[agent_id+1:]
        return self.model_copy(update={"agents": new_agents})
```

### Mutability Protection

**Problem:** Python's `frozen=True` is shallow - doesn't prevent mutation of mutable fields.

**Solution:** Validator + strict collection types

```python
def _check_immutable(obj: Any, path: str = "root") -> None:
    """Validate no mutable collections."""
    if isinstance(obj, (list, dict, set)):
        raise ValueError(f"Mutable {type(obj).__name__} at {path}. Use Tuple/FrozenSet.")
    if isinstance(obj, BaseModel):
        for name in obj.model_fields:
            _check_immutable(getattr(obj, name), f"{path}.{name}")
    elif isinstance(obj, tuple):
        for i, item in enumerate(obj):
            _check_immutable(item, f"{path}[{i}]")

class GameState(BaseModel):
    model_config = {"frozen": True}
    
    @model_validator(mode='after')
    def validate_immutability(self) -> "GameState":
        _check_immutable(self)
        return self
```

**Rules:**
- ✅ Use `Tuple` not `List`
- ✅ Use `FrozenSet` not `Set`
- ✅ All nested models also `frozen=True`
- ❌ Never use `List`, `Dict`, `Set` in state
- ✅ Validator catches violations at creation

### Command History: Flat, Not Nested

**Decision:** Flat command list with turn markers

**Rationale:**
- One turn can have multiple commands (LLM calls tool multiple times)
- Commands within turn have sequential dependencies
- Need mid-turn state inspection for debugging
- Flat list is simpler than nested structures

```python
# Command history is FLAT
history = [
    EatBerriesCommand(agent_id=0, count=5),      # Turn 0, action 0
    EatBerriesCommand(agent_id=0, count=3),      # Turn 0, action 1
    SpeakCommand(agent_id=0, left_msg="Hi"),     # Turn 0, action 2
    EndTurnCommand(agent_id=0, turn_number=0),   # Turn 0 ends
    EatBerriesCommand(agent_id=1, count=2),      # Turn 1, action 0
    EndTurnCommand(agent_id=1, turn_number=1),   # Turn 1 ends
]

# Navigation
state = engine.goto_turn(0)        # State after turn 0 ends
state = engine.goto_turn(0, 1)     # State mid-turn 0, after action 1
```

**Rejected Alternative:** Nested structure (AgentTurn wrapping commands)
- ❌ More complex to navigate
- ❌ Replay logic more complicated
- ❌ Can't easily inspect mid-turn state
- ❌ False abstraction - turns are just markers

**Git Analogy:**
- Commands = individual commits
- EndTurnCommand = tag marking release
- `goto_turn(n)` = checkout tag
- `goto_turn(n, k)` = checkout specific commit within release

### LLM Non-Determinism Handling

**Problem:** LLMs are stochastic - same input ≠ same output

**Solution:** Store decisions, not queries

```python
# WRONG: Store the query (non-deterministic replay)
class QueryLLMCommand:
    prompt: str
    def execute(self, state):
        response = llm.query(self.prompt)  # Different each time!
        return parse(response)

# RIGHT: Store the decision (deterministic replay)
class EatBerriesCommand:
    agent_id: int
    count: int  # LLM already decided this
    
    def execute(self, state):
        # Deterministic - just apply the decision
        return state.with_agent(self.agent_id, hunger=...)
```

**Key Insight:** Commands store **what the LLM decided**, not **how to ask the LLM again**.

Replay is deterministic because we replay the decisions, not the decision-making process.

### Memory Overhead: Commands vs States

**Actual Cost:**
```python
# Initial state: 32KB
# 100 commands × ~150 bytes/command = 15KB
# Total: 47KB (not 3.2MB!)

# Structural sharing means states don't fully copy
state1.agents is state2.agents  # Same tuple object!
```

Command history IS the incremental backup approach. We're already optimal.

---

## Overhead Expectations

### Initial Refactoring Effort

**Estimated time:** 6-10 hours
**Complexity:** Medium

#### Time breakdown:
1. **Create immutable GameState** (2 hours)
   - Define frozen dataclass
   - Implement `with_*` helper methods
   - Handle nested state updates

2. **Implement Command classes** (2-3 hours)
   - EatBerriesCommand
   - SpeakCommand  
   - SleepCommand
   - AdvanceTimeCommand (special meta-command)

3. **Refactor GameEngine** (2-3 hours)
   - Replace direct mutations with command execution
   - Implement history tracking
   - Add branch/replay functionality

4. **Separate LLM agents from state** (2-3 hours)
   - Extract physical state from BerriesAgent
   - Make agent memory part of GameState
   - Make agents stateless processors

5. **Update tests** (1 hour)
   - Adjust for new API
   - Add tests for branching/replay

### Ongoing Maintenance

**Good news:** Command Pattern has **less** maintenance burden than current hybrid approach.

- ✅ **Adding new actions:** Just add new Command class (isolated)
- ✅ **Testing:** Pure functions, no mocking needed
- ✅ **Debugging:** Time travel makes bugs easy to find
- ✅ **Extending:** Commands are independent, easy to add features

### Performance Impact

For this game:
- **Turn-based** - performance irrelevant
- **3 agents** - tiny scale
- **LLM bottleneck** - waiting seconds for LLM response makes copying state negligible

**Verdict:** Zero noticeable performance impact.

---

## Benefits After Refactor

### Immediate Benefits

#### 1. **No More Circular Dependencies**
```python
# Before: Circular
AgentBody → GameEngine → AgentBody

# After: One-way
Command → GameState (pure data)
```

#### 2. **Clean Testing**
```python
# Before: Need to mock everything
def test_eating():
    world = World()
    engine = GameEngine()
    agent = BerriesAgent(...)
    # Setup hell

# After: Pure functions
def test_eating():
    state = GameState(agents=(...), bush_berries=40)
    cmd = EatBerriesCommand(agent_id=0, count=5)
    new_state, msg = cmd.execute(state)
    assert new_state.agents[0].hunger == 15
```

#### 3. **Separation of Concerns**
```python
# Before: Mixed
class BerriesAgent(BaseAgent, AgentBody):  # LLM + State

# After: Separated  
class BerriesAgent(BaseAgent):  # LLM decision-maker (stateless)
class CharacterPhysicalState:  # Game state (data)
```

#### 4. **Domain Clarity**
```python
# All hunger logic in one place
class HungerRules:
    @staticmethod
    def consume_berries(hunger: float, berries: int) -> float:
        return min(24, hunger + berries)

# All bush logic in one place
class BushRules:
    @staticmethod
    def harvest(berries: float, count: int) -> Tuple[float, int]:
        actual = min(count, int(berries))
        return (berries - actual, actual)
```

### Research Benefits

#### 1. **A/B Testing**
```python
# Compare GPT-4 vs Claude at same decision point
state = engine.get_state(turn=15)

result_gpt = simulate_with_llm(state, agent_id=0, llm=GPT4)
result_claude = simulate_with_llm(state, agent_id=0, llm=CLAUDE)

analyze_differences(result_gpt, result_claude)
```

#### 2. **Counterfactual Analysis**
```python
# "What if Alice had eaten instead of talking?"
state = engine.get_state(turn=10)

# Original action
original = engine.history[10]  # SpeakCommand

# Counterfactual
alternative_engine = GameEngine(state)
alternative_engine.execute_command(EatBerriesCommand(0, 5))
alternative_engine.play_until_end()

compare_outcomes(engine, alternative_engine)
```

#### 3. **Prompt Engineering**
```python
# Test different prompts from same state
for prompt in prompt_variations:
    test_engine = engine.branch_from(turn=0)
    test_engine.agents[0].system_prompt = prompt
    results[prompt] = test_engine.play_until_end()
```

### Future Capabilities

#### 1. **Interactive Debugging**
```python
# Cursor through history
debugger = GameDebugger(engine)
debugger.goto_turn(15)
debugger.show_state()  # Inspect any past state
debugger.step_forward()
debugger.try_alternative_action(EatBerriesCommand(...))
```

#### 2. **Network Demo**
```python
# Server
@app.post("/execute")
def execute_command(cmd: CommandJSON):
    command = Command.from_json(cmd)
    new_state, result = command.execute(server.state)
    server.state = new_state
    return {"result": result, "state": new_state.to_json()}

# Client (with user's LLM)
my_llm = AnthropicLLM(api_key=user_api_key)
action = my_llm.decide(state)
response = requests.post("/execute", json=action.to_json())
```

#### 3. **Replay Visualization**
```python
# Generate HTML replay
replayer = GameReplayer(engine.history)
html = replayer.generate_interactive_replay()
# Users can scrub through game timeline
```

---

## Refactoring Plan by Module

### Phase 1: Core State (Immutable Foundation)

#### `objects/game_state.py` (NEW)
```python
@dataclass(frozen=True)
class GameState:
    """Immutable snapshot of entire game."""
    agents: Tuple[CharacterPhysicalState, ...]
    agent_memories: Tuple[ConversationMemory, ...]
    bush_berries: float
    message_queue: Tuple[NeighborMessage, ...]
    game_time: float
    turn_number: int
    
    # Helper methods for creating modified copies
    def with_agent_hunger(self, agent_id: int, hunger: float) -> "GameState":
        """Returns NEW state with updated agent hunger."""
        ...
    
    def with_bush_berries(self, berries: float) -> "GameState":
        """Returns NEW state with updated bush."""
        ...
    
    def with_message_added(self, msg: NeighborMessage) -> "GameState":
        """Returns NEW state with message added to queue."""
        ...
```

**Changes:**
- New file
- Frozen dataclass (immutable)
- All tuples instead of lists
- Helper methods for updates

**Status:** ✅ Ready to implement

---

#### `objects/agent_body.py` → `objects/agent_state.py` (REFACTOR)

**Before:**
```python
class AgentBody(BaseModel, AgentTools):
    """State + behavior + tools."""
    hunger: float
    _game_engine: GameEngine  # Circular dependency!
    
    def eat_berries(self, count: int) -> str:
        self.hunger += count  # Mutation!
```

**After:**
```python
@dataclass(frozen=True)
class CharacterPhysicalState:
    """Pure physical state (immutable)."""
    agent_id: int
    name: str
    hunger: float
    perceived_type: BodyType
    body_state: BodyState
    alive: bool
    total_berries_consumed: int
    
    # Query methods only (no mutations)
    def is_starving(self) -> bool:
        return self.hunger < 8
    
    def get_hunger_status(self) -> HungerStatus:
        return HungerStatus.from_hunger(self.hunger)
    
    def can_eat_berries(self, count: int) -> bool:
        return self.alive and count > 0

class CharacterRules:
    """Static methods for agent logic."""
    
    @staticmethod
    def calculate_hunger_gain(berries: int) -> float:
        return berries * HUNGER_PER_BERRY
    
    @staticmethod
    def calculate_time_until_death(hunger: float) -> float:
        return hunger / HUNGER_PER_HOUR
```

**Changes:**
- Rename file to `agent_state.py`
- Remove `AgentTools` inheritance
- Remove `_game_engine` dependency
- Make immutable
- Extract logic to `CharacterRules` class
- Keep only query methods

**Migration:**
1. Create `CharacterPhysicalState` dataclass
2. Create `CharacterRules` static class
3. Move all mutation logic to `CharacterRules`
4. Update `GameEngine` to use new classes
5. Delete old `AgentBody` class

**Status:** ⏳ Ready to implement after GameState

---

#### `objects/bush.py` (REFACTOR)

**Before:**
```python
class Bush(BaseModel):
    current_berries: float
    
    def harvest(self, count: int) -> int:
        self.current_berries -= count  # Mutation!
        return count
```

**After:**
```python
@dataclass(frozen=True)
class BushState:
    """Pure bush state (immutable)."""
    current_berries: float
    max_berries: int = 40
    regeneration_rate: float = 1.05
    
    # Query only
    def has_berries(self, count: int) -> bool:
        return self.current_berries >= count

class BushRules:
    """Static methods for bush logic."""
    
    @staticmethod
    def harvest(berries: float, count: int) -> Tuple[float, int]:
        """Returns (new_berries, actual_harvested)."""
        actual = min(count, int(berries))
        return (berries - actual, actual)
    
    @staticmethod
    def regenerate(berries: float, hours: float, rate: float, max_berries: int) -> float:
        """Returns new berry count after regeneration."""
        return min(max_berries, berries + hours * rate)
```

**Changes:**
- Make immutable dataclass
- Extract logic to `BushRules`
- Methods return new values instead of mutating

**Migration:**
1. Create `BushState` dataclass
2. Create `BushRules` static class  
3. Update all `bush.harvest()` calls to `BushRules.harvest(bush.berries, count)`
4. Update `GameState` to use `BushState`

**Status:** ⏳ Ready to implement after GameState

---

#### `objects/observations.py` (MINOR CHANGES)

**Changes needed:**
- Update to work with `CharacterPhysicalState` instead of `AgentBody`
- Observations are already immutable-ish (created per turn)
- Minimal changes needed

**Status:** ⏳ Update after agent_state refactor

---

### Phase 2: Commands (Action System)

#### `core/commands.py` (NEW)

```python
from pydantic import BaseModel, Field
from typing import Optional
from abc import ABC, abstractmethod

class Command(BaseModel, ABC):
    """Base class for all game commands (immutable)."""
    model_config = {"frozen": True}
    
    # Metadata (set by engine)
    sequence_number: int = Field(description="Global command index in history")
    agent_id: int = Field(description="Agent executing this command")
    timestamp: float = Field(description="Game time when command issued")
    
    @abstractmethod
    def execute(self, state: GameState) -> GameState:
        """Execute command, return new state."""
        pass
    
    def can_execute(self, state: GameState) -> bool:
        """Check if command is valid (optional validation)."""
        return True

class EatBerriesCommand(Command):
    """Agent eats berries from bush."""
    count: int = Field(ge=1, le=10, description="Berries to eat")
    
    def execute(self, state: GameState) -> GameState:
        # Validate
        if state.bush_berries < self.count:
            # Return unchanged state (failed action)
            return state
        
        agent = state.agents[self.agent_id]
        if not agent.alive:
            return state
        
        # Calculate changes
        new_berries = state.bush_berries - self.count
        new_hunger = min(24.0, agent.hunger + self.count * HUNGER_PER_BERRY)
        consumed = agent.total_berries_consumed + self.count
        
        # Apply changes immutably
        state = state.with_bush_berries(new_berries)
        state = state.with_agent(
            self.agent_id,
            hunger=new_hunger,
            total_berries_consumed=consumed
        )
        
        return state

class SpeakCommand(Command):
    """Agent speaks to neighbors."""
    left_msg: Optional[str] = None
    right_msg: Optional[str] = None
    
    def execute(self, state: GameState) -> GameState:
        # Add messages to queue
        if self.left_msg:
            left_id = (self.agent_id - 1) % 3
            msg = NeighborMessage(
                from_agent_id=self.agent_id,
                to_agent_id=left_id,
                content=self.left_msg,
                sender_type=state.agents[self.agent_id].perceived_type,
                game_time_sent=self.timestamp
            )
            state = state.with_message_added(msg)
        
        if self.right_msg:
            right_id = (self.agent_id + 1) % 3
            msg = NeighborMessage(
                from_agent_id=self.agent_id,
                to_agent_id=right_id,
                content=self.right_msg,
                sender_type=state.agents[self.agent_id].perceived_type,
                game_time_sent=self.timestamp
            )
            state = state.with_message_added(msg)
        
        return state

class SleepCommand(Command):
    """Agent sleeps for duration."""
    hours: int = Field(ge=1, le=8, description="Sleep duration")
    
    def execute(self, state: GameState) -> GameState:
        wake_time = state.game_time + self.hours
        return state.with_agent(
            self.agent_id,
            body_state=BodyState.ASLEEP,
            wake_time=wake_time
        )

class EndTurnCommand(Command):
    """Marker: agent's turn ends."""
    turn_number: int = Field(description="Turn that just ended")
    
    def execute(self, state: GameState) -> GameState:
        # Just increment turn counter
        return state.model_copy(update={"turn_number": state.turn_number + 1})

class AdvanceTimeCommand(Command):
    """Meta-command: advance game clock."""
    hours: float = Field(ge=0.0, description="Hours to advance")
    
    def execute(self, state: GameState) -> GameState:
        # Regenerate bush
        new_berries = min(
            40.0,
            state.bush_berries + self.hours * BUSH_REGENERATION_RATE
        )
        state = state.with_bush_berries(new_berries)
        
        # Update all agents
        for i, agent in enumerate(state.agents):
            if agent.alive:
                new_hunger = agent.hunger - self.hours * HUNGER_PER_HOUR
                if new_hunger <= 0:
                    # Agent dies
                    state = state.with_agent(i, hunger=0.0, alive=False)
                else:
                    state = state.with_agent(i, hunger=new_hunger)
        
        # Advance clock
        state = state.model_copy(update={"game_time": state.game_time + self.hours})
        
        return state
```

**Key Points:**
- Commands are **immutable Pydantic models**
- Commands are **deterministic** (no LLM calls in execute)
- `execute()` returns **new state** (never mutates)
- `EndTurnCommand` marks turn boundaries in flat history
- Commands store LLM decisions, not how to query LLM

**Status:** ⏳ Implement after Phase 1 complete

---

### Phase 3: Engine (Orchestration)

#### `core/game_engine.py` (MAJOR REFACTOR)

**Before:**
```python
class GameEngine(BaseModel):
    agents: List[AgentBody]  # Mutable
    bush: Bush  # Mutable
    
    def execute_eat_berries(self, agent_id: int, count: int):
        agent = self.agents[agent_id]
        harvested = self.bush.harvest(count)
        agent.eat_berries(harvested)
```

**After:**
```python
class GameEngine:
    """Command processor with flat history."""
    
    def __init__(self, initial_state: GameState):
        self.initial_state = initial_state  # Never changes!
        self.current_state = initial_state
        self.history: List[Command] = []  # Flat list of all commands
        
        # Current turn tracking
        self.current_turn_agent: Optional[int] = None
        self.turn_start_index: int = 0
    
    def start_turn(self, agent_id: int) -> None:
        """Begin a new turn."""
        self.current_turn_agent = agent_id
        self.turn_start_index = len(self.history)
    
    def execute_command(self, cmd: Command) -> str:
        """Execute command and add to flat history."""
        cmd = cmd.model_copy(update={"sequence_number": len(self.history)})
        new_state = cmd.execute(self.current_state)
        self.current_state = new_state
        self.history.append(cmd)
        return f"Executed {cmd.__class__.__name__}"
    
    def end_turn(self) -> None:
        """End current turn with marker command."""
        end_cmd = EndTurnCommand(
            sequence_number=len(self.history),
            agent_id=self.current_turn_agent,
            timestamp=self.current_state.game_time,
            turn_number=self.current_state.turn_number
        )
        self.execute_command(end_cmd)
        self.current_turn_agent = None
    
    def goto_turn(self, turn: int, action: Optional[int] = None) -> GameState:
        """
        Navigate to specific turn and optionally specific action.
        
        Args:
            turn: Turn number (0-indexed)
            action: Action index within turn (0-indexed), None = end of turn
        
        Returns:
            GameState at that point
        """
        boundaries = self.get_turn_boundaries()
        turn_start, turn_end = boundaries[turn]
        
        if action is None:
            cmd_index = turn_end  # After EndTurn
        else:
            cmd_index = turn_start + action
        
        return self.get_state_at_command(cmd_index)
    
    def branch_from(self, turn: int, action: Optional[int] = None) -> "GameEngine":
        """Create new engine branching from specific point."""
        boundaries = self.get_turn_boundaries()
        turn_start, turn_end = boundaries[turn]
        
        split_at = turn_end + 1 if action is None else turn_start + action + 1
        
        new_engine = GameEngine(self.initial_state)
        new_engine.history = self.history[:split_at].copy()
        new_engine.current_state = self.get_state_at_command(split_at - 1)
        return new_engine
    
    def get_turn_boundaries(self) -> List[Tuple[int, int]]:
        """Get (start_index, end_index) for each turn."""
        boundaries = []
        start = 0
        for i, cmd in enumerate(self.history):
            if isinstance(cmd, EndTurnCommand):
                boundaries.append((start, i))
                start = i + 1
        return boundaries
```

**Changes:**
- No longer inherits from `BaseModel`
- Flat command history (not nested)
- EndTurnCommand marks turn boundaries
- `goto_turn(n, k)` for mid-turn navigation
- `branch_from(turn, action)` for experimentation
- Stores initial state for replay

**Migration:**
1. Create new `GameEngine` class
2. Add `start_turn()` / `end_turn()` calls
3. Update all action methods to create commands
4. Update tests to use command pattern

**Status:** ⏳ Implement after Commands ready

---

### Phase 4: Agent Separation

#### `core/berries_agent.py` (MAJOR REFACTOR)

**Before:**
```python
class BerriesAgent(BaseAgent, AgentBody):
    """LLM + Physical state mixed."""
    hunger: float  # Physical state
    memory: List[Message]  # LLM state
    
    def eat_berries(self, count: int):
        # Direct mutation
        self.hunger += count
```

**After:**
```python
class BerriesAgent(BaseAgent):
    """Stateless LLM decision processor."""
    
    def __init__(self, agent_id: int, llm_config: LLMOptions):
        super().__init__(llm_options=llm_config)
        self.agent_id = agent_id
        # NO state stored here!
    
    def decide_action(
        self,
        memory: ConversationMemory,
        observation: AgentObservation
    ) -> Tuple[Command, ConversationMemory]:
        """
        Given memory + observation, decide action.
        Returns (command, updated_memory).
        """
        # Build prompt from observation
        prompt = self.build_prompt(observation)
        
        # Query LLM with memory
        response = self.query_with_memory(memory, prompt)
        
        # Parse response into command
        command = self.parse_command_from_response(response)
        
        # Return command + new memory
        new_memory = memory.with_message(
            Message(role="assistant", content=response)
        )
        
        return (command, new_memory)
    
    def build_prompt(self, obs: AgentObservation) -> str:
        """Build prompt from observation."""
        return f"""
        Your state: {obs.self_state.hunger}/24 hunger
        Left neighbor: {obs.left_neighbor.hunger_status}
        Right neighbor: {obs.right_neighbor.hunger_status}
        Bush: {obs.bush_berries}/40 berries
        
        What do you do?
        """
    
    def parse_command_from_response(self, response: str) -> Command:
        """Extract command from LLM response (tool call)."""
        # Parse tool call
        if tool_call.name == "eat_berries":
            return EatBerriesCommand(
                agent_id=self.agent_id,
                count=tool_call.args["count"]
            )
        elif tool_call.name == "speak":
            return SpeakCommand(
                agent_id=self.agent_id,
                left_msg=tool_call.args.get("say_to_left"),
                right_msg=tool_call.args.get("say_to_right"),
                wait_hours=tool_call.args["wait_for"]
            )
        # ...
```

**Changes:**
- Remove `AgentBody` inheritance
- Agent becomes stateless processor
- Memory passed in/out (not stored)
- Returns commands instead of mutating state
- Tools become command factories

**New supporting class:**
```python
@dataclass(frozen=True)
class ConversationMemory:
    """Immutable conversation history."""
    messages: Tuple[Message, ...]
    
    def with_message(self, msg: Message) -> "ConversationMemory":
        return ConversationMemory(
            messages=self.messages + (msg,)
        )
```

**Status:** ⏳ Implement after Engine refactor

---

### Phase 5: Main Loop

#### `main.py` (UPDATE)

**Before:**
```python
engine = GameEngine()
engine.initialize_agents(names)

while not game_over:
    agent_id = engine.get_next_agent()
    obs = engine.create_observation(agent_id)
    agent = agents[agent_id]
    agent.query_with_observation(obs)
    # Agent tools mutate state directly
```

**After:**
```python
# Initialize
initial_state = GameState(
    agents=tuple([CharacterPhysicalState(...) for _ in range(3)]),
    agent_memories=tuple([ConversationMemory(messages=()) for _ in range(3)]),
    bush_berries=40,
    message_queue=(),
    game_time=0.0,
    turn_number=0
)
engine = GameEngine(initial_state)

# LLM agents (stateless)
llm_agents = [
    BerriesAgent(agent_id=i, llm_config=llm_configs[i])
    for i in range(3)
]

# Game loop
while not game_over:
    state = engine.current_state
    agent_id = find_next_agent(state)
    
    # Get agent's memory from state
    memory = state.agent_memories[agent_id]
    
    # Create observation from current state
    obs = create_observation(state, agent_id)
    
    # Agent decides (pure function)
    command, new_memory = llm_agents[agent_id].decide_action(memory, obs)
    
    # Update state with new memory
    state = state.with_agent_memory(agent_id, new_memory)
    engine.current_state = state
    
    # Execute command
    result = engine.execute_command(command)
    
    print(f"Turn {state.turn_number}: Agent {agent_id} - {result}")
```

**Status:** ⏳ Update after all modules refactored

---

### Phase 6: Tests

#### `tests/` (UPDATE ALL)

**Changes needed:**
- Update imports
- Change mutable mutations to command executions
- Add new tests for branching/replay
- Simplify tests (no mocking needed!)

**New tests to add:**
```python
def test_state_branching():
    """Test creating variant timelines."""
    engine = create_test_engine()
    
    # Play 10 turns
    for _ in range(10):
        engine.execute_command(...)
    
    # Branch from turn 5
    variant = engine.branch_from_turn(5)
    
    # Play different actions
    variant.execute_command(different_command)
    
    # States should diverge
    assert engine.current_state != variant.current_state

def test_replay():
    """Test replaying game history."""
    engine = create_test_engine()
    
    # Play game
    for cmd in game_commands:
        engine.execute_command(cmd)
    
    final_state = engine.current_state
    
    # Replay
    engine.replay()
    
    # Should reach same state
    assert engine.current_state == final_state
```

**Status:** ⏳ Update throughout refactor

---

## Migration Checklist

### Phase 1: Foundation
- [ ] Create `objects/game_state.py`
- [ ] Refactor `objects/agent_body.py` → `objects/agent_state.py`
- [ ] Refactor `objects/bush.py` with `BushRules`
- [ ] Update `objects/observations.py`
- [ ] Run existing tests (should fail correctly)

### Phase 2: Commands
- [ ] Create `core/commands.py` base classes
- [ ] Implement `EatBerriesCommand`
- [ ] Implement `SpeakCommand`
- [ ] Implement `SleepCommand`
- [ ] Implement `AdvanceTimeCommand`
- [ ] Add command serialization (JSON)
- [ ] Unit test each command independently

### Phase 3: Engine
- [ ] Refactor `core/game_engine.py`
- [ ] Replace mutations with command execution
- [ ] Add history tracking
- [ ] Implement `branch_from_turn()`
- [ ] Implement `undo()`
- [ ] Implement `replay()`
- [ ] Test engine with commands

### Phase 4: Agents
- [ ] Create `ConversationMemory` dataclass
- [ ] Refactor `core/berries_agent.py`
- [ ] Remove state from agent
- [ ] Make `decide_action()` pure
- [ ] Update tool handling
- [ ] Test agent decision-making

### Phase 5: Integration
- [ ] Update `main.py` game loop
- [ ] Test end-to-end game
- [ ] Verify LLM agents work
- [ ] Test state branching
- [ ] Test replay functionality

### Phase 6: Cleanup
- [ ] Update all tests
- [ ] Remove old code
- [ ] Remove `core/world.py` singleton (if not needed)
- [ ] Update documentation
- [ ] Add examples of branching/replay

---

## Success Criteria

The refactor is complete when:

✅ No circular dependencies  
✅ State is immutable  
✅ Commands are replayable  
✅ Can branch from any turn  
✅ Can swap LLMs mid-game  
✅ Tests don't need mocking  
✅ Clear domain separation  
✅ All existing tests pass  
✅ New branching tests pass  

---

## Risk Mitigation

### Risk: Boilerplate Explosion
**Mitigation:** Use helper utilities
```python
class StateUpdater:
    """Helper class for complex state updates."""
    @staticmethod
    def update_agent_field(state, agent_id, field, value):
        # Reduces boilerplate
        ...
```

### Risk: Performance Regression
**Mitigation:** 
- Profile before/after
- For this game, LLM is bottleneck (seconds)
- State copying is microseconds
- No real risk

### Risk: Breaking Existing Code
**Mitigation:**
- Keep old code until new code works
- Migrate module-by-module
- Run tests after each phase
- Can always roll back

### Risk: Learning Curve
**Mitigation:**
- This document as reference
- Pair programming with AI
- Small, focused changes
- Test each piece independently

---

## Timeline Estimate

**Conservative estimate:** 10-12 hours total

- Phase 1 (Foundation): 2-3 hours
- Phase 2 (Commands): 2-3 hours  
- Phase 3 (Engine): 2-3 hours
- Phase 4 (Agents): 2 hours
- Phase 5 (Integration): 1 hour
- Phase 6 (Cleanup): 1 hour

**Optimistic estimate:** 6-8 hours

Can be done over 2-3 coding sessions.

---

## Post-Refactor Capabilities

Once complete, you'll be able to:

```python
# 1. Compare LLM strategies
gpt_outcome = test_llm_from_state(state, GPT4)
claude_outcome = test_llm_from_state(state, CLAUDE)

# 2. Find interesting moments
for turn in range(100):
    state = engine.get_state_at_turn(turn)
    if is_interesting(state):
        save_for_analysis(turn, state)

# 3. Test counterfactuals
if alice_had_eaten_at_turn_10 = test_alternative(
    engine,
    turn=10,
    agent_id=0,
    action=EatBerriesCommand(0, 5)
)

# 4. Build interactive demos
replayer = InteractiveReplayer(engine.history)
replayer.show_in_browser()  # Scrub timeline, inspect states

# 5. Academic reproducibility
paper_game_1_history = engine.history
save_json("paper_game_1.json", [cmd.to_json() for cmd in history])
# Anyone can replay exact game
```

---

## Summary of Final Decisions

### Technology Stack
- ✅ **Pydantic v2** with `frozen=True` for state models
- ✅ **Tuple-only** collections (no Lists/Dicts in state)
- ✅ **Built-in dataclasses** `model_copy(update={...})` for updates
- ✅ **Validator** to catch mutable collections at runtime
- ❌ **NOT** using pyrsistent (PVector/PMap) - unnecessary dependency
- ❌ **NOT** using vanilla dataclasses - need Pydantic validation

### Architecture
- ✅ **Flat command history** (not nested turns)
- ✅ **EndTurnCommand** marks turn boundaries
- ✅ **Navigation:** `goto_turn(n, k)` for turn n, action k
- ✅ **Branching:** `branch_from(turn, action)` for experiments
- ✅ **Commands store decisions**, not queries (deterministic replay)
- ❌ **NOT** wrapping commands in Turn objects

### Memory Model
- **Structural sharing:** Tuples share unchanged data (not full copies)
- **Command history:** ~150 bytes/command × 100 = 15KB
- **Initial state:** 32KB
- **Total for 100 turns:** ~47KB (not 3.2MB!)
- **Performance impact:** Zero (LLM is 1,000,000× slower bottleneck)

### Safety
- Pydantic validation catches type errors
- `frozen=True` prevents accidental assignment
- Immutability validator catches mutable collections
- Type hints + mypy for compile-time safety
- Acceptable risk: Small game, bugs caught quickly

### Git Analogy
- **Commits** = individual commands
- **Tags** = EndTurnCommand (marks releases)
- **Checkout tag** = `goto_turn(n)`
- **Checkout specific commit** = `goto_turn(n, k)`
- **Branch** = `branch_from(turn, action)`

## Conclusion

This refactor moves from **hybrid OOP** to **Command Pattern**, trading modest memory overhead for enormous gains in:
- Code clarity
- Testability  
- Debugging capability (time travel!)
- Research flexibility (A/B test LLMs)
- Future extensibility (networking ready)

The architecture choice is driven by the **experimental nature** of the project, not performance needs. For a prisoner's dilemma research platform, being able to branch timelines and compare LLM behaviors is worth far more than the 47KB of RAM it costs.

**Key insight:** Commands store what the LLM decided, not how to ask the LLM again. Replay is deterministic because we replay decisions, not decision-making.

**Next step:** Start with Phase 1 when ready!

