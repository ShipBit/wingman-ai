from typing import TYPE_CHECKING, Optional
import openai
import requests
from openai.types.audio import Transcription
from api.enums import (
    CommandTag,
    ConversationProvider,
    LogType,
    SttProvider,
    TtsProvider,
)
from api.interface import (
    AzureSttConfig,
    AzureTtsConfig,
    InworldConfig,
    SoundConfig,
    VoiceInfo,
    WingmanProSettings,
)
from providers.interfaces import (
    SttInterface,
    TtsInterface,
    LlmInterface,
    Transcript,
    stt_provider,
    tts_provider,
    llm_provider,
)
from services.audio_player import AudioPlayer
from services.openai_utils import get_minimal_reasoning_by_model
from services.printr import Printr
from services.secret_keeper import SecretKeeper

if TYPE_CHECKING:
    from api.interface import WingmanConfig


class WingmanSubscription:
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

    def send_server_error(self, response: requests.Response):
        self.printr.print(
            text=f"Server Error: {response.text}",
            color=LogType.ERROR,
        )

    def transcribe_whisper(self, filename: str):
        with open(filename, "rb") as audio_input:
            files = {"audio_file": (filename, audio_input)}
            response = requests.post(
                url=f"{self.settings.base_url}/transcribe-whisper",
                params={"region": self.settings.region},
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
            transcription = Transcription.model_validate(json)
            return transcription

    def transcribe_azure_speech(self, filename: str, config: AzureSttConfig):
        with open(filename, "rb") as audio_input:
            files = {"file": (filename, audio_input)}
            params = {
                "region": self.settings.region,
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
        deployment: str,
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

        # Get minimal reasoning effort for the model to reduce latency
        reasoning_params = get_minimal_reasoning_by_model(deployment)

        data = {
            "messages": serialized_messages,
            "deployment": deployment,
            "stream": stream,
            "tools": tools,
            **reasoning_params,
        }
        response = requests.post(
            url=f"{self.settings.base_url}/ask",
            params={"region": self.settings.region},
            headers=self._get_headers(),
            json=data,
            timeout=self.timeout,
        )
        if response.status_code == 401 or response.status_code == 403:
            self.send_unauthorized_error()
            return None
        elif response.status_code == 500:
            self.send_server_error(response)
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
                    params={"region": self.settings.region},
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
                params={"region": self.settings.region},
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
        voice: str,
        model: str,
        speed: float,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
    ):
        data = {
            "text": text,
            "voice_name": voice,
            "model": model,
            "speed": speed,
            "stream": False,
        }
        response = requests.post(
            url=f"{self.settings.base_url}/generate-openai-speech",
            params={
                "region": self.settings.region,
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

    async def generate_inworld_speech(
        self,
        text: str,
        config: InworldConfig,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
    ):
        data = {
            "text": text,
            "voice_id": config.voice_id,
            "stream": config.output_streaming,
            "model_id": config.model_id,
            "temperature": config.temperature,
        }
        if config.audio_config is not None:
            data["audio_config"] = config.audio_config.model_dump()

        if config.output_streaming:
            # For streaming, we need LINEAR16 format for raw PCM playback
            if data["audio_config"]:
                data["audio_config"]["audio_encoding"] = "LINEAR16"
                # Use streaming sample rate from config
                data["audio_config"][
                    "sample_rate_hertz"
                ] = config.audio_config.streaming_sample_rate_hertz

            def buffer_generator():
                with requests.post(
                    url=f"{self.settings.base_url}/generate-inworld-speech",
                    params={"region": self.settings.region},
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
                        # Skip WAV header if present (44 bytes starting with "RIFF")
                        if len(chunk) > 44 and chunk[:4] == b"RIFF":
                            chunk = chunk[44:]
                        if len(chunk) > 0:
                            yield chunk

            generator_instance = buffer_generator()
            incomplete_buffer = b""

            def buffer_callback(audio_buffer):
                nonlocal incomplete_buffer
                try:
                    chunk = next(generator_instance)
                    chunk = incomplete_buffer + chunk
                    remainder = len(chunk) % 2
                    if remainder:
                        incomplete_buffer = chunk[-remainder:]
                        chunk = chunk[:-remainder]
                    else:
                        incomplete_buffer = b""

                    audio_buffer[: len(chunk)] = chunk
                    return len(chunk)
                except StopIteration:
                    if incomplete_buffer:
                        audio_buffer[: len(incomplete_buffer)] = incomplete_buffer
                        chunk_length = len(incomplete_buffer)
                        incomplete_buffer = b""
                        return chunk_length
                    return 0

            await audio_player.stream_with_effects(
                buffer_callback=buffer_callback,
                config=sound_config,
                wingman_name=wingman_name,
                sample_rate=config.audio_config.streaming_sample_rate_hertz,
                channels=1,  # LINEAR16 is typically mono
                dtype="int16",  # LINEAR16 uses 16-bit integers
                use_gain_boost=True,  # Streaming audio needs gain boost for radio effects
            )
        else:
            response = requests.post(
                url=f"{self.settings.base_url}/generate-inworld-speech",
                params={"region": self.settings.region},
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
                "region": self.settings.region,
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
            params={"region": self.settings.region, "locale": locale},
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

    def get_available_inworld_voices(
        self, filter_language: Optional[str] = None
    ) -> list[VoiceInfo]:
        params = {"region": self.settings.region}
        if filter_language:
            params["filter"] = f"language={filter_language}"

        response = requests.get(
            url=f"{self.settings.base_url}/inworld-voices",
            params=params,
            timeout=self.timeout,
            headers=self._get_headers(),
        )
        if response.status_code == 403:
            self.send_unauthorized_error()
            return []
        else:
            response.raise_for_status()

        response_data = response.json()
        voices: list[VoiceInfo] = []
        for voice in response_data.get("voices", []):
            voice_name = voice.get("displayName", "")
            voice_id = voice.get("voiceId", "")
            voices.append(
                VoiceInfo(
                    id=voice_id,
                    name=voice_name or voice_id,
                    languages=voice.get("languages", []),
                )
            )
        return voices

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


# ---------------------------------------------------------------------------
# Adapter classes — bridge WingmanSubscription into unified provider interfaces
# ---------------------------------------------------------------------------


@stt_provider(SttProvider.WINGMAN_PRO)
class WingmanSubscriptionStt(SttInterface):
    def __init__(self, ws_instance: "WingmanSubscription", config: "WingmanConfig"):
        self._ws = ws_instance
        self._config = config

    async def transcribe(self, filename: str) -> Transcript | None:
        from api.enums import WingmanProSttProvider
        if self._config.wingman_pro.stt_provider == WingmanProSttProvider.WHISPER:
            result = self._ws.transcribe_whisper(filename=filename)
        elif self._config.wingman_pro.stt_provider == WingmanProSttProvider.AZURE_SPEECH:
            result = self._ws.transcribe_azure_speech(
                filename=filename, config=self._config.azure.stt
            )
        else:
            return None
        if result is None:
            return None
        # WingmanSubscription might return a dict instead of a real transcript object
        text = result.get("_text") if isinstance(result, dict) else result.text
        return Transcript(text=text) if text else None


@tts_provider(TtsProvider.WINGMAN_PRO)
class WingmanSubscriptionTts(TtsInterface):
    def __init__(self, ws_instance: "WingmanSubscription", config: "WingmanConfig"):
        self._ws = ws_instance
        self._config = config

    async def play_audio(self, text, sound_config, audio_player, wingman_name):
        from api.enums import WingmanProTtsProvider
        if self._config.wingman_pro.tts_provider == WingmanProTtsProvider.OPENAI:
            await self._ws.generate_openai_speech(
                text=text,
                voice=self._config.openai.tts_voice,
                model=self._config.openai.tts_model,
                speed=self._config.openai.tts_speed,
                sound_config=sound_config,
                audio_player=audio_player,
                wingman_name=wingman_name,
            )
        elif self._config.wingman_pro.tts_provider == WingmanProTtsProvider.AZURE:
            await self._ws.generate_azure_speech(
                text=text,
                config=self._config.azure.tts,
                sound_config=sound_config,
                audio_player=audio_player,
                wingman_name=wingman_name,
            )
        elif self._config.wingman_pro.tts_provider == WingmanProTtsProvider.INWORLD:
            await self._ws.generate_inworld_speech(
                text=text,
                config=self._config.inworld,
                sound_config=sound_config,
                audio_player=audio_player,
                wingman_name=wingman_name,
            )


@llm_provider(ConversationProvider.WINGMAN_PRO)
class WingmanSubscriptionLlm(LlmInterface):
    def __init__(self, ws_instance: "WingmanSubscription", config: "WingmanConfig"):
        self._ws = ws_instance
        self._config = config

    async def ask(self, messages, tools=None):
        return self._ws.ask(
            messages=messages,
            deployment=self._config.wingman_pro.conversation_deployment,
            tools=tools,
        )
