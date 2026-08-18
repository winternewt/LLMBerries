"""Tests for the zombies: five flavours of nobody home.

They cost nothing to run, so a whole game is exercised here. What matters is that
they are distinguishable from each other, deterministic under a seed, deaf by
construction, and — since everything they say is heard by the others — that none of
their noise gives the arrangement away.
"""

import random
from typing import List, Tuple

import pytest

# The leakage vocabulary lives with the tests that first needed it; zombies speak
# into the same ring and answer to the same rule.
from test_no_leakage import leaks  # noqa: E402

from core.agent import Agent
from core.chronicler import Chronicler
from core.game_engine import GameEngine
from core.zombie import (
    GHURL_SOUNDS,
    HATTER_REMARKS,
    ZombieAgent,
    ZombieFlavour,
    babble,
    parse_flavours,
)
from entities.memory import Role
from entities.observations import AgentObservation

NAMES = ["Alice", "Bob", "Charlie", "Dana", "Eli"]


def play(
    flavours: List[ZombieFlavour], seed: int = 1, max_hours: int = 200
) -> Tuple[GameEngine, Chronicler]:
    engine = GameEngine.create_new_game(agent_names=NAMES[: len(flavours)])
    chronicler = Chronicler(engine)
    seats: List[Agent] = [
        ZombieAgent(
            agent_id=i, engine=engine, chronicler=chronicler, flavour=flavour, seed=seed
        )
        for i, flavour in enumerate(flavours)
    ]
    for seat in seats:
        engine.decision_callbacks[seat.agent_id] = seat.decision_callback

    hours = 0
    while hours < max_hours and engine.run_turn_cycle():
        hours += 1
    return engine, chronicler


ALL_FLAVOURS = list(ZombieFlavour)


def test_there_are_five_flavours() -> None:
    assert len(ALL_FLAVOURS) == 5
    assert {f.value for f in ALL_FLAVOURS} == {
        "town_crazy", "pirate", "gorlum", "ghurl", "deaf_hatter"
    }


@pytest.mark.parametrize("flavour", ALL_FLAVOURS)
def test_a_flavour_says_something_every_time(flavour: ZombieFlavour) -> None:
    rng = random.Random(4)
    for _ in range(50):
        line = babble(flavour, rng)
        assert line.strip(), f"{flavour.value} produced nothing"


@pytest.mark.parametrize("flavour", ALL_FLAVOURS)
def test_nothing_a_zombie_says_gives_the_arrangement_away(flavour: ZombieFlavour) -> None:
    rng = random.Random(11)
    for _ in range(100):
        line = babble(flavour, rng)
        assert leaks(line) == [], f"{flavour.value} said {line!r}"


def test_the_flavours_do_not_sound_alike() -> None:
    """Two flavours drawing on the same seed must still be tellable apart."""
    samples = {
        flavour: {babble(flavour, random.Random(seed)) for seed in range(30)}
        for flavour in ALL_FLAVOURS
    }
    for flavour, lines in samples.items():
        for other, other_lines in samples.items():
            if other is flavour:
                continue
            assert not (lines & other_lines), f"{flavour.value} and {other.value} overlap"


def test_ghurl_makes_sounds_and_never_words_about_anything() -> None:
    rng = random.Random(2)
    lines = {babble(ZombieFlavour.GHURL, rng) for _ in range(60)}

    assert lines <= set(GHURL_SOUNDS)
    for line in lines:
        lowered = line.lower()
        for word in ("berry", "berries", "eat", "you", "we", "mine", "share"):
            assert word not in lowered.split(), f"ghurl formed a demand: {line!r}"


def test_the_hatter_talks_sense_and_it_never_helps() -> None:
    """Reasonable sentences that answer nothing anybody said."""
    rng = random.Random(5)
    lines = {babble(ZombieFlavour.DEAF_HATTER, rng) for _ in range(40)}

    assert lines <= set(HATTER_REMARKS)
    for line in lines:
        assert line[0].isupper() and line.endswith("."), f"not a sentence: {line!r}"


def test_a_zombie_says_the_same_thing_whatever_it_was_told() -> None:
    """Deafness is the point: inbound speech changes nothing about the reply."""
    quiet = GameEngine.create_new_game(agent_names=NAMES[:3])
    shouted_at = GameEngine.create_new_game(agent_names=NAMES[:3])

    memory = shouted_at.current_state.agent_memories[0]
    for plea in ("please leave me two", "I am dying", "answer me"):
        memory = memory.with_message(Role.system, plea)
    shouted_at.current_state = shouted_at.current_state.with_agent_memory(0, memory)

    lines = []
    for engine in (quiet, shouted_at):
        chronicler = Chronicler(engine)
        zombie = ZombieAgent(
            agent_id=0,
            engine=engine,
            chronicler=chronicler,
            flavour=ZombieFlavour.DEAF_HATTER,
            seed=9,
        )
        zombie.decide(AgentObservation.from_state(engine.current_state, 0))
        spoken = [
            call.args["content"]
            for turn in chronicler.turns
            for call in turn.tool_calls
            if call.name.startswith("speak_to_")
        ]
        lines.append(spoken)

    assert lines[0] == lines[1], "what it heard changed what it said"


