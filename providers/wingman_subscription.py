from typing import TYPE_CHECKING, Optional
import openai
import requests
from openai.types.audio import Transcription
from api.enums import (
    CommandTag,
    ConversationProvider,
    LogType,
    TtsProvider,
)
from api.interface import (
    InworldConfig,
    SoundConfig,
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
        """The monthly allowance is used up.

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
                f"Your Wingman allowance for this month is used up. It resets on {resets_at}."
                if resets_at
                else "Your Wingman allowance for this month is used up."
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
    ):
        data = {
            "provider": "inworld",
            "input": text,
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
                    url=f"{self.settings.base_url}/api/v1/audio/speech",
                    json=data,
                    headers=self._get_headers(),
                    timeout=self.timeout,
                    stream=True,
                ) as response:
                    if response.status_code in (401, 403):
                        self.send_unauthorized_error(response)
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
                url=f"{self.settings.base_url}/api/v1/audio/speech",
                headers=self._get_headers(),
                json=data,
                timeout=self.timeout,
            )
            if response.status_code in (401, 403):
                self.send_unauthorized_error(response)
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
            "prompt": text,
        }
        response = requests.post(
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

    def get_available_voices(self, locale: str = ""):
        """OpenAI voices. They carry no locale or gender — the fields stay in the
        answer because the settings UI reads them, they are simply empty now."""
        response = requests.get(
            url=f"{self.settings.base_url}/api/v1/voices",
            params={"provider": "openai"},
            timeout=self.timeout,
            headers=self._get_headers(),
        )
        if response.status_code in (401, 403):
            self.send_unauthorized_error(response)
            return None
        response.raise_for_status()

        return [
            {
                "short_name": entry.get("voiceId", ""),
                "name": entry.get("displayName", entry.get("voiceId", "")),
                "local_name": entry.get("displayName", entry.get("voiceId", "")),
                "locale": locale,
                "gender": "Unknown",
            }
            for entry in response.json().get("voices", [])
        ]

    def get_available_inworld_voices(
        self, filter_language: Optional[str] = None
    ) -> list[VoiceInfo]:
        params = {"provider": "inworld"}
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
    def __init__(self, ws_instance: "WingmanSubscription", config: "WingmanConfig"):
        self._ws = ws_instance
        self._config = config

    async def play_audio(self, text, sound_config, audio_player, wingman_name):
        # One provider, so nothing to dispatch on. `wingman_pro.tts_provider`
        # still exists and still says "inworld" — keeping the field means a
        # second provider can come back without a config migration.
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
