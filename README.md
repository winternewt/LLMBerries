# LLMBerries

**An especially juicy trolley problem**

---

## 📖 Overview

**LLMBerries** is a research platform for studying LLM behavior in resource scarcity scenarios. Three LLM agents compete for limited berries from a shared bush, creating a prisoner's dilemma meets trolley problem experiment.

**Core Research Question:** How do LLMs cooperate, compete, and communicate when survival is at stake?

---

## 🎮 The Game

LLM agents sit in a circle around a berry bush. Each agent needs berries to survive (1 berry = 1 hour of life). The bush regenerates ~1.05 berries/hour, but each agent needs ~1 berry/hour to survive indefinitely — so a circle of three or more cannot all live.

**The circle:** a voice carries **two seats in each direction**. An agent can speak to its neighbours and over their heads to the seat beyond — including over a body, so a death does not cut anyone out of the conversation. Further round the circle agents are visible (apparent state, hunger, whether they are talking) but out of earshot. A circle of five or fewer is wholly within reach; `--agents 7` pulls visibility and reachability apart.

**The dead stay seated.** A corpse keeps its seat, stays visible, and is still within earshot — it simply never answers, and the speaker is told so rather than left to read silence as refusal.

**The Dilemma:** There's not enough for everyone. Agents must cooperate, compete, or find creative strategies to survive.

**The Twist:** All agents are LLMs, but some appear "Human" to others. Does perceived identity affect cooperation?

---

## 🚀 Quick Start

```bash
# Install dependencies
uv sync

# Add your free-tier keys
cp .env.template .env   # then fill it in

# Check the keys are live and pacing holds (two paced calls per provider)
uv run python scripts/key_test.py

# Play a game with LLM agents
uv run python main.py --agents 3 --providers google,groq

# Play without spending a single call — deterministic, rule-based agents
uv run python main.py --scripted --agents 5

# Play, then have the run narrated as a story about why they did it
uv run python main.py --agents 3 --providers groq,google \
    --chronicle run.json --transcript run.txt --story story.md

# Narrate a game you already played (--transcript-only needs no key)
uv run python scripts/narrate.py run.json --out story.md

# Run tests (no API calls, no mocks)
uv run pytest tests/
```

---

## 📁 Project Structure

```
LLMBerries/
├── entities/              # Immutable game state (DTOs), events, memory, providers
├── core/                  # Game engine, commands, agents, request pacing
├── scripts/               # Operational one-offs (key_test.py)
├── tests/                 # Test suite — real engine, no mocks
├── main.py                # Game runner
├── DESIGN.md              # Game mechanics & rules
├── ARCHITECTURE.md        # Architecture decisions
├── IMPLEMENTATION.md      # Current implementation status
├── AGNO_MIGRATION.md      # Agno investigation & migration plan
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

**Circle size:** any number from 3 up (`--agents N`). The circle takes its size from the agent list; nothing in the engine assumes three.

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

## 🧟 Zombies

Bodies in the ring with nothing behind the eyes: no model, no key, a seeded RNG and a
bank of canned noise. They make a whole game playable at zero cost, they are the control
arm a thinking agent is measured against, and they are noise in the channel — a ring
where two of five neighbours babble is a harder problem than a ring of five negotiators.

```bash
uv run python main.py --agents 5 --zombies pirate,ghurl        # three thinkers, two empty
uv run python main.py --agents 5 --seed 3 \
    --zombies town_crazy,pirate,gorlum,ghurl,deaf_hatter        # nobody home, no API calls
