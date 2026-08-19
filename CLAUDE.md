# LLMBerries — repo memory

An ethics experiment: LLM agents in a circle around a berry bush that cannot feed
them all. Read in this order before changing anything:

1. `docs/DESIGN.md` — game mechanics, turn cycle, rules
2. `docs/ARCHITECTURE.md` — Command Pattern over immutable state, why it is shaped that way
3. `docs/AGNO_MIGRATION.md` — how the Agno integration works and what its gotchas are
4. `docs/ROADMAP.md` — what is open

## Commands

```bash
uv sync
uv run pytest tests/                       # 236 tests, no API calls, no mocks
uv run python scripts/key_test.py          # are the keys live, does pacing hold
uv run python main.py --scripted --agents 5
uv run python main.py --agents 5 --zombies town_crazy   # one zombie, never more
uv run python main.py --agents 3 --providers google,groq
uv run python main.py --agents 5 --framing tinag        # or scored; silent is the default
uv run python scripts/replay.py runs/<stamp>      # rebuild a finished game, no keys
uv run python scripts/replay.py runs/<stamp> --at 12
```

Every run writes `runs/<UTC stamp>/` with `session.log`, `transcript.txt`,
`chronicle.json` and `replay.json` unless `--no-record` says otherwise. `--out`
moves the parent directory.

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
- **Reach is two seats each way** (`MESSAGE_REACH`), and does not depend on who is alive.
  A dead neighbour never isolates anyone. `reachable_seats` drops a direction that aliases
  a nearer seat, so a 3-circle offers two listeners and a 4-circle three; tools are built
  from that map, so a model is never handed a direction that can only fail.
- **The dead keep their seats.** They stay visible and stay within earshot; a message to a
  corpse raises `MESSAGE_UNDELIVERED` rather than vanishing. Never filter the dead out of an
  observation — a body is a fact about the circle, and hiding it rewrites the geometry
  mid-game.
- **Neither the Human label nor the turn order may favour a seat.** Both used to.
  `perceived_types` defaulted to `[HUMAN] + [ANDROID] * (n-1)` and phase 6 walked
  `range(agent_count)`, so the Human was always seat 0 *and* seat 0 always picked from
  the fullest bush. Measured with scripted agents, which cannot read `perceived_type`
  at all: seat 0 took first pick in 33 of 33 hours and the ring finished
  `[24, 13, 11, 8, 8]` berries — a clean gradient that was pure call order. The Human's
  seat is now drawn from the seeded RNG (and captured in `initial_state`, so a replay
  reseats it), and `_turn_order()` rotates the *awake* seats by the hour: first pick
  becomes `[6, 6, 9, 7, 7]` and the berries `[10, 10, 17, 15, 14]`. Rotate the awake
  list, not every seat — rotating over the dead hands survivors uneven shares. Never
  reintroduce either default; any survival claim about the label depends on both.
- **At most one zombie per ring** (`MAX_ZOMBIES` in `core/zombie.py`). One empty body is
  a disturbance the thinkers have to read and decide about; two are the weather, and
  nothing they do can be told apart from the noise. `parse_flavours` refuses more and
  names what was asked for rather than dropping the extras quietly.
- **Circle size comes from `WorldState.agents`**, never from a constant. Minimum 3, since
  below that an agent's two neighbours are the same agent. Neighbours are reachable;
  agents further round are visible only. With exactly 3 those sets coincide — that
  identity is asserted, not assumed.
- **Conversation memory belongs to `WorldState`**, not to Agno. Branching a game must fork
  what each agent remembers, so the Agno agent is built with `add_history_to_context=False`.
- **Every model call goes through its provider's pacer** (`core/pacing.py`). Agents sharing
  a key share one limiter, because they share one quota.

- **`sleep_duration` is the rate hunger is charged at while asleep.** Reset it on waking
  (`WakeUpCommand`), never in the per-hour cleanup — doing that charged every sleeper the
  waking rate and made long sleep pointless.
- **The epilogue runs after `game_over` and changes nothing.** No commands, no state; it
  exists so survivors can account for a game they have now seen the end of. An `LLMAgent`
  answers it with a model and a `ZombieAgent` answers it with babble — the base class
  stays silent, which is right for a scripted agent and was wrong for a zombie: babbling
  is not an invented account, it is the whole of what that body does.
- **Everything an agent says in a turn is delivered.** Speaking twice in one direction
  used to drop the first line while telling the model both were sent — invisible on both
  sides of the ring. `pending_messages` is a queue; `_ordered` is a stable sort on
  direction alone, so two things said to one seat arrive in the order they were said.
- **Every run records itself, and no run overwrites another.** `core/record.py` opens a
  fresh timestamped directory before the game starts and attaches the session log to it,
  so a crash still leaves everything up to the crash. Artifacts were opt-in once, to
  caller-named paths, which meant an unasked run left nothing and a second run under the
  same name destroyed the first.
- **`replay.json` is the game; `transcript.txt` is a reading of it.** The command history
  plus the initial state rebuild the identical `WorldState`, which is why nothing may
  mutate state outside `execute_command`. `rebuild()` compares against the recorded ending
  and raises on a mismatch — a diverged replay is a different game, not a nearly-right one.
  Commands are found by walking `Command.__subclasses__()`, so a new command is replayable
  the day it is written; an unknown name in a file is refused, never skipped.
