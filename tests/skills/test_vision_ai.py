"""Vision AI on a main model that cannot see: a clear tool result instead of a
screenshot the provider refuses."""

import asyncio
import time
from types import SimpleNamespace

import pytest

import services.model_metadata as metadata_module
from api.enums import ConversationProvider
from services.model_metadata import ModelMetadata, ModelMetadataService
from skills.vision_ai.main import VisionAI
from wingmen.facade import SkillAi


@pytest.fixture
def metadata(monkeypatch):
    """Model metadata as if just fetched, so nothing goes to the network."""
    service = ModelMetadataService()
    service._cache = {
        "text-only-1": ModelMetadata({"supports_vision": False}),
        "sees-1": ModelMetadata({"supports_vision": True}),
    }
    service._last_fetch = time.time()
    monkeypatch.setattr(metadata_module, "_shared", service)
    return service


def _ai(model: str) -> SkillAi:
    config = SimpleNamespace(
        features=SimpleNamespace(conversation_provider=ConversationProvider.OPENAI),
        openai=SimpleNamespace(conversation_model=model),
    )
    return SkillAi(SimpleNamespace(config=config))


@pytest.mark.parametrize(
    "model, sees", [("text-only-1", False), ("sees-1", True), ("my-local-model", True)]
)
def test_only_a_model_known_without_vision_does_not_see(metadata, model, sees):
    assert asyncio.run(_ai(model).sees_images()) is sees


def test_the_skill_says_why_instead_of_taking_a_screenshot(metadata):
    captured = []

    async def capture(display):
        captured.append(display)
        raise AssertionError("no screenshot for a model that cannot see")

    skill = object.__new__(VisionAI)
    skill.wingman = SimpleNamespace(
        ai=_ai("text-only-1"), screen=SimpleNamespace(capture=capture)
    )

    result = asyncio.run(skill.analyse_screen("What is on my screen?"))

    assert "cannot see images" in result
    assert captured == []
