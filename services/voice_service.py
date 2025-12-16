import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter
from api.enums import AzureRegion
from api.interface import (
    AzureTtsConfig,
    EdgeTtsConfig,
    ElevenlabsConfig,
    HumeConfig,
    InworldConfig,
    SoundConfig,
    VoiceInfo,
    XVASynthTtsConfig,
)
from providers.edge import Edge
from providers.elevenlabs import ElevenLabs
from providers.hume import Hume
from providers.inworld import Inworld
from providers.open_ai import OpenAi, OpenAiAzure, OpenAiCompatibleTts
from providers.wingman_pro import WingmanPro
from providers.xvasynth import XVASynth
from services.audio_player import AudioPlayer
from services.config_manager import ConfigManager
from services.printr import Printr
from services.secret_keeper import SecretKeeper


class VoiceService:
    def __init__(
        self,
        config_manager: ConfigManager,
        audio_player: AudioPlayer,
        xvasynth: XVASynth,
    ):
        self.printr = Printr()
        self.config_manager = config_manager
        self.audio_player = audio_player
        self.xvasynth = xvasynth
        self.secret_keeper = SecretKeeper()

        self.router = APIRouter()
        tags = ["voice"]
        self.router.add_api_route(
            methods=["GET"],
            path="/voices/elevenlabs",
            endpoint=self.get_elevenlabs_voices,
            response_model=list[VoiceInfo],
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/voices/hume",
            endpoint=self.get_hume_voices,
            response_model=list[VoiceInfo],
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/voices/inworld",
            endpoint=self.get_inworld_voices,
            response_model=list[VoiceInfo],
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/voices/openai-compatible",
            endpoint=self.get_openai_compatible_voices,
            response_model=list[VoiceInfo],
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/voices/azure",
            endpoint=self.get_azure_voices,
            response_model=list[VoiceInfo],
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/voices/azure/wingman-pro",
            endpoint=self.get_wingman_pro_azure_voices,
            response_model=list[VoiceInfo],
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/voices/inworld/wingman-pro",
            endpoint=self.get_wingman_pro_inworld_voices,
            response_model=list[VoiceInfo],
            tags=tags,
        )

        self.router.add_api_route(
            methods=["POST"],
            path="/voices/preview/openai",
            endpoint=self.play_openai_tts,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/voices/preview/openai-compatible",
            endpoint=self.play_openai_compatible_tts,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/voices/preview/azure",
            endpoint=self.play_azure_tts,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/voices/preview/elevenlabs",
            endpoint=self.play_elevenlabs_tts,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/voices/preview/hume",
            endpoint=self.play_hume,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/voices/preview/inworld",
            endpoint=self.play_inworld,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/voices/preview/edgetts",
            endpoint=self.play_edge_tts,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/voices/preview/xvasynth",
            endpoint=self.play_xvasynth_tts,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/voices/preview/wingman-pro/azure",
            endpoint=self.play_wingman_pro_azure,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/voices/preview/wingman-pro/openai",
            endpoint=self.play_wingman_pro_openai,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/voices/preview/wingman-pro/inworld",
            endpoint=self.play_wingman_pro_inworld,
            tags=tags,
        )

    def __convert_azure_voice(self, voice):
        # retrieved from Wingman Pro as serialized dict
        if isinstance(voice, dict):
            return VoiceInfo(
                id=voice.get("short_name"),
                name=voice.get("local_name"),
                gender=voice.get("gender"),
                locale=voice.get("locale"),
            )
        # coming directly from Azure API as a voice object
        else:
            return VoiceInfo(
                id=voice.short_name,
                name=voice.local_name,
                gender=voice.gender.name,
                locale=voice.locale,
            )

    # GET /voices/elevenlabs
    async def get_elevenlabs_voices(self, api_key: str) -> list[VoiceInfo]:
        elevenlabs = ElevenLabs(api_key=api_key, wingman_name="")
        try:
            # Run the synchronous method in a separate thread
            loop = asyncio.get_running_loop()
            with ThreadPoolExecutor() as pool:
                voices = await loop.run_in_executor(
                    pool, elevenlabs.get_available_voices
                )

            convert = lambda voice: VoiceInfo(id=voice.voiceID, name=voice.name)
            result = [convert(voice) for voice in voices]
            return result
        except ValueError as e:
            self.printr.toast_error(f"Elevenlabs: \n{str(e)}")
            return []

    # GET /voices/hume
    async def get_hume_voices(self, api_key: str) -> list[VoiceInfo]:
        hume = Hume(api_key=api_key, wingman_name="")
        result = await hume.get_available_voices()
        return result

    # GET /voices/inworld
    async def get_inworld_voices(self, api_key: str) -> list[VoiceInfo]:
        inworld = Inworld(api_key=api_key, wingman_name="")
        result = await inworld.get_available_voices()
        return result

    # GET /voices/openai-compatible
    async def get_openai_compatible_voices(
        self,
        api_key: str,
        base_url: str,
        voices_endpoint: str | None = None,
    ) -> list[VoiceInfo]:
        openai_compatible = OpenAiCompatibleTts(api_key=api_key, base_url=base_url)
        return await openai_compatible.get_available_voices(
            voices_endpoint=voices_endpoint
        )

    # GET /voices/azure
    def get_azure_voices(self, api_key: str, region: AzureRegion, locale: str = ""):
        azure = OpenAiAzure()
        voices = azure.get_available_voices(
            api_key=api_key, region=region.value, locale=locale
        )
        result = [self.__convert_azure_voice(voice) for voice in voices]
        return result

    # GET /voices/azure/wingman-pro
    async def get_wingman_pro_azure_voices(self, locale: str = ""):
        api_key = await self.secret_keeper.retrieve(
            requester="VoiceService",
            key="wingman_pro",
            prompt_if_missing=False,
        )
        if not api_key:
            return []
        wingman_pro = WingmanPro(
            wingman_config=None,
            provider_settings=self.config_manager.settings_config.wingman_pro,
            api_key=api_key,
            wingman_name="VoiceService",
        )
        voices = wingman_pro.get_available_voices(locale=locale)
        if not voices:
            return []
        result = [self.__convert_azure_voice(voice) for voice in voices]
        return result

    # GET /voices/inworld/wingman-pro
    async def get_wingman_pro_inworld_voices(
        self, filter_language: str = None
    ) -> list[VoiceInfo]:
        api_key = await self.secret_keeper.retrieve(
            requester="VoiceService",
            key="wingman_pro",
            prompt_if_missing=False,
        )
        if not api_key:
            return []
        wingman_pro = WingmanPro(
            wingman_config=None,
            provider_settings=self.config_manager.settings_config.wingman_pro,
            api_key=api_key,
            wingman_name="VoiceService",
        )
        voices = wingman_pro.get_available_inworld_voices(
            filter_language=filter_language
        )
        return voices

    # POST /play/openai
    async def play_openai_tts(
        self,
        text: str,
        api_key: str,
        voice: str,
        model: str,
        speed: float,
        sound_config: SoundConfig,
        stream: bool,
    ):
        openai = OpenAi(api_key=api_key)
        await openai.synthesize(
            text=text,
            audio_player=self.audio_player,
            sound_config=sound_config,
            wingman_name="system",
            voice=voice,
            model=model,
            speed=speed,
            stream=stream,
        )

    # POST /play/openai-compatible
    async def play_openai_compatible_tts(
        self,
        text: str,
        api_key: str,
        base_url: str,
        voice: str,
        model: str,
        speed: float,
        sound_config: SoundConfig,
        stream: bool,
    ):
        openai = OpenAiCompatibleTts(api_key=api_key, base_url=base_url)
        await openai.synthesize(
            text=text,
            audio_player=self.audio_player,
            sound_config=sound_config,
            wingman_name="system",
            voice=voice,
            model=model,
            speed=speed,
            stream=stream,
        )

    # POST /play/azure
    async def play_azure_tts(
        self, text: str, api_key: str, config: AzureTtsConfig, sound_config: SoundConfig
    ):
        # Create a minimal Azure instance for preview (tts_api_key only)
        from types import SimpleNamespace

        minimal_config = SimpleNamespace()
        azure = OpenAiAzure(
            config=minimal_config,
            whisper_api_key=None,
            speech_api_key=None,
            tts_api_key=api_key,
            llm_api_key=None,
        )
        azure.tts_config = config
        await azure.synthesize(
            text=text,
            audio_player=self.audio_player,
            sound_config=sound_config,
            wingman_name="system",
        )

    # POST /play/elevenlabs
    async def play_elevenlabs_tts(
        self,
        text: str,
        api_key: str,
        config: ElevenlabsConfig,
        sound_config: SoundConfig,
    ):
        elevenlabs = ElevenLabs(config=config, api_key=api_key, wingman_name="")
        await elevenlabs.synthesize(
            text=text,
            audio_player=self.audio_player,
            sound_config=sound_config,
            wingman_name="system",
            stream=False,
        )

    # POST /play/edgetts
    async def play_edge_tts(
        self, text: str, config: EdgeTtsConfig, sound_config: SoundConfig
    ):
        edge = Edge(config=config)
        await edge.synthesize(
            text=text,
            audio_player=self.audio_player,
            sound_config=sound_config,
            wingman_name="system",
        )

    # POST /play/hume
    async def play_hume(
        self, text: str, api_key: str, config: HumeConfig, sound_config: SoundConfig
    ):
        hume = Hume(config=config, api_key=api_key, wingman_name="")
        await hume.synthesize(
            text=text,
            audio_player=self.audio_player,
            sound_config=sound_config,
            wingman_name="system",
        )

    # POST /play/inworld
    async def play_inworld(
        self, text: str, api_key: str, config: InworldConfig, sound_config: SoundConfig
    ):
        inworld = Inworld(config=config, api_key=api_key, wingman_name="")
        await inworld.synthesize(
            text=text,
            audio_player=self.audio_player,
            sound_config=sound_config,
            wingman_name="system",
        )

    # POST /play/xvasynth
    async def play_xvasynth_tts(
        self, text: str, config: XVASynthTtsConfig, sound_config: SoundConfig
    ):
        await self.xvasynth.play_audio(
            text=text,
            config=config,
            sound_config=sound_config,
            audio_player=self.audio_player,
            wingman_name="system",
        )

    # POST /play/wingman-pro/azure
    async def play_wingman_pro_azure(
        self, text: str, config: AzureTtsConfig, sound_config: SoundConfig
    ):
        api_key = await self.secret_keeper.retrieve(
            requester="VoiceService",
            key="wingman_pro",
            prompt_if_missing=False,
        )
        if not api_key:
            return
        wingman_pro = WingmanPro(
            wingman_config=None,
            provider_settings=self.config_manager.settings_config.wingman_pro,
            api_key=api_key,
            wingman_name="VoiceService",
        )
        await wingman_pro.generate_azure_speech(
            text=text,
            config=config,
            sound_config=sound_config,
            audio_player=self.audio_player,
            wingman_name="system",
        )

    # POST /play/wingman-pro/openai
    async def play_wingman_pro_openai(
        self, text: str, voice: str, model: str, speed: float, sound_config: SoundConfig
    ):
        api_key = await self.secret_keeper.retrieve(
            requester="VoiceService",
            key="wingman_pro",
            prompt_if_missing=False,
        )
        if not api_key:
            return
        wingman_pro = WingmanPro(
            wingman_config=None,
            provider_settings=self.config_manager.settings_config.wingman_pro,
            api_key=api_key,
            wingman_name="VoiceService",
        )
        await wingman_pro.generate_openai_speech(
            text=text,
            voice=voice,
            model=model,
            speed=speed,
            sound_config=sound_config,
            audio_player=self.audio_player,
            wingman_name="system",
        )

    # POST /play/wingman-pro/inworld
    async def play_wingman_pro_inworld(
        self,
        text: str,
        config: InworldConfig,
        sound_config: SoundConfig,
    ):
        api_key = await self.secret_keeper.retrieve(
            requester="VoiceService",
            key="wingman_pro",
            prompt_if_missing=False,
        )
        if not api_key:
            return
        wingman_pro = WingmanPro(
            wingman_config=None,
            provider_settings=self.config_manager.settings_config.wingman_pro,
            api_key=api_key,
            wingman_name="VoiceService",
        )
        await wingman_pro.generate_inworld_speech(
            text=text,
            config=config,
            sound_config=sound_config,
            audio_player=self.audio_player,
            wingman_name="system",
        )
