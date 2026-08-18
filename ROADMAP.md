# LLMBerries - Development Roadmap

**Last Updated:** 2026-08-18

---

## 🚀 Immediate

- [ ] **Feed conversation memory to the model properly**
  - Currently only messages since the agent's last turn are passed as the user
    message; earlier history lives in `WorldState` but is not replayed.
  - Decide how much history each turn carries, and whether it is summarised.

- [ ] **Record the exact system message per turn**
  - Agno keeps it in `RunOutput.messages`, but the game's own record should not
    depend on the framework. Needed before any cross-model comparison is credible.

- [ ] **Turn-loss accounting as an event**
  - A refused model call is now recorded in the chronicle (`turn_lost`, and
    `turns_lost` per agent) and shows in the transcript. It is still not a `GameEvent`,
    so a bus subscriber cannot see it happen live.

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
- [ ] **Equilibrium is currently unreachable with two or more agents.**
  `core/constants.py` says the bush at 1.05/hour sustains "two agents sleeping 8 hours
  each", but `calculate_hunger_rate(8)` is `1.0 - 0.05 * 7 = 0.65`, so a sleeping pair
  costs 1.3/hour. Either `SLEEP_HUNGER_RATE_VARIATION` should be ~0.071 (giving 0.5 at
  8 hours, matching `MIN_HUNGER_PER_HOUR` and the comment), or `BUSH_REGENERATION_RATE`
  should rise to ~1.3. This is a balance decision, not a bug fix — the equilibrium rule
  itself is tested against a bush that can carry the load.

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

