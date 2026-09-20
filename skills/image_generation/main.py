from os import listdir, path, remove
import base64
import datetime
import re
import requests
from typing import TYPE_CHECKING
from urllib.parse import quote
from api.enums import LogSource, LogType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill, tool

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext

DATA_URL_PATTERN = re.compile(
    r"^data:(?P<mime>image/[a-zA-Z0-9.+-]+);base64,(?P<data>.+)$", re.DOTALL
)

# Characters Windows refuses in file names
FILENAME_UNSAFE_PATTERN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

MIME_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}

# How many images stay on disk when the user did not ask to keep them. They have
# to outlive the chat message that shows them, so this is not 1.
UNSAVED_IMAGE_LIMIT = 25


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
        description="""Generates an image using the configured image provider based on a text description.

        WHEN TO USE:
        - User requests image creation: 'Generate an image of...', 'Create a picture of...'
        - User wants visual content created from a description
        - Any request for AI-generated artwork or illustrations

        Produces high-quality, detailed images matching user specifications.""",
        wait_response=True,
    )
    async def generate_image(self, prompt: str) -> str:
        """
        Args:
            prompt: The image generation prompt describing what to create.
        """
        if self.settings.debug_mode:
            self.log.info(f"Generate image with prompt: {prompt}.")

        image = await self.wingman.ai.generate_image(prompt)

        function_response = "Unable to generate an image. Please try another provider."

        if image:
            function_response = "Here is an image based on your prompt."

            # The client fetches the image over HTTP and only gets a short path
            # here. Sending the provider's data URL instead would push megabytes
            # of base64 through the WebSocket.
            image_path = self._store_image(image, prompt)
            image_url = (
                f"/generated-images/{quote(path.basename(image_path))}"
                if image_path
                else image
            )

            await self.printr.print_async(
                "",
                color=LogType.INFO,
                source=LogSource.WINGMAN,
                source_name=self.wingman.name,
                skill_name=self.name,
                additional_data={"image_url": image_url},
            )

            if image_path and self._get_save_images():
                function_response += f" The image has also been stored to {image_path}."
                if self.settings.debug_mode:
                    self.log.info(f"Image displayed and saved at {image_path}.")
            else:
                self._prune_images()
        else:
            await self.printr.print_async(
                "",
                color=LogType.INFO,
                source=LogSource.WINGMAN,
                source_name=self.wingman.name,
                skill_name=self.name,
                additional_data={"image_url": ""},
            )

        return function_response

    def _store_image(self, image: str, prompt: str) -> str:
        """Write the generated image into the skill's generated files directory.

        Providers either return an http(s) URL or an inline data URL - both are
        handled. Returns the path, or an empty string if the image could not be
        stored; the caller then falls back to handing the client the raw image."""
        try:
            data_url = DATA_URL_PATTERN.match(image)

            if data_url:
                extension = MIME_EXTENSIONS.get(data_url.group("mime").lower(), "png")
                content = base64.b64decode(data_url.group("data"))
            else:
                response = requests.get(image, timeout=30)
                if response.status_code != 200:
                    return ""
                mime = response.headers.get("content-type", "")
                extension = MIME_EXTENSIONS.get(
                    mime.split(";")[0].strip().lower(), "png"
                )
                content = response.content

            name = FILENAME_UNSAFE_PATTERN.sub("_", prompt[:40]).strip() or "image"
            stem = f"{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{name}"
            image_path = path.join(self.image_path, f"{stem}.{extension}")
            # The timestamp only resolves to seconds - two images from the same
            # second must not overwrite each other, the client links to the file.
            counter = 1
            while path.exists(image_path):
                image_path = path.join(self.image_path, f"{stem}_{counter}.{extension}")
                counter += 1

            with open(image_path, "wb") as file:
                file.write(content)

            return image_path
        except Exception as e:
            self.log.warning(f"Unable to store the generated image: {e}")
            return ""

    def _prune_images(self) -> None:
        """Keep only the newest UNSAVED_IMAGE_LIMIT images.

        Every image goes to disk so the client can fetch it. When the user did
        not switch 'Keep generated images' on, the directory must not grow
        without bound."""
        try:
            files = [
                entry
                for entry in (
                    path.join(self.image_path, name)
                    for name in listdir(self.image_path)
                )
                if path.isfile(entry)
            ]
            files.sort(key=path.getmtime, reverse=True)

            for stale in files[UNSAVED_IMAGE_LIMIT:]:
                remove(stale)
        except Exception as e:
            self.log.warning(f"Unable to clean up old generated images: {e}")
