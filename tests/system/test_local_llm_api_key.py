"""The client tells users to put their OpenAI-compatible endpoint's key in the
`local_llm` secret. Core used to hard-code "not-needed" and never read it, so
Ollama Cloud and any other hosted gateway answered 401. The key has to reach
the OpenAI client now, without prompting the people running keyless.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.enums import ConversationProvider
from services.provider_factory import ProviderFactory

ENDPOINT = "https://ollama.com/v1"


def _factory(stored_secret: str) -> ProviderFactory:
    secret_keeper = MagicMock()
    secret_keeper.retrieve = AsyncMock(return_value=stored_secret)
    config = SimpleNamespace(
        features=SimpleNamespace(conversation_provider=ConversationProvider.LOCAL_LLM),
        local_llm=SimpleNamespace(endpoint=ENDPOINT, conversation_model="qwen3"),
    )
    return ProviderFactory(
        config=config,
        settings=MagicMock(),
        secret_keeper=secret_keeper,
        shared_providers={},
        wingman_name="test",
    )


def test_stored_key_reaches_the_client():
    factory = _factory("sk-ollama-123")
    llm = asyncio.run(factory.create_llm([]))
    assert llm._openai.api_key == "sk-ollama-123"
    assert str(llm._openai.client.base_url).rstrip("/") == ENDPOINT


def test_reading_the_key_never_prompts():
    factory = _factory("sk-ollama-123")
    asyncio.run(factory.create_llm([]))
    factory._secret_keeper.retrieve.assert_awaited_once_with(
        requester="local_llm", key="local_llm", prompt_if_missing=False
    )


@pytest.mark.parametrize("stored", ["", "   ", "not-set", None])
def test_keyless_setups_still_start(stored):
    """A llama.cpp server on localhost wants no key. The OpenAI client rejects
    an empty api_key, so a dummy goes in and no init error is raised."""
    errors = []
    llm = asyncio.run(_factory(stored).create_llm(errors))
    assert llm._openai.api_key == "not-needed"
    assert errors == []
