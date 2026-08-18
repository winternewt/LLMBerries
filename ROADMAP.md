# LLMBerries - Development Roadmap

**Last Updated:** 2025-11-09

---

## 🚀 Immediate (Required for Running Game)

- [ ] **LLM Agent Integration**
  - [ ] Implement `decide(observation)` method in agent class
  - [ ] Parse LLM tool calls → Commands
  - [ ] Handle all 5 agent tools (think, eat, speak_left, speak_right, choose_sleep)
  - [ ] Add observation to agent conversation history before decision
  - [ ] Connect to game engine Phase 6

- [ ] **Test Full Game Loop**
  - [ ] Create test script with 3 LLM agents
  - [ ] Run complete game until game over
  - [ ] Verify all 7 phases execute correctly
  - [ ] Check event generation
  - [ ] Validate command history

- [ ] **Fix Remaining Issues**
  - [ ] Rename `entities/messsage.py` → `entities/message.py`
  - [ ] Update all imports
  - [ ] Verify no import errors

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

### Minor
- [ ] Filename typo: `entities/messsage.py` → `entities/message.py`
- [ ] ConversationMemory shadows parent "messages" (warning, not error)

### Nice to Have
- [ ] Add type stubs for just-agents library
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

### 🚧 Milestone 2: Playable Game (IN PROGRESS)
- LLM integration (TODO)
- End-to-end testing (TODO)
- Basic logging (TODO)

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

