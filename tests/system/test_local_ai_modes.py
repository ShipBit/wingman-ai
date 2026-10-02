"""Which of the three places a call goes to, and — the subtle half — embeddings.

Cloud mode splits something that used to move together: the support model answers
over the network while the embedding model still runs here, because the vector
database it feeds is local and vectors from another model would not be comparable
to the ones already in it.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api.enums import LocalAiMode
from services.local_ai_service import CLOUD_CONTEXT_TOKENS, LocalAiService


def _service(mode: LocalAiMode) -> LocalAiService:
    settings = SimpleNamespace(n_ctx=4096, mode=mode)
    return LocalAiService(
        provider=MagicMock(), remote=MagicMock(), cloud=MagicMock(), settings=settings
    )


@pytest.mark.parametrize(
    "mode,target",
    [
        (LocalAiMode.CLOUD, "cloud"),
        (LocalAiMode.LOCAL, "provider"),
        (LocalAiMode.SERVER, "remote"),
    ],
)
def test_a_support_call_goes_to_the_right_place(mode, target):
    service = _service(mode)
    service.support(text="hello", system_prompt="sys")

    for name in ("cloud", "provider", "remote"):
        called = getattr(service, name).support.called
        assert called is (name == target), f"{name}.support called={called}"


@pytest.mark.parametrize("mode", [LocalAiMode.CLOUD, LocalAiMode.LOCAL])
def test_embeddings_stay_on_this_machine(mode):
    """Including in cloud mode. Computing them in the cloud would mean every
    fact already stored has to be recomputed before it can be found again."""
    service = _service(mode)
    service.embed(["some text"])

    assert service.provider.embed.called
    assert not service.remote.embed.called


def test_embeddings_follow_the_user_to_their_own_server():
    service = _service(LocalAiMode.SERVER)
    service.embed(["some text"])

    assert service.remote.embed.called
    assert not service.provider.embed.called


def test_readiness_is_asked_of_the_model_that_would_answer():
    service = _service(LocalAiMode.CLOUD)
    service.cloud.is_ready.return_value = True
    service.provider.support_is_ready.return_value = False

    assert service.is_ready() is True


def test_the_support_model_being_remote_does_not_make_memory_ready():
    """Two separate questions since cloud mode. Memory needs embeddings, and
    those can be missing while the support model answers perfectly well."""
    service = _service(LocalAiMode.CLOUD)
    service.cloud.is_ready.return_value = True
    service.provider.embed_is_ready.return_value = False

    assert service.is_ready() is True
    assert service.embed_ready() is False


def test_the_remote_embed_server_answers_for_itself():
    """Two hosts, two ports, two answers. Asking the support server whether
    embeddings work made the embed test fail whenever support was unreachable,
    however healthy the embedding server was."""
    service = _service(LocalAiMode.SERVER)
    service.remote.is_ready.return_value = False
    service.remote.embed_is_ready.return_value = True

    assert service.is_ready() is False
    assert service.embed_ready() is True


def test_the_budget_follows_the_model_that_answers():
    """n_ctx is a llama.cpp setting and means nothing to a cloud model. Planning
    against 4096 there would chunk every summary into needless pieces."""
    local = _service(LocalAiMode.LOCAL).get_token_budget("sys")
    cloud = _service(LocalAiMode.CLOUD).get_token_budget("sys")

    assert local.n_ctx == 4096
    assert cloud.n_ctx == CLOUD_CONTEXT_TOKENS
    assert cloud.max_input_tokens > local.max_input_tokens
