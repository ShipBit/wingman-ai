import re
from typing import Any
import google.genai as genai
from google.genai import types
from openai import APIStatusError, OpenAI
from openai.types.chat import ChatCompletion
from api.interface import GoogleConfig
from providers.provider_base import (
    BaseProvider,
    ProviderCapability,
    capabilities,
    LlmProvider,
)
from services.printr import Printr

printr = Printr()


@capabilities(ProviderCapability.LLM)
class GoogleGenAI(BaseProvider, LlmProvider):
    """Google Gemini provider supporting LLM capabilities.

    Uses Google's Generative AI API with OpenAI-compatible interface.
    """

    def __init__(self, config: GoogleConfig, api_key: str):
        BaseProvider.__init__(self, config=config, api_key=api_key)

        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(api_version="v1alpha"),
        )
        self.openai_client = OpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )

    def _handle_key_error(self):
        printr.toast_error(
            "The Gemini API key you provided is invalid. Please check the GUI settings or your 'secrets.yaml'"
        )

    def _handle_api_error(self, api_response):
        printr.toast_error(
            f"The OpenAI API sent the following error code {api_response.status_code} ({api_response.type})"
        )
        m = re.search(
            r"'message': (?P<quote>['\"])(?P<message>.+?)(?P=quote)",
            api_response.message,
        )
        if m is not None:
            message = m["message"].replace(". ", ".\n")
            printr.toast_error(message)
        elif api_response.message:
            printr.toast_error(api_response.message)
        else:
            printr.toast_error("The API did not provide further information.")

    def get_minimal_reasoning_by_model(self, model_name: str) -> dict:
        """Return minimal allowed OpenAI `reasoning_effort` for Gemini models.

        Gemini models support thinking controls that map to OpenAI's `reasoning_effort`.
        We always send the lowest allowed value to minimize latency.

                Rules (practical constraints from Gemini's OpenAI-compatible endpoint):
                - Gemini 2.5 Flash-family: supports `reasoning_effort="none"` (fastest).
                - Gemini 2.5 Pro-family: do not disable thinking; use the lowest supported value.
                - Gemini 3-family: does NOT accept `"minimal"` (e.g. gemini-3-flash-preview).
                    The lowest supported value is `"low"`.

                For non-Gemini models and unknown/legacy Gemini aliases, we omit the parameter
                to avoid sending unsupported values.
        """

        if not model_name:
            return {}

        normalized = model_name.lower()

        # Only apply to Gemini models; don't risk sending unknown params to other providers.
        if "gemini" not in normalized:
            return {}

        # Gemini 2.5 models
        if "2.5" in normalized:
            # Reasoning cannot be turned off for 2.5 Pro.
            if "pro" in normalized:
                return {"reasoning_effort": "low"}
            # Flash and other non-Pro 2.5 variants allow disabling thinking.
            return {"reasoning_effort": "none"}

        # Gemini 3 models: minimal is not a valid value; use the lowest supported value.
        if re.search(r"(^|[^0-9])3([^0-9]|$)", normalized):
            return {"reasoning_effort": "low"}

        # Other Gemini aliases (e.g. gemini-flash-latest / gemini-pro-latest) may vary.
        # Don't send reasoning_effort unless we know it's supported.
        return {}

    def _sanitize_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        """Sanitize messages for Google Gemini OpenAI-compatible endpoint.

        Google's OpenAI-compatible endpoint is stricter than OpenAI's:
        - `content` must not be null (use empty string)
        - tool-related fields should be preserved as-is

        Wingman may pass either dicts or OpenAI message objects; normalize both.
        """

        sanitized: list[dict[str, Any]] = []
        for msg in messages:
            if isinstance(msg, dict):
                msg_copy = msg.copy()
                if msg_copy.get("content") is None:
                    msg_copy["content"] = ""
                sanitized.append(msg_copy)
                continue

            msg_dict: dict[str, Any] = {
                "role": msg.role if hasattr(msg, "role") else msg.get("role"),
                "content": (
                    msg.content if hasattr(msg, "content") else msg.get("content")
                ),
            }

            if msg_dict.get("content") is None:
                msg_dict["content"] = ""

            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                msg_dict["tool_calls"] = tool_calls
            elif isinstance(msg, dict) and "tool_calls" in msg:
                msg_dict["tool_calls"] = msg["tool_calls"]

            tool_call_id = getattr(msg, "tool_call_id", None)
            if tool_call_id:
                msg_dict["tool_call_id"] = tool_call_id
            elif isinstance(msg, dict) and "tool_call_id" in msg:
                msg_dict["tool_call_id"] = msg["tool_call_id"]

            name = getattr(msg, "name", None)
            if name:
                msg_dict["name"] = name
            elif isinstance(msg, dict) and "name" in msg:
                msg_dict["name"] = msg["name"]

            sanitized.append(msg_dict)

        return sanitized

    # Protocol implementation: LlmProvider
    async def complete(
        self, messages: list[dict], tools: list[dict] = None, **kwargs
    ) -> ChatCompletion | None:
        """Generate completion using Google Gemini.

        Args:
            messages: List of message dicts with 'role' and 'content'
            tools: Optional list of tool definitions for function calling
            **kwargs: Additional parameters (model, stream, etc.)

        Returns:
            ChatCompletion object from Google's OpenAI-compatible API, or None on error
        """
        model = kwargs.get("model", self.config.conversation_model)
        stream = kwargs.get("stream", False)

        messages = self._sanitize_messages(messages)

        # Direct implementation - no legacy method needed
        try:
            reasoning_params = self.get_minimal_reasoning_by_model(model)
            if not tools:
                completion = self.openai_client.chat.completions.create(
                    stream=stream,
                    messages=messages,
                    model=model,
                    **reasoning_params,
                )
            else:
                completion = self.openai_client.chat.completions.create(
                    stream=stream,
                    messages=messages,
                    model=model,
                    tools=tools,
                    tool_choice="auto",
                    **reasoning_params,
                )
            return completion
        except APIStatusError as e:
            self._handle_api_error(e)
            return None
        except UnicodeEncodeError:
            self._handle_key_error()
            return None

    def get_available_models(self):
        models: list[types.Model] = []
        for model in self.client.models.list():
            for action in model.supported_actions:
                if action == "generateContent":
                    models.append(model)
        return models