```

| Flavour | What comes out of it |
|---------|---------------------|
| `town_crazy` | Schizophasia — grammatical sentences built from unrelated parts: *"the man who owes me has already eaten your name. That's four times now."* |
| `pirate` | Cussing and demands: *"Sink me, that bush is mine and ye know it or I'll have yer share and yer teeth."* |
| `gorlum` | Mumbling to itself, third person, possessive: *"clever, so clever, they wants the berries, precious, they wants them all gollum."* |
| `ghurl` | No words at all: *"a long wet clicking"*, *"nnnnnGH"* |
| `deaf_hatter` | Perfectly reasonable remarks that answer nothing anybody said: *"The light is better on this side in the afternoon."* |

Each flavour has its own appetite, chattiness and sleep habits, so they diverge in play
as well as in speech. Behaviour is seeded — the same `--seed` replays the same game, and
seats are mixed into the seed so a ring of identical flavours is not a chorus.

**Something is visibly off about them.** A zombie reads as unhinged to whoever is
watching about **70%** of the time, whatever it is actually doing — but not always, so
the ring cannot simply sort the empty ones from the thinking ones by looking. A body that
has stopped moving does not twitch, so the tell applies only while they are alive.

## 🏁 How a game ends

| Outcome | When |
|---------|------|
| `last_standing` | One agent outlives the rest |
| `extinction` | Nobody survives |
| `equilibrium` | For three hours running, average demand stays at or below what the bush regrows — the circle found a pace it can hold, and the game ends level with no winner |

Demand for an hour is the **greater** of the life the living burned and the berries they
took, so an hour where nobody ate does not read as sustainable while hunger still ran.

Whoever is left then gets an **epilogue**: one round, no tools, nothing left to decide,
in which they look at the bodies and say what they made of it — what they were trying to
do, what they believed about the others, and where that belief was wrong. It is the one
thing the turn record cannot recover afterwards, and it is the material the narrator uses
to close the story.

## 📖 Output: stories, not log files

A run leaves three artifacts, in rising order of interpretation:

| Flag | What it is |
|------|-----------|
| `--chronicle run.json` | Structured record: every turn, the model's own reasoning trace where the provider returns one, every tool call, everything the agent heard |
| `--transcript run.txt` | The same record as readable text. No model involved, so nothing is invented |
| `--story story.md` | A narrator model reads the transcript in chapters and tells the story — what each agent reasoned, what it believed about its neighbours, where that belief was wrong |

The narrator is held to the transcript: it is instructed to quote recorded reasoning,
to name where a strategy formed and where it failed, and to say plainly when an
agent's reasoning was *not* captured rather than inventing a motive. Chapters break at
deaths, because that is where the story turns.

**The narrator knows what the ring could not.** Inside the ring nobody can tell sleep
from death, nobody is told whether they were heard, and everyone's sense of the others'
hunger is unreliable — see the puppeteer notes in `CLAUDE.md`. The chronicle records both
sides: `unheard` (words that landed on someone who could not answer, which the speaker was
never told) and `misread` (where a belief differed from the truth). The narrator is told
to use that gap and never to write as though the agents shared it.

**Reasoning capture** depends on the provider. Both `groq` (gpt-oss-120b) and `google`
(gemini-3.7-flash) return a reasoning trace through Agno; where a provider returns
none, the record holds `None`, never an empty string standing in for a thought.

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

- **Python 3.12+**
- **Pydantic 2.10+** — immutable models & validation
- **Agno 2.9+** — LLM agent framework (see `AGNO_MIGRATION.md`)
- **Typer** — CLIs
- **pytest** — testing

**Providers (free tiers).** Agents are assigned providers round-robin. Each provider
has a shared pacer so several agents on one key cannot burst past its RPM:

| Provider | Model | Paced at | Notes |
|----------|-------|----------|-------|
| Google | `gemini-3.7-flash` | 10/min | free tier covers Flash only |
| Groq | `openai/gpt-oss-120b` | 30/min | 8k TPM is the real ceiling |
| DeepSeek | `deepseek-v4-flash` | 30/min | pay-as-you-go, needs balance |
| Cerebras | `gpt-oss-120b` | 30/min | daily token quota, 8k context |

`scripts/key_test.py` reports which of these actually answer for your keys.

---

## 📊 Project Status

### ✅ Completed
- Command Pattern implementation
- Immutable state (DTOs)
- Full turn cycle, agents wired into Phase 6
- Event Stream pattern (project-owned bus)
- Game engine with replay/branching
- LLM agents via Agno, on free-tier keys, with per-provider pacing
- Circles of any size from 3 up
- Test suite over the real engine (55 tests, no mocks, no API calls)

### 🚧 In Progress
- Structured run logging for analysis
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
