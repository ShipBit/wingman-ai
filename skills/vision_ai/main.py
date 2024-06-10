import base64
import io
from mss import (mss)
from typing import TYPE_CHECKING
from PIL import Image
from api.enums import LogSource, LogType
from api.interface import (
    SettingsConfig,
    SkillConfig,
    WingmanConfig,
    WingmanInitializationError,
)
from skills.skill_base import Skill
from services.printr import Printr

if TYPE_CHECKING:
    from wingmen.wingman import Wingman

printr = Printr()

class VisionAI(Skill):

    def __init__(
        self,
        config: SkillConfig,
        wingman_config: WingmanConfig,
        settings: SettingsConfig,
        wingman: "Wingman",
    ) -> None:
        super().__init__(
            config=config, wingman_config=wingman_config, settings=settings, wingman=wingman
        )

        self.monitor_to_capture = 1
        self.show_screenshots_in_terminal = False

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        self.monitor_to_capture = self.retrieve_custom_property_value("monitor_to_capture", errors)
        self.show_screenshots_in_terminal = self.retrieve_custom_property_value("show_screenshots_in_terminal", errors)

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
            # Take a screenshot
            with mss() as sct:
                main_monitor = sct.monitors[self.monitor_to_capture]
                screenshot = sct.grab(main_monitor)

                # Create a PIL image from array
                image = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

                desired_width = 1000
                aspect_ratio = image.height / image.width
                new_height = int(desired_width * aspect_ratio)

                resized_image = image.resize((desired_width, new_height))
          
                png_base64 = self.pil_image_to_base64(resized_image)

                if self.show_screenshots_in_terminal:
                    await printr.print_async(
                        "Analyzing this image",
                        color=LogType.INFO,
                        source=LogSource.WINGMAN,
                        source_name=self.wingman.name,
                        skill_name=self.name,
                        additional_data={"image": png_base64},
                    )

                question = parameters.get("question", "What’s in this image?")

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
                            {"type": "text", "text": question},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{png_base64}",
                                    "detail": "high"
                                },
                            },
                        ],
                    },
                ]
                completion = await self.llm_call(messages)
                answer = (
                    completion.choices[0].message.content
                    if completion and completion.choices
                    else ""
                )

                if answer:
                    function_response = answer

        return function_response, instant_response

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
        pil_image.save(buffer, format='PNG')
        # Get the byte data from the buffer
     
        # Encode the byte data to Base64
        base64_encoded_data = base64.b64encode(buffer.getvalue())
        # Convert the base64 bytes to a string
        base64_string = base64_encoded_data.decode('utf-8')
    
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
        base64_string = base64_encoded_data.decode('utf-8')
        return base64_string
