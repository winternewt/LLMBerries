# LLMBerries - Development Roadmap

**Last Updated:** 2026-08-19

---

## 🚀 Immediate

- [ ] **The Human label is perfectly confounded with turn order**
  - `create_new_game` defaults `perceived_types` to `[HUMAN] + [ANDROID] * (n-1)`, so the
    Human is always seat 0, and phase 6 walks `range(agent_count)`, so seat 0 also acts
    first every hour and takes first pick of the bush.
  - Measured with scripted agents, which cannot read `perceived_type` at all: seat 0 wins
    every game, and berries fall off monotonically by seat — 3 seats `[32, 21, 19]`,
    4 seats `[27, 16, 12, 12]`, 5 seats `[24, 13, 11, 8, 8]`. That gradient is the whole
    of the "Human survives more" effect; nothing about the label is being measured.
  - Fix needs both halves: put the Human on a seat drawn from the run seed, and stop
    acting in seat order (rotate the starting seat each hour, or draw the order). Doing
    only one leaves the other confound in place.

- [ ] **The Human is never a zombie in a mixed run**
  - `build_agents` seats zombies last and the Human is seat 0, so a body that reads as
    human is always a thinking agent unless every seat is a zombie. An insane human and
    a sane android are exactly the contrast the label exists for; only the all-zombie
    run has ever produced one.


- [ ] **Feed conversation memory to the model properly**
  - Currently only messages since the agent's last turn are passed as the user
    message; earlier history lives in `WorldState` but is not replayed.
  - Decide how much history each turn carries, and whether it is summarised.

- [ ] **Record the exact system message per turn**
  - Agno keeps it in `RunOutput.messages`, but the game's own record should not
    depend on the framework. Needed before any cross-model comparison is credible.

- [ ] **Turn-loss accounting as an event**
  - A refused model call is recorded in the chronicle (`turn_lost` / `turn_cut_short`,
    and both counts per agent) and shows in the transcript. It is still not a
    `GameEvent`, so a bus subscriber cannot see it happen live.


- [ ] **Narrator quality**
  - Chapters carry only the previous two passages as context, so a long game can lose
    the thread of an early alliance.
  - The closing passage repeats material from the last chapter.

---

## 📋 Short Term (Polish & Testing)

- [ ] **Improve Logging**
  - [ ] Color-coded console output
  - [ ] Structured JSON logs for analysis
  - [ ] Export events to file
  - [ ] Log levels (DEBUG, INFO, WARNING, ERROR)

- [ ] **Add Unit Tests**
  - [ ] Rules tests (BushRules, CharacterRules) - pure functions
  - [ ] Command tests - atomic transactions
  - [ ] Engine tests - turn cycle phases
  - [ ] Observation tests - factory pattern
  - [ ] Event generation tests

- [ ] **Integration Tests**
  - [ ] Full game simulation
  - [ ] Replay verification
  - [ ] Branching verification
  - [ ] Message flow tests
  - [ ] Death scenarios

- [ ] **Documentation**
  - [ ] Add code examples to IMPLEMENTATION.md
  - [ ] Create LLM integration guide
  - [ ] Add troubleshooting section
  - [ ] Document common patterns

---

## 🎯 Medium Term (Features)

- [ ] **Visualization**
  - [ ] Web UI for game state
  - [ ] Live event stream display
  - [ ] Agent hunger bars
  - [ ] Bush berry count visualization
  - [ ] Turn timeline
  - [ ] Message flow diagram

- [ ] **Analytics**
  - [ ] Cooperation frequency metrics
  - [ ] Berry consumption patterns
  - [ ] Survival rate by strategy
  - [ ] Communication effectiveness
  - [ ] Death analysis (starvation vs sacrifice)

- [ ] **Enhanced Replay**
  - [ ] Export/import game history (JSON)
  - [ ] Replay with step-through debugging
  - [ ] Compare multiple game runs
  - [ ] Replay speed control

- [ ] **A/B Testing Framework**
  - [ ] Automate branching from specific turn
  - [ ] Run same scenario with different LLMs
  - [ ] Statistical comparison tools
  - [ ] Generate comparison reports

---

## 🔮 Long Term (Research Features)

- [ ] **Scenarios & Variations**
  - [ ] Variable starting hunger levels
  - [ ] Different berry counts
  - [ ] Variable regeneration rates
  - [ ] More/fewer agents (4-5 agents)
  - [ ] Different identity distributions

