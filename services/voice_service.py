import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter
from api.interface import (
    EdgeTtsConfig,
    ElevenlabsConfig,
    HumeConfig,
    InworldConfig,
    SoundConfig,
    VoiceInfo,
    XVASynthTtsConfig,
    PocketTTSConfig,
)
from providers.edge import Edge
from providers.elevenlabs import ElevenLabs
from providers.hume import Hume
from providers.inworld import Inworld
from providers.open_ai import OpenAi, OpenAiCompatibleTts
from providers.wingman_subscription import WingmanSubscription
from providers.xvasynth import XVASynth
from providers.pocket_tts import PocketTTS

from services.audio_player import AudioPlayer
from services.config_manager import ConfigManager
from services.printr import Printr


class VoiceService:
    def __init__(
        self,
        config_manager: ConfigManager,
        audio_player: AudioPlayer,
        xvasynth: XVASynth,
        pocket_tts: PocketTTS,
    ):
        self.printr = Printr()
        self.config_manager = config_manager
        self.audio_player = audio_player
        self.xvasynth = xvasynth
        self.pocket_tts = pocket_tts

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
            path="/voices/inworld/wingman-pro",
            endpoint=self.get_wingman_pro_inworld_voices,
            response_model=list[VoiceInfo],
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/voices/pocket-tts",
            endpoint=self.get_pocket_tts_voices,
            response_model=list[VoiceInfo],
            tags=tags,
        )

        self.router.add_api_route(
            methods=["POST"],
            path="/voices/preview/pocket-tts",
            endpoint=self.play_pocket_tts,
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
            path="/voices/preview/wingman-pro/inworld",
            endpoint=self.play_wingman_pro_inworld,
            tags=tags,
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

    # GET /voices/inworld/wingman-pro
    def get_wingman_pro_inworld_voices(
        self, filter_language: str = None
    ) -> list[VoiceInfo]:
        wingman_pro = WingmanSubscription(
            wingman_name="", settings=self.config_manager.settings_config.wingman_pro
        )
        voices = wingman_pro.get_available_inworld_voices(
            filter_language=filter_language
        )
        return voices

    @staticmethod
    async def _run_playback(playback):
        """Run a playback coroutine in a worker thread with its own event loop.

        Playback previews block their loop (audio pumping + drain), so running
        them on the API event loop would freeze the server and make POST
        /stop-playback unreachable until the preview ends. This mirrors how
        wingmen play TTS via threaded_execution.
        """
        await asyncio.to_thread(asyncio.run, playback)

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
        await self._run_playback(
            openai.play_audio(
                text=text,
                voice=voice,
                model=model,
                speed=speed,
                sound_config=sound_config,
                audio_player=self.audio_player,
                wingman_name="system",
                stream=stream,
            )
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
        await self._run_playback(
            openai.play_audio(
                text=text,
                voice=voice,
                model=model,
                speed=speed,
                sound_config=sound_config,
                audio_player=self.audio_player,
                wingman_name="system",
                stream=stream,
            )
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
        await self._run_playback(
            elevenlabs.play_audio(
                text=text,
                config=config,
                sound_config=sound_config,
                audio_player=self.audio_player,
                wingman_name="system",
                stream=False,
            )
        )

    # POST /play/edgetts
    async def play_edge_tts(
        self, text: str, config: EdgeTtsConfig, sound_config: SoundConfig
    ):
        edge = Edge()
        await self._run_playback(
            edge.play_audio(
                text=text,
                config=config,
                sound_config=sound_config,
                audio_player=self.audio_player,
                wingman_name="system",
            )
        )

    # POST /play/hume
    async def play_hume(
        self, text: str, api_key: str, config: HumeConfig, sound_config: SoundConfig
    ):
        hume = Hume(api_key=api_key, wingman_name="")
        await self._run_playback(
            hume.play_audio(
                text=text,
                config=config,
                sound_config=sound_config,
                audio_player=self.audio_player,
                wingman_name="system",
            )
        )

    # POST /play/inworld
    async def play_inworld(
        self, text: str, api_key: str, config: InworldConfig, sound_config: SoundConfig
    ):
        inworld = Inworld(api_key=api_key, wingman_name="")
        await self._run_playback(
            inworld.play_audio(
                text=text,
                config=config,
                sound_config=sound_config,
                audio_player=self.audio_player,
                wingman_name="system",
            )
        )

    # POST /play/xvasynth
    async def play_xvasynth_tts(
        self, text: str, config: XVASynthTtsConfig, sound_config: SoundConfig
    ):
        await self._run_playback(
            self.xvasynth.play_audio(
                text=text,
                config=config,
                sound_config=sound_config,
                audio_player=self.audio_player,
                wingman_name="system",
            )
        )

    # GET /voices/pocket-tts
    async def get_pocket_tts_voices(self) -> list[VoiceInfo]:
        return await self.pocket_tts.get_available_voices()
    
    # POST /play/pocket-tts
    async def play_pocket_tts(
        self, text: str, config: PocketTTSConfig, sound_config: SoundConfig
    ):
        await self._run_playback(
            self.pocket_tts.play_audio(
                text=text,
                config=config,
                sound_config=sound_config,
                audio_player=self.audio_player,
                wingman_name="system",
            )
        )


    # POST /play/wingman-pro/inworld
    async def play_wingman_pro_inworld(
        self,
        text: str,
        config: InworldConfig,
        sound_config: SoundConfig,
    ):
        wingman_pro = WingmanSubscription(
            wingman_name="system",
            settings=self.config_manager.settings_config.wingman_pro,
        )
        await self._run_playback(
            wingman_pro.generate_inworld_speech(
                text=text,
                config=config,
                sound_config=sound_config,
                audio_player=self.audio_player,
                wingman_name="system",
            )
        )
