import re
from openai import OpenAI, APIStatusError
from services.printr import Printr

printr = Printr()
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
        response_format: str = "json",
        **params,
    ):
        try:
            with open(filename, "rb") as audio_input:
                transcript = self.client.audio.transcriptions.create(
                    model=model,
                    file=audio_input,
                    response_format=response_format,
                    **params,
                )
                return transcript
        except APIStatusError as e:
            self._handle_api_error(e)
            return None
        except UnicodeEncodeError:
            self._handle_key_error()
            return None

    def ask(
        self,
        messages: list[dict[str, str]],
        model: str,
        stream: bool = False,
        tools: list[dict[str, any]] = None,
    ):
        if not model:
            model = "gpt-3.5-turbo-1106"

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
        except UnicodeEncodeError:
            self._handle_key_error()
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
        except UnicodeEncodeError:
            self._handle_key_error()
            return None

    def _handle_key_error(self):
        printr.err_print("The OpenAI API key you provided is invalid. Please check your 'apikey.yaml'")

    def _handle_api_error(self, api_response):
        printr.err_print(
            f"The OpenAI API send the following error code {printr.BOLD}{api_response.status_code}{printr.NORMAL_WEIGHT} ({printr.FAINT}{api_response.type}{printr.NORMAL_WEIGHT})"
        )
        # get API message from appended JSON object in the "message" part of the exception
        m = re.search(
            r"'message': (?P<quote>['\"])(?P<message>.+?)(?P=quote)",
            api_response.message,
        )
        if m is not None:
            message_lines = m["message"].split(". ")
            for line in message_lines:
                printr.err_print(line, False)
        elif api_response.message:
            printr.err_print(api_response.message, False)
        else:
            printr.err_print("The API did not provide further information.", False)

        # Provide additional info an known issues
        match api_response.status_code:
            case 400:
                printr.info_print("These errors can have multiple root causes.", False)
                printr.info_print(
                    "Please have an eye on our Discord 'early-access' channel for the latest updates.",
                    False,
                )
            case 401:
                printr.info_print("This is a key related issue. Please check the keys you provided in your 'apikeys.yaml'", False)
            case 404:
                printr.info_print(
                    "The key you are using might not be eligible for the gpt-4 model.",
                    False,
                )
                printr.info_print(
                    "Access to gpt-4 is granted, after you spent at least 1$ on your Open AI account.",
                    False,
                )
                printr.info_print(
                    "Have a look at our Discord 'early-access' channel for more information on that topic.",
                    False,
                )
            case _:
                pass  # ¯\_(ツ)_/¯
