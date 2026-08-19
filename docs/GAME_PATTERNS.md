# Game Architecture Patterns

A comprehensive guide to common game architecture patterns, with examples, comparisons, and practical advice.

---

## Overview: Patterns in Industry

Game architecture has evolved significantly over the decades. While there's no single "correct" pattern, different approaches suit different game types. Here are the three most common patterns in modern game development:

### Pattern 1: Service Layer (MVC-style)
**Used by:** XCOM 2, Civilization series, Slay the Spire, most turn-based strategy games  
**Philosophy:** Separate data from logic using stateless services  
**Style:** Functional programming with mutable data

### Pattern 2: Command Pattern
**Used by:** Hearthstone, Magic: The Gathering Arena, chess engines, card games  
**Philosophy:** Actions are first-class objects, state is immutable  
**Style:** Functional programming with immutable data

### Pattern 3: Entity-Manager (Traditional OOP)
**Used by:** Baldur's Gate 3, Divinity: Original Sin, most RPGs  
**Philosophy:** Entities own their behavior, managers coordinate  
**Style:** Object-oriented programming

### ECS (Entity-Component-System)
**Used by:** Unity DOTS, Unreal Mass Entity, Bevy, large-scale simulations  
**Philosophy:** Pure data-oriented design, cache-friendly  
**Style:** Data-oriented programming  
**Note:** Primarily for performance-critical games (1000+ entities, real-time)

---

## Detailed Examples

All examples implement the same scenario: **"Agent wants to eat 5 berries from a bush"**

### Pattern 1: Service Layer

```python
# ===== DATA MODELS (just state) =====
class AgentData(BaseModel):
    agent_id: int
    name: str
    hunger: float
    alive: bool = True

class Bush(BaseModel):
    current_berries: float
    max_berries: int = 40

# ===== SERVICES (stateless logic) =====
class BushService:
    """Stateless utility functions for bush operations."""
    
    @staticmethod
    def can_harvest(bush: Bush, count: int) -> bool:
        return bush.current_berries >= count
    
    @staticmethod
    def harvest(bush: Bush, count: int) -> int:
        """Mutates bush, returns actual harvested."""
        actual = min(count, int(bush.current_berries))
        bush.current_berries -= actual  # MUTATES IN PLACE
        return actual

class HungerService:
    """Stateless utility functions for hunger operations."""
    
    @staticmethod
    def feed(agent: AgentData, berries: int) -> float:
        """Mutates agent, returns hunger gained."""
        old = agent.hunger
        agent.hunger = min(24, agent.hunger + berries)  # MUTATES IN PLACE
        return agent.hunger - old

# ===== CONTROLLER (orchestration) =====
class GameController:
    def __init__(self):
        self.agents: List[AgentData] = []
        self.bush: Bush = Bush(current_berries=40)
    
    def execute_eat(self, agent_id: int, count: int) -> str:
        agent = self.agents[agent_id]
        
        # Coordinate services
        if not BushService.can_harvest(self.bush, count):
            return "Not enough berries"
        
        harvested = BushService.harvest(self.bush, count)
        gained = HungerService.feed(agent, harvested)
        
        return f"Ate {harvested}, gained {gained} hunger"

# ===== USAGE =====
controller = GameController()
controller.agents.append(AgentData(agent_id=0, name="Alice", hunger=10))
result = controller.execute_eat(agent_id=0, count=5)
# State is mutated in place
```

**Key characteristics:**
- Services are pure functions (no state)
- Data is mutable
- Controller owns all game state
- One-way flow: Controller → Service → Data

---

### Pattern 2: Command Pattern

