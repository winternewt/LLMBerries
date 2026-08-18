# LLMBerries Architecture Summary

## Pattern: Frozen Class + Rules in Same Module

Each domain entity follows this consistent pattern:

### 1. Bush (`objects/bush.py`)
```python
class BushState(BaseModel):
    """Frozen immutable state"""
    model_config = ConfigDict(validate_assignment=True, frozen=True)
    current_berries: float
    max_berries: float
    regeneration_rate: float

class BushRules:
    """Pure functions that mutate state immutably"""
    @staticmethod
    def harvest(bush: BushState, count: int) -> Tuple[BushState, int]:
        new_bush = bush.model_copy(update={"current_berries": ...})
        return new_bush, actual_harvested
```

### 2. Agent (`objects/agent_state.py`)
```python
class CharacterPhysicalState(BaseModel):
    """Frozen immutable state"""
    model_config = ConfigDict(validate_assignment=True, frozen=True)
    agent_id: int
    name: str
    hunger: float
    # ... more fields

class CharacterRules:
    """Pure functions that mutate state immutably"""
    @staticmethod
    def eat_berries(hunger: float, berries: int) -> Tuple[float, int, str]:
        # Returns (new_hunger, consumed, message)
```

### 3. GameState (`objects/game_state.py`)
```python
class GameState(BaseModel):
    """Top-level frozen game state"""
    model_config = {"frozen": True}
    agents: Tuple[CharacterPhysicalState, ...]
    bush: BushState
    message_queue: Tuple[dict, ...]
    
    # Helper methods for updates
    def with_agent(self, agent_id: int, **fields) -> "GameState":
        """Returns NEW state with updated agent"""
        
    def with_bush(self, bush: BushState) -> "GameState":
        """Returns NEW state with updated bush"""
```

---

## Command Pattern

Commands store LLM decisions and apply them immutably:

```python
class EatBerriesCommand(Command):
    count: int  # LLM decided this
    
    def execute(self, state: GameState) -> tuple[GameState, str]:
        # Use Rules to calculate new state
        new_bush, harvested = BushRules.harvest(state.bush, self.count)
        new_hunger, consumed, msg = CharacterRules.eat_berries(...)
        
        # Return NEW state immutably
        return state.with_bush(new_bush).with_agent(...), msg
```

---

## File Organization

```
objects/
├── bush.py              # BushState + BushRules
├── agent_state.py       # CharacterPhysicalState + CharacterRules
├── game_state.py        # GameState + ConversationMemory
├── observations_v2.py   # Observation factories
├── agent_body.py        # Legacy (mutable)
└── observations.py      # Legacy

core/
├── commands.py          # All command classes
├── game_engine_v2.py    # New engine with history/branching
├── game_engine.py       # Legacy (mutable)
└── common.py            # Constants and enums
```

---

## Key Principles

1. **Co-location**: Frozen class + Rules live in the same module
2. **Immutability**: All state uses `frozen=True` and Tuples
3. **Pure Functions**: Rules are static methods with no side effects
4. **Command Pattern**: LLM decisions stored as data, not queries
5. **No Circular Dependencies**: One-way flow (Command → GameState)

---

## Benefits

- ✅ **Testable**: Pure functions, no mocking needed
- ✅ **Time Travel**: Can navigate to any turn
- ✅ **Branching**: Create alternate timelines
- ✅ **Reproducible**: Deterministic replay from command history
- ✅ **Research-Ready**: A/B test LLMs from same starting point

---

## Next: Integration

Now that the foundation is solid, next steps:
1. Make LLM agents return Commands instead of mutating state
2. Update main game loop to use GameEngineV2
3. Add command serialization for save/load
4. Build replay visualization tools

