import asyncio
from typing import TYPE_CHECKING, Optional
import openai
import requests
from openai.types.audio import Transcription
from api.enums import (
    CommandTag,
    ConversationProvider,
    LogType,
    TtsProvider,
    TtsVoiceGender,
    WingmanProTtsProvider,
)
from api.interface import (
    AzureTtsConfig,
    InworldConfig,
    SoundConfig,
    SubscriptionTtsModels,
    VoiceInfo,
    WingmanProSettings,
)
from providers.interfaces import (
    TtsInterface,
    LlmInterface,
    tts_provider,
    llm_provider,
)
from services.audio_player import AudioPlayer
from services.openai_utils import get_minimal_reasoning_by_model
from services.printr import Printr
from services.context_budget import ContextOverflowError, is_context_overflow
from services.secret_keeper import SecretKeeper
from services.spoken_language import inworld_language

if TYPE_CHECKING:
    from api.interface import SettingsConfig, WingmanConfig

# The only Inworld model the backend accepts for subscriptions. Any other id
# (an old config may still say inworld-tts-2) is answered with 400
# unknown_model, so the configured model_id is ignored here.
SUBSCRIPTION_INWORLD_MODEL = "inworld-tts-2-flash"

# Azure through the backend: raw PCM when streaming, MP3 otherwise.
AZURE_STREAM_SAMPLE_RATE = 24000

_substitution_noted = False
"""The hint about a substituted voice is shown once per process, not on
every sentence the Wingman speaks."""


def tts_models_from(body: dict) -> SubscriptionTtsModels:
    """The `tts` part of the backend's /api/v1/models answer. Empty when it
    has none (an older backend, or not signed in)."""
    tts = body.get("tts") if isinstance(body, dict) else None
    if not isinstance(tts, dict):
        return SubscriptionTtsModels()
    return SubscriptionTtsModels(**tts)


def _voice_gender(value) -> Optional[TtsVoiceGender]:
    try:
        return TtsVoiceGender(value) if value else TtsVoiceGender.UNKNOWN
    except ValueError:
        return TtsVoiceGender.UNKNOWN


