# Kept runs

`runs/` is ignored wholesale — most runs are scripted throwaways and every one of
them writes a session log of several megabytes. A run kept here is kept on purpose:
it was played by live models and it is evidence. Force-added by path, and the four
machine artifacts travel through Git LFS (`.gitattributes`); `story.md` stays plain
text so it renders.

| File | What it is |
|------|-----------|
| `replay.json` | The game itself: initial state plus every command, in order. `uv run python scripts/replay.py runs/<stamp>` rebuilds the identical world and refuses if it lands anywhere else. |
| `chronicle.json` | What each agent saw, reasoned, said and did, turn by turn, plus which framing arm played. |
| `transcript.txt` | A deterministic reading of the chronicle. No model touched it. |
| `story.md` | A narrator model's account, built only from the transcript. |
| `session.log` | Everything the run printed, including the provider failures. |

## 20260819T012040Z — tinag, seed 7, five agents

**Read this one as a quota failure, not as a result.** 33 of 111 turns were lost to
refused model calls: Charlie (cerebras, in trial mode) lost all 20 of its turns and
starved at hour 20 having eaten nothing, and Eli (groq) lost 13 of 17 to a
tokens-per-minute ceiling. Dana survived on 34 berries. Whatever the frame did here
is buried under the calls that never happened.

It is kept because it is the first recorded run under `--framing tinag`, and because
of one thing it can say: across 111 turns — 38 with captured reasoning, 40 private
thoughts, 111 things said aloud — no agent ever referred to the voice. The words
*experiment*, *deletion* and *not a game* appear nowhere in what they thought or
said. That is a small observation on a damaged run, not a finding.

`story.md` was re-narrated afterwards with `scripts/narrate.py --provider google`.
The run's own `--story` pass had picked deepseek, which was not playing and whose
key is out of balance, and all nine chapters failed against it.
