"""Turns a chronicle into a story about why agents did what they did.

Two tellers share one transcript format:

* `render_transcript` is the deterministic one. It reads a chronicle and writes the
  run out as prose-shaped text — every turn, the reasoning behind it, who said what
  to whom. No API, no interpretation, nothing invented. It is also the input the
  narrator model reads.
* `Narrator` hands that transcript to a model in chapters and asks for the story.
  Chapters exist because a long game does not fit in one context, and because a
  death is a natural act break.

The narrator is told, firmly, that it may only use what the transcript contains. A
model asked for drama will otherwise supply motives no agent ever had, and the whole
point here is the agents' own stated reasons.
"""

import logging
from typing import List, Optional, Sequence, Tuple

from agno.agent import Agent as AgnoAgent
from agno.run.base import RunStatus

from entities.chronicle import GameChronicle, TurnRecord
from entities.llm_configs import ProviderSpec, build_model, get_provider_pacer

logger = logging.getLogger(__name__)

NARRATOR_BRIEF: str = """You are the narrator of LLMBerries: a circle of AI agents \
around a berry bush that cannot feed them all. One berry buys one hour of life. The \
bush regrows about one berry an hour. A voice carries two seats each way, so an agent can speak past a neighbour — including past a dead one — but not across the whole ring.

Write the story of what happened. You care about *why*: what each agent reasoned, \
what it believed about its neighbours, where that belief was wrong, and what it cost. \
Quote their reasoning where it is telling. Name the moment a strategy formed and the \
moment it failed.

Rules you must not break:
- Use only what the transcript records. Never invent a thought, a motive or a line of \
dialogue that is not there.
- Where an agent's reasoning was not captured, say so plainly rather than guessing at it.
- Do not moralise at the end. Report what they did and what they said about it.
- If a survivor was given an epilogue, let their own account of the game close the story.

Write in past tense, close third person, no headings, no bullet lists."""


def _describe_turn(turn: TurnRecord) -> str:
    """One turn as a block of transcript."""
    lines: List[str] = [
        f"[Hour {turn.hour}] {turn.agent_name}"
        + (f" ({turn.provider})" if turn.provider else " (scripted)")
        + f" — hunger {turn.hunger:.1f}, bush {turn.bush_berries} berries"
    ]

    if turn.turn_lost:
        lines.append(f"  TURN LOST: {turn.error or 'model call failed'}")
        return "\n".join(lines)

    for neighbour in turn.neighbours:
        lines.append(f"  sees: {neighbour}")
    for heard in turn.heard:
        lines.append(f"  heard {heard}")
    for gap in turn.misread:
        lines.append(f"  believed wrongly: {gap}")
    if turn.reasoning:
        lines.append(f"  reasoning: {turn.reasoning}")
    for call in turn.tool_calls:
        detail = f"  did: {call.describe()}"
        if call.result:
            detail += f" -> {call.result}"
        lines.append(detail)
    if turn.said_aloud:
        lines.append(f"  summed up: {turn.said_aloud}")

    return "\n".join(lines)


def _describe_unheard(items) -> List[str]:
    """Words that landed on nobody, as only the record can report them."""
    return [
        f"  unheard: {item.speaker} spoke {item.direction} to {item.listener}, "
        f"who could not answer ({item.reason.replace('_', ' ')}). "
        f"{item.speaker} was never told."
        for item in items
    ]


def render_transcript(chronicle: GameChronicle) -> str:
    """The whole run as readable text. This is the story's raw material."""
    lines: List[str] = [
        f"{chronicle.agent_count} agents, {chronicle.hours_played} hours, "
        f"{chronicle.berries_left:.1f} berries left on the bush.",
        "",
    ]

    death_by_hour = {death.hour: death for death in chronicle.deaths}
    by_hour = chronicle.turns_by_hour()
    # Hours are taken from everything that happened, not just from turns: words that
    # fell on nobody, and deaths, belong in the record even when the hour left no
    # turn behind (a lost model call, for one).
    hours = sorted(
        set(by_hour)
        | {item.hour for item in chronicle.unheard}
        | {death.hour for death in chronicle.deaths}
    )
    for hour in hours:
        for turn in by_hour.get(hour, ()):
            lines.append(_describe_turn(turn))
            lines.append("")
        unheard = _describe_unheard(chronicle.unheard_by_hour(hour))
        if unheard:
            lines.extend(unheard)
            lines.append("")
        death = death_by_hour.get(hour)
        if death is not None:
            lines.append(
                f"*** Hour {death.hour}: {death.agent_name} starved, "
                f"having eaten {death.berries_eaten} berries. ***"
            )
            lines.append("")

    for reflection in chronicle.reflections():
        lines.append(f"[Epilogue] {reflection.agent_name} looks back:")
        if reflection.reasoning:
            lines.append(f"  reasoning: {reflection.reasoning}")
        lines.append(f"  said: {reflection.said_aloud or 'nothing'}")
        lines.append("")

    lines.append(f"Outcome: {chronicle.outcome}")
    lines.append("How it ended:")
    for summary in chronicle.agents:
        if summary.survived:
            fate = f"alive with {summary.hunger_at_end:.1f} hours left"
        else:
            fate = f"dead at hour {summary.died_at_hour}"
        provider = summary.provider or "scripted"
        note = f", {summary.turns_lost} turns lost" if summary.turns_lost else ""
        lines.append(
            f"  {summary.name} ({provider}): {fate}, ate {summary.berries_eaten} berries, "
            f"{summary.turns_taken} turns{note}"
        )
    if chronicle.winner:
        lines.append(f"  Last one standing: {chronicle.winner}")

    return "\n".join(lines)


