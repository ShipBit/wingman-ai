"""The avatar studio writes the prompt in one step and paints it in another.
What the user edits in between is what the image model gets."""

import asyncio
import base64
import json
from os import path
from types import SimpleNamespace

import pytest

from api.enums import ImageStyle
from api.interface import AvatarGenerationRequest, AvatarPromptRequest
from services import avatar_studio
from services.image_generation import (
    AVATAR_FRAMING,
    AVATAR_FRAMING_REFINE,
    STYLE_PROMPTS,
)

# A 1x1 PNG, enough for store_image.
PIXEL = "data:image/png;base64," + base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
    )
).decode()


class FakeWingman:
    name = "Fox"

    def __init__(self, description: str = "A fox in a flight jacket."):
        self.config = SimpleNamespace(prompts=SimpleNamespace(backstory="A pilot."))
        self.description = description
        self.sent_prompts: list[str] = []
        self.llm_messages: list = []

    async def actual_llm_call(self, messages):
        self.llm_messages.append(messages)
        message = SimpleNamespace(content=self.description)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    async def generate_image(self, text, aspect=None, reference_images=None):
        self.sent_prompts.append(text)
        return PIXEL


@pytest.fixture
def studio_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(
        avatar_studio, "get_generated_files_dir", lambda name: str(tmp_path / name)
    )
    return tmp_path


def test_written_prompt_has_style_description_and_framing(studio_dir):
    wingman = FakeWingman()
    request = AvatarPromptRequest(
        wingman_name="Fox", style=ImageStyle.ANIME, wishes="", refine=False
    )
    prompt = asyncio.run(avatar_studio.write_prompt(wingman, request))
    assert prompt.startswith(STYLE_PROMPTS[ImageStyle.ANIME])
    assert "A fox in a flight jacket." in prompt
    assert prompt.endswith(AVATAR_FRAMING)


def test_refine_prompt_uses_refine_framing(studio_dir):
    wingman = FakeWingman("The same character, now with a red scarf.")
    request = AvatarPromptRequest(
        wingman_name="Fox", style=ImageStyle.NONE, wishes="red scarf", refine=True
    )
    prompt = asyncio.run(avatar_studio.write_prompt(wingman, request))
    assert prompt.endswith(AVATAR_FRAMING_REFINE)
    assert "red scarf" in wingman.llm_messages[0][0]["content"]


def test_edited_prompt_reaches_the_image_model_unchanged(studio_dir):
    wingman = FakeWingman()
    edited = "Watercolor fox, wearing a monocle, plain blue background."
    request = AvatarGenerationRequest(
        wingman_name="Fox", prompt=edited, style=ImageStyle.CINEMATIC
    )
    variant = asyncio.run(avatar_studio.generate_variant(wingman, request))
    assert wingman.sent_prompts == [edited]
    assert wingman.llm_messages == []
    assert variant.prompt == edited
    assert variant.style == ImageStyle.CINEMATIC
    assert avatar_studio.list_variants("Fox")[0].prompt == edited


def test_empty_prompt_is_refused(studio_dir):
    request = AvatarGenerationRequest(
        wingman_name="Fox", prompt="   ", style=ImageStyle.NONE
    )
    with pytest.raises(avatar_studio.AvatarStudioError):
        asyncio.run(avatar_studio.generate_variant(FakeWingman(), request))


def test_older_variant_shows_the_prompt_that_was_sent(studio_dir):
    """Variants made before the prompt step stored only the description."""
    directory = avatar_studio.variants_dir("Fox", create=True)
    with open(path.join(directory, "avatar_old.png"), "wb") as file:
        file.write(base64.b64decode(PIXEL.split(",", 1)[1]))
    with open(path.join(directory, "avatar_old.json"), "w") as file:
        json.dump({"prompt": "A fox", "style": "photo"}, file)

    variant = avatar_studio.list_variants("Fox")[0]
    assert variant.prompt == (
        f"{STYLE_PROMPTS[ImageStyle.PHOTO]} A fox. {AVATAR_FRAMING}"
    )
