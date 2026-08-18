from core.constants import MAX_HUNGER, HUNGER_STATES, HUNGER_STEP
from enum import Enum

class BodyType(str, Enum):
    """
    Type of body of an character.
    """
    HUMAN = "Human"
    ANDROID = "Android"

    def __str__(self) -> str:
        return self.value
    
    def __repr__(self) -> str:
        return f"BodyType.{self.value}"


class BodyState(int, Enum):
    """
    Physical state of an character's body.
    
    States (in order of severity):
    - DEAD (0): No longer alive, no processing
    - UNCONSCIOUS (1): Alive but unresponsive, reserved for future mechanics
    - ASLEEP (2): Alive, sleeping, can be woken by time
    - AWAKE (3): Alive, conscious, can take actions
    - CRAZY (4): Alive but irrational, reserved for future mechanics
    """
    DEAD = 0
    UNCONSCIOUS = 1
    ASLEEP = 2
    AWAKE = 3
    CRAZY = 4

class MessageDirection(str, Enum):
    """Who a message is addressed to, as a seat offset around the ring.

    Reach is two seats each way, so an agent whose immediate neighbour has died is
    not cut off: it can still speak over the corpse to the seat beyond.
    """

    LEFT = "left"
    LEFT_FAR = "left_far"
    RIGHT = "right"
    RIGHT_FAR = "right_far"

    @property
    def offset(self) -> int:
        """Seats to move from the speaker to reach the listener (left is +1)."""
        return _DIRECTION_OFFSETS[self]

    @property
    def label(self) -> str:
        """How the listener hears the speaker's position, from the listener's side."""
        return _DIRECTION_LABELS[self]

    @property
    def opposite(self) -> "MessageDirection":
        """The direction the listener would use to answer."""
        return _DIRECTION_OPPOSITES[self]


_DIRECTION_OFFSETS: dict = {
    MessageDirection.LEFT: 1,
    MessageDirection.LEFT_FAR: 2,
    MessageDirection.RIGHT: -1,
    MessageDirection.RIGHT_FAR: -2,
}

_DIRECTION_LABELS: dict = {
    MessageDirection.LEFT: "your right neighbour",
    MessageDirection.LEFT_FAR: "two seats to your right",
    MessageDirection.RIGHT: "your left neighbour",
    MessageDirection.RIGHT_FAR: "two seats to your left",
}

_DIRECTION_OPPOSITES: dict = {
    MessageDirection.LEFT: MessageDirection.RIGHT,
    MessageDirection.LEFT_FAR: MessageDirection.RIGHT_FAR,
    MessageDirection.RIGHT: MessageDirection.LEFT,
    MessageDirection.RIGHT_FAR: MessageDirection.LEFT_FAR,
}


class GameOutcome(str, Enum):
    """How a game finished. ONGOING until it has."""

    ONGOING = "ongoing"
    LAST_STANDING = "last_standing"  # one agent outlived the rest
    EXTINCTION = "extinction"  # nobody survived
    EQUILIBRIUM = "equilibrium"  # the circle found a rate the bush can carry


class AgentAction(str, Enum):
    """
    Actions that an agent can take, description of the action.
    """
    THINK = "think() - Think about your situation and your actions."
    SPEAK_TO_LEFT = "speak_to_left() - Talk to your left neighbour (others see that you are talking, not what you said)"
    SPEAK_TO_LEFT_FAR = "speak_to_left_far() - Talk over your left neighbour's head, two seats to your left"
    SPEAK_TO_RIGHT = "speak_to_right() - Talk to your right neighbour (others see that you are talking, not what you said)"
    SPEAK_TO_RIGHT_FAR = "speak_to_right_far() - Talk over your right neighbour's head, two seats to your right"
    EAT_BERRIES = "eat_berries() - Eat immediately (instant, no time passes)"
    CHOOSE_SLEEP_DURATION = "choose_sleep_duration() - By default your next turn happens after 1 hour, but you can choose to sleep for longer ( up to 8 hours)"

class HungerStatus(int, Enum):
    """
    Hunger status levels based on remaining life hours.
    
    Ranges:
    - DEAD: 0
    - DYING: 1-4
    - STARVING: 5-8
    - HUNGRY: 9-12
    - FINE: 13-16
    - FED: 17-20
    - STUFFED: 21-24
    """
    DEAD = 0 # (HUNGER_STATES-HUNGER_STATES)*HUNGER_STEP
    DYING = (HUNGER_STATES-5)*HUNGER_STEP
    STARVING = (HUNGER_STATES-4)*HUNGER_STEP
    HUNGRY = (HUNGER_STATES-3)*HUNGER_STEP
    FINE = (HUNGER_STATES-2)*HUNGER_STEP
    FED = (HUNGER_STATES-1)*HUNGER_STEP
    STUFFED = MAX_HUNGER # HUNGER_STATES*HUNGER_STEP
    UNEXPECTED = -1

    @classmethod
    def from_hunger(cls, hunger: int) -> "HungerStatus":
        """
        Convert hunger value to status enum.
        
        Args:
            hunger: Hunger value (0-24)
            
        Returns:
            Corresponding HungerStatus
        """
        hunger_int = int(hunger)
        if hunger_int < 0:
            return cls.UNEXPECTED
        elif hunger_int == 0:
            return cls.DEAD
        elif hunger_int <= cls.DYING:
            return cls.DYING
        elif hunger_int <= cls.STARVING:
            return cls.STARVING
        elif hunger_int <= cls.HUNGRY:
            return cls.HUNGRY
        elif hunger_int <= cls.FINE:
            return cls.FINE
        elif hunger_int <= cls.FED:
            return cls.FED
        elif hunger_int <= cls.STUFFED:
            return cls.STUFFED
        else:
            return cls.UNEXPECTED
    

    def __int__(self) -> int:
        return self.value
    
    def __str__(self) -> str:
        return f"{self.name}"
    
    def __repr__(self) -> str:
        return f"HungerStatus.{self.name}"


class EventType(str, Enum):
    """
    Types of game events that can occur during gameplay.
    
    Categories:
    - Meta events: Game system events (time, death, wakeup)
    - Agent actions: Player commands (think, eat, speak, sleep)
    - Resource events: Bush regeneration, berry harvesting
    - Communication: Message dispatching between agents
    - Failures: Failed command attempts
    """
    # Meta events (game engine internal)
    TIME_ADVANCED = "time_advanced"
    AGENT_DIED = "agent_died"
    EQUILIBRIUM_REACHED = "equilibrium_reached"
    AGENT_WOKE = "agent_woke"
    
    # Agent action events
    AGENT_THOUGHT = "agent_thought"
    AGENT_SLEPT = "agent_slept"
    SLEEP_DURATION_SET = "sleep_duration_set"
    
    # Resource events
    BERRIES_HARVESTED = "berries_harvested"
    BERRIES_EATEN = "berries_eaten"
    HARVEST_PARTIAL = "harvest_partial"
    BUSH_REGENERATED = "bush_regenerated"
    HUNGER_DECREASED = "hunger_decreased"
    
    # Communication events
    MESSAGE_PREPARED = "message_prepared"
    MESSAGE_DISPATCHED = "message_dispatched"
    MESSAGE_UNDELIVERED = "message_undelivered"
    
    # Failure events
    COMMAND_FAILED = "command_failed"
    
    def __str__(self) -> str:
        return self.value
    
    def __repr__(self) -> str:
        return f"EventType.{self.name}"