```python
# ===== IMMUTABLE STATE =====
@dataclass(frozen=True)  # IMMUTABLE!
class GameState:
    agents: Tuple[AgentData, ...]  # Tuples, not lists
    bush_berries: float
    turn_number: int
    
    def with_agent_hunger(self, agent_id: int, new_hunger: float) -> "GameState":
        """Create NEW state with updated agent hunger."""
        new_agents = list(self.agents)
        old_agent = new_agents[agent_id]
        new_agents[agent_id] = AgentData(
            agent_id=old_agent.agent_id,
            name=old_agent.name,
            hunger=new_hunger,
            alive=old_agent.alive
        )
        return GameState(
            agents=tuple(new_agents),
            bush_berries=self.bush_berries,
            turn_number=self.turn_number
        )
    
    def with_bush_berries(self, new_berries: float) -> "GameState":
        """Create NEW state with updated bush."""
        return GameState(
            agents=self.agents,
            bush_berries=new_berries,
            turn_number=self.turn_number
        )

# ===== COMMANDS (first-class actions) =====
class Command(ABC):
    @abstractmethod
    def execute(self, state: GameState) -> Tuple[GameState, str]:
        """Returns (new_state, result_message)."""
        pass
    
    @abstractmethod
    def can_execute(self, state: GameState) -> bool:
        """Check if command is valid."""
        pass

class EatBerriesCommand(Command):
    """A command is a DATA OBJECT representing an action."""
    
    def __init__(self, agent_id: int, count: int):
        self.agent_id = agent_id
        self.count = count
        self.timestamp = time.time()  # For replay
    
    def can_execute(self, state: GameState) -> bool:
        return state.bush_berries >= self.count
    
    def execute(self, state: GameState) -> Tuple[GameState, str]:
        """Creates entirely NEW state."""
        if not self.can_execute(state):
            return (state, "Not enough berries")  # No change
        
        agent = state.agents[self.agent_id]
        
        # Create new state step by step (immutable!)
        state = state.with_bush_berries(state.bush_berries - self.count)
        new_hunger = min(24, agent.hunger + self.count)
        state = state.with_agent_hunger(self.agent_id, new_hunger)
        
        return (state, f"Ate {self.count} berries")

# ===== ENGINE (command processor) =====
class GameEngine:
    def __init__(self, initial_state: GameState):
        self.current_state = initial_state
        self.history: List[Command] = []  # For undo/replay!
        self.initial_state = initial_state
    
    def execute_command(self, cmd: Command) -> str:
        new_state, message = cmd.execute(self.current_state)
        self.current_state = new_state  # Replace entire state
        self.history.append(cmd)
        return message
    
    def undo(self):
        """Replay all commands except last."""
        if not self.history:
            return
        
        self.history.pop()
        # Rebuild state from scratch
        self.current_state = self.initial_state
        for cmd in self.history:
            self.current_state, _ = cmd.execute(self.current_state)
    
    def replay(self):
        """Replay entire game from history."""
        self.current_state = self.initial_state
        for cmd in self.history:
            self.current_state, msg = cmd.execute(self.current_state)
            print(f"Turn {cmd.timestamp}: {msg}")
    
    def branch_from(self, turn: int) -> "GameEngine":
        """Create new engine from historical point."""
        commands = self.history[:turn]
        new_engine = GameEngine(self.initial_state)
        for cmd in commands:
            new_engine.execute_command(cmd)
        return new_engine

# ===== USAGE =====
initial = GameState(
    agents=(AgentData(agent_id=0, name="Alice", hunger=10),),
    bush_berries=40,
    turn_number=0
)
engine = GameEngine(initial)

# Commands are objects you can store/send/replay
cmd = EatBerriesCommand(agent_id=0, count=5)
result = engine.execute_command(cmd)

# Can undo!
engine.undo()

# Can replay entire game!
engine.replay()

# Can branch from any point!
variant_engine = engine.branch_from(turn=10)
```

**Key characteristics:**
- State is immutable (functional style)
- Actions are objects (can be serialized)
- Automatic undo/redo via replay
- Time travel debugging possible
- Easy networking (send commands as JSON)

---

### Pattern 3: Entity-Manager

