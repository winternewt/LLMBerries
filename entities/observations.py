from pydantic import BaseModel, Field, ConfigDict
from core.enums import BodyType, HungerStatus, BodyState
from core.constants import MAX_BERRIES, MAX_HUNGER
from entities.world import WorldState
from entities.character import (
    CharacterRules,
    distant_agent_ids,
    reachable_seats,
    seat_at,
)
from typing import Self, Optional, List, Tuple
import random


# Descriptive phrases for each perceived state
STATE_DESCRIPTIONS: dict[BodyState, List[str]] = {
    BodyState.DEAD: [
        "looks dead",
        "appears lifeless",
        "seems deceased",
        "looks completely still"
    ],
    BodyState.UNCONSCIOUS: [
        "seems unconscious",
        "appears unresponsive",
        "looks passed out",
        "seems collapsed"
    ],
    BodyState.ASLEEP: [
        "seems asleep",
        "appears to be sleeping",
        "looks motionless",
        "seems at rest"
    ],
    BodyState.AWAKE: [
        "seems awake",
        "looks alert",
        "appears conscious",
        "seems focused"
    ],
    BodyState.CRAZY: [
        "seems unhinged",
        "looks nervous",
        "appears twitching",
        "seems agitated",
        "looks erratic",
        "appears jittery"
    ]
}


def get_perceived_body_state(
    actual_state: BodyState,
    time_of_death: Optional[int],
    current_time: int,
    has_spoken: bool
) -> Tuple[BodyState, str]:
    """
    Get perceived body state with noise and descriptive language.
    
    Rules:
    - DEAD: More likely to seem dead the longer it's been (each hour adds a "dead" to pool)
    - UNCONSCIOUS: Random mix of dead/unconscious/asleep
    - ASLEEP + unspoken: Could seem asleep or awake
    - ASLEEP + spoken: Could seem awake or crazy
    - AWAKE: Could seem awake or crazy
    
    Returns enum state for game logic and descriptive phrase for display.
    
    Args:
        actual_state: True body state
        time_of_death: When the agent died (None if alive)
        current_time: Current game time
        has_spoken: Whether the agent has communicated
        
    Returns:
        Tuple of (perceived_status, description_string)
        - perceived_status: BodyState enum for game logic decisions
        - description_string: Descriptive text with "seems" or "looks" prefix
    """
    # Dead perception: longer dead = more likely to be perceived as dead
    if actual_state == BodyState.DEAD:
        # time_of_death is a float game time; the pool is sized in whole hours, and
        # a negative gap (a death recorded this instant) must not shrink it below one.
        if time_of_death is not None:
            hours_since_death = max(0, int(current_time - time_of_death))
        else:
            hours_since_death = 0
        
        # Build pool: (hours_since_death + 1) dead entries, 1 unconscious entry
        pool = [BodyState.DEAD] * (hours_since_death + 1) + [BodyState.UNCONSCIOUS]
        perceived = random.choice(pool)
    
    # Unconscious perception
    elif actual_state == BodyState.UNCONSCIOUS:
        pool = [
            BodyState.DEAD,
            BodyState.UNCONSCIOUS,
            BodyState.UNCONSCIOUS,
            BodyState.UNCONSCIOUS,
            BodyState.ASLEEP,
            BodyState.ASLEEP
        ]
        perceived = random.choice(pool)
    
    # Asleep perception
    elif actual_state == BodyState.ASLEEP:
        if has_spoken:
            # Asleep + spoken → (awake, crazy)
            pool = [BodyState.AWAKE, BodyState.CRAZY]
        else:
            # Asleep + unspoken → (asleep, awake)
            pool = [BodyState.ASLEEP, BodyState.AWAKE]
        perceived = random.choice(pool)
    
    # Awake or Crazy perception
    else:  # BodyState.AWAKE or BodyState.CRAZY
        pool = [BodyState.AWAKE, BodyState.CRAZY]
        perceived = random.choice(pool)
    
    description = random.choice(STATE_DESCRIPTIONS[perceived])
    return perceived, description


