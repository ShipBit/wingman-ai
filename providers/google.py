import re
from google import genai
from google.genai import types
from openai import APIStatusError, OpenAI
from services.printr import Printr

printr = Printr()


class GoogleGenAI:
    def __init__(self, api_key: str):
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

    def ask(
        self,
        messages: list[dict[str, str]],
        model: str,
        stream: bool = False,
        tools: list[dict[str, any]] = None,
    ):
        try:
            if not tools:
                completion = self.openai_client.chat.completions.create(
                    stream=stream,
                    messages=messages,
                    model=model,
                )
            else:
                completion = self.openai_client.chat.completions.create(
                    stream=stream,
                    messages=messages,
                    model=model,
                    tools=tools,
                    tool_choice="auto",
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