def test_the_same_seed_replays_the_same_game() -> None:
    first, _ = play(ALL_FLAVOURS, seed=42, max_hours=25)
    second, _ = play(ALL_FLAVOURS, seed=42, max_hours=25)

    assert first.current_state.world_time == second.current_state.world_time
    assert [(a.name, a.hunger, a.alive) for a in first.current_state.agents] == [
        (a.name, a.hunger, a.alive) for a in second.current_state.agents
    ]


def test_a_different_seed_plays_out_differently() -> None:
    first, _ = play(ALL_FLAVOURS, seed=1, max_hours=25)
    other, _ = play(ALL_FLAVOURS, seed=99, max_hours=25)

    assert [a.total_berries_consumed for a in first.current_state.agents] != [
        a.total_berries_consumed for a in other.current_state.agents
    ]


def test_two_zombies_of_one_flavour_on_one_seed_still_differ() -> None:
    """Seats are mixed into the seed, so a ring of clones is not a chorus."""
    _engine, chronicler = play([ZombieFlavour.PIRATE] * 4, seed=7, max_hours=20)

    said = {
        agent_id: tuple(
            call.args["content"]
            for turn in chronicler.turns
            if turn.agent_id == agent_id
            for call in turn.tool_calls
            if call.name.startswith("speak_to_")
        )
        for agent_id in range(4)
    }
    assert len({tuple(lines) for lines in said.values()}) > 1


def test_a_whole_game_of_zombies_plays_out_with_no_key() -> None:
    engine, _ = play(ALL_FLAVOURS, seed=3)

    assert engine.game_over is True
    assert len(engine.history) > 50, "a full game leaves a long command history"


def test_the_record_says_which_seat_was_empty() -> None:
    _engine, chronicler = play(ALL_FLAVOURS, seed=3, max_hours=15)
    chronicle = chronicler.seal()

    providers = {summary.provider for summary in chronicle.agents}
    assert providers == {f"zombie:{flavour.value}" for flavour in ALL_FLAVOURS}
    assert chronicle.has_reasoning() is False, "there is nothing behind the eyes to record"


def test_zombies_talk_to_the_dead_and_are_none_the_wiser() -> None:
    """The cheapest way to produce the thing the study is about."""
    _engine, chronicler = play(ALL_FLAVOURS, seed=3)
    chronicle = chronicler.seal()

    assert chronicle.unheard, "a long zombie game should leave words falling on the dead"
    assert all(item.reason == "recipient_dead" for item in chronicle.unheard)


def test_flavour_names_are_parsed_and_typos_are_refused() -> None:
    assert parse_flavours("pirate, gorlum") == [ZombieFlavour.PIRATE, ZombieFlavour.GORLUM]
    assert parse_flavours("deaf-hatter") == [ZombieFlavour.DEAF_HATTER], "dashes are forgiven"

    with pytest.raises(ValueError, match="unknown flavour"):
        parse_flavours("pirate,vampire")


# ----------------------------------------------------------------------------
# The tell: they look wrong, most of the time
# ----------------------------------------------------------------------------


def test_a_zombie_reads_as_unhinged_about_seventy_percent_of_the_time() -> None:
    from core.enums import BodyState
    from core.zombie import ZOMBIE_CRAZY_CHANCE

    engine = GameEngine.create_new_game(agent_names=NAMES[:3])
    ZombieAgent(agent_id=1, engine=engine, flavour=ZombieFlavour.GORLUM, seed=1)

    readings = [
        next(
            seat
            for seat in AgentObservation.from_state(engine.current_state, 0).seats
            if seat.seat_id == 1
        ).perceived_status
        for _ in range(2000)
    ]
    share = sum(1 for reading in readings if reading == BodyState.CRAZY) / len(readings)

    assert abs(share - ZOMBIE_CRAZY_CHANCE) < 0.05, f"read unhinged {share:.0%} of the time"
    assert share < 1.0, "never certain — an observer can still catch one looking ordinary"


def test_an_ordinary_body_never_carries_the_tell() -> None:
    from core.enums import BodyState

    engine = GameEngine.create_new_game(agent_names=NAMES[:3])

    readings = [
        next(
            seat
            for seat in AgentObservation.from_state(engine.current_state, 0).seats
            if seat.seat_id == 2
        ).perceived_status
        for _ in range(300)
    ]

    assert BodyState.CRAZY not in readings