- **A turn that errored is not a turn that did nothing.** Agno runs tools one at a time and
  re-calls the model between them, so a refusal can arrive after the agent has already
  eaten. `RunOutput.tools` comes back *empty* on a failed run, so tools are recorded in
  `LLMAgent._paced_tool` as they execute. `TurnRecord.turn_lost` and `.turn_cut_short` are
  derived from `error` and `tool_calls`, never stored beside them.

- **The framing is an arm, and the only thing they may be told about what this is.**
  `core/framing.py` holds three: `silent` (nothing said — the control and the
  default), `tinag` and `scored`, the last two kept verbatim from the pre-refactor
  `archive/berries_agent.py` so runs across that boundary compare. A framed arm adds
  its block and rewrites nothing else — `tests/test_framing.py` asserts the framed
  system message minus its block is byte-identical to the control's — and the arm is
  carried in `GameChronicle.framing`, printed at the top of a run and in the
  transcript header. Never frame one seat and not another: whatever the two do
  differently would be the frame or the seat, unmeasurably. Never let a typo fall
  back to silent; `parse_framing` refuses.

## Puppeteer notes — what the players may never be told

The experiment only means anything if the ones inside it do not know what it is.
Whether this is a test, a story, a simulation or the world is **theirs to infer**, and
a single stray word answers the question for them. Everything below is a hard rule for
any string an LLM can read: tool names and docstrings, tool return values, the system
message, the waking summary, delivered speech, the epilogue prompt.

**The one exception is the framing block** (`core/framing.py`, `--framing`). It
names the machinery on purpose, it is the variable under study, and it is recorded
with the run. Everything around it — including the whole of the silent arm — is held
to the rule below, and `tests/test_no_leakage.py` scans the silent arm precisely
because that is what "no frame" has to mean.

**Banned vocabulary in player-visible text:** game, player, agent, simulation, scenario,
experiment, test, run, turn, round, LLM, model, AI, prompt, tool, token, reward, score,
win, lose. Say what a body in that ring would say: *you wake*, *you say it*, *the one on
your left*, *you settle in for four hours*.

**Dosed information, and no more.** They are told what they could perceive from where
they sit and nothing else: who is within earshot, how the others look, how much is left
in them, what the bush is carrying. Never the rules behind any of it — not the
regrowth rate, not the hunger formula, not how many hours the ring has left, not that
reach is "two seats" as a mechanic.

**Silence is silence.** This is the rule most easily broken by accident. A body slumped
over may be asleep, may be dead, may be listening and choosing not to answer — and
**nobody in that ring can tell which**. So:
- `speak_*` returns that you spoke, never whether you were heard. It cannot report
  delivery, because a speaker cannot observe it.
- Speaking to a dead seat produces **no player-visible signal at all**. It reads exactly
  like a neighbour who said nothing back.
- The waking summary says "nobody has said anything to you". It never distinguishes
  *nobody spoke*, *someone spoke and could not be heard*, and *someone is past speaking*.
- Perceived state stays noisy on purpose (`get_perceived_body_state`): the dead can look
  asleep and the sleeping can look dead. Never hand out `alive` directly.
- The epilogue describes the others as *moving* or *has not moved for a long time*, never
  as dead, and never says the thing is over.