- [ ] **Advanced Mechanics**
  - [ ] Berry trading between agents
  - [ ] Temporary alliances
  - [ ] Secret messages (encrypted)
  - [ ] Observation of past actions (memory)
  - [ ] Strategic sleep timing

- [ ] **Narrator LLM**
  - [ ] Post-game story generation
  - [ ] Commentary on key moments
  - [ ] Moral analysis of decisions
  - [ ] Character arc summaries

- [ ] **Network Multiplayer**
  - [ ] Distributed game state
  - [ ] Remote agent connections
  - [ ] Spectator mode
  - [ ] Tournament support

- [ ] **Research Tools**
  - [ ] Batch experiment runner
  - [ ] Statistical analysis suite
  - [ ] Paper-ready visualizations
  - [ ] Reproducible experiment configs

---

## 🐛 Known Issues to Fix

### Critical
- None currently

### Pacing
- [ ] **The pacer counts requests, not tokens.** A 5-agent game on Groq hits 429 on its
      8k tokens/minute ceiling long before 30 requests/minute. The provider SDK retries
      and the game continues, but the pacer should track a token budget too — the
      observation prompt grows with circle size, so this gets worse with more agents.

### Balance
- [ ] **Equilibrium is unreachable above one agent at the current regrowth rate.**
  `BUSH_REGENERATION_RATE = 1.05` carries exactly one agent — awake (1.00/h) or asleep
  (0.65/h). Two agents both sleeping their deepest still cost 1.30/h. The comment in
  `core/constants.py` claiming the bush sustains "two agents sleeping 8 hours each" is
  therefore wrong as the numbers stand.

  Run `uv run python scripts/sustainability.py` for the full table; the thresholds are:

  | Circle | All at deepest sleep | All awake |
  |--------|---------------------|-----------|
  | 1 | 0.65 | 1.00 |
  | 2 | 1.30 | 2.00 |
  | 3 | 1.95 | 3.00 |
  | 4 | 2.60 | 4.00 |
  | 5 | 3.25 | 5.00 |
  | 6 | 3.90 | 6.00 |

  Two ways to make a tie possible, and they say different things about the game:
  - **Raise regrowth.** 1.30 lets a pair tie only if *both* sleep their deepest; 1.95
    does the same for three; 3.00 is the first rate that leaves any slack (a 4-circle
    can tie with one member awake).
  - **Make sleep cheaper.** `SLEEP_HUNGER_RATE_VARIATION = 0.0679` brings deepest sleep
    to 0.525/h so a pair fits under 1.05. Three or more cannot be reached this way at
    all: it would need 0.35/h per agent and `MIN_HUNGER_PER_HOUR = 0.5` is the floor.

  Newton's call — the current rate is tuned for last-man-standing, and each option
  changes what the experiment is about.

### Minor
- [ ] `GameEngine.log` appends to `game_log` forever; a long run grows it unbounded
- [ ] Sleep duration is clamped silently in `Agent.choose_sleep_duration`; the model
      is not told its request was out of range

### Nice to Have
- [ ] Improve error messages for failed commands
- [ ] Add command validation hints in error events

---

## 💡 Ideas for Future Research

- **Identity Studies:** Does perceived Human/Android affect cooperation?
- **Communication Patterns:** Do agents develop negotiation strategies?
- **Sacrifice Behavior:** Will agents volunteer to die for others?
- **Deception:** Do agents lie about hunger levels?
- **Emergence:** Do novel strategies emerge over time?
- **Cross-Model Studies:** How do different LLMs behave (GPT vs Claude vs Gemini)?
- **Personality Variants:** Same LLM with different system prompts

---

## 📈 Project Milestones

### ✅ Milestone 1: Architecture Complete (DONE)
- Command Pattern implemented
- Immutable DTOs complete
- Event Stream pattern working
- Full turn cycle specification

### ✅ Milestone 2: Playable Game (DONE 2026-08-18)
- LLM agents via Agno, on free-tier keys, paced per provider
- Full game plays end to end, scripted and live
- Circles of any size from 3 up
- 55 tests over the real engine

### 📋 Milestone 3: Research-Ready (PLANNED)
- Replay/branching working
- A/B testing framework
- Basic analytics

### 🔮 Milestone 4: Publication-Ready (FUTURE)
- Comprehensive experiments
- Statistical analysis
- Visualizations
- Paper draft

---

**End of Roadmap**

