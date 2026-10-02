"""Every limit comes from the main model's window, capped by an absolute ceiling.

The ceilings protect the allowance from a skill that returns half a million
tokens; the shares keep a small model from being sent more than it can read.
"""

from types import SimpleNamespace

from api.enums import ConversationProvider
from services.context_budget import (
    DEFAULT_WINDOW,
    LOCAL_LLM_WINDOW,
    ContextBudget,
    is_context_overflow,
    learn_window,
    model_window,
)


def config(provider, model=None, deployment=""):
    return SimpleNamespace(
        features=SimpleNamespace(conversation_provider=provider),
        openai=SimpleNamespace(conversation_model=model),
        openrouter=SimpleNamespace(conversation_model=model),
        local_llm=SimpleNamespace(conversation_model=model),
        wingman_pro=SimpleNamespace(conversation_deployment=deployment),
    )


def test_a_big_window_hits_the_absolute_ceilings():
    b = ContextBudget(1_000_000)
    assert (b.tool_cap, b.history_limit, b.keep_tokens) == (32_000, 64_000, 16_000)
    assert b.brake == 900_000


def test_a_small_window_scales_everything_down():
    b = ContextBudget(8_000)
    assert (b.tool_cap, b.history_limit, b.keep_tokens, b.brake) == (2_000, 4_000, 1_000, 7_200)


def test_known_models_come_from_the_table():
    assert model_window(config(ConversationProvider.OPENAI, "gpt-4.1-mini")) == 1_047_576
    assert model_window(config(ConversationProvider.WINGMAN_PRO, deployment="google/gemini-2.5-flash")) == 1_048_576


def test_unknown_models_get_the_provider_default():
    assert model_window(config(ConversationProvider.OPENAI, "some-new-model")) == DEFAULT_WINDOW
    assert model_window(config(ConversationProvider.LOCAL_LLM, "my-finetune")) == LOCAL_LLM_WINDOW


def test_reported_beats_the_table_and_learned_beats_both():
    c = config(ConversationProvider.OPENROUTER, "openai/gpt-4.1-mini")
    assert model_window(c, reported=200_000) == 200_000
    assert model_window(c, reported=200_000, learned=9_000) == 9_000


def test_learning_lands_below_the_refused_request():
    assert learn_window(20_000) == 15_000
    assert learn_window(1_000) == 4_000


def test_overflow_is_recognised_but_rate_limits_are_not():
    assert is_context_overflow("This model's maximum context length is 8192 tokens")
    assert is_context_overflow("the request exceeds the available context size")
    assert not is_context_overflow("Request too large for model in organization on tokens per min")