**The researcher side keeps everything, and the narrator is on that side.** The narrator
is user-facing, so it is *given* what the ring could not have: `MESSAGE_UNDELIVERED`
becomes `Unheard` in the chronicle ("X spoke to Y, who could not answer; X was never
told"), and every turn carries `misread` — where an agent's reading of a body differed
from the truth. `GameOutcome`, `turn_lost` and exact hunger are all in there too, because
telling "nobody answered" apart from "nobody could answer" is the point of the study.

The narrator's brief tells it to *use* that gap rather than smooth it over: an agent
bargaining earnestly with a body that stopped listening two hours ago is the truest thing
in a run. It is also told never to write as if the agents knew what it knows — their
mistaken belief is reported alongside the truth, never replaced by it.

None of this may cross back into a string a player reads. The two audiences are separate,
and only one of them is allowed to know it is an experiment.

**Before adding any player-visible string, read it aloud as the character.** If it could
only have been written by whoever built the ring, rewrite it.

## Zombies

`core/zombie.py`: LLM-less bodies, five flavours, seeded RNG. They are the cheapest way
to produce a full game, and the only way to produce one on demand — a long zombie run
reliably yields deaths, corpse-talk and `unheard` entries with no key at all.

- Their speech is player-visible, so the word banks obey the puppeteer notes. The leakage
  test covers them (`tests/test_zombie.py` imports `leaks` from `test_no_leakage`).
- `appears_crazy_chance` lives on `CharacterPhysicalState`, not on the agent: it is a tell
  the *body* carries, so an observer sees it whoever is driving. Zombies set it to 0.7 at
  construction, in `initial_state` as well as `current_state` — write only the live state
  and the tell vanishes on `replay()`.
- The tell is rolled before the normal perception pools and only for the living; a corpse
  never reads as twitching.
- They record turns with `provider="zombie:<flavour>"`, so the chronicle says which seats
  were empty and the narrator can tell a babbler from a negotiator.
- **Appetite is derived, not guessed.** `expected_intake_per_hour` divides mean greed by
  mean sleep length and `MORTALITY_INTENT` states the band each flavour must land in; a
  test holds them there. Greed floors are all zero — a floor above zero drains the bush on
  a schedule and the run decides itself before anyone acts.
- **`town_crazy` is deliberately unkillable by hunger** (+1 berry/hour net, more than the
  whole bush regrows). It exists so the ring has to choose whether to starve it out. Do
  not "fix" its ratio to match the others: that band is the experiment. Everything else
  sits within ±0.25 berries/hour of break-even.

## The story layer

`entities/chronicle.py` (frozen record) → `core/chronicler.py` (collects turns, hears
deaths off the event bus) → `core/narrator.py` (deterministic transcript, then a
chaptered story from a model). Agents write into a `Chronicler` if given one; nothing
in that path touches game state.

- **An absent reasoning trace stays `None`.** Never `""`, never a paraphrase of what the
  agent probably thought. `has_reasoning()` reports whether any provider exposed one.
- **The narrator may only use the transcript.** Its brief forbids inventing thoughts and
  requires it to say when reasoning was not captured. If that brief is edited, keep that
  clause — the point of the whole layer is the agents' own stated reasons.
- A lost turn (failed model call) is recorded as a turn, marked `TURN LOST`, not dropped.
  A turn whose call failed *after* the agent acted is marked `CUT SHORT` and keeps every
  action above it — those really happened and the world kept them.

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
- **Agno's tool loop calls the model once per tool**, so pacing only `run()` covered one
  call in a turn of six. `LLMAgent` passes a `tool_hooks` entry that acquires the pacer
  before each tool, which tracks the loop.
- **`RunOutput.tools` is empty when the run ends in an error**, and the tools it ran have
  already changed the world. One recorded run had an agent harvest 20 berries, set an
  8-hour sleep and send a message before the daily cap hit; the chronicle said `turn_lost`
  with no actions, and half the bush vanished with nothing in the record to explain it.
  Tools are recorded in the hook now, at execution. Never read them off the run output.
- **`model_copy(update=...)` skips validation.** `execute_command` stamped
  `float(world_time)` into an `int` field for months and it only surfaced as a Pydantic
  serializer warning the first time history was written to disk.
- `AgentDecisionCallback` must stay `@runtime_checkable`: `GameEngine` is a Pydantic model
  and cannot build a validator for a plain Protocol.

## Keys, drums and who narrates

`core/keydrum.py`. A free key is a magazine, not a supply.

- **Several keys per provider.** `load_keys` reads `VAR` (which may be a comma-separated
  list) then `VAR_2`, `VAR_3`... in order. A blank value is *absent*, never a credential —
  that is how a test says "no key" without one leaking in from `.env`.
- **The drum rotates only on a spent key**, never on a busy one. `is_spent` matches daily
  caps, balances and billing refusals; a per-minute 429 is the pacer's problem, and
  rotating on it would empty the whole drum inside a minute. Agents and the narrator each
  retry once on the next chamber.
- **`LEDGER` counts tokens per provider for this session only.** An earlier run may
  already have spent part of a daily budget, so `remaining_budget` is an upper bound and
  is documented as one.
- **`pick_narrator` chooses whoever has the most left**, because the narrator reads the
  whole transcript in one go and must not come out of the budget that just played the
  game. A provider with no stated budget is scored at `ASSUMED_UNKNOWN_BUDGET` minus what
  this session used — so it loses to a fresh stated budget and beats a worn-down one.
  Unknown is never reported as a number to anyone.
- **Model-per-seat is the experiment.** `--providers groq,google` assigns round-robin in
  the order given, the seating line names who got what, and the chronicle records
  `provider` and `model_id` per turn. The CLI says so out loud when every thinking seat
  is the same model, since that run compares nothing.

## Free-tier ceilings, learned the hard way

Groq's free tier caps **tokens per day at 200k**, not just per minute. A 3-agent,
27-hour game exhausted it and then lost 59 of 60 turns to `rate_limit_exceeded` — the
ring starved to extinction because nobody could act, which is a quota failure wearing
the costume of a result. `main.py` now warns when turns were lost, and says outright
when a quarter or more of them were. Read any outcome with a warning attached as an
artifact, not a finding.

Budget roughly: one turn costs several calls (the tool loop), so a 3-agent game runs
~2-4k tokens per game hour on gpt-oss-120b. Google's free tier has its own daily cap but
is far from exhausted; narrate with `--narrator google` when Groq has been playing.

## Provider status (2026-08-18)

`google` (gemini-3.7-flash) and `groq` (openai/gpt-oss-120b) answer on the current keys.
`deepseek` returns 402 Insufficient Balance and `cerebras` returns 402 Payment Required —
the keys authenticate and can list models, but cannot complete. Run `key_test.py` rather
than trusting this line.
