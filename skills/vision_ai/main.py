import base64
import io
from typing import TYPE_CHECKING
from mss import mss
from PIL import Image
from api.enums import LogSource, LogType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class VisionAI(Skill):

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

        self.display = 1
        self.show_screenshots = False

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        self.display = self.retrieve_custom_property_value("display", errors)
        self.show_screenshots = self.retrieve_custom_property_value(
            "show_screenshots", errors
        )

        return errors

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = [
            (
                "analyse_what_you_or_user_sees",
                {
                    "type": "function",
                    "function": {
                        "name": "analyse_what_you_or_user_sees",
                        "description": "Analyse what you or the user sees and answer questions about it.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "question": {
                                    "type": "string",
                                    "description": "The question to answer about the image.",
                                }
                            },
                            "required": ["question"],
                        },
                    },
                },
            ),
        ]
        return tools

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        function_response = ""
        instant_response = ""

        if tool_name == "analyse_what_you_or_user_sees":

            question = parameters.get("question", "What's in this image?")
            answer = await self.analyse_screen(question)

            if answer:
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        f"Vision analysis: {answer}.", color=LogType.INFO
                    )
                function_response = answer

        return function_response, instant_response

    async def analyse_screen(self, prompt: str, desired_image_width: int = 1000):
        function_response = ""

        # Take a screenshot
        with mss() as sct:
            main_display = sct.monitors[self.display]
            screenshot = sct.grab(main_display)

            # Create a PIL image from array
            image = Image.frombytes(
                "RGB", screenshot.size, screenshot.bgra, "raw", "BGRX"
            )

            aspect_ratio = image.height / image.width
            new_height = int(desired_image_width * aspect_ratio)

            resized_image = image.resize((desired_image_width, new_height))

            png_base64 = self.pil_image_to_base64(resized_image)

            if self.show_screenshots:
                await self.printr.print_async(
                    "Analyzing this image",
                    color=LogType.INFO,
                    source=LogSource.WINGMAN,
                    source_name=self.wingman.name,
                    skill_name=self.name,
                    additional_data={"image_base64": png_base64},
                )

            messages = [
                {
                    "role": "system",
                    "content": """
                        You are a helpful ai assistant.
                    """,
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{png_base64}",
                                "detail": "high",
                            },
                        },
                    ],
                },
            ]
            completion = await self.llm_call(messages)
            function_response = (
                completion.choices[0].message.content
                if completion and completion.choices
                else ""
            )

        return function_response

    async def is_summarize_needed(self, tool_name: str) -> bool:
        """Returns whether a tool needs to be summarized."""
        return True

    async def is_waiting_response_needed(self, tool_name: str) -> bool:
        """Returns whether a tool probably takes long and a message should be printet in between."""
        return True

    def pil_image_to_base64(self, pil_image):
        """
        Convert a PIL image to a base64 encoded string.

        :param pil_image: PIL Image object
        :return: Base64 encoded string of the image
        """
        # Create a bytes buffer to hold the image data
        buffer = io.BytesIO()
        # Save the PIL image to the bytes buffer in PNG format
        pil_image.save(buffer, format="PNG")
        # Get the byte data from the buffer

        # Encode the byte data to Base64
        base64_encoded_data = base64.b64encode(buffer.getvalue())
        # Convert the base64 bytes to a string
        base64_string = base64_encoded_data.decode("utf-8")

        return base64_string

    def convert_png_to_base64(self, png_data):
        """
        Convert raw PNG data to a base64 encoded string.

        :param png_data: A bytes object containing the raw PNG data
        :return: A base64 encoded string.
        """
        # Encode the PNG data to base64
        base64_encoded_data = base64.b64encode(png_data)
        # Convert the base64 bytes to a string
        base64_string = base64_encoded_data.decode("utf-8")
        return base64_string