class WingmanSubscription:
    def __init__(
        self, wingman_name: str, settings: WingmanProSettings, timeout: int = 120
    ):
        self.wingman_name: str = wingman_name
        self.settings: WingmanProSettings = settings
        self.printr = Printr()
        self.secret_keeper: SecretKeeper = SecretKeeper()
        self.timeout = timeout

    def send_unauthorized_error(self, response: Optional[requests.Response] = None):
        """Not allowed — but there are two very different reasons.

        401 means no valid session: the client shows the login screen, which is
        the right answer. 403 means the session is fine and the plan does not
        cover this — telling someone who is signed in to sign in is a dead end,
        so the backend's own sentence is shown instead ("This plan has no tts
        access."). Free accounts hit this on speech, and before the split they
        got a bare "Unauthorized" with nothing to act on.
        """
        if response is not None and response.status_code == 403:
            message = ""
            try:
                message = (response.json().get("message") or "").strip()
            except Exception:
                pass
            self.printr.print(
                text=message or "Your plan does not include this feature.",
                color=LogType.ERROR,
            )
            return

        self.printr.print(
            text="Unauthorized",
            command_tag=CommandTag.UNAUTHORIZED,
            color=LogType.ERROR,
        )

    def send_quota_error(self, response: requests.Response):
        """The allowance of the account's current window is used up. Each
        account's window starts on its own day of the month, so the date comes
        from the backend.

        The backend's own sentence is preferred: it knows the plan, and what a
        free account should hear ("a subscription lifts the limit") is not what a
        paying one should. Ours is the fallback for an answer we cannot read.
        """
        message = ""
        resets_at = ""
        try:
            body = response.json()
            message = (body.get("message") or "").strip()
            resets_at = (body.get("resets_at") or "")[:10]
        except Exception:
            pass

        if not message:
            message = (
                f"Your Wingman allowance is used up. It resets on {resets_at}."
                if resets_at
                else "Your Wingman allowance is used up."
            )

        self.printr.print(text=message, color=LogType.ERROR)

    def send_server_error(self, response: requests.Response):
        self.printr.print(
            text=f"Server Error: {response.text}",
            color=LogType.ERROR,
        )

    def transcribe(self, filename: str, languages: Optional[list[str]] = None):
        """One call for all cloud transcription. Which model runs behind it is
        the backend's business (plan section 6.2); the shape is OpenAI's, so the
        answer is a Transcription with `.text`."""
        with open(filename, "rb") as audio_input:
            files = {"file": (filename, audio_input)}
            data = {}
            # OpenAI takes a single language hint, not a list.
            if languages:
                data["language"] = languages[0]
            response = requests.post(
                url=f"{self.settings.base_url}/api/v1/audio/transcriptions",
                files=files,
                data=data,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
        if response.status_code in (401, 403):
            self.send_unauthorized_error(response)
            return None
        if response.status_code == 429:
            self.send_quota_error(response)
            return None
        response.raise_for_status()
        return Transcription.model_validate(response.json())

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

        # `deployment` is a gateway model id, straight from the config — the
        # same string the backend hands out in /api/v1/models. A config naming a
        # model the plan no longer offers is not an error: the backend answers
        # with the plan default and says so in `x-wingman-substituted`.
        data = {
            "messages": serialized_messages,
            "model": deployment,
            "stream": stream,
            "tools": tools,
            **reasoning_params,
        }
        response = requests.post(
            url=f"{self.settings.base_url}/api/v1/chat/completions",
            headers=self._get_headers(),
            json=data,
            timeout=self.timeout,
        )
        if response.status_code == 401 or response.status_code == 403:
            self.send_unauthorized_error(response)
            return None
        elif response.status_code == 429:
            self.send_quota_error(response)
            return None
        elif response.status_code >= 500:
            self.send_server_error(response)
            return None
        elif response.status_code == 400:
            # "The conversation is too large": over the backend's 400 KB. The
            # wingman shortens and retries once instead of failing every turn.
            try:
                message = (response.json().get("message") or "").strip()
            except Exception:
                message = ""
            if "too large" in message.lower() or is_context_overflow(message):
                raise ContextOverflowError(message)
            response.raise_for_status()
        else:
            response.raise_for_status()

        json_response = response.json()
        completion = openai.types.chat.ChatCompletion.model_validate(json_response)
        return completion

    async def generate_inworld_speech(
        self,
        text: str,
        config: InworldConfig,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
        language: Optional[str] = None,
        preview: bool = False,
    ):
        data = {
            "provider": "inworld",
            "input": text,
            "voice_id": config.voice_id,
            "stream": config.output_streaming,
            # Not config.model_id: see SUBSCRIPTION_INWORLD_MODEL.
            "model_id": SUBSCRIPTION_INWORLD_MODEL,
            "temperature": config.temperature,
        }
        if language:
            data["language"] = language
        if preview:
            data["preview"] = True
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

            await self._stream_speech(
                data=data,
                sound_config=sound_config,
                audio_player=audio_player,
                wingman_name=wingman_name,
                sample_rate=config.audio_config.streaming_sample_rate_hertz,
                # Inworld puts a 44-byte WAV header in front of LINEAR16.
                strip_riff_header=True,
            )
        else:
            await self._play_speech(
                data=data,
                sound_config=sound_config,
                audio_player=audio_player,
                wingman_name=wingman_name,
            )

    async def generate_azure_speech(
        self,
        text: str,
        config: AzureTtsConfig,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
        language: Optional[str] = None,
        preview: bool = False,
    ):
        data = {
            "provider": "azure",
            "input": text,
            "voice_id": config.voice,
            "stream": config.output_streaming,
        }
        if language:
            data["language"] = language
        if preview:
            data["preview"] = True

        if config.output_streaming:
            # Raw PCM, 16-bit signed little-endian, mono, 24 kHz, no header.
            await self._stream_speech(
                data=data,
                sound_config=sound_config,
                audio_player=audio_player,
                wingman_name=wingman_name,
                sample_rate=AZURE_STREAM_SAMPLE_RATE,
                strip_riff_header=False,
            )
        else:  # non-streaming: MP3
            await self._play_speech(
                data=data,
                sound_config=sound_config,
                audio_player=audio_player,
                wingman_name=wingman_name,
            )

    def _speech_refused(self, response: requests.Response) -> bool:
        """True (after telling the user) when the backend did not speak."""
        if response.status_code in (401, 403):
            self.send_unauthorized_error(response)
            return True
        if response.status_code == 429:
            # Without this branch a used-up allowance surfaced as "Error during
            # TTS playback".
            self.send_quota_error(response)
            return True
        response.raise_for_status()
        return False

    async def _note_substitution(self, voice: Optional[str], wingman_name: str):
        """The plan does not include the configured voice, so the backend
        spoke with its free voice of the same gender. Said once per process."""
        global _substitution_noted
        if not voice or _substitution_noted:
            return
        _substitution_noted = True
        await self.printr.print_async(
            f"This voice needs a higher plan. Playing {voice} instead.",
            color=LogType.INFO,
            source_name=wingman_name,
        )

    async def _stream_speech(
        self,
        data: dict,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
        sample_rate: int,
        strip_riff_header: bool,
    ):
        substituted: Optional[str] = None

        def buffer_generator():
            nonlocal substituted
            with requests.post(
                url=f"{self.settings.base_url}/api/v1/audio/speech",
                json=data,
                headers=self._get_headers(),
                timeout=self.timeout,
                stream=True,
            ) as response:
                if self._speech_refused(response):
                    return None
                substituted = response.headers.get("x-voice-substituted")
                for chunk in response.iter_content(chunk_size=2048):
                    if not chunk:
                        break
                    # Skip WAV header if present (44 bytes starting with "RIFF")
                    if strip_riff_header and len(chunk) > 44 and chunk[:4] == b"RIFF":
                        chunk = chunk[44:]
                    if len(chunk) > 0:
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
                    # Handle any remaining incomplete buffer when the stream ends
                    audio_buffer[: len(incomplete_buffer)] = incomplete_buffer
                    chunk_length = len(incomplete_buffer)
                    incomplete_buffer = b""  # Clear the storage
                    return chunk_length
                return 0

        await audio_player.stream_with_effects(
            buffer_callback=buffer_callback,
            config=sound_config,
            wingman_name=wingman_name,
            sample_rate=sample_rate,
            channels=1,
            dtype="int16",
            use_gain_boost=True,  # Streaming audio needs gain boost for radio effects
        )
        await self._note_substitution(substituted, wingman_name)

    async def _play_speech(
        self,
        data: dict,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
    ):
        response = requests.post(
            url=f"{self.settings.base_url}/api/v1/audio/speech",
            headers=self._get_headers(),
            json=data,
            timeout=self.timeout,
        )
        if self._speech_refused(response):
            return

        await self._note_substitution(
            response.headers.get("x-voice-substituted"), wingman_name
        )
        await audio_player.play_with_effects(
            input_data=response.content,
            config=sound_config,
            wingman_name=wingman_name,
        )

    async def generate_image(
        self,
        text: str,
        aspect: str = "square",
        images: Optional[list[str]] = None,
    ):
        """`images` are reference pictures as small JPEG data URLs (see
        services/image_generation.reference_data_url). With them the backend
        edits instead of generating from scratch."""
        data = {
            "prompt": text,
            "aspect": aspect,
        }
        if images:
            data["images"] = images
        # An image takes 7 to 15 seconds. In a thread, so Core keeps talking to
        # the client and listening meanwhile.
        response = await asyncio.to_thread(
            requests.post,
            url=f"{self.settings.base_url}/api/v1/images/generations",
            headers=self._get_headers(),
            json=data,
            timeout=self.timeout,
        )
        if response is not None:
            if response.status_code in (401, 403):
                self.send_unauthorized_error(response)
                return
            else:
                response.raise_for_status()
            # The answer is OpenAI-shaped; callers want the data URL they used to
            # get from the old endpoint.
            data = response.json().get("data") or [{}]
            return data[0].get("url", "")

    def _get_voices(
        self, provider: str, filter_language: Optional[str] = None
    ) -> list[VoiceInfo]:
        params = {"provider": provider}
        if filter_language:
            params["language"] = filter_language

        response = requests.get(
            url=f"{self.settings.base_url}/api/v1/voices",
            params=params,
            timeout=self.timeout,
            headers=self._get_headers(),
        )
        if response.status_code in (401, 403):
            self.send_unauthorized_error(response)
            return []
        else:
            response.raise_for_status()

        voices: list[VoiceInfo] = []
        for voice in response.json().get("voices", []):
            voice_id = voice.get("voiceId", "")
            voice_name = voice.get("displayName", "")
            voices.append(
                VoiceInfo(
                    id=voice_id,
                    name=voice_name or voice_id,
                    gender=_voice_gender(voice.get("gender")),
                    locale=voice.get("locale") or None,
                    languages=voice.get("languages", []),
                    provider=provider,
                    # One sentence from Inworld, the personality words from
                    # Azure. The picker shows it and searches in it.
                    description=voice.get("description") or None,
                    locked=bool(voice.get("locked", False)),
                )
            )
        return voices

    def get_available_azure_voices(
        self, filter_language: Optional[str] = None
    ) -> list[VoiceInfo]:
        """Azure voices, every one of them, `locked` where the plan does not
        include it."""
        return self._get_voices("azure", filter_language)

    def get_available_inworld_voices(
        self, filter_language: Optional[str] = None
    ) -> list[VoiceInfo]:
        return self._get_voices("inworld", filter_language)

    def _get_headers(self):
        token = self.secret_keeper.secrets.get("wingman_pro", "")
        return {
            "Authorization": f"Bearer {token}",
        }

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


@tts_provider(TtsProvider.WINGMAN_PRO)
class WingmanSubscriptionTts(TtsInterface):
    def __init__(
        self,
        ws_instance: "WingmanSubscription",
        config: "WingmanConfig",
        settings: "SettingsConfig",
    ):
        self._ws = ws_instance
        self._config = config
        self._settings = settings

    async def play_audio(self, text, sound_config, audio_player, wingman_name):
        language = inworld_language(
            self._settings.spoken_language, self._settings.other_language
        )
        if self._config.wingman_pro.tts_provider == WingmanProTtsProvider.AZURE:
            await self._ws.generate_azure_speech(
                text=text,
                config=self._config.wingman_pro.azure,
                sound_config=sound_config,
                audio_player=audio_player,
                wingman_name=wingman_name,
                language=language,
            )
        elif self._config.wingman_pro.tts_provider == WingmanProTtsProvider.INWORLD:
            await self._ws.generate_inworld_speech(
                text=text,
                config=self._config.inworld,
                sound_config=sound_config,
                audio_player=audio_player,
                wingman_name=wingman_name,
                language=language,
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