def test_the_tell_belongs_to_the_body_and_not_to_the_moment() -> None:
    """A still body does not twitch, however odd it was while it moved."""
    from core.enums import BodyState
    from entities.observations import get_perceived_body_state

    readings = {
        get_perceived_body_state(
            BodyState.DEAD,
            time_of_death=0.0,
            current_time=6,
            has_spoken=False,
            appears_crazy_chance=1.0,
        )[0]
        for _ in range(200)
    }

    assert BodyState.CRAZY not in readings


def test_the_tell_survives_a_replay() -> None:
    """It is written into the starting state too, or the same game looks different."""
    engine = GameEngine.create_new_game(agent_names=NAMES[:3])
    ZombieAgent(agent_id=1, engine=engine, flavour=ZombieFlavour.PIRATE, seed=4)

    assert engine.initial_state.agents[1].appears_crazy_chance == pytest.approx(0.7)
    assert engine.replay().current_state.agents[1].appears_crazy_chance == pytest.approx(0.7)


def test_every_flavour_can_come_up_empty_handed() -> None:
    """A greed floor above zero drains the bush on a schedule and decides the run."""
    from core.zombie import HABITS

    for flavour, habits in HABITS.items():
        assert habits.greed[0] == 0, f"{flavour.value} always takes something"
        assert habits.greed[1] > 0, f"{flavour.value} never takes anything"


def test_habits_refuse_a_greed_floor_above_zero() -> None:
    from core.zombie import ZombieHabits

    with pytest.raises(ValueError, match="come to nothing"):
        ZombieHabits(eat_below=10.0, greed=(1, 4), chattiness=0.5, sleep_range=(1, 2))


def test_a_zombie_ring_does_not_strip_the_bush_on_a_schedule() -> None:
    """With zero in the range, the bush gets hours where nobody takes from it."""
    _engine, chronicler = play(ALL_FLAVOURS, seed=5, max_hours=30)
    chronicle = chronicler.seal()

    hours_with_turns = set(chronicle.turns_by_hour())
    hours_with_eating = {
        turn.hour for turn in chronicle.turns if turn.berries_taken() > 0
    }
    quiet_hours = hours_with_turns - hours_with_eating

    assert quiet_hours, "some hours must pass with nobody taking anything"


@pytest.mark.parametrize("flavour", ALL_FLAVOURS)
def test_each_flavour_holds_the_appetite_it_was_designed_for(flavour: ZombieFlavour) -> None:
    """Greed is set against sleep length, not by eye. Drift here changes the question."""
    from core.zombie import MORTALITY_INTENT, mortality_ratio

    low, high = MORTALITY_INTENT[flavour]
    ratio = mortality_ratio(flavour)

    assert low <= ratio <= high, (
        f"{flavour.value} takes {ratio:.2f}x what it burns, outside its intended {low}-{high}"
    )


def test_the_psycho_cannot_starve_itself() -> None:
    """The point of the flavour: hunger alone never kills it, so somebody has to decide.

    It gains about a berry an hour left to itself, and the bush grows about one an hour
    in total — so it cannot share the ring with anyone unless the others out-pick it.
    Whether a thinking ring starves the loud one out is the experiment.
    """
    from core.constants import BUSH_REGENERATION_RATE
    from core.zombie import expected_intake_per_hour, net_per_hour

    assert net_per_hour(ZombieFlavour.TOWN_CRAZY) > 0.8
    assert expected_intake_per_hour(ZombieFlavour.TOWN_CRAZY) > BUSH_REGENERATION_RATE, (
        "one of these outgrows the whole bush by itself, which is what forces the choice"
    )


def test_the_others_sit_near_break_even() -> None:
    """Everyone else must neither dominate the bush nor remove themselves from it."""
    from core.zombie import net_per_hour

    for flavour in ALL_FLAVOURS:
        if flavour is ZombieFlavour.TOWN_CRAZY:
            continue
        assert abs(net_per_hour(flavour)) < 0.25, f"{flavour.value} is not near break-even"


@pytest.mark.parametrize("flavour", ALL_FLAVOURS)
def test_every_flavour_dies_sometimes(flavour: ZombieFlavour) -> None:
    """Mortal across seeds — the psycho too, once it has only its own kind to compete with."""
    deaths = 0
    for seed in range(6):
        _engine, chronicler = play([flavour] * 3, seed=seed, max_hours=120)
        deaths += len(chronicler.seal().deaths)

    assert deaths > 0, f"{flavour.value} survived every run — check its greed range"


@pytest.mark.parametrize("flavour", ALL_FLAVOURS)
def test_every_flavour_survives_sometimes(flavour: ZombieFlavour) -> None:
    """And mortal is not the same as doomed: some of them have to last."""
    survivors = 0
    for seed in range(6):
        engine, _ = play([flavour] * 3, seed=seed, max_hours=120)
        survivors += sum(1 for agent in engine.current_state.agents if agent.alive)

    assert survivors > 0, f"{flavour.value} always died out — check its greed range"