```python
# ===== ENTITIES (state + behavior) =====
class Agent:
    """Entity with its own behavior."""
    
    def __init__(self, agent_id: int, name: str):
        self.agent_id = agent_id
        self.name = name
        self.hunger = 10.0
        self.alive = True
    
    def is_hungry(self) -> bool:
        """Entities can answer questions about themselves."""
        return self.hunger < 12
    
    def eat(self, berries: int) -> float:
        """Entities can modify their own state."""
        old = self.hunger
        self.hunger = min(24, self.hunger + berries)
        gained = self.hunger - old
        print(f"{self.name} ate {berries} berries, gained {gained} hunger")
        return gained
    
    def can_survive_hours(self, hours: float) -> bool:
        """Domain logic inside entity."""
        return self.hunger >= hours

class Bush:
    """Entity with its own behavior."""
    
    def __init__(self):
        self.current_berries = 40
        self.max_berries = 40
    
    def has_berries(self, count: int) -> bool:
        """Bush answers questions."""
        return self.current_berries >= count
    
    def harvest(self, count: int) -> Optional[int]:
        """Bush manages its own harvesting."""
        if not self.has_berries(count):
            print("Not enough berries!")
            return None
        
        actual = min(count, int(self.current_berries))
        self.current_berries -= actual
        print(f"Harvested {actual} berries, {self.current_berries} remain")
        return actual
    
    def regenerate(self, hours: float):
        """Bush regenerates itself."""
        old = self.current_berries
        self.current_berries = min(self.max_berries, self.current_berries + hours * 1.8)
        print(f"Bush regenerated {self.current_berries - old} berries")

# ===== MANAGERS (coordinate entities) =====
class ResourceManager:
    """Coordinates resource transactions between entities."""
    
    def __init__(self, bush: Bush):
        self.bush = bush
    
    def transfer_berries_to_agent(self, agent: Agent, count: int) -> bool:
        """Coordinate bush → agent transaction."""
        harvested = self.bush.harvest(count)
        if harvested is None:
            return False
        
        agent.eat(harvested)
        return True

class GameManager:
    """Top-level coordinator."""
    
    def __init__(self):
        self.agents: Dict[int, Agent] = {}
        self.bush = Bush()
        self.resource_manager = ResourceManager(self.bush)
        self.time = 0.0
    
    def get_agent(self, agent_id: int) -> Agent:
        return self.agents[agent_id]
    
    def execute_eat_action(self, agent_id: int, count: int) -> str:
        """High-level action coordinating multiple managers."""
        agent = self.get_agent(agent_id)
        
        if not agent.alive:
            return f"{agent.name} is dead"
        
        success = self.resource_manager.transfer_berries_to_agent(agent, count)
        
        if success:
            return f"{agent.name} successfully ate berries"
        else:
            return "Failed to eat berries"
    
    def advance_time(self, hours: float):
        """Coordinate time passage across all entities."""
        self.bush.regenerate(hours)
        
        for agent in self.agents.values():
            if agent.alive:
                agent.hunger -= hours
                if agent.hunger <= 0:
                    agent.alive = False
                    print(f"{agent.name} died!")
        
        self.time += hours

# ===== USAGE =====
game = GameManager()
game.agents[0] = Agent(agent_id=0, name="Alice")
game.agents[1] = Agent(agent_id=1, name="Bob")

# Entities interact through managers
result = game.execute_eat_action(agent_id=0, count=5)

# Entities can also interact directly (more flexible but riskier)
alice = game.agents[0]
if alice.is_hungry() and game.bush.has_berries(3):
    berries = game.bush.harvest(3)
    alice.eat(berries)
```

**Key characteristics:**
- Entities are smart objects (state + behavior)
- Entities can validate themselves
- Managers coordinate interactions
- Traditional OOP style
- Flexible but potentially chaotic

---

## Comparison Table

| Aspect | Service Layer | Command Pattern | Entity-Manager |
|--------|--------------|-----------------|----------------|
| **State Mutability** | Mutable data classes | Immutable snapshots | Mutable objects |
| **Logic Location** | Static services | Command objects | Inside entities |
| **Data & Logic** | Separated | Separated | Together |
| **Undo/Redo** | ❌ Manual | ✅ Built-in | ❌ Manual |
| **Time Travel Debug** | ❌ No | ✅ Yes | ❌ No |
| **State Branching** | ❌ Manual | ✅ Easy | ❌ Difficult |
| **Networking** | ⚠️ Manual | ✅ Easy (send commands) | ⚠️ Manual |
| **Serialization** | ✅ Easy | ✅ Easy | ⚠️ Requires work |
| **Testing** | ✅ Easy (pure functions) | ✅ Easy (pure) | ⚠️ Harder (mocking) |
| **Boilerplate** | Low | High | Medium |
| **Memory Usage** | Low | Higher (copies) | Low |
| **Performance** | Fast | Slower (copying) | Fast |
| **OOP Style** | No (functional) | No (functional) | Yes (classic OOP) |
| **Learning Curve** | Low | Medium | Low |
| **Flexibility** | Medium | Low (rigid) | High (maybe too high) |
| **Best For** | Simple games | Multiplayer/Replays | Complex domains |

---

## Pros & Cons of Each Pattern

### Service Layer

