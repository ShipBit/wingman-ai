import base64
import io
from mss import (mss, tools)
from PIL import Image
from api.interface import (
    SettingsConfig,
    SkillConfig,
    WingmanConfig,
    WingmanInitializationError,
)
from skills.skill_base import Skill


class VisionAI(Skill):

    def __init__(
        self,
        config: SkillConfig,
        wingman_config: WingmanConfig,
        settings: SettingsConfig,
    ) -> None:
        super().__init__(
            config=config, wingman_config=wingman_config, settings=settings
        )

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
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
                main_monitor = sct.monitors[2]
                screenshot = sct.grab(main_monitor)

                # Create a PIL image from array
                image = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

                desired_width = 1200
                aspect_ratio = image.height / image.width
                new_height = int(desired_width * aspect_ratio)

                resized_image = image.resize((desired_width, new_height))
          
                png_base64 = self.pil_image_to_base64(resized_image)

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
                completion = await self.gpt_call(messages)
                answer = (
                    completion.choices[0].message.content
                    if completion and completion.choices
                    else ""
                )

                if answer:
                    print(answer)
                    function_response = answer

        return function_response, instant_response
    
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
