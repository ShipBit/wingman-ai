import sys
from openai import OpenAI, APIStatusError
from services.printr import Printr


class OpenAi:
    def __init__(
        self,
        openai_api_key: str = "",
    ):
        self.api_key = openai_api_key
        self.client = OpenAI(
            api_key=openai_api_key,
        )

    def transcribe(
        self,
        filename: str,
        model: str = "whisper-1",
        **params,
    ):
        try:
            with open(filename, "rb") as audio_input:
                transcript = self.client.audio.transcriptions.create(
                    model=model,
                    file=audio_input,
                    **params,
                )
                return transcript
        except APIStatusError as e:
            self._handle_api_error(e)
            return None

    def ask(
        self,
        messages: list[dict[str, str]],
        model: str = "gpt-4-1106-preview",
        stream: bool = False,
        tools: list[dict[str, any]] = None,
    ):
        try:
            if not tools:
                completion = self.client.chat.completions.create(
                    stream=stream,
                    messages=messages,
                    model=model,
                )
            else:
                completion = self.client.chat.completions.create(
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

    def speak(self, text: str, voice: str = "nova"):
        try:
            if not voice:
                voice = "nova"
            response = self.client.audio.speech.create(
                model="tts-1",
                voice=voice,
                input=text,
            )
            return response
        except APIStatusError as e:
            self._handle_api_error(e)
            return None

    def _handle_api_error(self, api_response):
        # TODO: improve error handling
        if api_response.status_code == 401:
            Printr.err_print("The OpenAI API key you provided is invalid. Please check your config.yaml")
        else:
            Printr.err_print(f"The OpenAI API send the following error code {api_response.status_code}")
        print("")