#### Pros
- ✅ **Simple to understand** - clear separation of concerns
- ✅ **Easy to test** - services are pure functions
- ✅ **Low boilerplate** - minimal code overhead
- ✅ **Fast execution** - in-place mutation, no copying
- ✅ **Memory efficient** - single copy of state
- ✅ **Easy refactoring** - move logic between services easily
- ✅ **Clear ownership** - controller owns all state

#### Cons
- ❌ **No built-in undo** - must implement manually
- ❌ **No state history** - can't replay or branch
- ❌ **Harder networking** - must serialize state manually
- ❌ **Mutation bugs** - accidental state changes hard to track
- ❌ **No time travel debugging** - can't inspect past states

#### Best For
- Turn-based strategy games
- Single-player games
- Simple game rules
- Performance-critical sections
- First-time game developers

---

### Command Pattern

#### Pros
- ✅ **Free undo/redo** - replay command history
- ✅ **Time travel debugging** - inspect any past state
- ✅ **Easy state branching** - create variant timelines
- ✅ **Trivial networking** - commands are just data
- ✅ **Perfect replay system** - store and playback entire games
- ✅ **Easy testing** - commands are pure functions
- ✅ **Clear audit trail** - every action is recorded
- ✅ **Deterministic** - same commands = same result

#### Cons
- ❌ **High boilerplate** - need `with_*` methods for every field
- ❌ **Memory overhead** - copies state frequently
- ❌ **Slower performance** - constant copying vs mutation
- ❌ **Steeper learning curve** - immutability is harder
- ❌ **Verbose** - more code to maintain
- ❌ **Can be overkill** - for simple games without replay needs

#### Best For
- Multiplayer games (especially turn-based)
- Card games
- Chess/board game engines
- Games needing replay systems
- Experimental/research games (like LLM experiments)
- Debugging complex game logic

---

### Entity-Manager

#### Pros
- ✅ **Intuitive OOP** - familiar to most developers
- ✅ **Flexible** - entities can interact freely
- ✅ **Rich domain models** - entities contain domain logic
- ✅ **Easy to prototype** - quick to add new behavior
- ✅ **Natural for complex domains** - models real-world relationships
- ✅ **Less code** - behavior lives with data

#### Cons
- ❌ **Reference spaghetti** - entities can call entities
- ❌ **Circular dependencies** - easy to create
- ❌ **Harder to test** - need to mock dependencies
- ❌ **Hidden coupling** - entity changes affect others
- ❌ **Difficult debugging** - state changes scattered
- ❌ **No clear boundaries** - logic can leak everywhere
- ❌ **Harder serialization** - objects have references

#### Best For
- Complex RPGs with many interacting systems
- Story-driven games
- Games with rich NPC behavior
- Large teams (can split by entity type)
- When domain complexity > architectural complexity

---

## Common Pitfalls for Each Pattern

### Service Layer Pitfalls

#### 1. Services Become God Classes
```python
# BAD: One service doing everything
class GameService:
    @staticmethod
    def do_everything(game_state, action):
        # 500 lines of mixed logic
        pass

# GOOD: Small, focused services
class HungerService: ...
class BushService: ...
class CombatService: ...
```

#### 2. Controller Becomes Too Big
```python
# BAD: Controller has all game logic
class GameController:
    def execute_eat(self, ...):
        # 100 lines of eating logic here
        pass

# GOOD: Controller delegates to services
class GameController:
    def execute_eat(self, agent_id, count):
        harvested = BushService.harvest(self.bush, count)
        HungerService.feed(self.agents[agent_id], harvested)
```

#### 3. Hidden State Mutations
```python
# BAD: Service mutates unexpected things
class BushService:
    @staticmethod
    def harvest(bush, agent):  # Takes agent!
        bush.berries -= 5
        agent.hunger += 5  # Hidden side effect!

# GOOD: Explicit mutations
class BushService:
    @staticmethod
    def harvest(bush, count) -> int:
        bush.berries -= count
        return count  # Caller decides what to do
```

---

### Command Pattern Pitfalls

#### 1. Forgetting Immutability
```python
# BAD: Command mutates state
class EatCommand(Command):
    def execute(self, state):
        state.agents[0].hunger += 5  # MUTATION!
        return state

# GOOD: Command creates new state
class EatCommand(Command):
    def execute(self, state):
        return state.with_agent_hunger(0, state.agents[0].hunger + 5)
```