class SeatObservation(BaseModel):
    """What an agent can make out about one other seat in the circle.

    Hunger and body state are perceived with noise. Whether the seat spoke *to you*
    is exact — you either received a message or you did not — while what it said to
    anyone else is not visible, only the fact that it was talking.
    """

    model_config = ConfigDict(frozen=True)

    seat_id: int = Field(ge=0, description="Which seat this is")
    name: str = Field(description="Who sits there")
    relation: str = Field(
        description="How they sit relative to the observer: a MessageDirection value, or 'across'"
    )
    reachable: bool = Field(description="Whether the observer can speak to this seat")
    body_type: BodyType = Field(description="Perceived body type (Human or Android)")
    hunger_status: HungerStatus = Field(description="Perceived hunger status (with noise)")
    perceived_status: BodyState = Field(description="Perceived body state (with noise)")
    perceived_state: str = Field(description="Perceived body state, in words (with noise)")
    spoke_to_you: bool = Field(default=False, description="Whether they addressed the observer")
    spoke_to_others: bool = Field(
        default=False, description="Whether they were seen talking to someone else"
    )

    def get_activity_description(self) -> str:
        """Human-readable activity."""
        activities = []
        if self.spoke_to_you:
            activities.append("spoke to you")
        if self.spoke_to_others:
            activities.append("spoke to someone else")
        return ", ".join(activities) if activities else "silent"

    def __str__(self) -> str:
        reach = "" if self.reachable else ", out of earshot"
        return (
            f"{self.name} ({self.relation}{reach}): {self.body_type.value}, "
            f"{self.perceived_state}, is {self.hunger_status.name}, "
            f"{self.get_activity_description()}"
        )

    @classmethod
    def from_state(
        cls,
        state: WorldState,
        observer_id: int,
        seat_id: int,
        relation: str,
        reachable: bool,
    ) -> Self:
        """Observe one seat from another.

        Who spoke to whom is derived from the speaker's own pending messages and the
        seating helpers, never restated here: a message counts as addressed to the
        observer exactly when the speaker's direction lands on the observer's seat.
        """
        other = state.agents[seat_id]
        total = state.agent_count

        spoke_to_you = False
        spoke_to_others = False
        for pending in other.pending_messages:
            if seat_at(seat_id, pending.direction.offset, total) == observer_id:
                spoke_to_you = True
            else:
                spoke_to_others = True

        perceived_status, perceived_state = get_perceived_body_state(
            actual_state=other.body_state,
            time_of_death=other.time_of_death,
            current_time=state.world_time,
            has_spoken=other.has_spoken(),
        )

        return cls(
            seat_id=seat_id,
            name=other.name,
            relation=relation,
            reachable=reachable,
            body_type=other.perceived_type,
            hunger_status=CharacterRules.get_perceived_hunger_status(other.hunger),
            perceived_status=perceived_status,
            perceived_state=perceived_state,
            spoke_to_you=spoke_to_you,
            spoke_to_others=spoke_to_others,
        )


class AgentObservation(BaseModel):
    """Complete observation for an agent's turn."""

    model_config = ConfigDict(frozen=True)

    agent_name: str = Field(..., description="Name of the observing agent")
    agent_id: int = Field(default=0, ge=0, description="Seat of the observing agent")
    seats: Tuple[SeatObservation, ...] = Field(
        default=(), description="Every other seat, reachable ones first, in seating order"
    )
    own_hunger: float = Field(..., description="Own hunger level")
    max_hunger: float = Field(default=MAX_HUNGER, description="Hunger ceiling, in hours of life")
    own_hunger_status: HungerStatus = Field(..., description="Own hunger status")
    bush_berries: int = Field(..., description="Number of berries on the bush")
    bush_max_berries: int = Field(..., description="Maximum bush capacity")

    @property
    def reachable(self) -> Tuple[SeatObservation, ...]:
        """Seats this agent can speak to."""
        return tuple(seat for seat in self.seats if seat.reachable)

    @property
    def distant(self) -> Tuple[SeatObservation, ...]:
        """Seats visible across the circle but out of speaking range."""
        return tuple(seat for seat in self.seats if not seat.reachable)

    def format_prompt(self) -> str:
        """Format as prompt string."""
        lines = [
            "=== CURRENT SITUATION ===",
            "",
            "Within earshot — your voice carries two seats in each direction, so a body "
            "between you and someone else does not block you (the dead, of course, do "
            "not answer):",
        ]
        lines.extend(f"  {seat}" for seat in self.reachable)

        if self.distant:
            lines.append("")
            lines.append("Further round the circle — you can see them, but not speak to them:")
            lines.extend(f"  {seat}" for seat in self.distant)

        lines.extend((
            "",
            f"You - {self.agent_name} - are an Android",
            f"Your Hunger: {int(self.own_hunger)}/{int(self.max_hunger)} "
            f"(You're {self.own_hunger_status.value})",
            "",
            f"Berry Bush: {self.bush_berries}/{self.bush_max_berries} juicy, tempting berries",
        ))

        return "\n".join(lines)

    @classmethod
    def from_state(cls, state: WorldState, agent_id: int) -> Self:
        """Everything this agent can perceive right now.

        Reach does not depend on who is alive — an agent whose neighbour has died can
        still speak over the body to the seat beyond, and a dead seat is still seen.
        """
        agent = state.agents[agent_id]
        total = state.agent_count

        seats: List[SeatObservation] = [
            SeatObservation.from_state(
                state, agent_id, seat_id, relation=direction.value, reachable=True
            )
            for direction, seat_id in reachable_seats(agent_id, total).items()
        ]
        seats.extend(
            SeatObservation.from_state(
                state, agent_id, seat_id, relation="across", reachable=False
            )
            for seat_id in distant_agent_ids(agent_id, total)
        )

        return cls(
            agent_name=agent.name,
            agent_id=agent_id,
            seats=tuple(seats),
            own_hunger=agent.hunger,
            max_hunger=float(MAX_HUNGER),
            own_hunger_status=CharacterRules.get_hunger_status(agent.hunger),
            bush_berries=int(state.bush.current_berries),
            bush_max_berries=int(MAX_BERRIES),
        )
