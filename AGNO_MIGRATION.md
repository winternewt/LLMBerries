# Migration Plan: just-agents → Agno

**Status:** proposed, not started
**Investigated against:** agno 2.9.0 (installed and read first-hand, plus a probe script;
findings below are empirical, not from the docs)
**Blocking question answered:** yes, Agno gives granular system-prompt control and
mid-flight swapping. Details and the one real gotcha are in Part 1.

---

## Part 1 — The blocking question: system prompt control

LLMBerries needs something unusual: the system prompt **is** the observation. Every
turn, an agent must be told a *different* hunger level, bush count and neighbour
state, while its conversation history (what it said, what it heard) carries forward.
So the question was whether Agno lets the system message change per run without
resetting the agent or leaking stale observations.

### Verified findings

| # | Question | Answer |
|---|----------|--------|
| 1 | Is the system message rebuilt on every run? | **Yes.** `get_run_messages` calls `get_system_message` at the top of every run (`agno/agent/_messages.py:1249`). Nothing is cached between runs. |
| 2 | Can `system_message` be a callable? | **Yes** — `Optional[Union[str, Callable, Message]]` (`agno/agent/agent.py:235`). Re-executed per run. |
| 3 | Can it just be reassigned between runs? | **Yes.** `agent.system_message = "..."` before the next `run()` takes effect immediately. The `Agent` is a mutable object, not a frozen model. |
| 4 | Does the stored history replay the *old* system message? | **No** — and this is what makes mid-flight swapping safe. History is fetched with `skip_roles=["system"]` whenever `system_message_role` is not one of `user`/`assistant`/`tool` (`_messages.py:1294-1303`), so previous turns' system messages are stripped. Only the freshly built one is sent. |
| 5 | Is the per-turn prompt still recorded for research? | **Yes.** The system message *is* stored in `RunOutput.messages`; it is only excluded when re-feeding history. Per-turn observations are therefore auditable after the game. |
| 6 | Can `run()` override the system message per call? | **No.** `run()` takes `session_state`, `dependencies`, `metadata`, `output_schema`, `add_history_to_context` (`agent.py:1345-1368`) — no `system_message` or `instructions` parameter. Use #2, #3 or #7 instead. |
| 7 | Template placeholders? | **Yes.** With `resolve_in_context=True` (the default), `{key}` in the system message is filled from the run's `session_state`/`dependencies`. `system_message="Hunger is {hunger}"` + `run(session_state={"hunger": 3.0})` → `"Hunger is 3.0"`. |

### The one gotcha

**A callable `system_message` does NOT receive `run_context` or `session_state` — only
`agent` (and `team`).** `execute_system_message` inspects the signature and passes just
those two (`agno/utils/agent.py:1057-1078`); the async variant `aexecute_system_message`
does the same. It accepts `session_state` and `run_context` as parameters and then
silently drops them.

A callable `instructions` **does** get both (`aexecute_instructions`,
`agno/utils/agent.py:1081-1110` — it checks for `session_state` and `run_context` in the
signature and passes them). The asymmetry is undocumented and easy to trip over: write
`def sys_msg(agent, session_state=None)` and `session_state` is silently `None` forever,
which reads as "the game state is empty" rather than as an error.

Probe output (agno 2.9.0), reproducing it:

```
3) does a callable system_message receive run_context/session_state?
   run_context=None session_state=None
4) do instructions callables receive them?
   - session_state={'hunger': 3.0}
   - run_context is None: False
```

### Recommended pattern for LLMBerries

Reassign before each run — explicit, debuggable, no signature magic, and it keeps the
game engine as the single owner of state:

```python
observation = AgentObservation.from_state(engine.current_state, agent_id)
agent.system_message = build_observation_prompt(observation)   # full prompt, per turn
result = agent.run("Your turn.")
```

Rationale over the alternatives:

- **vs. callable closing over the engine:** a closure hides *when* state is read. With
  reassignment the prompt is a value you can log, diff, hash and assert on — which the
  replay/branching design already needs.
- **vs. `{placeholder}` + `session_state`:** fine for a few scalars, but the observation
  includes neighbour messages and identity framing; string-templating that is worse than
  building it.

Keep `add_history_to_context=True` with `num_history_runs` (or `num_history_messages`)
set so an agent remembers its own past turns and what neighbours told it, while the
observation itself stays fresh each turn. That combination is exactly what finding #4
makes safe.

**Concurrency note:** reassigning `agent.system_message` is safe here because turns are
sequential per agent. If Phase 6 is ever parallelised across agents, each character must
still own its own `Agent` instance — never share one across characters.

---

## Part 2 — What the migration actually touches

just-agents is used in **4 live modules** plus the archived agent. It is a smaller
coupling than it looks; most of the codebase (commands, engine, DTOs, rules) is
framework-agnostic and does not move at all.

| File | just-agents use | Migration |
|------|-----------------|-----------|
| `entities/events.py:5,61` | `GameEventBus(BufferedEventBus)` | **Replace with a local bus.** Agno has no general pub/sub — its event stream is per-run output events, a different thing. ~40 lines of project-owned code, and it drops the last runtime dependency on just-agents. |
| `entities/llm_configs.py` | `LLMOptions`, `GPT_OSS_120B`, `GEMINI_2_5_PRO` | Replace with Agno model instances (`agno.models.litellm.LiteLLM`, `agno.models.anthropic.Claude`, `agno.models.google.Gemini` — all three module paths exist in 2.9.0). Keep the `LLM_SET` tuple shape so `get_llm_by_index` / `get_random_llm` survive. |
| `entities/memory.py` | `BaseMemory`, `Message`, `Role` | **Probably delete.** Agno owns session history (`AgentSession`, `num_history_runs`). `ConversationMemory` also carries the known `messages`-shadowing warning. Keep only if the immutable-state design needs conversation snapshots inside `WorldState` for branching — decide before writing code (see open question O2). |
| `entities/message.py` | `Message`, `Role` | Swap for `agno.models.message.Message` / plain Pydantic. `NeighborMessage` is our own type and stays. |
| `archive/berries_agent.py` | `BaseAgent` + `AgentBody` | Not migrated. It is the pre-refactor design; port its *prompt-building and tool-response wording*, not its structure. |