#### 2. Overly Complex State Updates
```python
# BAD: Nested immutable updates are painful
state = state.with_agent(
    agent_id,
    state.agents[agent_id].with_inventory(
        state.agents[agent_id].inventory.with_item(
            item_id,
            state.agents[agent_id].inventory.items[item_id].with_count(5)
        )
    )
)

# GOOD: Use helper methods or lenses
state = StateUpdater.update_item_count(state, agent_id, item_id, 5)
```

#### 3. Commands Become Too Granular
```python
# BAD: Too many tiny commands
HarvestBerryCommand(1)
UpdateHungerCommand(agent_id, +1)
LogEventCommand("ate berry")
CheckDeathCommand(agent_id)

# GOOD: Atomic game actions
EatBerriesCommand(agent_id, count=1)
# Internally handles all consequences
```

#### 4. Forgetting to Store Initial State
```python
# BAD: Can't replay without initial state
class GameEngine:
    def __init__(self, state):
        self.state = state  # Only current state

# GOOD: Store initial state for replay
class GameEngine:
    def __init__(self, state):
        self.initial_state = copy.deepcopy(state)
        self.current_state = state
```

---

### Entity-Manager Pitfalls

#### 1. Circular Dependencies
```python
# BAD: Entities reference each other
class Agent:
    def __init__(self, bush):
        self.bush = bush  # Agent → Bush
        bush.register_agent(self)  # Bush → Agent

# GOOD: Manager mediates
class GameManager:
    def __init__(self):
        self.agents = []
        self.bush = Bush()
    
    def agent_harvest(self, agent_id, count):
        agent = self.agents[agent_id]
        berries = self.bush.harvest(count)
        agent.eat(berries)
```

#### 2. Logic Leakage
```python
# BAD: Game logic in multiple entities
class Agent:
    def eat(self, berries):
        if berries > 5:  # Rule here
            self.special_bonus = True

class Bush:
    def harvest(self, count):
        if count > 5:  # Same rule duplicated!
            self.trigger_event()

# GOOD: Rules in one place (manager or service)
class GameRules:
    LARGE_MEAL_THRESHOLD = 5

class GameManager:
    def execute_eat(self, agent, count):
        if count > GameRules.LARGE_MEAL_THRESHOLD:
            self.trigger_large_meal_event(agent)
```

#### 3. God Objects
```python
# BAD: Entity does everything
class Agent:
    def eat(self): ...
    def fight(self): ...
    def trade(self): ...
    def build(self): ...
    def talk(self): ...
    # 500 more lines

# GOOD: Split by domain
class CharacterPhysicalState: ...
class AgentInventory: ...
class AgentCombat: ...
# Managers coordinate
```

---

## Poor Architecture Choice Flags

### 🚩 You Need Service Layer When...

You see these problems:
- Domain logic scattered across many entity methods
- Hard to find where a rule is implemented
- Testing requires mocking many objects
- Circular dependencies between entities

Signs you chose wrong pattern:
- Implementing manual undo in OOP (should use Command)
- Need networking but entities have complex references
- Performance issues from deep object graphs

---

### 🚩 You Need Command Pattern When...

You see these problems:
- Can't debug what happened 10 turns ago
- Need to A/B test different game variations
- Want to implement multiplayer
- Need replay system
- Branching timelines (research/experiments)

Signs you chose wrong pattern:
- Memory usage is critical (Command wastes memory)
- Game loop runs 60+ times per second (Command too slow)
- Simple single-player game (Command is overkill)

---

### 🚩 You Need Entity-Manager When...

You see these problems:
- Services become huge with tons of parameters
- Complex inter-entity relationships
- Rich domain model (many entity types)
- Entities have complex lifecycle

Signs you chose wrong pattern:
- Entities only have getters/setters (use Service Layer)
- Need undo/time travel (use Command)
- Debugging is nightmare (too much coupling)

---

## General Architecture Red Flags

### 🚨 Critical Warning Signs

1. **Circular imports** - usually means wrong ownership hierarchy
2. **God classes** - one class doing everything
3. **Shotgun surgery** - one feature change requires editing 10 files
4. **Mystery guests** - functions take 8+ parameters
5. **Hidden dependencies** - object needs global state to work
6. **Clone-and-modify** - copying code instead of abstracting
7. **Fragile base class** - changing parent breaks children

### ✅ Good Architecture Indicators

