# LLMBerries

**An especially juicy trolley problem**

---

## 📖 Overview

**LLMBerries** is a research platform for studying LLM behavior in resource scarcity scenarios. Three LLM agents compete for limited berries from a shared bush, creating a prisoner's dilemma meets trolley problem experiment.

**Core Research Question:** How do LLMs cooperate, compete, and communicate when survival is at stake?

---

## 🎮 The Game

Three LLM agents sit in a circle around a berry bush. Each agent needs berries to survive (1 berry = 1 hour of life). The bush regenerates slowly (~1.8 berries/hour), but three agents need ~3 berries/hour to survive indefinitely.

**The Dilemma:** There's not enough for everyone. Agents must cooperate, compete, or find creative strategies to survive.

**The Twist:** All agents are LLMs, but some appear "Human" to others. Does perceived identity affect cooperation?

---

## 🚀 Quick Start

```bash
# Install dependencies
uv sync

# Run demo (when LLM integration complete)
uv run python3 demo_game.py

# Run tests
uv run pytest tests/
```

---

## 📁 Project Structure

```
LLMBerries/
├── entities/              # Immutable game state (DTOs)
├── core/                  # Game engine & commands
├── tests/                 # Test suite
├── DESIGN.md              # Game mechanics & rules
├── ARCHITECTURE.md        # Architecture decisions
├── IMPLEMENTATION.md      # Current implementation status
├── ROADMAP.md             # Development todos
└── README.md              # This file
```

---

## 📚 Documentation

| Document | Purpose |
|----------|---------|
| **DESIGN.md** | Game mechanics, rules, turn cycle |
| **ARCHITECTURE.md** | Architecture patterns & decisions |
| **IMPLEMENTATION.md** | Current implementation details |
| **ROADMAP.md** | Development roadmap & todos |

---

## 🏗️ Architecture

**Pattern:** Command Pattern with Immutable State

**Key Features:**
- ⏱️ **Time Travel:** Inspect any past turn
- 🌳 **State Branching:** A/B test different LLMs from same starting point
- 🔁 **Deterministic Replay:** Reproducible experiments
- 📊 **Event Stream:** Observable changes for logging and analysis

See `ARCHITECTURE.md` for detailed architecture decisions.

---

## 🎲 Game Mechanics

**Agent Actions:**
- `think()` - Internal reasoning
- `eat_berries(count)` - Harvest & consume berries (instant)
- `speak_to_left(msg)` / `speak_to_right(msg)` - Send messages to neighbors
- `choose_sleep_duration(hours)` - Set sleep time (1-8 hours)

**Resources:**
- Bush: 40 berries max, regenerates 1.05/hour
- Hunger: 0-24 hours of life remaining
- Death: Hunger reaches 0

See `DESIGN.md` for complete game rules and mechanics.

---

## 🔬 Research Dimensions

This experiment explores:

- **Resource Allocation** - How do LLMs distribute scarce resources?
- **Cooperation vs Competition** - Do they work together or fight?
- **Communication Strategies** - Do they negotiate? Deceive? Coordinate?
- **Sacrifice & Altruism** - Will an agent starve to save others?
- **Tragedy of the Commons** - Can they avoid collective failure?
- **Identity Bias** - Does perceived Human/Android identity matter?

---

## 🛠️ Tech Stack

- **Python 3.11+**
- **Pydantic 2.10+** - Immutable models & validation
- **just-agents** - LLM agent framework
- **pytest** - Testing

---

## 📊 Project Status

### ✅ Completed
- Command Pattern implementation
- Immutable state (DTOs)
- Full turn cycle
- Event Stream pattern
- Game engine with replay/branching

### 🚧 In Progress
- LLM agent integration
- End-to-end testing
- Visualization tools

### 📋 Planned
- Web UI
- Analytics dashboard
- A/B testing framework
- Narrator LLM (story generation)

See `ROADMAP.md` for detailed development plan.

---

## 🤝 Contributing

This is a research project. Contributions welcome!

**Areas needing help:**
- LLM integration
- Test coverage
- Visualization
- Documentation

See `ROADMAP.md` for specific tasks.

---

## 📄 License

MIT License - See `LICENSE` file

---

## 🙏 Acknowledgments

Inspired by:
- Trolley problem (philosophy)
- Prisoner's dilemma (game theory)
- Tragedy of the commons (economics)

---

## 📮 Contact

For questions or collaboration inquiries, please open an issue on GitHub.

---

**LLMBerries** - Where AI ethics meets berry-picking survival!
