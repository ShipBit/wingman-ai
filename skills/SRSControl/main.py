import socket
from typing import TYPE_CHECKING
from api.enums import LogType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill
if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman

class UdpRequestSkill(Skill):
    def __init__(self, config: SkillConfig, settings: SettingsConfig, wingman: "OpenAiWingman") -> None:
        super().__init__(config, settings, wingman)
    def get_tools(self) -> list[tuple[str, dict]]:
        return [
            (
                "send_udp_request",
                {
                    "type": "function",
                    "function": {
                        "name": "send_udp_request",
                        "description": "Sends a UDP request to localhost on the specified port.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "port": {
                                    "type": "integer",
                                    "description": "The port to send the UDP request to.",
                                },
                                "message": {
                                    "type": "string",
                                    "description": "The message to send in the UDP request.",
                                },
                            },
                            "required": ["port", "message"],
                        },
                    },
                },
            )
        ]
    async def execute_tool(self, tool_name: str, parameters: dict[str, any]) -> tuple[str, str]:
        function_response = "Error in sending UDP request. Can you please try your command again?"
        instant_response = ""
        if tool_name == "send_udp_request":
            if self.settings.debug_mode:
                self.start_execution_benchmark()
                await self.printr.print_async(
                    f"Executing send_udp_request function with parameters: {parameters}",
                    color=LogType.INFO,
                )
            ip_address = "localhost"
            port = 9040
            message = parameters.get("message")
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.sendto(message.encode(), (ip_address, port))
                sock.close()
                function_response = f"Message sent to {ip_address}:{port}"
            except Exception as e:
                function_response = f"Failed to send message. Error: {str(e)}"
            if self.settings.debug_mode:
                await self.print_execution_time()
        return function_response, instant_response
    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        return errors