1. **Easy to test** - can test components in isolation
2. **Clear ownership** - obvious who owns what data
3. **One place for rules** - domain logic centralized
4. **Easy to extend** - adding features is straightforward
5. **Clear boundaries** - modules have well-defined interfaces
6. **Reversible decisions** - can swap patterns later
7. **Understandable** - new developer can follow the flow

---

## Decision Matrix

| Your Game Needs | Choose Pattern |
|-----------------|----------------|
| Simple turn-based, no replay | **Service Layer** |
| Multiplayer or networking | **Command Pattern** |
| Replay system | **Command Pattern** |
| Experimental/research (A/B testing) | **Command Pattern** |
| Complex entity interactions | **Entity-Manager** |
| Rich NPC behavior | **Entity-Manager** |
| Performance critical (1000+ entities) | **ECS** (not covered) |
| Real-time action game | **ECS** or **Service Layer** |
| First game project | **Service Layer** |

---

## Further Reading

- **Game Programming Patterns** by Robert Nystrom (free online)
- **Entity-Component-System** - Unity DOTS documentation
- **Command Pattern** - Gang of Four Design Patterns
- **Event Sourcing** - Martin Fowler's blog (advanced Command pattern)
- **Data-Oriented Design** - Mike Acton's talks

---

**Remember:** Architecture is about trade-offs, not absolutes. Choose based on your specific needs, not ideology. The best architecture is the one you understand and can maintain.

---

## Command Pattern FAQ

### Q: Should commands be atomic or represent game actions?

**A: Game actions (composite), not atomic operations.**

Commands should represent **meaningful player intentions**, not implementation details.

```python
# ❌ BAD: Too atomic (leaky abstraction)
HarvestBerriesCommand(count=5)  # Implementation detail
UpdateHungerCommand(agent_id, +5)  # Implementation detail
CheckDeathCommand(agent_id)  # Side effect

# ✅ GOOD: Game action (what player intends)
EatBerriesCommand(agent_id, count=5)
# Internally: harvest + consume + update hunger + check death
```

**Why?** Commands are your **API to game actions**. Players think "I want to eat," not "I want to harvest, then update hunger, then check death."

**Industry examples:**
- **Hearthstone:** `PlayCardCommand` (not `DrawCardCommand` + `RemoveManaCommand` + `TriggerEffectCommand`)
- **XCOM 2:** `MoveToLocationCommand` (not `DeductActionPointCommand` + `UpdatePositionCommand` + `TriggerOverwatchCommand`)
- **Chess engines:** `MovePieceCommand(from, to)` (not `RemovePieceCommand` + `PlacePieceCommand` + `UpdateCastlingRights`)

**When to split commands:**
- ✅ If actions can be taken independently (e.g., `EatCommand` vs `SpeakCommand`)
- ❌ Don't split if they're always done together (harvest → eat with no inventory)

---

### Q: How do I handle command success/failure?

**A: Multiple valid patterns, choose based on your needs.**

#### Option 1: Inline Validation (Simplest)

```python
def execute(self, state: GameState) -> Tuple[GameState, str]:
    # Validate conditions
    if not agent.alive:
        return state, "ERROR: Cannot act while dead"  # Unchanged state
    
    if not state.bush.has_berries(self.count):
        return state, f"FAILED: Only {available} berries"  # Unchanged state
    
    # Success path - mutate state
    new_state = state.with_bush(...).with_agent(...)
    return new_state, "Ate 5 berries"
```

**Use when:** Simple game, don't need pre-validation, single-player

#### Option 2: Separate `can_execute()` (Industry Standard)

```python
def can_execute(self, state: GameState) -> bool:
    """Pre-check if command is valid."""
    agent = state.agents[self.agent_id]
    return agent.alive and state.bush.has_berries(self.count)

def execute(self, state: GameState) -> Tuple[GameState, str]:
    if not self.can_execute(state):
        return state, "Cannot execute"
    
    # Success path
    new_state = state.with_bush(...).with_agent(...)
    return new_state, "Success"
```

**Use when:** Multiplayer (server validates before executing), need UI to gray out invalid actions

**Used by:** Hearthstone, Magic Arena, most card games

#### Option 3: Result Object (Professional)

```python
@dataclass
class CommandResult:
    status: Literal["success", "failed", "error"]
    new_state: GameState
    message: str
    error_code: str | None = None

def execute(self, state: GameState) -> CommandResult:
    if not agent.alive:
        return CommandResult(
            status="error",
            new_state=state,  # Unchanged
            message="Dead agents cannot act",
            error_code="AGENT_DEAD"
        )
    
    # Success
    return CommandResult(
        status="success",
        new_state=new_state,
        message="Ate 5 berries"
    )
```