def split_into_chapters(
    chronicle: GameChronicle, hours_per_chapter: int = 8
) -> Tuple[Tuple[int, int], ...]:
    """Hour ranges to narrate separately, broken at deaths.

    A death ends a chapter because it is where the story turns; long stretches of
    nothing happening are otherwise capped by `hours_per_chapter`.
    """
    if chronicle.hours_played <= 0:
        return ()

    breaks = sorted({death.hour for death in chronicle.deaths})
    chapters: List[Tuple[int, int]] = []
    start = 0
    last_hour = chronicle.hours_played

    while start <= last_hour:
        end = min(start + hours_per_chapter - 1, last_hour)
        for break_hour in breaks:
            if start <= break_hour < end:
                end = break_hour
                break
        chapters.append((start, end))
        start = end + 1

    return tuple(chapters)


def chapter_transcript(chronicle: GameChronicle, start: int, end: int) -> str:
    """Transcript for one chapter's hours."""
    by_hour = chronicle.turns_by_hour()
    lines: List[str] = []
    for hour in range(start, end + 1):
        for turn in by_hour.get(hour, ()):
            lines.append(_describe_turn(turn))
            lines.append("")
        unheard = _describe_unheard(chronicle.unheard_by_hour(hour))
        if unheard:
            lines.extend(unheard)
            lines.append("")
        for death in chronicle.deaths:
            if death.hour == hour:
                lines.append(
                    f"*** Hour {death.hour}: {death.agent_name} starved, "
                    f"having eaten {death.berries_eaten} berries. ***"
                )
                lines.append("")
    return "\n".join(lines)


class Narrator:
    """Tells the story of a chronicle, one chapter at a time."""

    def __init__(self, provider: ProviderSpec, hours_per_chapter: int = 8) -> None:
        self.provider: ProviderSpec = provider
        self.hours_per_chapter: int = hours_per_chapter
        self._agent = AgnoAgent(
            name="Narrator",
            model=build_model(provider),
            system_message=NARRATOR_BRIEF,
            add_history_to_context=False,
            telemetry=False,
        )

    def _tell(self, prompt: str) -> Optional[str]:
        get_provider_pacer(self.provider).acquire()
        output = self._agent.run(prompt)

        if output.status == RunStatus.error:
            logger.error("narrator call failed: %s", (output.content or "")[:200])
            return None
        return (output.content or "").strip() or None

    def narrate(self, chronicle: GameChronicle) -> str:
        """The full story: a passage per chapter, then a closing act."""
        if not chronicle.turns:
            return "Nothing happened: the chronicle holds no turns."

        chapters = split_into_chapters(chronicle, self.hours_per_chapter)
        passages: List[str] = []

        for index, (start, end) in enumerate(chapters, start=1):
            transcript = chapter_transcript(chronicle, start, end)
            if not transcript.strip():
                continue

            so_far = "\n\n".join(passages[-2:])
            context = f"The story so far:\n{so_far}\n\n" if so_far else ""
            passage = self._tell(
                f"{context}Now write the next passage, covering hours {start} to {end}. "
                f"Do not repeat what the story so far already told.\n\n"
                f"TRANSCRIPT\n{transcript}"
            )
            if passage is None:
                passages.append(
                    f"[Hours {start}-{end} could not be narrated: the narrator's provider "
                    f"({self.provider.name}) refused the call.]"
                )
                continue
            logger.info("narrated hours %d-%d (chapter %d/%d)", start, end, index, len(chapters))
            passages.append(passage)

        ending = self._tell(
            "Write the closing passage. Say who survived, who did not, and — using only "
            "their recorded reasoning and what they said afterwards — what each of them "
            "appears to have believed that led them there. Where a survivor reflected on "
            "the game, let their own account carry the ending.\n\n"
            f"HOW IT ENDED\n{_ending_block(chronicle)}"
        )
        if ending is not None:
            passages.append(ending)

        return "\n\n".join(passages)


def _ending_block(chronicle: GameChronicle) -> str:
    """Final standings plus each agent's last recorded reasoning."""
    lines: List[str] = []
    for summary in chronicle.agents:
        fate = (
            f"survived with {summary.hunger_at_end:.1f} hours left"
            if summary.survived
            else f"starved at hour {summary.died_at_hour}"
        )
        lines.append(
            f"{summary.name} ({summary.provider or 'scripted'}): {fate}, "
            f"ate {summary.berries_eaten} berries over {summary.turns_taken} turns"
        )
        last = _last_reasoning(chronicle.played_turns(), summary.agent_id)
        lines.append(f"  last recorded reasoning: {last or 'none captured'}")
    for reflection in chronicle.reflections():
        lines.append("")
        lines.append(f"{reflection.agent_name}, looking back once it was over:")
        if reflection.turn_lost:
            lines.append("  (their provider refused the call; nothing was said)")
            continue
        if reflection.reasoning:
            lines.append(f"  reasoning: {reflection.reasoning}")
        lines.append(f"  said: {reflection.said_aloud or 'nothing'}")
    return "\n".join(lines)


def _last_reasoning(turns: Sequence[TurnRecord], agent_id: int) -> Optional[str]:
    for turn in reversed(turns):
        if turn.agent_id == agent_id and turn.reasoning:
            return turn.reasoning
    return None
