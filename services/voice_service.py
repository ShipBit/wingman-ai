import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter
from api.enums import AzureRegion
from api.interface import (
    AzureTtsConfig,
    EdgeTtsConfig,
    ElevenlabsConfig,
    SoundConfig,
    VoiceInfo,
    XVASynthTtsConfig,
)
from providers.edge import Edge
from providers.elevenlabs import ElevenLabs
from providers.open_ai import OpenAi, OpenAiAzure
from providers.wingman_pro import WingmanPro
from providers.xvasynth import XVASynth
from services.audio_player import AudioPlayer
from services.config_manager import ConfigManager
from services.printr import Printr


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
            methods=["POST"],
            path="/voices/preview/openai",
            endpoint=self.play_openai_tts,
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

    # GET /voices/azure
    def get_azure_voices(self, api_key: str, region: AzureRegion, locale: str = ""):
        azure = OpenAiAzure()
        voices = azure.get_available_voices(
            api_key=api_key, region=region.value, locale=locale
        )
        result = [self.__convert_azure_voice(voice) for voice in voices]
        return result

    # GET /voices/azure/wingman-pro
    def get_wingman_pro_azure_voices(self, locale: str = ""):
        wingman_pro = WingmanPro(
            wingman_name="", settings=self.config_manager.settings_config.wingman_pro
        )
        voices = wingman_pro.get_available_voices(locale=locale)
        if not voices:
            return []
        result = [self.__convert_azure_voice(voice) for voice in voices]
        return result

    # POST /play/openai
    async def play_openai_tts(
        self,
        text: str,
        api_key: str,
        voice: str,
        model: str,
        speed: float,
        sound_config: SoundConfig,
    ):
        openai = OpenAi(api_key=api_key)
        await openai.play_audio(
            text=text,
            voice=voice,
            model=model,
            speed=speed,
            sound_config=sound_config,
            audio_player=self.audio_player,
            wingman_name="system",
        )

    # POST /play/azure
    async def play_azure_tts(
        self, text: str, api_key: str, config: AzureTtsConfig, sound_config: SoundConfig
    ):
        azure = OpenAiAzure()
        await azure.play_audio(
            text=text,
            api_key=api_key,
            config=config,
            sound_config=sound_config,
            audio_player=self.audio_player,
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
        elevenlabs = ElevenLabs(api_key=api_key, wingman_name="")
        await elevenlabs.play_audio(
            text=text,
            config=config,
            sound_config=sound_config,
            audio_player=self.audio_player,
            wingman_name="system",
            stream=False,
        )

    # POST /play/edgetts
    async def play_edge_tts(
        self, text: str, config: EdgeTtsConfig, sound_config: SoundConfig
    ):
        edge = Edge()
        await edge.play_audio(
            text=text,
            config=config,
            sound_config=sound_config,
            audio_player=self.audio_player,
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
        wingman_pro = WingmanPro(
            wingman_name="system",
            settings=self.config_manager.settings_config.wingman_pro,
        )
        await wingman_pro.generate_azure_speech(
            text=text,
            config=config,
            sound_config=sound_config,
            audio_player=self.audio_player,
            wingman_name="system",
        )

    # POST /play/wingman-pro/azure
    async def play_wingman_pro_openai(
        self, text: str, voice: str, model: str, speed: float, sound_config: SoundConfig
    ):
        wingman_pro = WingmanPro(
            wingman_name="system",
            settings=self.config_manager.settings_config.wingman_pro,
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
