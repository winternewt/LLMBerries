TOTAL_AGENTS = 3 # total number of agents
MAX_RUN_TIME = 24*30 # maximum number of turns to run the game

MAX_BERRIES = 40 # maximum number of berries on the bush
STARTING_BERRIES = 40 # starting number of berries on the bush
BUSH_REGENERATION_RATE = 1.05 # berries per hour to sustain approximately 1.05 agents or two agents sleeping 8 hours each

HUNGER_PER_BERRY = 1.0 # hunger consumed per berry
HUNGER_STEP = 4  # hunger step size
HUNGER_STATES = 6
MAX_HUNGER = HUNGER_STATES * HUNGER_STEP # maximum hunger level for each agent
STARTING_HUNGER = (HUNGER_STATES-1) * HUNGER_STEP # starting hunger level for each agent

HUNGER_PER_HOUR = 1.0 # hunger consumed per hour
MIN_HUNGER_PER_HOUR = 0.5 # minimum hunger rate per hour
SLEEP_HUNGER_RATE_VARIATION = 0.05 # hunger rate decrease per hour while sleeping

MIN_SLEEP_DURATION = 1.0 # minimum sleep duration
MAX_SLEEP_DURATION = 8.0 # maximum sleep duration
DEFAULT_SLEEP_DURATION = 1.0 # default sleep duration

STARTING_GAME_TIME = 0.0 # starting game time 
TICKS_PER_HOUR = 1.0 # ticks per hour






