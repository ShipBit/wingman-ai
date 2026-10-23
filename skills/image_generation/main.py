import asyncio
from os import path
from typing import TYPE_CHECKING, Literal, Optional
from urllib.parse import quote
from api.enums import ImageStyle, LogSource, LogType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from services.image_generation import (
    MAX_REFERENCE_IMAGES,
    compose_prompt,
    list_images,
    prune_images,
    reference_data_url,
    reference_from_data_url,
    safe_file_in,
    store_image,
)
from skills.skill_base import Skill, tool

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext

# How many images stay on disk when the user did not ask to keep them. They have
# to outlive the chat message that shows them, so this is not 1. They are also
# what "last" and file names in reference_images point to.
UNSAVED_IMAGE_LIMIT = 25

Style = Literal[
    "none",
    "cinematic",
    "photo",
    "anime",
    "ghibli",
    "pixar",
    "cartoon",
    "comic",
    "oil_painting",
    "pixel_art",
    "synthwave",
    "retro_scifi",
    "claymation",
    "sketch",
]


class ImageGeneration(Skill):

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "WingmanContext",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)
        self.image_path = self.get_generated_files_dir()

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        self.retrieve_custom_property_value("save_images", errors)

        return errors

    def _get_save_images(self) -> bool:
        """Get save_images property value just-in-time."""
        errors = []
        return self.retrieve_custom_property_value("save_images", errors)

    @tool(
        name="generate_image",
        description="""Creates an image and shows it in the chat.
style: if the user named a style or said any style is fine, call right away. Only if they said nothing about style, ask first and suggest 3 fitting styles.
prompt: ALWAYS English, even when the user speaks another language. 1-4 plain sentences: main subject and action, concrete visual details, setting, lighting, composition. Text that must appear goes in "double quotes". No keyword lists, no "no X" phrases, no style words.
reference_images: to change or build on an image. ["last"] is the previous generated image, ["attached"] the images the user attached, or file names from earlier results. Then describe the whole result, starting with what stays the same.""",
        wait_response=True,
    )
    async def generate_image(
        self,
        prompt: str,
        style: Style = "none",
        aspect: Literal["square", "portrait", "landscape"] = "square",
        reference_images: Optional[list[str]] = None,
    ) -> str:
        full_prompt = compose_prompt(prompt, ImageStyle(style))
        if self.settings.debug_mode:
            self.log.info(
                f"Generate image with prompt: {full_prompt}", server_only=True
            )

        references = await asyncio.to_thread(
            self._resolve_references, reference_images or []
        )
        if isinstance(references, str):
            return references

        image = await self.wingman.ai.generate_image(
            full_prompt, aspect=aspect, reference_images=references or None
        )

        if not image:
            await self._show("")
            return "Unable to generate an image. Please try again later."

        # The client fetches the image over HTTP and only gets a short path
        # here. Sending the provider's data URL instead would push megabytes
        # of base64 through the WebSocket.
        try:
            image_path = await asyncio.to_thread(
                store_image, image, self.image_path, prompt
            )
        except Exception as e:
            self.log.warning(f"Unable to store the generated image: {e}")
            await self._show(image)
            return "Here is the image. It could not be saved, so it cannot be used as a reference later."

        await self._show(f"/generated-images/{quote(path.basename(image_path))}")

        response = f"Here is the image, file name {path.basename(image_path)}."
        if self._get_save_images():
            response += f" Stored at {image_path}."
        else:
            await asyncio.to_thread(self._prune)
        return response

    def _resolve_references(self, names: list[str]) -> list[str] | str:
        """Data URLs for the reference names the model passed, or an error
        message for the model when one cannot be found."""
        references: list[str] = []
        for name in names:
            name = name.strip()
            if not name:
                continue
            if name == "attached":
                attached = self.wingman.ai.recent_user_images()
                if not attached:
                    return "The user has not attached an image. Ask them to attach one, or generate without reference."
                references.extend(reference_from_data_url(url) for url in attached)
            elif name == "last":
                images = list_images(self.image_path)
                if not images:
                    return "There is no earlier generated image. Generate without reference."
                references.append(self._load(images[0]))
            else:
                file_path = safe_file_in(self.image_path, name)
                if not file_path:
                    return f'There is no generated image called {name}. Use "last" or a file name from an earlier result.'
                references.append(self._load(file_path))
        return references[:MAX_REFERENCE_IMAGES]

    @staticmethod
    def _load(file_path: str) -> str:
        with open(file_path, "rb") as file:
            return reference_data_url(file.read())

    async def _show(self, image_url: str) -> None:
        await self.printr.print_async(
            "",
            color=LogType.INFO,
            source=LogSource.WINGMAN,
            source_name=self.wingman.name,
            skill_name=self.name,
            additional_data={"image_url": image_url},
        )

    def _prune(self) -> None:
        """Every image goes to disk so the client can fetch it. When the user
        did not switch 'Keep generated images' on, the directory must not grow
        without bound."""
        try:
            prune_images(self.image_path, UNSAVED_IMAGE_LIMIT)
        except Exception as e:
            self.log.warning(f"Unable to clean up old generated images: {e}")