**Use when:** Networking (need error codes), telemetry, complex error handling

**Used by:** Civilization series, large-scale multiplayer games

---

### Q: What about "floating variables" during command execution?

**A: Commands are atomic transactions - no intermediate state should escape.**

```python
# ❌ BAD: Variables in limbo
def execute(self, state):
    berries = BushRules.harvest(state.bush, 5)  # Berries floating!
    
    if not agent.alive:
        return state, "Dead"  # Berries disappeared into void!
    
    new_hunger = agent.hunger + berries  # ...

# ✅ GOOD: Validate first, then transact atomically
def execute(self, state):
    # Check ALL preconditions BEFORE any changes
    if not agent.alive:
        return state, "Dead"  # No changes yet
    
    if not state.bush.has_berries(self.count):
        return state, "Not enough"  # No changes yet
    
    # All checks passed - now ATOMICALLY update everything
    new_bush, harvested = BushRules.harvest(state.bush, self.count)
    new_agent_hunger = agent.hunger + harvested
    
    # Build new state in one transaction
    new_state = state.with_bush(new_bush).with_agent(...)
    return new_state, "Success"
```

**Key principle:** Return **either** old state (failure) **or** fully updated state (success). Never partial updates.

**Think of it like database transactions:**
```sql
BEGIN TRANSACTION
    UPDATE bush SET berries = berries - 5;
    UPDATE agents SET hunger = hunger + 5;
    -- Either both succeed or both roll back
COMMIT
```

---

### Q: Where do log messages/events belong?

**A: Separate from state - use Event Stream pattern.**

The problem: Commands produce multiple observable changes, but state only captures final result.

```python
# One command execution:
EatBerriesCommand.execute(state)
  → Harvest 5 berries from bush  # Observable event 1
  → Agent gains 5 hunger          # Observable event 2
  → Hunger now 18/24              # Observable event 3
  → Returns: (new_state, "Ate 5 berries")  # Summary message
```

**Where do the intermediate observations go?**

#### Option 1: Event Stream (RECOMMENDED)

Events are **separate** from game state - ephemeral or stored independently.

```python
@dataclass(frozen=True)
class GameEvent:
    """Observable game event."""
    sequence_number: int
    event_type: str  # "berries_harvested", "hunger_updated"
    message: str  # Human-readable
    data: dict  # Structured data for UI/logging

class Command:
    def execute(self, state: GameState) -> Tuple[GameState, List[GameEvent]]:
        """Return new state + events generated."""
        events = []
        
        new_bush, harvested = BushRules.harvest(state.bush, self.count)
        events.append(GameEvent(
            event_type="berries_harvested",
            message=f"Harvested {harvested} berries",
            data={"count": harvested}
        ))
        
        new_hunger = agent.hunger + harvested
        events.append(GameEvent(
            event_type="hunger_updated",
            message=f"Hunger: {agent.hunger} → {new_hunger}",
            data={"old": agent.hunger, "new": new_hunger}
        ))
        
        return new_state, events

class GameEngine:
    def __init__(self):
        self.history: List[Command] = []  # For replay
        self.events: List[GameEvent] = []  # For observation
    
    def execute_command(self, cmd: Command) -> List[GameEvent]:
        new_state, events = cmd.execute(self.current_state)
        self.current_state = new_state
        self.history.append(cmd)
        self.events.extend(events)  # Store separately
        return events
```

**Pros:**
- ✅ Clean separation: state (what is) vs events (what happened)
- ✅ Multiple granularities (fine-grained events + summary)
- ✅ Events can be stored/replayed independently
- ✅ UI can subscribe to event stream

**Cons:**
- ❌ More boilerplate (but cleaner architecture)

**Used by:** Hearthstone, Civilization VI, most games with replay systems

#### Option 2: Event Log in State

```python
class GameState(BaseModel):
    # ... game data ...
    event_log: Tuple[str, ...] = ()  # Bounded log with rotation
    
    def with_event_logged(self, msg: str) -> "GameState":
        events = self.event_log + (msg,)
        if len(events) > 100:
            events = events[-100:]  # Keep last 100
        return self.model_copy(update={"event_log": events})
```

