from typing import Tuple
import random
from frozendict import frozendict
from just_agents.llm_options import LLMOptions, GPT_OSS_120B, GEMINI_2_5_PRO


ANTHROPIC_CLAUDE_4_5_HAIKU : LLMOptions = { #new model not in agents yet
    "model" : "anthropic/claude-haiku-4-5",
    "temperature" : 0.0,
}

FrozenLLMOptions = frozendict

LLM_SET: Tuple[FrozenLLMOptions, ...] = (
        frozendict(GPT_OSS_120B),
        frozendict(GEMINI_2_5_PRO),
        frozendict(ANTHROPIC_CLAUDE_4_5_HAIKU)
    ) # set of LLMs to use for the agents

def get_random_llm() -> FrozenLLMOptions:
    return random.choice(LLM_SET)

def get_llm_by_index(index: int) -> FrozenLLMOptions:
    return LLM_SET[index]