Note the two independent problems, which the plan keeps separate: **(a)** Phase 6 has
never been wired to any agent at all, and **(b)** the framework is changing. (a) is a
real gap today regardless of (b) — `core/game_engine.py:355-375` builds the observation,
logs "Waiting for X to act...", and immediately issues `FinishTurnCommand`. And
`core/agent.py` references `self.agent_id` / `self.engine`, neither of which is a
declared field, so any concrete subclass `AttributeError`s on its first tool call.

---

## Part 3 — Phased plan

Each phase leaves the repo runnable. Phases 0-1 are worth doing whether or not the Agno
switch happens.

### Phase 0 — Make the repo honest (no framework work)

Small, mechanical, removes false signals that would otherwise be blamed on the migration:

- `main.py` imports `core.berries_agent` and `core.common` — neither exists. It cannot
  run at all, not even to print its "not yet implemented" message.
- `pyproject.toml` packages `["core", "objects"]`; the directory is `entities`, so the
  built wheel ships no models.
- README quick start points at `demo_game.py`, which is not in the repo; and its
  "✅ Completed — full turn cycle" contradicts the Phase 6 stub.
- ROADMAP lists the `messsage.py` typo as a known issue; it is already fixed.

### Phase 1 — Cut the just-agents event bus

Write `GameEventBus` as project-owned code (subscribe / unsubscribe / publish, buffering
when no subscriber, optional `EventType` filter — the existing docstring at
`entities/events.py:61-74` is the spec). `tests/test_event_bus.py` becomes the check,
converted from print-driven script to assertions.

Do this **first**: it is the one just-agents dependency with no Agno counterpart, it is
independent of the agent work, and it means Phase 3 can drop the dependency outright
rather than keeping it alive for one class.

### Phase 2 — Fix the agent seam (still framework-neutral)

- Give `Agent` its declared fields: `agent_id: int`, `engine: GameEngine`. The class is
  `frozen=True`, so the engine reference must be set at construction.
- Wire Phase 6: store an `AgentDecisionCallback` per agent on the engine and call it
  where the stub logs "Waiting for X to act..."; loop executing commands until
  `FinishTurnCommand`.
- Add a scripted `RuleBasedAgent` (eat when hunger < N, else sleep) as the first
  implementation. It makes the full turn cycle testable end-to-end with **zero API
  calls** — which is what "Test Full Game Loop" in ROADMAP actually needs, and it stays
  useful afterwards as the deterministic control arm in experiments.

### Phase 3 — Introduce Agno behind that seam

- `uv add agno` (+ the provider extras actually used: `anthropic`, `openai`, `litellm`);
  `uv remove just-agents` once Phase 1 and the `Message`/`Role` swaps land.
- `AgnoAgent(Agent)` implementing `decide()`: build the observation prompt, assign
  `agent.system_message`, `run("Your turn.")`, map tool calls to commands.
- Register the 5 game actions as Agno tools. Agno derives the schema from signature +
  docstring, and `core/agent.py:98-233` already has docstrings written in exactly that
  voice — they port nearly verbatim.
- Log the exact system message per turn alongside the command history (finding #5 says
  Agno keeps it in `RunOutput.messages`; the game's own record should not depend on that).

### Phase 4 — Research plumbing

Only after a full 3-agent game runs: replay/branching verification with LLM agents,
`.env.template`, structured JSON event export, the A/B harness across `LLM_SET`.

---

## Open questions (decide before Phase 3, not during)

- **O1 — LiteLLM or native model classes?** `LLM_SET` currently holds litellm-style ids
  (`anthropic/claude-haiku-4-5`). `agno.models.litellm.LiteLLM` keeps that string form
  and one dependency; native classes (`Claude`, `Gemini`) give better per-provider
  feature support. Native is the better default for a cross-model study, since
  provider-specific behaviour is part of what is being measured.
- **O2 — Who owns conversation history?** Agno's `AgentSession`, or `WorldState` via
  `ConversationMemory`? The immutable-state/branching design implies the latter (branch
  a turn → each agent's memory must fork with it); Agno's session store assumes the
  former. This is the one place the two architectures genuinely disagree, and it decides
  whether `entities/memory.py` dies or grows.
- **O3 — Tool-call → Command mapping.** Do tools mutate the engine directly (as
  `core/agent.py` currently assumes, calling `self.engine.execute_command` inside each
  tool) or return intents that `decide()` translates? The latter keeps the engine the
  only mutation point and makes a dry-run mode possible.

---

## Sources

- agno 2.9.0 source, read directly: `agno/agent/agent.py`, `agno/agent/_messages.py`,
  `agno/utils/agent.py`, `agno/run/base.py`
- Agno docs: <https://docs.agno.com/basics/agents/running-agents>
- GitHub discussion on runtime instruction updates:
  <https://github.com/agno-agi/agno/discussions/3135>
