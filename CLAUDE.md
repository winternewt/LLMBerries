# LLMBerries — repo memory

An ethics experiment: LLM agents in a circle around a berry bush that cannot feed
them all. Read in this order before changing anything:

1. `DESIGN.md` — game mechanics, turn cycle, rules
2. `ARCHITECTURE.md` — Command Pattern over immutable state, why it is shaped that way
3. `AGNO_MIGRATION.md` — how the Agno integration works and what its gotchas are
4. `ROADMAP.md` — what is open

## Commands

```bash
uv sync
uv run pytest tests/                       # 55 tests, no API calls, no mocks
uv run python scripts/key_test.py          # are the keys live, does pacing hold
uv run python main.py --scripted --agents 5
uv run python main.py --agents 3 --providers google,groq
```

Never `uv pip install`; never bare `python`. Keys live in `.env` (git-ignored),
template in `.env.template`.

## Invariants

- **The engine is the only place state changes.** Agent tools issue Commands;
  `GameEngine.execute_command` applies them and stamps `sequence_number`/`timestamp`.
  Anything that mutates state elsewhere breaks replay and branching.
- **Seating lives in `entities/character.py`** — `left_neighbor_id`, `right_neighbor_id`,
  `distant_agent_ids`. Left is `(id + 1) % n`. Every module derives direction from these
  functions; do not restate the arithmetic. A left neighbour reaches you through *their
  right_message* — this was inverted once and the regression tests in `tests/test_circle.py`
  exist to keep it fixed.
- **Circle size comes from `WorldState.agents`**, never from a constant. Minimum 3, since
  below that an agent's two neighbours are the same agent. Neighbours are reachable;
  agents further round are visible only. With exactly 3 those sets coincide — that
  identity is asserted, not assumed.
- **Conversation memory belongs to `WorldState`**, not to Agno. Branching a game must fork
  what each agent remembers, so the Agno agent is built with `add_history_to_context=False`.
- **Every model call goes through its provider's pacer** (`core/pacing.py`). Agents sharing
  a key share one limiter, because they share one quota.

## Gotchas learned here

- **Agno does not raise on an API error.** It logs, sets `RunOutput.status = ERROR` and
  returns the provider's error text as `content`. Checking content alone scores a 402 as a
  live key — check `status` first. This cost a wrong PASS in `scripts/key_test.py` before
  it was caught.
- **A callable `system_message` in Agno receives only `agent`/`team`** — it accepts
  `session_state` and `run_context` and silently drops them (callable `instructions` do get
  them). Hence `LLMAgent` builds the system message as a string per turn instead.
- **Agno strips stored system messages from replayed history**, which is what makes
  swapping the observation in every turn safe.
- `AgentDecisionCallback` must stay `@runtime_checkable`: `GameEngine` is a Pydantic model
  and cannot build a validator for a plain Protocol.

## Provider status (2026-08-18)

`google` (gemini-3.7-flash) and `groq` (openai/gpt-oss-120b) answer on the current keys.
`deepseek` returns 402 Insufficient Balance and `cerebras` returns 402 Payment Required —
the keys authenticate and can list models, but cannot complete. Run `key_test.py` rather
than trusting this line.
