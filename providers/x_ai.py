from typing import TYPE_CHECKING
from openai import OpenAI, APIStatusError
from api.enums import ConversationProvider
from providers.interfaces import LlmInterface, llm_provider
from providers.open_ai import OpenAi

if TYPE_CHECKING:
    from api.interface import WingmanConfig


class XAi(OpenAi):
    def _perform_ask(
        self,
        client: OpenAI,
        messages: list[dict[str, str]],
        stream: bool,
        tools: list[dict[str, any]],
        model: str = None,
    ):
        try:
            if not tools:
                completion = client.chat.completions.create(
                    stream=stream,
                    messages=messages,
                    model=model,
                )
            else:
                completion = client.chat.completions.create(
                    stream=stream,
                    messages=messages,
                    model=model,
                    tools=self._fix_tools(tools),
                    tool_choice="auto",
                )
            return completion
        except APIStatusError as e:
            self._handle_api_error(e)
            return None
        except UnicodeEncodeError:
            self._handle_key_error()
            return None

    def _fix_tools(self, tools: list[dict[str, any]]) -> list[dict[str, any]]:
        # X.AI must have a "parameters" field in each tool
        fixed_tools = []
        for tool in tools:
            fixed_tool = {
                "type": "function",
                "function": {
                    "name": tool.get("function", {}).get("name"),
                    "description": tool.get("function", {}).get("description"),
                    "parameters": tool.get("function", {}).get("parameters", {}),
                },
            }
            fixed_tools.append(fixed_tool)
        return fixed_tools


@llm_provider(ConversationProvider.XAI)
class XAiLlm(LlmInterface):
    def __init__(self, xai_instance: "XAi", config: "WingmanConfig"):
        self._xai = xai_instance
        self._config = config

    async def ask(self, messages, tools=None):
        return self._xai.ask(
            messages=messages, tools=tools,
            model=self._config.xai.conversation_model,
        )
