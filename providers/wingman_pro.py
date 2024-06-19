import openai
import requests
from api.enums import CommandTag, LogType, OpenAiTtsVoice, WingmanProAzureDeployment
from api.interface import (
    AzureSttConfig,
    AzureTtsConfig,
    SoundConfig,
    WingmanProSettings,
)
from services.audio_player import AudioPlayer
from services.printr import Printr
from services.secret_keeper import SecretKeeper


class WingmanPro:
    def __init__(
        self, wingman_name: str, settings: WingmanProSettings, timeout: int = 120
    ):
        self.wingman_name: str = wingman_name
        self.settings: WingmanProSettings = settings
        self.printr = Printr()
        self.secret_keeper: SecretKeeper = SecretKeeper()
        self.timeout = timeout

    def send_unauthorized_error(self):
        self.printr.print(
            text="Unauthorized",
            command_tag=CommandTag.UNAUTHORIZED,
            color=LogType.ERROR,
        )

    def transcribe_whisper(self, filename: str):
        with open(filename, "rb") as audio_input:
            files = {"audio_file": (filename, audio_input)}
            response = requests.post(
                url=f"{self.settings.base_url}/transcribe-whisper",
                params={"region": self.settings.region.value},
                files=files,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            if response.status_code == 403:
                self.send_unauthorized_error()
                return None
            else:
                response.raise_for_status()
            json = response.json()
            transcription = openai.types.audio.Transcription.model_validate(json)
            return transcription

    def transcribe_azure_speech(self, filename: str, config: AzureSttConfig):
        with open(filename, "rb") as audio_input:
            files = {"file": (filename, audio_input)}
            params = {
                "region": self.settings.region.value,
                "languages": config.languages,
            }
            response = requests.post(
                url=f"{self.settings.base_url}/transcribe-azure-speech",
                params=params,
                headers=self._get_headers(),
                files=files,
                timeout=self.timeout,
            )
        if response.status_code == 403:
            self.send_unauthorized_error()
            return None
        else:
            response.raise_for_status()
        json = response.json()
        return json

    def ask(
        self,
        messages: list[dict[str, str]],
        deployment: WingmanProAzureDeployment,
        stream: bool = False,
        tools: list[dict[str, any]] = None,
    ):
        serialized_messages = []
        for message in messages:
            if isinstance(message, openai.types.chat.ChatCompletionMessage):
                message_dict = self.__remove_nones(message.dict())
                serialized_messages.append(message_dict)
            else:
                serialized_messages.append(message)

        data = {
            "messages": serialized_messages,
            "deployment": deployment.value,
            "stream": stream,
            "tools": tools,
        }
        response = requests.post(
            url=f"{self.settings.base_url}/ask",
            params={"region": self.settings.region.value},
            headers=self._get_headers(),
            json=data,
            timeout=self.timeout,
        )
        if response.status_code == 401 or response.status_code == 403:
            self.send_unauthorized_error()
            return None
        else:
            response.raise_for_status()

        json_response = response.json()
        completion = openai.types.chat.ChatCompletion.model_validate(json_response)
        return completion

    async def generate_azure_speech(
        self,
        text: str,
        config: AzureTtsConfig,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
    ):
        data = {
            "text": text,
            "voice_name": config.voice,
            "stream": config.output_streaming,
        }
        if config.output_streaming:

            def buffer_generator():
                with requests.post(
                    url=f"{self.settings.base_url}/generate-azure-speech",
                    params={"region": self.settings.region.value},
                    json=data,
                    headers=self._get_headers(),
                    timeout=self.timeout,
                    stream=True,
                ) as response:
                    if response.status_code == 403:
                        self.send_unauthorized_error()
                        return None
                    else:
                        response.raise_for_status()
                    for chunk in response.iter_content(chunk_size=2048):
                        if not chunk:
                            break
                        yield chunk

            generator_instance = buffer_generator()
            # Initialize an incomplete buffer storage
            incomplete_buffer = b""

            def buffer_callback(audio_buffer):
                nonlocal incomplete_buffer
                try:
                    chunk = next(generator_instance)
                    # Prepend any previously incomplete buffer to the chunk
                    chunk = incomplete_buffer + chunk
                    # Compute new incomplete buffer size if any
                    remainder = len(chunk) % 2  # 2 bytes for 'int16'
                    if remainder:
                        # Store incomplete bytes for next callback
                        incomplete_buffer = chunk[-remainder:]
                        # Exclude the incomplete buffer from the current chunk
                        chunk = chunk[:-remainder]
                    else:
                        # No incomplete bytes, reset the incomplete buffer
                        incomplete_buffer = b""

                    audio_buffer[: len(chunk)] = chunk
                    return len(chunk)
                except StopIteration:
                    if incomplete_buffer:
                        # Handle any remaining incomplete buffer, if present, when the stream ends
                        audio_buffer[: len(incomplete_buffer)] = incomplete_buffer
                        chunk_length = len(incomplete_buffer)
                        incomplete_buffer = b""  # Clear the storage
                        return chunk_length
                    return 0

            await audio_player.stream_with_effects(
                buffer_callback=buffer_callback,
                config=sound_config,
                wingman_name=wingman_name,
                use_gain_boost=True,  # "Azure Streaming" low gain workaround
            )
        else:  # non-streaming
            response = requests.post(
                url=f"{self.settings.base_url}/generate-azure-speech",
                params={"region": self.settings.region.value},
                headers=self._get_headers(),
                json=data,
                timeout=self.timeout,
            )
            if response.status_code == 403:
                self.send_unauthorized_error()
                return
            else:
                response.raise_for_status()

            audio_data = response.content
            await audio_player.play_with_effects(
                input_data=audio_data,
                config=sound_config,
                wingman_name=wingman_name,
            )

    async def generate_openai_speech(
        self,
        text: str,
        voice: OpenAiTtsVoice,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
    ):
        data = {
            "text": text,
            "voice_name": voice.value,
            "stream": False,
        }
        response = requests.post(
            url=f"{self.settings.base_url}/generate-openai-speech",
            params={
                "region": self.settings.region.value,
            },
            headers=self._get_headers(),
            json=data,
            timeout=self.timeout,
        )
        if response is not None:
            if response.status_code == 403:
                self.send_unauthorized_error()
                return
            else:
                response.raise_for_status()
            await audio_player.play_with_effects(
                input_data=response.content,
                config=sound_config,
                wingman_name=wingman_name,
            )

    async def generate_image(
        self,
        text: str,
    ):
        data = {
            "text": text,
        }
        response = requests.post(
            url=f"{self.settings.base_url}/generate-image",
            params={
                "region": self.settings.region.value,
            },
            headers=self._get_headers(),
            json=data,
            timeout=self.timeout,
        )
        if response is not None:
            if response.status_code == 403:
                self.send_unauthorized_error()
                return
            else:
                response.raise_for_status()
            return response.text

    def get_available_voices(self, locale: str = ""):
        response = requests.get(
            url=f"{self.settings.base_url}/azure-voices",
            params={"region": self.settings.region.value, "locale": locale},
            timeout=self.timeout,
            headers=self._get_headers(),
        )
        if response.status_code == 403:
            self.send_unauthorized_error()
            return None
        else:
            response.raise_for_status()
        voices_dict = response.json()
        voice_infos = [
            {
                "short_name": entry.get("_short_name", ""),
                "name": entry.get("_local_name", ""),
                "local_name": entry.get("_local_name", ""),
                "locale": entry.get("_locale", ""),
                "gender": self.__resolve_gender(entry.get("_gender")),
            }
            for entry in voices_dict
        ]

        return voice_infos

    def _get_headers(self):
        token = self.secret_keeper.secrets.get("wingman_pro", "")
        return {
            "Authorization": f"Bearer {token}",
        }

    def __resolve_gender(self, enum_value: int):
        if enum_value == 1:
            return "Female"
        if enum_value == 2:
            return "Male"
        if enum_value == 3:
            return "Neutral"
        return "Unknown"

    def __remove_nones(self, obj):
        """Recursive function to remove None values from a data structure."""
        if isinstance(obj, (list, tuple, set)):
            return type(obj)(self.__remove_nones(x) for x in obj if x is not None)
        elif isinstance(obj, dict):
            return type(obj)(
                (k, self.__remove_nones(v)) for k, v in obj.items() if v is not None
            )
        else:
            return obj
