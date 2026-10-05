"""The avatar studio: generated avatar variants per wingman.

Two steps, so the user can edit the prompt before paying for an image. First
the wingman's main model writes the character description from the backstory
and the user's wishes (prompts/avatar-image*.md), and Core puts the style
preset in front and the fixed avatar framing behind it, for a square, centered
portrait that needs no crop. Then the user edits that prompt as they like and
Core sends it to the image model as is. Every variant is kept on disk with its
prompt, so the user can flip back to an older one, even after closing the
studio.
"""

import json
import re
import time
from os import listdir, makedirs, path, remove
from typing import TYPE_CHECKING
from urllib.parse import quote

from api.enums import ImageAspect, ImageStyle
from api.interface import (
    AvatarGenerationRequest,
    AvatarPromptRequest,
    AvatarVariant,
    ImageStylePrompt,
)
from services.file import get_generated_files_dir, get_prompt
from services.image_generation import (
    AVATAR_FRAMING,
    AVATAR_FRAMING_REFINE,
    STYLE_PROMPTS,
    compose_prompt,
    list_images,
    prune_images,
    reference_data_url,
    reference_from_data_url,
    safe_file_in,
    store_image,
)

if TYPE_CHECKING:
    from wingmen.wingman import Wingman

AVATAR_STUDIO_DIR = "AvatarStudio"

# Variants per wingman. At 0.03 to 0.04 $ a picture nobody makes hundreds, and
# the list in the studio stays short enough to flip through.
MAX_VARIANTS = 40

# Characters that are unsafe in a directory name on any of the three systems.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class AvatarStudioError(Exception):
    """A message for the user, shown by the client as is."""


def variants_dir(wingman_name: str, create: bool = False) -> str:
    name = _UNSAFE.sub("_", wingman_name).strip(" .") or "wingman"
    directory = path.join(get_generated_files_dir(AVATAR_STUDIO_DIR), name)
    if create:
        makedirs(directory, exist_ok=True)
    return directory


def list_variants(wingman_name: str) -> list[AvatarVariant]:
    """All variants of a wingman, newest first."""
    directory = variants_dir(wingman_name)
    return [_variant(wingman_name, file) for file in list_images(directory)]


def delete_variant(wingman_name: str, file_name: str) -> None:
    file_path = safe_file_in(variants_dir(wingman_name), file_name)
    if not file_path:
        return
    remove(file_path)
    meta = _meta_path(file_path)
    if path.exists(meta):
        remove(meta)


def variant_file(wingman_name: str, file_name: str) -> str | None:
    return safe_file_in(variants_dir(wingman_name), file_name)


def style_prompts() -> list[ImageStylePrompt]:
    """The text of every style preset. The studio swaps it in the prompt when
    the user picks another style."""
    return [
        ImageStylePrompt(style=style, prompt=STYLE_PROMPTS.get(style, ""))
        for style in ImageStyle
    ]


async def write_prompt(wingman: "Wingman", request: AvatarPromptRequest) -> str:
    """The complete prompt for a new variant: style, description, framing."""
    description = await _write_description(
        wingman, request.wishes, refine=request.refine
    )
    return compose_prompt(
        description,
        request.style,
        AVATAR_FRAMING_REFINE if request.refine else AVATAR_FRAMING,
    )


async def generate_variant(
    wingman: "Wingman", request: AvatarGenerationRequest
) -> AvatarVariant:
    prompt = " ".join(request.prompt.split())
    if not prompt:
        raise AvatarStudioError("The prompt is empty.")
    directory = variants_dir(wingman.name, create=True)
    reference = _reference(directory, request.reference)

    image = await wingman.generate_image(
        prompt,
        aspect=ImageAspect.SQUARE,
        reference_images=[reference] if reference else None,
    )
    if not image:
        raise AvatarStudioError("The image could not be generated.")

    file_path = store_image(image, directory, "avatar")
    with open(_meta_path(file_path), "w", encoding="utf-8") as file:
        json.dump(
            {"image_prompt": prompt, "style": request.style.value},
            file,
            ensure_ascii=False,
        )
    _prune(directory)
    return _variant(wingman.name, file_path)


async def _write_description(wingman: "Wingman", wishes: str, refine: bool) -> str:
    """The main model turns backstory and wishes into a picture description.
    It gets one user turn and no tools: this is a writing job, not a
    conversation."""
    template = get_prompt("avatar-image-refine" if refine else "avatar-image")
    text = template.format(
        name=wingman.name,
        backstory=(wingman.config.prompts.backstory or "").strip() or "(none)",
        wishes=wishes.strip() or "(none)",
    )
    completion = await wingman.actual_llm_call(
        messages=[{"role": "user", "content": text}]
    )
    content = ""
    if completion and completion.choices:
        content = completion.choices[0].message.content or ""
    # Some models wrap the answer in quotes or a code fence despite the rules.
    content = content.strip().strip("`").strip().strip('"').strip()
    if not content:
        raise AvatarStudioError("The AI model did not write an image description.")
    return " ".join(content.split())


def _reference(directory: str, reference: str | None) -> str | None:
    """The reference as a small JPEG data URL: an earlier variant by file
    name, or an image the user uploaded as data URL."""
    if not reference:
        return None
    try:
        if reference.startswith("data:"):
            return reference_from_data_url(reference)
        file_path = safe_file_in(directory, reference)
        if not file_path:
            raise AvatarStudioError("The reference image no longer exists.")
        with open(file_path, "rb") as file:
            return reference_data_url(file.read())
    except AvatarStudioError:
        raise
    except Exception as e:
        raise AvatarStudioError(f"The reference image could not be read: {e}")


def _variant(wingman_name: str, file_path: str) -> AvatarVariant:
    meta = {}
    try:
        with open(_meta_path(file_path), "r", encoding="utf-8") as file:
            meta = json.load(file)
    except Exception:
        pass
    try:
        style = ImageStyle(meta.get("style", ImageStyle.NONE.value))
    except ValueError:
        style = ImageStyle.NONE
    prompt = meta.get("image_prompt")
    if prompt is None:
        # Older variants stored only the character description. Rebuild what
        # was sent, so generating from it gives the same kind of image again.
        description = meta.get("prompt", "")
        prompt = (
            compose_prompt(description, style, AVATAR_FRAMING) if description else ""
        )
    file_name = path.basename(file_path)
    return AvatarVariant(
        file_name=file_name,
        url=f"/avatar-images/{quote(wingman_name)}/{quote(file_name)}",
        path=file_path,
        prompt=prompt,
        style=style,
        created=path.getmtime(file_path) if path.exists(file_path) else time.time(),
    )


def _meta_path(file_path: str) -> str:
    return path.splitext(file_path)[0] + ".json"


def _prune(directory: str) -> None:
    kept = {
        path.splitext(path.basename(f))[0]
        for f in list_images(directory)[:MAX_VARIANTS]
    }
    prune_images(directory, MAX_VARIANTS)
    for name in listdir(directory):
        stem, extension = path.splitext(name)
        if extension == ".json" and stem not in kept:
            remove(path.join(directory, name))