**Pros:**
- ✅ Events persist with state
- ✅ Simple architecture

**Cons:**
- ❌ Mixing concerns (events in game state)
- ❌ Log bloat (need rotation)

**Use when:** Small game, want events in save files

#### Option 3: Ephemeral Messages Only

```python
class GameEngine:
    def execute_command(self, cmd: Command) -> str:
        new_state, message = cmd.execute(self.current_state)
        self.game_log.append(message)  # Log outside state
        return message  # Show to player
```

**Pros:**
- ✅ Simplest approach
- ✅ No state bloat

**Cons:**
- ❌ Lose granular events
- ❌ Can't replay with exact messages

**Use when:** Simple single-player game, don't need detailed logging

---

### Q: Should turn_number be in state and sequence_number in commands?

**A: Yes - they serve different purposes.**

```python
# WorldState tracks GAME TIME
class WorldState(BaseModel):
    turn_number: int = 5  # Game domain concept

# Command tracks HISTORY POSITION
class Command(BaseModel):
    sequence_number: int = 42  # History index for replay

# Engine bridges them
class GameEngine:
    history: List[Command] = [...]  # sequence_number = list index
    current_state: WorldState  # turn_number embedded
```

**Why separate?**
- **turn_number** = game domain (NPCs care, game rules use it)
- **sequence_number** = replay domain (time travel, debugging)

**Example:**
```
Turn 3:
  - sequence 8: ClearMessagesCommand
  - sequence 9: EatBerriesCommand ← User action
  - sequence 10: DispatchMessagesCommand
  - sequence 11: EndTurnCommand
Turn 4:
  - sequence 12: ClearMessagesCommand
  ...
```

One turn can have multiple commands. `turn_number` groups game turns, `sequence_number` enables precise replay.

---

### Q: Should each state hold the preceding command that created it?

**A: No - violates separation of concerns.**

```python
# ❌ BAD: State knows about commands
class GameState:
    agents: Tuple[...]
    bush: BushState
    preceding_command: Command  # Circular dependency!

# ✅ GOOD: Engine tracks state-command relationship
class GameEngine:
    history: List[Command]  # Commands that led to current state
    current_state: GameState  # Pure game data, no command knowledge
```

**Why?**
1. **Circular dependency:** Command creates State, State references Command
2. **Serialization hell:** Can't save state without serializing entire command history
3. **Mixing concerns:** State = "what is", Commands = "what happened"

**If you need to know "how did we get here?"** → Query engine history, don't embed in state.

```python
# Get command that created current state
last_command = engine.history[-1]

# Get state at specific point
state_at_turn_5 = engine.replay_until(turn=5)
```

---

### Q: True transactional model - stack changes, then commit?

**A: Your current approach is already "atomic enough."**

```python
# Current approach (semantically atomic)
def execute(self, state):
    state = state.with_bush(new_bush)     # intermediate_state_1
    state = state.with_agent(...)          # intermediate_state_2
    return state, msg                       # final_state

# True transactional (one commit)
def execute(self, state):
    updates = {}
    updates["bush"] = new_bush
    updates["agents"] = new_agents
    return state.model_copy(update=updates), msg
```

**Both are "atomic" from external perspective:**
- Intermediate states never escape the command
- Only final state is returned
- From outside: it's one transition `old_state → new_state`

**Use true transactional when:**
- ✅ Need to validate ALL changes before committing
- ✅ Complex rollback logic
- ✅ Multiple top-level fields change at once

**Current approach is fine when:**
- ✅ Sequential dependencies (need `new_bush` to compute `new_hunger`)
- ✅ Intermediates never escape
- ✅ Simpler, more readable code

**Recommendation:** Keep current approach unless you need explicit transaction boundaries.

---

## Command Pattern: Best Practices Summary

### ✅ DO:
- Commands represent **game actions** (what player wants)
- Validate **before** making any state changes
- Return **either** unchanged state (fail) or fully updated state (success)
- Use **Event Stream** for observable changes
- Keep **turn_number** in state, **sequence_number** in commands
- Commands are **atomic transactions** (all-or-nothing)

### ❌ DON'T:
- Split actions into too-fine-grained commands (leaky abstraction)
- Allow "floating variables" between checks and commits
- Embed commands in state (circular dependency)
- Mix event logging with game state (unless using bounded log)
- Create intermediate states that can escape command scope

---

