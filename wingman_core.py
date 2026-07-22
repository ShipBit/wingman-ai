import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
import platform
import re
import threading
from typing import Optional
import pygame
from google.genai import types
from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
import requests
import sounddevice as sd
from showinfm import show_in_file_manager
import azure.cognitiveservices.speech as speechsdk
import keyboard.keyboard as keyboard
import mouse.mouse as mouse
from api.commands import (
    AudioLibraryPlaybackFinishedCommand,
    CoreStateChangedCommand,
    LogCommand,
    VoiceActivationMutedCommand,
)
from api.enums import (
    AzureRegion,
    CommandTag,
    ConversationProvider,
    CoreState,
    LogSource,
    LogType,
    VoiceActivationSttProvider,
    WingmanInitializationErrorType,
)
from api.interface import (
    AudioDevice,
    AudioFile,
    AzureSttConfig,
    CommandJoystickConfig,
    Config,
    ConfigWithDirInfo,
    CoreStatusResponse,
    ElevenlabsModel,
    MemoryEntryResponse,
    MemoryUpdateRequest,
    MicStatusResponse,
    OpenRouterEndpointResult,
    DetectContextSizeRequest,
    MemorySuiteRequest,
    PlaygroundChatRequest,
    ParakeetSttConfig,
    PocketTTSConfig,
    PocketTTSPreloadResult,
    SoundConfig,
    TestConnectionResult,
    VoiceActivationSettings,
    WingmanInitializationError,
)
from providers.elevenlabs import ElevenLabs
from providers.faster_whisper import FasterWhisper
from providers.parakeet import Parakeet
from providers.google import GoogleGenAI
from providers.llama_cpp_provider import LlamaCppProvider
from providers.llama_cpp_remote import LlamaCppRemote
from providers.open_ai import OpenAi
from providers.whispercpp import Whispercpp
from providers.wingman_subscription import WingmanSubscription
from providers.xvasynth import XVASynth
from providers.pocket_tts import PocketTTS
from wingmen.open_ai_wingman import OpenAiWingman
from wingmen.wingman import Wingman
from services.file import (
    get_writable_dir,
    get_audio_library_dir,
    get_custom_voices_dir,
    get_custom_skills_dir,
    get_models_dir,
    get_pocket_tts_models_dir,
    get_prompt,
)
from services.model_downloader import ModelDownloader
from services.stt_provider_manager import SttProviderManager
from services.local_ai_service import LocalAiService
from services.token_utils import count_tokens
from services.local_model_manager import LocalModelManager
from services.voice_service import VoiceService
from services.settings_service import SettingsService
from services.config_service import ConfigService
from services.audio_player import AudioPlayer
from services.audio_library import AudioLibrary
from services.benchmark import Benchmark
from services.image_processing import process_image, validate_image_mime
from services.model_metadata import ModelMetadataService
from services.audio_recorder import RECORDING_PATH, AudioRecorder
from services.threading_utils import threaded_execution
from services.config_manager import ConfigManager
from services.printr import Printr
from services.secret_keeper import SecretKeeper
from services.system_manager import SystemManager
from services.tower import Tower
from services.websocket_user import WebSocketUser
from hud_server.server import HudServer
from hud_server.validation import validate_hud_settings, get_invalid_summary


class WingmanCore(WebSocketUser):
    def __init__(
        self,
        config_manager: ConfigManager,
        app_root_path: str,
        app_is_bundled: bool,
        system_manager: SystemManager,
    ):
        self.printr = Printr()
        self.app_root_path = app_root_path
        self.system_manager = system_manager
        self.is_client_logged_in: bool = False
        self.client_plan: str = "Free"
        self.client_account_name: str = ""

        self.router = APIRouter()
        tags = ["core"]
        self.router.add_api_route(
            methods=["GET"],
            path="/audio-devices",
            endpoint=self.get_audio_devices,
            response_model=list[AudioDevice],
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/voice-activation/mute",
            endpoint=self.start_voice_recognition,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/startup-errors",
            endpoint=self.get_startup_errors,
            response_model=list[WingmanInitializationError],
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/stop-playback",
            endpoint=self.stop_playback,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/send-text-to-wingman",
            endpoint=self.send_text_to_wingman,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/start-recording-for-wingman",
            endpoint=self.start_recording_for_wingman,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/stop-recording-for-wingman",
            endpoint=self.stop_recording_for_wingman,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/generate-greeting",
            endpoint=self.generate_greeting,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/ask-wingman-conversation-provider",
            endpoint=self.ask_wingman_conversation_provider,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/generate-image",
            endpoint=self.generate_image,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/send-audio-to-wingman",
            endpoint=self.send_audio_to_wingman,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/reset-conversation-history",
            endpoint=self.reset_conversation_history,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/condense-conversation",
            endpoint=self.condense_conversation,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/wingman-context",
            response_model=str,
            endpoint=self.get_wingman_context,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/wingman-conversation",
            response_model=list[dict],
            endpoint=self.get_wingman_conversation,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/fasterwhisper/modelsizes",
            response_model=list[str],
            endpoint=self.get_fasterwhisper_modelsizes,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/fasterwhisper/computetypes",
            response_model=list[str],
            endpoint=self.get_fasterwhisper_computetypes,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/fasterwhisper/devices",
            response_model=list[str],
            endpoint=self.get_fasterwhisper_devices,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/xvasynth/start",
            endpoint=self.start_xvasynth,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/xvasynth/stop",
            endpoint=self.stop_xvasynth,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/xvsynth/model_dirs",
            response_model=list[str],
            endpoint=self.get_xvasynth_model_dirs,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/xvsynth/voices",
            response_model=list[str],
            endpoint=self.get_xvasynth_voices,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/pocket_tts/start",
            endpoint=self.start_pocket_tts,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/pocket_tts/stop",
            endpoint=self.stop_pocket_tts,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/pocket_tts/status",
            endpoint=self.get_pocket_tts_status,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/pocket_tts/models",
            endpoint=self.get_pocket_tts_models,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/pocket_tts/preload_voice",
            response_model=PocketTTSPreloadResult,
            endpoint=self.preload_pocket_tts_voice,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/pocket_tts/precompute_voices",
            endpoint=self.precompute_pocket_tts_voices,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/open-filemanager/pocket-tts-models",
            endpoint=self.open_pocket_tts_models_directory,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/voices/preprocess",
            endpoint=self.preprocess_custom_voice,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/open-filemanager",
            endpoint=self.open_file_manager,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/open-filemanager/config",
            endpoint=self.open_config_directory,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/open-filemanager/logs",
            endpoint=self.open_logs_directory,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/open-filemanager/audio-library",
            endpoint=self.open_audio_library_directory,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/open-filemanager/custom-voices",
            endpoint=self.open_custom_voices_directory,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/open-filemanager/local-models",
            endpoint=self.open_local_models_directory,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/open-filemanager/custom-skills",
            endpoint=self.open_custom_skills_directory,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/models/openrouter",
            response_model=list,
            endpoint=self.get_openrouter_models,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/models/openrouter/endpoints",
            response_model=Optional[OpenRouterEndpointResult],
            endpoint=self.get_openrouter_model_endpoints,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/models/groq",
            response_model=list,
            endpoint=self.get_groq_models,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/models/cerebras",
            response_model=list,
            endpoint=self.get_cerebras_models,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/models/xai",
            response_model=list,
            endpoint=self.get_xai_models,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/models/mistral",
            response_model=list,
            endpoint=self.get_mistral_models,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/models/openai",
            response_model=list,
            endpoint=self.get_openai_models,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/models/elevenlabs",
            response_model=list[ElevenlabsModel],
            endpoint=self.get_elevenlabs_models,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/models/google",
            response_model=list[types.Model],
            endpoint=self.get_google_models,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/models/metadata",
            endpoint=self.get_model_metadata_all,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/models/metadata/{model_id:path}",
            endpoint=self.get_model_metadata,
            tags=tags,
        )
        # TODO: Refactor - move these to a new AudioLibrary service:
        self.router.add_api_route(
            methods=["GET"],
            path="/audio-library",
            response_model=list[AudioFile],
            endpoint=self.get_audio_library,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/audio-library/play",
            endpoint=self.play_from_audio_library,
            tags=tags,
        )
        # ── Local AI Routes ──────────────────────────────────────────
        self.router.add_api_route(
            methods=["GET"],
            path="/settings/local-ai/status",
            endpoint=self.get_local_ai_status,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/local-ai/download-models",
            endpoint=self.download_local_ai_models,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/settings/local-ai/backends",
            endpoint=self.get_local_ai_backends,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/settings/local-ai/support-models",
            endpoint=self.get_local_ai_support_models,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/settings/local-ai/embed-models",
            endpoint=self.get_local_ai_embed_models,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/local-ai/playground/chat",
            endpoint=self.playground_chat,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/local-ai/playground/embed",
            endpoint=self.playground_embed,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/local-ai/playground/benchmark",
            endpoint=self.playground_benchmark,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/settings/local-ai/playground/prompts",
            endpoint=self.playground_list_prompts,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/settings/local-ai/playground/presets",
            endpoint=self.playground_list_presets,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/local-ai/detect-context-size",
            endpoint=self.detect_remote_context_size,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/settings/local-ai/playground/memory-scenarios",
            endpoint=self.playground_list_memory_scenarios,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/local-ai/playground/memory-suite",
            endpoint=self.playground_run_memory_scenario,
            tags=tags,
        )

        # Connection test endpoints
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/test/whispercpp",
            endpoint=self.test_whispercpp,
            response_model=TestConnectionResult,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/test/parakeet",
            endpoint=self.test_parakeet,
            response_model=TestConnectionResult,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/test/xvasynth",
            endpoint=self.test_xvasynth,
            response_model=TestConnectionResult,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/test/local-ai/support",
            endpoint=self.test_local_ai_support,
            response_model=TestConnectionResult,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/test/local-ai/embed",
            endpoint=self.test_local_ai_embed,
            response_model=TestConnectionResult,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/test/hud-server",
            endpoint=self.test_hud_server,
            response_model=TestConnectionResult,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/test/pocket-tts",
            endpoint=self.test_pocket_tts,
            response_model=TestConnectionResult,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/test/openai-compatible-tts",
            endpoint=self.test_openai_compatible_tts,
            response_model=TestConnectionResult,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/local-ai/support",
            endpoint=self.api_support,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/local-ai/enhance-backstory",
            endpoint=self.api_enhance_backstory,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/local-ai/enhance-backstory-budget",
            endpoint=self.api_enhance_backstory_budget,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/local-ai/embed",
            endpoint=self.api_embed,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/elevenlabs/generate-sfx",
            endpoint=self.generate_sfx_elevenlabs,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/elevenlabs/subscription-data",
            endpoint=self.get_elevenlabs_subscription_data,
            response_model=dict,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/shutdown",
            endpoint=self.shutdown,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/models/wingman-pro",
            response_model=list,
            endpoint=self.get_wingman_pro_models,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/regions/wingman-pro",
            response_model=list,
            endpoint=self.get_wingman_pro_regions,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["GET"],
            path="/memories/{wingman_name}",
            endpoint=self.get_memories,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["PUT"],
            path="/memories/{entry_id}",
            endpoint=self.update_memory,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["DELETE"],
            path="/memories/{entry_id}",
            endpoint=self.delete_memory,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["DELETE"],
            path="/memories/{wingman_name}/all",
            endpoint=self.clear_memories,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/memories/{wingman_name}/test-extraction",
            endpoint=self.test_memory_extraction,
            tags=tags,
        )

        self.config_manager = config_manager
        self.config_manager.perform_hardware_scan(self.system_manager)
        self.config_service = ConfigService(config_manager=config_manager)
        self.config_service.config_events.subscribe(
            "config_loaded", self.initialize_tower
        )
        self.config_service.config_events.subscribe(
            "wingman_config_saved", self.on_wingman_config_saved
        )

        self.secret_keeper: SecretKeeper = SecretKeeper()

        self.event_queue = asyncio.Queue()
        self.audio_player = AudioPlayer(
            event_queue=self.event_queue,
            on_playback_started=self.on_playback_started,
            on_playback_finished=self.on_playback_finished,
        )
        self.audio_library = AudioLibrary(
            callback_playback_finished=self.on_audio_library_playback_finished,
        )

        self.tower: Tower = None

        # HUD Server
        self._hud_server: Optional[HudServer] = None

        self.active_recording = {"key": "", "wingman": None}

        self.is_started = False
        self.core_state: CoreState = CoreState.STARTING
        self._last_logged_state: Optional[CoreState] = None
        self.core_state_message: str | None = None
        self.core_state_progress: float | None = None
        self.startup_errors: list[WingmanInitializationError] = []
        self.tower_errors: list[WingmanInitializationError] = []

        self.azure_speech_recognizer: speechsdk.SpeechRecognizer = None
        self.is_listening = False
        # User's mute intent, independent of transient playback pauses. is_listening is
        # the actual recognizer state; mic_intent is what the user wants after playback.
        self.mic_intent = False
        # Serializes mute/unmute transitions across their entry points (hotkey thread,
        # API threadpool, main-loop playback callbacks). RLock: start_voice_recognition ->
        # _apply_voice_recognition nests.
        self._va_state_lock = threading.RLock()

        self.key_events = {}

        # Joystick thread management
        self._joystick_thread: Optional[threading.Thread] = None
        self._joystick_loop: Optional[asyncio.AbstractEventLoop] = None
        self._joystick_task: Optional[asyncio.Task] = None
        self._joystick_configs: list = []
        self._mouse_hook_registered: bool = False
        self._joystick_recording_active: bool = False
        self._joystick_recording_event: Optional[threading.Event] = None
        self._joystick_recording_result: Optional[dict] = None

        self.settings_service = SettingsService(
            config_manager=config_manager, config_service=self.config_service
        )
        # Surface STT download/init progress during runtime settings switches
        # via the same LOADING_CONFIG indicator used at startup; flip back to
        # READY when the switch finishes.
        self.settings_service.stt_status_callback = self._broadcast_loading_status
        self.settings_service.stt_done_callback = self._broadcast_ready
        self.settings_service.settings_events.subscribe(
            "audio_devices_changed", self.on_audio_devices_changed
        )
        self.settings_service.settings_events.subscribe(
            "voice_activation_changed", self.set_voice_activation
        )
        self.settings_service.settings_events.subscribe(
            "va_settings_changed", self.on_va_settings_changed
        )
        self.settings_service.settings_events.subscribe(
            "hud_server_settings_changed", self._on_hud_server_settings_changed
        )

        self.whispercpp = Whispercpp(
            settings=self.settings_service.settings.voice_activation.whispercpp,
        )
        self.fasterwhisper = FasterWhisper(
            settings=self.settings_service.settings.voice_activation.fasterwhisper,
        )
        self.parakeet = Parakeet(
            settings=self.settings_service.settings.voice_activation.parakeet,
        )
        self.xvasynth = XVASynth(settings=self.settings_service.settings.xvasynth)
        self.pocket_tts = PocketTTS(
            settings=self.settings_service.settings.pocket_tts,
            defer_load=True,
        )
        self.pocket_tts.on_model_reloaded = self._on_pocket_tts_reloaded
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None

        # Unified model management
        self.model_downloader = ModelDownloader(models_root=get_models_dir())

        # STT provider lifecycle manager
        self.stt_provider_manager = SttProviderManager(
            settings_service=self.settings_service,
            system_manager=self.system_manager,
            model_downloader=self.model_downloader,
            parakeet=self.parakeet,
            fasterwhisper=self.fasterwhisper,
            app_root_path=app_root_path,
        )

        # Local AI (llama.cpp for summarization + embedding)
        llama_cpp_settings = self.settings_service.settings.llama_cpp
        self.local_model_manager = LocalModelManager(settings=llama_cpp_settings)
        self.llama_cpp_provider = LlamaCppProvider(
            settings=llama_cpp_settings,
            model_manager=self.local_model_manager,
        )
        self.llama_cpp_remote = LlamaCppRemote(settings=llama_cpp_settings)
        self.local_ai_service = LocalAiService(
            provider=self.llama_cpp_provider,
            remote=self.llama_cpp_remote,
            settings=llama_cpp_settings,
        )

        self.settings_service.initialize(
            whispercpp=self.whispercpp,
            fasterwhisper=self.fasterwhisper,
            parakeet=self.parakeet,
            xvasynth=self.xvasynth,
            pocket_tts=self.pocket_tts,
            local_ai_service=self.local_ai_service,
            stt_provider_manager=self.stt_provider_manager,
        )

        self.voice_service = VoiceService(
            config_manager=self.config_manager,
            audio_player=self.audio_player,
            xvasynth=self.xvasynth,
            pocket_tts=self.pocket_tts,
        )

        self.model_metadata_service = ModelMetadataService()

        # restore settings
        self.audio_recorder = AudioRecorder(
            on_speech_recorded=self.on_audio_recorder_speech_recorded
        )

        if self.settings_service.settings.audio:
            sd.default.device = [
                self.settings_service.settings.audio.input,
                self.settings_service.settings.audio.output,
            ]
            self.audio_recorder.update_input_stream()

    async def startup(self):
        # Capture the main loop so background workers can schedule coroutines.
        self._main_loop = asyncio.get_running_loop()

        # 1. Detect hardware
        await self.set_core_state(
            CoreState.LOADING_CONFIG,
            message="Detecting hardware...",
        )
        self.system_manager.is_cuda_available()

        # 2. STT initialization (settings-aware)
        async def stt_status(message: str, progress: float | None = None):
            await self.set_core_state(
                CoreState.LOADING_CONFIG,
                message=message,
                progress=progress,
            )

        await self.stt_provider_manager.initialize(on_status=stt_status)

        # 3. Voice activation
        if self.settings_service.settings.voice_activation.enabled:
            await self.set_voice_activation(is_enabled=True)

        # 4. TTS initialization (settings-aware, deferred from __init__)
        pocket_settings = self.settings_service.settings.pocket_tts
        if pocket_settings.enable:
            await self.set_core_state(
                CoreState.LOADING_CONFIG,
                message="Downloading TTS model..." if pocket_settings.run_locally else "Initializing text-to-speech...",
            )
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.pocket_tts.deferred_init)

        # 5. Local AI download + init (settings-aware)
        llama_settings = self.settings_service.settings.llama_cpp
        if (
            llama_settings.run_locally
            and not self.local_model_manager.models_available()
        ):
            await self.printr.print_async(
                "Local AI models not found — downloading automatically...",
                color=LogType.INFO,
                server_only=True,
            )

            progress_state = {}

            def on_download_progress(filename, pct, downloaded_mb, total_mb):
                progress_state["filename"] = filename
                progress_state["pct"] = pct
                progress_state["downloaded_mb"] = downloaded_mb
                progress_state["total_mb"] = total_mb

            download_task = asyncio.create_task(
                self.local_model_manager.download_models(
                    cuda_available=self.system_manager.is_cuda_available(),
                    on_progress=on_download_progress,
                )
            )

            while not download_task.done():
                if progress_state:
                    fname = progress_state.get("filename", "")
                    pct = progress_state.get("pct", 0)
                    dl_mb = progress_state.get("downloaded_mb", 0)
                    t_mb = progress_state.get("total_mb", 0)
                    short_name = (
                        fname.split("-")[0]
                        if "-" in fname
                        else fname.replace(".gguf", "")
                    )
                    await self.set_core_state(
                        CoreState.LOADING_CONFIG,
                        message=f"Downloading Local AI model ({short_name})... ({dl_mb} / {t_mb} MB)",
                        progress=pct / 100.0 if pct else None,
                    )
                await asyncio.sleep(0.5)

            if not await download_task:
                self.printr.toast_error(
                    "Could not download the Local AI models. "
                    "Please check your internet connection and retry the download "
                    "in Settings > Local AI, or restart Wingman AI."
                )

        if llama_settings.run_locally and self.local_model_manager.models_available():
            await self.set_core_state(
                CoreState.LOADING_CONFIG,
                message="Initializing Local AI...",
            )
        await self.local_ai_service.initialize()

        # 6. HUD server
        hud_settings = getattr(self.settings_service.settings, "hud_server", None)
        if hud_settings and hud_settings.enabled:
            await self.set_core_state(
                CoreState.LOADING_CONFIG,
                message="Starting HUD server...",
            )
        await self._start_hud_server_if_enabled()

    def _get_validated_hud_settings(
        self, hud_settings, log_invalid: bool = True
    ) -> dict:
        """Validate HUD settings and return dict with defaults for invalid values."""
        result = validate_hud_settings(hud_settings)
        invalid = result.pop("_invalid", {})

        if log_invalid and invalid:
            self.printr.print(
                "[HUD] " + get_invalid_summary(invalid), color=LogType.INFO
            )

        return result

    async def _start_hud_server_if_enabled(self):
        """Start the HUD server if enabled in settings."""
        hud_settings = getattr(self.settings_service.settings, "hud_server", None)
        if not hud_settings or not hud_settings.enabled:
            return

        if platform.system() != "Windows":
            self.printr.print(
                "[HUD] Server is only supported on Windows.",
                color=LogType.WARNING,
                server_only=True,
            )
            return

        try:
            validated = self._get_validated_hud_settings(hud_settings)
            self._hud_server = HudServer()
            # Run blocking start() in executor to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                None,
                self._hud_server.start,
                validated["host"],
                validated["port"],
                validated["framerate"],
                validated["layout_margin"],
                validated["layout_spacing"],
                validated["screen"],
            )
            if not success:
                self.printr.print(
                    f"[HUD] Server failed to start on port {validated['port']}",
                    color=LogType.ERROR,
                    server_only=False,
                )
                self._hud_server = None
        except Exception as e:
            self.printr.print(
                f"[HUD] Server error: {e}",
                color=LogType.ERROR,
                server_only=False,
            )
            self._hud_server = None

    async def _on_hud_server_settings_changed(self, hud_settings):
        """Handle HUD server settings changes — start or stop as needed."""
        # Validate settings and apply defaults for invalid values
        validated = self._get_validated_hud_settings(hud_settings)

        should_run = (
            hud_settings is not None
            and hud_settings.enabled
            and platform.system() == "Windows"
        )
        is_running = self._hud_server is not None and self._hud_server.is_running

        if should_run and not is_running:
            await self._start_hud_server_if_enabled()
        elif not should_run and is_running:
            await self._stop_hud_server()
        elif should_run and is_running:
            # Server already running - update settings without restart
            try:
                self._hud_server.update_settings(
                    framerate=validated["framerate"],
                    layout_margin=validated["layout_margin"],
                    layout_spacing=validated["layout_spacing"],
                    screen=validated["screen"],
                )
            except Exception as e:
                self.printr.print(
                    f"Error updating HUD server settings: {e}",
                    color=LogType.ERROR,
                    server_only=True,
                )

    async def _stop_hud_server(self):
        """Stop the HUD server if running."""
        if self._hud_server and self._hud_server.is_running:
            await self._hud_server.stop()
            self._hud_server = None

    async def _broadcast_loading_status(
        self, message: str, progress: float | None = None
    ) -> None:
        """Convenience wrapper: emit a LOADING_CONFIG state with a status message.

        Used as the ``stt_status_callback`` so SttProviderManager can surface
        download/init progress during runtime settings changes without needing
        a direct reference to ``set_core_state``.
        """
        await self.set_core_state(
            CoreState.LOADING_CONFIG, message=message, progress=progress
        )

    async def _broadcast_ready(self) -> None:
        """Flip core state back to READY — paired with _broadcast_loading_status."""
        await self.set_core_state(CoreState.READY)

    async def set_core_state(
        self,
        state: CoreState,
        message: str | None = None,
        progress: float | None = None,
    ) -> None:
        """Update the core state and broadcast to all connected clients.

        Args:
            state: The new CoreState
            message: Optional human-readable sub-step detail
            progress: Optional 0.0-1.0 progress for operations with known duration
        """
        self.core_state = state
        self.core_state_message = message
        self.core_state_progress = progress

        # Update is_started for backwards compatibility
        self.is_started = state == CoreState.READY

        # Broadcast state change to connected clients
        if self._connection_manager:
            command = CoreStateChangedCommand(
                state=state, message=message, progress=progress
            )
            await self._connection_manager.broadcast(command)

        # Only log actual state changes, not progress updates within the same state
        if state != self._last_logged_state:
            self._last_logged_state = state
            self.printr.print(
                f"Core state changed: {state.value}",
                color=LogType.STARTUP,
                server_only=True,
            )

    def get_status(self) -> CoreStatusResponse:
        """Get the current core status for the /ping endpoint."""
        return CoreStatusResponse(
            state=self.core_state,
            message=self.core_state_message,
            progress=self.core_state_progress,
        )

    def get_mic_status(self) -> MicStatusResponse:
        """Snapshot of the current mic / voice-activation state (voice_events payload)."""
        rec_wingman = self.active_recording.get("wingman")
        rec_name = getattr(rec_wingman, "name", None) if rec_wingman else None
        rec_avatar = None
        if rec_wingman is not None:
            getter = getattr(rec_wingman, "get_avatar_path", None)
            if callable(getter):
                try:
                    rec_avatar = getter()
                except Exception:
                    rec_avatar = None
        return MicStatusResponse(
            listening=bool(self.is_listening),
            voice_activation_enabled=bool(
                self.settings_service.settings.voice_activation.enabled
            ),
            playing=bool(self.audio_player.is_playing),
            recording=self.active_recording.get("key", "") != "",
            recording_wingman=rec_name,
            recording_wingman_avatar=rec_avatar,
        )

    def _run_on_main_loop(self, coro) -> None:
        """Schedule a coroutine on the main loop from any thread. The WebSocket
        connections and the ConnectionManager's asyncio.Lock belong to the main loop;
        awaiting them from a throwaway asyncio.run() loop (hotkey threads, FastAPI
        threadpool) intermittently fails or reorders sends."""
        loop = self._main_loop
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, loop)
        else:
            # Pre-startup only; no clients/subscribers exist yet.
            self.ensure_async(coro)

    def _emit_voice_state(self) -> None:
        """Cache the current mic status on the shared AudioPlayer and notify subscribers.

        Routed through the main loop so subscribers run there even when called from the
        keyboard/mouse/joystick input threads (on_press/on_release)."""
        status = self.get_mic_status()
        self.audio_player.voice_state = status
        self._run_on_main_loop(self.audio_player.voice_events.publish("changed", status))

    def is_mouse_configured(self, config: Config) -> bool:
        return any(
            config.wingmen[wingman].record_mouse_button for wingman in config.wingmen
        )

    def is_joystick_configured(self, config: Config) -> bool:
        is_any_wingman_joystick_configured = any(
            config.wingmen[wingman].record_joystick_button for wingman in config.wingmen
        )

        cancel_tts_joystick_button = getattr(
            self.settings_service.settings,
            "cancel_tts_joystick_button",
            None,
        )

        is_cancel_tts_joystick_configured = (
            cancel_tts_joystick_button is not None
            and cancel_tts_joystick_button.guid is not None
        )

        return is_any_wingman_joystick_configured or is_cancel_tts_joystick_configured

    async def start_joysticks(self):
        pygame.init()
        # Initialize ALL joysticks upfront so they generate events for both
        # normal operation and recording mode.
        joysticks = [
            pygame.joystick.Joystick(x) for x in range(pygame.joystick.get_count())
        ]
        for joystick in joysticks:
            joystick.init()

        running = True
        while running and pygame.joystick.get_init():
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.JOYBUTTONDOWN:
                    joystick_origin = pygame.joystick.Joystick(event.joy)
                    # In recording mode, skip normal press handling
                    if not self._joystick_recording_active:
                        for joystick_config in self._joystick_configs:
                            if joystick_origin.get_guid() == joystick_config.guid:
                                self.on_press(
                                    joystick_config=CommandJoystickConfig(
                                        guid=joystick_config.guid, button=event.button
                                    )
                                )
                elif event.type == pygame.JOYBUTTONUP:
                    joystick_origin = pygame.joystick.Joystick(event.joy)
                    # In recording mode, capture the button press and signal the caller
                    if (
                        self._joystick_recording_active
                        and self._joystick_recording_event
                    ):
                        self._joystick_recording_result = {
                            "button": event.button,
                            "guid": joystick_origin.get_guid(),
                            "name": joystick_origin.get_name(),
                        }
                        self._joystick_recording_event.set()
                    else:
                        for joystick_config in self._joystick_configs:
                            if joystick_origin.get_guid() == joystick_config.guid:
                                self.on_release(
                                    joystick_config=CommandJoystickConfig(
                                        guid=joystick_config.guid, button=event.button
                                    )
                                )

            # Sleep longer when idle (no configs and not recording) to reduce CPU usage
            if not self._joystick_configs and not self._joystick_recording_active:
                await asyncio.sleep(0.1)
            else:
                await asyncio.sleep(0.01)

    def _build_joystick_configs(self, config: Config) -> list:
        """Build the list of joystick configs from wingman and settings config."""
        joystick_configs: list[CommandJoystickConfig] = [
            config.wingmen[wingman].record_joystick_button
            for wingman in config.wingmen
            if config.wingmen[wingman].record_joystick_button
        ]
        cancel_tts_joystick_button = getattr(
            self.settings_service.settings, "cancel_tts_joystick_button", None
        )
        if cancel_tts_joystick_button is not None and cancel_tts_joystick_button.guid:
            joystick_configs.append(cancel_tts_joystick_button)
        return joystick_configs

    async def init_joystick(self, config: Config):
        # Update the configs that the joystick loop reads dynamically
        self._joystick_configs = self._build_joystick_configs(config)

        # If the thread is already running, no need to restart it.
        # The loop reads _joystick_configs on every iteration.
        if self._joystick_thread and self._joystick_thread.is_alive():
            return

        # Clear stale references from a previously dead thread
        self._joystick_thread = None
        self._joystick_loop = None
        self._joystick_task = None

        def run_async_process():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._joystick_loop = loop  # Store reference for cleanup
            try:
                self._joystick_task = loop.create_task(self.start_joysticks())

                # Stop the loop if the task finishes unexpectedly (e.g. exception)
                # so the finally block runs and the thread exits cleanly.
                def on_task_done(task):
                    if task.exception():
                        self.printr.print(
                            f"Joystick event loop error: {task.exception()}",
                            color=LogType.WARNING,
                            server_only=True,
                        )
                    loop.call_soon_threadsafe(loop.stop)

                self._joystick_task.add_done_callback(on_task_done)
                loop.run_forever()
            finally:
                # Ensure the task is cancelled and awaited before closing the loop.
                # asyncio.all_tasks() raises RuntimeError when no loop is running
                # (Python 3.10+), so we use the task reference directly instead.
                task = self._joystick_task
                if task and not task.done():
                    task.cancel()
                    try:
                        loop.run_until_complete(
                            asyncio.gather(task, return_exceptions=True)
                        )
                    except Exception:
                        pass
                loop.close()

        self._joystick_thread = threading.Thread(target=run_async_process, daemon=True)
        self._joystick_thread.name = "JoystickEventLoop"
        self._joystick_thread.start()

    async def record_joystick_action(self) -> dict | None:
        """Record a single joystick button press using the existing joystick event loop.

        If no joystick thread is running, starts one for recording.
        Returns a dict with 'button', 'guid', and 'name' keys, or None if cancelled.
        """
        if not self._joystick_thread or not self._joystick_thread.is_alive():
            config = (
                self.tower.config if self.tower else self.config_service.current_config
            )
            await self.init_joystick(config)

        # Use a threading.Event to synchronize across event loops instead of
        # asyncio futures, which cannot be awaited from a different loop.
        self._joystick_recording_event = threading.Event()
        self._joystick_recording_result = None
        self._joystick_recording_active = True

        try:
            # Poll the threading event from the caller's async loop
            while not self._joystick_recording_event.is_set():
                await asyncio.sleep(0.01)
            return self._joystick_recording_result
        finally:
            self._joystick_recording_active = False
            self._joystick_recording_event = None
            self._joystick_recording_result = None

    def cancel_joystick_recording(self):
        """Cancel an in-progress joystick recording."""
        self._joystick_recording_active = False
        if self._joystick_recording_event:
            self._joystick_recording_event.set()

    async def refresh_input_hooks(self):
        """Refresh mouse and joystick hooks based on current wingman configurations.

        This method should be called when a wingman's activation key (mouse button or
        joystick button) configuration changes to ensure the new keys take effect immediately.

        Note: The on_press handler already dynamically checks tower.wingmen for activation keys,
        so we only need to ensure the hooks are registered and joystick thread has latest config.
        """
        if not self.tower:
            return

        # Check if any wingman has a mouse button configured
        needs_mouse = any(
            wingman.get_record_mouse_button() for wingman in self.tower.wingmen
        )

        # Register mouse hook if needed and not already registered
        if needs_mouse and not self._mouse_hook_registered:
            mouse.hook(self.on_mouse)
            self._mouse_hook_registered = True
            self.printr.print(
                "Mouse hook registered for new activation key.",
                color=LogType.INFO,
                server_only=True,
            )

        # Check if any wingman has a joystick button configured
        needs_joystick = any(
            wingman.get_record_joystick_button() for wingman in self.tower.wingmen
        )

        # Also check for cancel TTS joystick button in settings
        cancel_tts_joystick_button = getattr(
            self.settings_service.settings, "cancel_tts_joystick_button", None
        )
        if cancel_tts_joystick_button is not None and cancel_tts_joystick_button.guid:
            needs_joystick = True

        joystick_running = (
            self._joystick_thread is not None and self._joystick_thread.is_alive()
        )

        if needs_joystick:
            # Update joystick configs dynamically — no thread restart needed.
            # The joystick loop reads _joystick_configs on every iteration.
            current_wingmen = {
                wingman.name: wingman.config for wingman in self.tower.wingmen
            }
            current_config = self.tower.config.model_copy(
                update={"wingmen": current_wingmen}
            )
            await self.init_joystick(current_config)
            self.printr.print(
                "Joystick hooks refreshed for new activation key.",
                color=LogType.INFO,
                server_only=True,
            )
        elif joystick_running and not needs_joystick:
            # No joystick needed anymore — clear configs so the loop idles,
            # but keep the thread alive for future recordings.
            self._joystick_configs = []

    async def on_wingman_config_saved(self, wingman_config):
        """Called when a wingman config is saved. Refreshes input hooks if needed."""
        await self.refresh_input_hooks()

    async def initialize_tower(self, config_dir_info: ConfigWithDirInfo):
        if not self.is_client_logged_in:
            self.printr.print(
                "Client not logged in yet - skipping Tower initialization.",
                color=LogType.WARNING,
                server_only=True,
            )
            return

        # Broadcast state change - wingmen are being initialized
        await self.set_core_state(CoreState.INITIALIZING_WINGMEN)

        await self.unload_tower()

        config = config_dir_info.config

        # Register hooks
        if self.is_mouse_configured(config):
            mouse.hook(self.on_mouse)
            self._mouse_hook_registered = True
        if self.is_joystick_configured(config):
            await self.init_joystick(config)

        # Skill pre-flight: gate eligibility once, before any Wingman loads skills.
        from services.skill_catalog import SkillCatalog
        from api.commands import SkillRegisteredCommand

        skill_catalog = SkillCatalog()
        skill_catalog.scan()
        for rec in skill_catalog.telemetry_records():
            await self._connection_manager.broadcast(SkillRegisteredCommand(**rec))

        # Auto-disable legacy/incompatible skills that are still enabled in any wingman config.
        await self.config_service.disable_ineligible_skills(skill_catalog.ineligible_skill_names())

        self.tower = Tower(
            config=config,
            config_dir=config_dir_info.config_dir,
            config_manager=self.config_manager,
            audio_player=self.audio_player,
            audio_library=self.audio_library,
            whispercpp=self.whispercpp,
            fasterwhisper=self.fasterwhisper,
            parakeet=self.parakeet,
            xvasynth=self.xvasynth,
            pocket_tts=self.pocket_tts,
            settings_service=self.settings_service,
        )
        self.tower_errors = await self.tower.instantiate_wingmen(
            self.config_manager.settings_config
        )

        for rec in skill_catalog.drain_runtime_records():
            await self._connection_manager.broadcast(SkillRegisteredCommand(**rec))

        for wingman in self.tower.wingmen:
            if isinstance(wingman, OpenAiWingman):
                wingman.local_ai_service = self.local_ai_service

        # Only show toast errors for non-MCP errors (MCP errors are already logged in mcp_client.py)
        for error in self.tower_errors:
            if error.error_type != WingmanInitializationErrorType.MCP_CONNECTION_FAILED:
                self.printr.toast_error(error.message)

        self.config_service.set_tower(self.tower)
        self._emit_voice_state()

        # Warm the PocketTTS voice cache for all voices used in this config.
        await self._preload_pocket_tts_voices()

        # Broadcast state change - ready again after tower init
        await self.set_core_state(CoreState.READY)

        self.printr.print(
            "Tower initializated.",
            color=LogType.POSITIVE,
            server_only=True,
        )

    async def unload_tower(self):
        if self.tower:
            for wingman in self.tower.wingmen:
                await wingman.unload()
            self.tower = None
            self.config_service.set_tower(None)

            # Clear joystick configs so the loop idles, but keep the thread
            # alive. Restarting it on a new thread breaks pygame's DirectInput
            # handles which are bound to the thread that created them.
            self._joystick_configs = []

            # Unhook mouse to prevent duplicate hooks
            try:
                mouse.unhook_all()
                self._mouse_hook_registered = False
            except Exception:
                pass  # May fail if no hooks are registered

            self.printr.print(
                "Tower unloaded.",
                server_only=True,
            )

    def is_hotkey_pressed(self, hotkey: list[int] | str) -> bool:
        codes = []

        if isinstance(hotkey, str):
            hotkey_codes = keyboard.parse_hotkey(hotkey)
            codes = [item[0] for tup in hotkey_codes for item in tup]

        if isinstance(hotkey, list):
            codes = hotkey

        if not codes:
            return False

        # check if all hotkey codes are in the key events code list
        is_pressed = all(code in self.key_events for code in codes)

        return is_pressed

    def on_press(
        self, key=None, mouse_button=None, joystick_config: CommandJoystickConfig = None
    ):
        is_mute_hotkey_pressed = self.is_hotkey_pressed(
            self.settings_service.settings.voice_activation.mute_toggle_key_codes
            or self.settings_service.settings.voice_activation.mute_toggle_key
        )
        if (
            self.settings_service.settings.voice_activation.enabled
            and is_mute_hotkey_pressed
        ):
            self.toggle_voice_recognition()

        is_cancel_tts_hotkey_pressed = self.is_hotkey_pressed(
            self.settings_service.settings.cancel_tts_key_codes
            or self.settings_service.settings.cancel_tts_key
        )
        if is_cancel_tts_hotkey_pressed:
            self.ensure_async(self.stop_playback())

        cancel_tts_joystick_button = getattr(
            self.settings_service.settings, "cancel_tts_joystick_button", None
        )
        if (
            joystick_config
            and cancel_tts_joystick_button is not None
            and cancel_tts_joystick_button.guid is not None
            and cancel_tts_joystick_button.button is not None
            and joystick_config.guid == cancel_tts_joystick_button.guid
            and joystick_config.button == cancel_tts_joystick_button.button
        ):
            self.ensure_async(self.stop_playback())

        if self.tower and self.active_recording["key"] == "":
            wingman = None
            for potential_wingman in self.tower.wingmen:
                if key:
                    if potential_wingman.get_record_key() and self.is_hotkey_pressed(
                        potential_wingman.get_record_key()
                    ):
                        wingman = potential_wingman
                        break
                if mouse_button:
                    if potential_wingman.get_record_mouse_button() == mouse_button:
                        wingman = potential_wingman
                        break
                if joystick_config:
                    if (
                        potential_wingman.get_record_joystick_button()
                        == f"{joystick_config.guid}{joystick_config.button}"
                    ):
                        wingman = potential_wingman
                        break

            if wingman:
                if key:
                    self.active_recording = dict(key=key.name, wingman=wingman)
                elif mouse_button:
                    self.active_recording = dict(key=mouse_button, wingman=wingman)
                elif joystick_config:
                    self.active_recording = dict(
                        key=f"{joystick_config.guid}{joystick_config.button}",
                        wingman=wingman,
                    )

                if (
                    self.settings_service.settings.voice_activation.enabled
                    and self.is_listening
                ):
                    # transient like playback pauses: a PTT hold isn't a mute-intent change
                    self._apply_voice_recognition(mute=True, is_transient=True)

                self.audio_recorder.start_recording(wingman_name=wingman.name)
                self._emit_voice_state()

    def on_release(
        self, key=None, mouse_button=None, joystick_config: CommandJoystickConfig = None
    ):
        if self.tower and (
            key is not None
            and self.active_recording["key"] == key.name
            or self.active_recording["key"] == mouse_button
            or (
                joystick_config
                and self.active_recording["key"]
                == f"{joystick_config.guid}{joystick_config.button}"
            )
        ):
            wingman = self.active_recording["wingman"]
            recorded_audio_wav = self.audio_recorder.stop_recording(
                wingman_name=wingman.name
            )
            self.active_recording = {"key": "", "wingman": None}

            # restore from intent so a mute set during the hold survives the release;
            # if playback is still running, on_playback_finished resumes instead
            if (
                self.settings_service.settings.voice_activation.enabled
                and self.mic_intent
                and not self.is_listening
                and not self.audio_player.is_playing
            ):
                self._apply_voice_recognition(mute=False, is_transient=True)

            self._emit_voice_state()

            def run_async_process():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    if isinstance(wingman, Wingman):
                        loop.run_until_complete(
                            wingman.process(audio_input_wav=str(recorded_audio_wav))
                        )
                finally:
                    loop.close()

            if recorded_audio_wav:
                play_thread = threading.Thread(target=run_async_process)
                play_thread.start()

    def on_key(self, key):
        if key.event_type == "down":
            if key.scan_code not in self.key_events:
                self.key_events[key.scan_code] = key
            self.on_press(key=key)
        elif key.event_type == "up":
            if key.scan_code in self.key_events:
                del self.key_events[key.scan_code]
            self.on_release(key=key)

    def on_mouse(self, event):
        # Check if event is of type ButtonEvent
        if not isinstance(event, mouse.ButtonEvent):
            return

        if event.event_type == "down":
            self.on_press(mouse_button=event.button)
        elif event.event_type == "up":
            self.on_release(mouse_button=event.button)

    # called when AudioRecorder regonized voice
    def on_audio_recorder_speech_recorded(self, recording_file: str):
        def run_async_process():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(wingman.process(transcript=text))
            finally:
                loop.close()

        provider = self.settings_service.settings.voice_activation.stt_provider
        text = None

        if provider == VoiceActivationSttProvider.WINGMAN_PRO:
            wingman_pro = WingmanSubscription(
                wingman_name="system",
                settings=self.settings_service.settings.wingman_pro,
            )
            transcription = wingman_pro.transcribe_azure_speech(
                filename=recording_file,
                config=AzureSttConfig(
                    languages=self.settings_service.settings.voice_activation.azure.languages,
                    # unused as Wingman Pro sets this at API level - just for Pydantic:
                    region=AzureRegion.WESTEUROPE,
                ),
            )
            if transcription:
                text = transcription.get("_text")
        elif provider == VoiceActivationSttProvider.WHISPERCPP:

            def filter_and_clean_text(text):
                # First, save the original text for comparison
                original_text = text
                # Remove the ambient noise descriptions
                noise_pattern = r"(\(.*?\))|(\[.*?\])|(\*.*?\*)"
                text = re.sub(noise_pattern, "", text)
                # Remove extra spaces, newlines, and commas
                cleanup_pattern = r"[\s,]+"
                text = re.sub(cleanup_pattern, " ", text)
                # Strip leading and trailing whitespaces
                text = text.strip()

                return original_text != text, text

            transcription = self.whispercpp.transcribe(
                filename=recording_file,
                config=self.settings_service.settings.voice_activation.whispercpp_config,
            )
            if transcription:
                cleaned, text = filter_and_clean_text(transcription.text)
                if cleaned:
                    self.printr.print(
                        f"Cleaned original transcription: {transcription.text}",
                        server_only=True,
                        color=LogType.SYSTEM,
                    )
        elif provider == VoiceActivationSttProvider.OPENAI:
            # TODO: can't await secret_keeper.retrieve here, so just assume the secret is there...
            openai = OpenAi(api_key=self.secret_keeper.secrets["openai"])
            transcription = openai.transcribe(filename=recording_file)
            text = transcription.text
        elif provider == VoiceActivationSttProvider.GROQ:
            # TODO: can't await secret_keeper.retrieve here, so just assume the secret is there...
            groq = OpenAi(
                api_key=self.secret_keeper.secrets["groq"],
                base_url="https://api.groq.com/openai/v1/",
            )
            transcription = groq.transcribe(
                filename=recording_file, model="whisper-large-v3-turbo"
            )
            text = transcription.text
        elif provider == VoiceActivationSttProvider.FASTER_WHISPER:
            combined_hotwords: list[str] = []

            # add the default hotwords from settings
            default_hotwords = (
                self.settings_service.settings.voice_activation.fasterwhisper_config.hotwords
            )
            if default_hotwords and len(default_hotwords) > 0:
                combined_hotwords.extend(default_hotwords)

            for wingman in self.tower.wingmen:
                # add the wingman names explicitly
                combined_hotwords.append(wingman.name)
                # and their additional hotwords
                wingman_hotwords = wingman.config.fasterwhisper.additional_hotwords
                if wingman_hotwords and len(wingman_hotwords) > 0:
                    combined_hotwords.extend(wingman_hotwords)

            transcription = self.fasterwhisper.transcribe(
                config=self.settings_service.settings.voice_activation.fasterwhisper_config,
                filename=recording_file,
                hotwords=list(set(combined_hotwords)),
            )
            text = transcription.text
        elif provider == VoiceActivationSttProvider.PARAKEET:
            transcription = self.parakeet.transcribe(
                config=self.settings_service.settings.voice_activation.parakeet_config,
                filename=recording_file,
            )
            if transcription:
                text = transcription.text

        if text:
            wingman = self.tower.get_wingman_from_text(text)
            if wingman:
                play_thread = threading.Thread(target=run_async_process)
                play_thread.start()
        else:
            self.printr.print(
                "ignored empty transcription - probably just noise.", server_only=True
            )

    async def on_audio_devices_changed(self, devices: tuple[int | None, int | None]):
        # devices: [input_device, output_device]

        # get current audio devices
        current_mic = sd.default.device[0]

        # set new devices
        sd.default.device = devices

        # update input stream if the input device has changed
        if current_mic != devices[0]:
            self.audio_recorder.valid_mic = True  # this allows a new error message
            self.audio_recorder.update_input_stream()
            if self.is_listening:
                self._apply_voice_recognition(mute=True)
                self._apply_voice_recognition(mute=False, adjust_for_ambient_noise=True)

    async def set_voice_activation(self, is_enabled: bool):
        if is_enabled:
            if (
                self.settings_service.settings.voice_activation.stt_provider
                == VoiceActivationSttProvider.AZURE
                and not self.azure_speech_recognizer
            ):
                await self.__init_azure_voice_activation()
        else:
            self._apply_voice_recognition(mute=True)
            self.azure_speech_recognizer = None

    # called when Azure Speech Recognizer recognized voice
    def on_azure_voice_recognition(self, voice_event):
        def run_async_process():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(wingman.process(transcript=text))
            finally:
                loop.close()

        text = voice_event.result.text
        wingman = self.tower.get_wingman_from_text(text)
        if text and wingman:
            play_thread = threading.Thread(target=run_async_process)
            play_thread.start()

    async def __init_azure_voice_activation(self):
        if self.azure_speech_recognizer or not self.config_service.current_config:
            return

        key = await self.secret_keeper.retrieve(
            requester="Voice Activation",
            key="azure_tts",
            prompt_if_missing=True,
        )

        speech_config = speechsdk.SpeechConfig(
            region=self.settings_service.settings.voice_activation.azure.region.value,
            subscription=key,
        )

        auto_detect_source_language_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=self.settings_service.settings.voice_activation.azure.languages
        )

        self.azure_speech_recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            auto_detect_source_language_config=auto_detect_source_language_config,
        )
        self.azure_speech_recognizer.recognized.connect(self.on_azure_voice_recognition)

    async def on_playback_started(self, wingman_name: str):
        await self.printr.print_async(
            text=f"Playback started ({wingman_name})",
            source_name=wingman_name,
            command_tag=CommandTag.PLAYBACK_STARTED,
        )

        if (
            self.settings_service.settings.voice_activation.enabled
            and self.is_listening
        ):
            await asyncio.to_thread(
                self._apply_voice_recognition, mute=True, is_transient=True
            )

        self._emit_voice_state()

    async def on_playback_finished(self, wingman_name: str):
        await self.printr.print_async(
            text=f"Playback finished ({wingman_name})",
            source_name=wingman_name,
            command_tag=CommandTag.PLAYBACK_STOPPED,
        )

        if (
            self.settings_service.settings.voice_activation.enabled
            and self.mic_intent
            and not self.is_listening
            and not self.audio_player.is_playing
            # don't resume into an active PTT/GUI recording; its stop path resumes
            and self.active_recording.get("key", "") == ""
        ):
            await asyncio.to_thread(
                self._apply_voice_recognition, mute=False, is_transient=True
            )

        self._emit_voice_state()

    async def process_events(self):
        while True:
            callback, wingman_name = await self.event_queue.get()
            await callback(wingman_name)

    def on_va_settings_changed(self, _va_settings: VoiceActivationSettings):
        # restart VA with new settings
        if self.is_listening:
            self._apply_voice_recognition(mute=True)
            self._apply_voice_recognition(mute=False, adjust_for_ambient_noise=True)

    def _apply_voice_recognition(
        self,
        mute: Optional[bool] = False,
        adjust_for_ambient_noise: Optional[bool] = False,
        is_transient: bool = False,
    ):
        # Transient calls (playback pause/resume) change only the recognizer, not the
        # user's mute intent (mic_intent). The resulting recognizer state is still
        # broadcast and emitted below, same as for a non-transient call.
        with self._va_state_lock:
            target_listening = not mute
            if not is_transient:
                # Record the intent BEFORE the (slow) recognizer transition so a
                # toggle fired meanwhile reads the fresh value, not a stale one.
                self.mic_intent = target_listening
            # Skip the recognizer transition when already in the requested state: a
            # duplicate unmute must never start a second recognizer session (the
            # recorder blocks on that), a duplicate mute must not double-stop.
            changed = self.is_listening != target_listening
            self.is_listening = target_listening
            if changed:
                if target_listening:
                    if (
                        self.settings_service.settings.voice_activation.stt_provider
                        == VoiceActivationSttProvider.AZURE
                    ):
                        self.azure_speech_recognizer.start_continuous_recognition()
                    else:
                        if adjust_for_ambient_noise:
                            self.audio_recorder.adjust_for_ambient_noise()
                        if not self.audio_recorder.start_continuous_listening(
                            va_settings=self.settings_service.settings.voice_activation
                        ):
                            self.is_listening = False
                else:
                    if (
                        self.settings_service.settings.voice_activation.stt_provider
                        == VoiceActivationSttProvider.AZURE
                    ):
                        self.azure_speech_recognizer.stop_continuous_recognition()
                    else:
                        self.audio_recorder.stop_continuous_listening()

            command = VoiceActivationMutedCommand(muted=not self.is_listening)
            self._run_on_main_loop(self._connection_manager.broadcast(command))
            self._emit_voice_state()

    def start_voice_recognition(
        self,
        mute: Optional[bool] = False,
        adjust_for_ambient_noise: Optional[bool] = False,
    ):
        """Set the user's mute intent. Bound to POST /voice-activation/mute.

        (Kept as the endpoint's public name/signature so the client's generated API
        stays stable; the recognizer transition itself lives in _apply_voice_recognition.)

        During playback the recognizer is already paused so the wingman doesn't hear
        itself; toggling then must only record the post-playback intent (applied by
        on_playback_finished) and reflect it to clients - starting the recognizer
        mid-playback, or letting on_playback_finished override the user, would be wrong.
        All mute entry points (hotkey + this endpoint) go through here, so the intent is
        consistent and can't be clobbered by the on_playback_started race.
        """
        with self._va_state_lock:
            if (
                self.audio_player
                and self.audio_player.is_playing
                and self.settings_service.settings.voice_activation.enabled
            ):
                self.mic_intent = not mute
                self._run_on_main_loop(
                    self._connection_manager.broadcast(
                        VoiceActivationMutedCommand(muted=mute)
                    )
                )
                self._emit_voice_state()
                return

            self._apply_voice_recognition(
                mute=mute, adjust_for_ambient_noise=adjust_for_ambient_noise
            )

    def toggle_voice_recognition(self):
        # Flip the user's mute intent, not the possibly-transient recognizer state.
        # Read the intent under the lock so rapid toggles strictly alternate.
        with self._va_state_lock:
            self.start_voice_recognition(mute=self.mic_intent)

    # GET /audio-devices
    def get_audio_devices(self):
        audio_devices = sd.query_devices()
        return audio_devices

    # GET /startup-errors
    def get_startup_errors(self):
        return self.startup_errors

    # POST /stop-playback
    async def stop_playback(self):
        await self.audio_player.stop_playback()

    # POST /start-recording-for-wingman
    async def start_recording_for_wingman(self, wingman_name: str):
        """Start audio recording for a wingman (GUI mic toggle)."""
        if not self.tower or self.active_recording["key"] != "":
            return

        wingman = self.tower.get_wingman_by_name(wingman_name)
        if not wingman:
            return

        self.active_recording = dict(key="__gui__", wingman=wingman)
        if (
            self.settings_service.settings.voice_activation.enabled
            and self.is_listening
        ):
            # transient like playback pauses; see on_press
            self._apply_voice_recognition(mute=True, is_transient=True)

        self.audio_recorder.start_recording(wingman_name=wingman.name)
        self._emit_voice_state()

    # POST /stop-recording-for-wingman
    async def stop_recording_for_wingman(self, wingman_name: str):
        """Stop audio recording and process the result (GUI mic toggle)."""
        if (
            not self.tower
            or self.active_recording["key"] != "__gui__"
        ):
            return

        wingman = self.active_recording["wingman"]
        recorded_audio_wav = self.audio_recorder.stop_recording(
            wingman_name=wingman.name
        )
        self.active_recording = {"key": "", "wingman": None}

        # restore from intent; see on_release
        if (
            self.settings_service.settings.voice_activation.enabled
            and self.mic_intent
            and not self.is_listening
            and not self.audio_player.is_playing
        ):
            self._apply_voice_recognition(mute=False, is_transient=True)

        self._emit_voice_state()

        if recorded_audio_wav and isinstance(wingman, Wingman):
            threaded_execution(wingman.process, str(recorded_audio_wav))

    # POST /ask-wingman-conversation-provider
    async def ask_wingman_conversation_provider(
        self, wingman_name: str, text: str = Body(...)
    ):
        wingman = self.tower.get_wingman_by_name(wingman_name)

        if wingman and text:
            if isinstance(wingman, OpenAiWingman):
                messages = [{"role": "user", "content": text}]

                completion = await wingman.actual_llm_call(messages=messages)

                return completion.choices[0].message.content

        return None

    # POST /generate-image
    async def generate_image(self, text: str, wingman_name: str):
        wingman = self.tower.get_wingman_by_name(wingman_name)

        if wingman and text:
            if isinstance(wingman, OpenAiWingman):
                return await wingman.generate_image(text=text)

        return None

    # POST /send-text-to-wingman
    async def send_text_to_wingman(
        self,
        text: str = Form(""),
        wingman_name: str = Form(""),
        images: list[UploadFile] = None,
    ):
        wingman = self.tower.get_wingman_by_name(wingman_name)
        if not wingman or not text:
            return

        processed_images = None
        if images:
            if len(images) > 2:
                raise HTTPException(
                    status_code=422, detail="Maximum 2 images allowed per message."
                )

            # Resolve the active conversation model ID from the wingman config.
            # The model lives under the provider-specific sub-config, not features.
            model_id = ""
            if hasattr(wingman, "config") and hasattr(wingman.config, "features"):
                provider = wingman.config.features.conversation_provider
                cfg = wingman.config
                if provider == ConversationProvider.OPENAI and cfg.openai:
                    model_id = cfg.openai.conversation_model or ""
                elif provider == ConversationProvider.MISTRAL and cfg.mistral:
                    model_id = cfg.mistral.conversation_model or ""
                elif provider == ConversationProvider.GROQ and cfg.groq:
                    model_id = cfg.groq.conversation_model or ""
                elif provider == ConversationProvider.CEREBRAS and cfg.cerebras:
                    model_id = cfg.cerebras.conversation_model or ""
                elif provider == ConversationProvider.GOOGLE and cfg.google:
                    model_id = cfg.google.conversation_model or ""
                elif provider == ConversationProvider.OPENROUTER and cfg.openrouter:
                    model_id = cfg.openrouter.conversation_model or ""
                elif provider == ConversationProvider.LOCAL_LLM and cfg.local_llm:
                    model_id = cfg.local_llm.conversation_model or ""
                elif provider == ConversationProvider.WINGMAN_PRO and cfg.wingman_pro:
                    model_id = cfg.wingman_pro.conversation_deployment or ""
                elif provider == ConversationProvider.AZURE and cfg.azure and cfg.azure.conversation:
                    model_id = cfg.azure.conversation.deployment_name or ""
                elif provider == ConversationProvider.PERPLEXITY and cfg.perplexity:
                    pmodel = cfg.perplexity.conversation_model
                    model_id = pmodel.value if hasattr(pmodel, "value") else str(pmodel)
                elif provider == ConversationProvider.XAI and cfg.xai:
                    model_id = cfg.xai.conversation_model or ""

            if model_id:
                supports_vision = await self.model_metadata_service.supports_vision(model_id)
                if not supports_vision:
                    raise HTTPException(
                        status_code=422,
                        detail="The configured conversation model does not support vision/images.",
                    )

            processed_images = []
            for img_file in images:
                if not validate_image_mime(img_file.content_type or ""):
                    raise HTTPException(
                        status_code=422,
                        detail=f"Unsupported image type: {img_file.content_type}. Allowed: PNG, JPEG, WebP, GIF.",
                    )
                img_bytes = await img_file.read()
                b64, mime = process_image(img_bytes)
                processed_images.append((b64, mime))

        def run_async_process():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    wingman.process(transcript=text, images=processed_images)
                )
            finally:
                loop.close()

        play_thread = threading.Thread(target=run_async_process)
        play_thread.start()

    # POST /generate-greeting
    async def generate_greeting(self, wingman_name: str):
        """Generate an in-character greeting using the support model. UI-only — not sent to TTS or conversation history."""
        wingman = self.tower.get_wingman_by_name(wingman_name)
        if not wingman:
            return

        config = wingman.config

        backstory = ""
        if config.prompts and config.prompts.backstory:
            backstory = config.prompts.backstory

        # Check for a previous session summary to personalize the greeting
        session_summary = ""
        if hasattr(wingman, "ensure_memory_initialized"):
            wingman.ensure_memory_initialized()
        mem_service = getattr(wingman, "persistent_memory_service", None)
        if mem_service:
            try:
                summaries = mem_service.get_all(entry_type="session_summary")
                if summaries:
                    session_summary = summaries[0].content
            except Exception as e:
                await self.printr.print_async(
                    text=f"[{wingman_name}] Failed to retrieve session summary: {e}",
                    color=LogType.WARNING,
                    source=LogSource.SYSTEM,
                    server_only=True,
                )

        await self.printr.print_async(
            text=f"[{wingman_name}] Greeting: mem_service={'yes' if mem_service else 'no'}, session_summary={'yes' if session_summary else 'no'}",
            color=LogType.INFO,
            source=LogSource.SYSTEM,
            server_only=True,
        )

        from services.skill_local_ai import SamplingPreset

        if session_summary:
            system_prompt = get_prompt("greeting-returning").format(
                name=config.name,
                backstory=backstory,
                session_summary=session_summary,
            )
            greeting_preset = SamplingPreset.CREATIVE
        else:
            system_prompt = get_prompt("greeting-default").format(
                name=config.name,
                backstory=backstory,
            )
            greeting_preset = SamplingPreset.BALANCED

        try:
            response = self.local_ai_service.support(
                text="Generate your greeting.",
                system_prompt=system_prompt,
                preset=greeting_preset,
            )

            from services.memory_debug_log import log_memory_event

            log_memory_event(
                "greeting",
                wingman_name,
                variant="returning" if session_summary else "default",
                preset=greeting_preset.name,
                session_summary=session_summary or None,
                raw_output=response.text if response else None,
            )

            if response and self._connection_manager:
                text = response.text or ""
                additional_data = None

                # Extract <mem>...</mem> tagged memory segments
                mem_segments = re.findall(r"<mem>(.*?)</mem>", text, re.DOTALL)
                if mem_segments:
                    additional_data = {
                        "memory_segments": [s.strip() for s in mem_segments]
                    }
                # Strip the tags from the displayed text
                text = re.sub(r"</?mem>", "", text)

                # Broadcast directly to set wingman_name explicitly
                # (printr uses stack inspection which won't find a Wingman instance here)
                await self._connection_manager.broadcast(
                    LogCommand(
                        text=text,
                        log_type=LogType.LOCALMODEL,
                        source=LogSource.WINGMAN,
                        source_name=wingman_name,
                        wingman_name=wingman_name,
                        additional_data=additional_data,
                    )
                )
        except Exception as e:
            await self.printr.print_async(
                text=f"Could not generate greeting: {e}",
                color=LogType.WARNING,
                source=LogSource.SYSTEM,
            )

    # POST /send-audio-to-wingman
    async def send_audio_to_wingman(
        self, wingman_name: str, file: UploadFile = File(...)
    ):
        wingman = self.tower.get_wingman_by_name(wingman_name)
        if not wingman:
            return

        contents = await file.read()

        filename = os.path.join(
            get_writable_dir(RECORDING_PATH), "client_recording.wav"
        )
        with open(filename, "wb") as f:
            f.write(contents)

        def run_async_process():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                if isinstance(wingman, Wingman):
                    loop.run_until_complete(
                        wingman.process(audio_input_wav=str(filename))
                    )
            finally:
                loop.close()

        if filename:
            play_thread = threading.Thread(target=run_async_process)
            play_thread.start()

    # POST /reset-conversation-history
    async def reset_conversation_history(self, wingman_name: Optional[str] = None):
        if wingman_name:
            wingman = self.tower.get_wingman_by_name(wingman_name)
            if wingman:
                await wingman.reset_conversation_history()
                self.printr.toast(
                    f"Conversation history cleared for {wingman_name}.",
                )
        else:
            for wingman in self.tower.wingmen:
                await wingman.reset_conversation_history()
            self.printr.toast(
                "Conversation history cleared.",
            )
        return True

    # POST /condense-conversation
    async def condense_conversation(self, wingman_name: str):
        wingman = self.tower.get_wingman_by_name(wingman_name)
        if not wingman:
            self.printr.toast_warning(
                f"Cannot summarize: Wingman '{wingman_name}' not found."
            )
            return False
        await wingman.condenser.condense(
            local_ai_service=wingman.local_ai_service,
            persistent_memory_service=wingman.persistent_memory_service,
            force=True,
        )
        return True

    # GET /wingman-context
    def get_wingman_context(self, wingman_name: str) -> str:
        wingman = self.tower.get_wingman_by_name(wingman_name)
        if not wingman or not hasattr(wingman, "get_last_context"):
            return ""
        return wingman.get_last_context()

    # GET /wingman-conversation
    def get_wingman_conversation(
        self, wingman_name: str, strip_nulls: bool = True
    ) -> list[dict]:
        wingman = self.tower.get_wingman_by_name(wingman_name)
        if not wingman or not hasattr(wingman, "get_conversation_messages"):
            return []
        return wingman.get_conversation_messages(strip_nulls=strip_nulls)

    # GET /fasterwhisper/modelsizes
    def get_fasterwhisper_modelsizes(self):
        model_sizes = [
            "tiny",
            "tiny.en",
            "base",
            "base.en",
            "small",
            "small.en",
            "distil-small.en",
            "medium",
            "medium.en",
            "distil-medium.en",
            "large-v1",
            "large-v2",
            "large-v3",
            "large",
            "distil-large-v2",
            "distil-large-v3",
            "large-v3-turbo",
            "turbo",
        ]
        return model_sizes

    # GET /fasterwhisper/computetypes
    def get_fasterwhisper_computetypes(self):
        compute_types = [
            "default",
            "auto",
            "int8",
            "int16",
            "int8_float16",
            "int8_float32",
            "float16",
            "float32",
        ]
        return compute_types

    # GET /fasterwhisper/devices
    def get_fasterwhisper_devices(self):
        devices = [
            "auto",
            "cpu",
        ]
        if self.system_manager.is_cuda_available():
            devices.append("cuda")
        return devices

    def _collect_pocket_tts_voice_ids(self) -> list[str]:
        """Collect the PocketTTS voice IDs used by wingmen in the current tower."""
        if not self.tower:
            return []
        ids: list[str] = []
        seen: set[str] = set()
        for wingman in self.tower.wingmen:
            try:
                voice_id = wingman.config.pocket_tts.voice
            except AttributeError:
                continue
            if not voice_id or voice_id in seen:
                continue
            seen.add(voice_id)
            ids.append(voice_id)
        return ids

    async def _preload_pocket_tts_voices(
        self,
        voice_ids: Optional[list[str]] = None,
        state_message_prefix: str = "Preloading voices",
        restore_ready_state: bool = False,
    ) -> dict[str, bool]:
        """Warm PocketTTS voice state cache.

        When ``voice_ids`` is None, preloads every voice used by the current
        tower. Broadcasts LOADING_CONFIG progress messages so the app header
        bar shows the shared loading indicator. When ``restore_ready_state``
        is True, flips the core state back to READY on completion — use that
        for ad-hoc preloads outside the main startup flow (e.g. a user picks
        a voice in the config screen).
        """
        if not self.pocket_tts.settings.enable or not self.pocket_tts.settings.run_locally:
            return {}
        if not self.pocket_tts.model:
            return {}
        if voice_ids is None:
            voice_ids = self._collect_pocket_tts_voice_ids()
        if not voice_ids:
            return {}

        loop = asyncio.get_running_loop()
        preload_task = loop.run_in_executor(
            None,
            lambda: self.pocket_tts.preload_voice_states(voice_ids),
        )
        try:
            await self.set_core_state(
                CoreState.LOADING_CONFIG,
                message=state_message_prefix,
            )
            return await preload_task
        finally:
            if restore_ready_state:
                await self.set_core_state(CoreState.READY)

    def _on_pocket_tts_reloaded(self) -> None:
        """Callback fired after the PocketTTS model finishes (re)loading.

        Runs from the model-load worker thread, so schedule the async preload
        onto the main loop.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = getattr(self, "_main_loop", None)
            if loop is None:
                self.printr.print(
                    "PocketTTS model reload: main loop not captured; skipping preload.",
                    color=LogType.WARNING,
                    server_only=True,
                )
                return
        future = asyncio.run_coroutine_threadsafe(
            self._preload_pocket_tts_voices(
                state_message_prefix="Preloading voices",
                restore_ready_state=True,
            ),
            loop,
        )

        def _log_preload_failure(fut):
            exc = fut.exception()
            if exc:
                self.printr.print(
                    f"PocketTTS background preload failed: {exc}",
                    color=LogType.ERROR,
                    server_only=True,
                )

        future.add_done_callback(_log_preload_failure)

    # POST /pocket_tts/preload_voice
    async def preload_pocket_tts_voice(self, voice: str) -> PocketTTSPreloadResult:
        """Warm the voice-state cache for a single voice (e.g. after a user picks it).

        Broadcasts LOADING_CONFIG core state while working, so the client
        picks up progress via the shared header bar indicator. Resolves once
        the clone + on-disk cache are ready and the core state is back to READY.
        """
        voice = (voice or "").strip()
        if not voice:
            return PocketTTSPreloadResult(ok=False, reason="empty voice id")
        if not self.pocket_tts.settings.enable or not self.pocket_tts.settings.run_locally:
            return PocketTTSPreloadResult(ok=False, reason="pocket_tts unavailable")
        if not self.pocket_tts.model:
            return PocketTTSPreloadResult(ok=False, reason="model not loaded")

        results = await self._preload_pocket_tts_voices(
            voice_ids=[voice],
            state_message_prefix="Preloading voice",
            restore_ready_state=True,
        )
        return PocketTTSPreloadResult(ok=bool(results.get(voice, False)), voice=voice)

    # POST /pocket_tts/precompute_voices
    async def precompute_pocket_tts_voices(self) -> dict:
        """Kick off a background precompute pass over all custom voices
        missing a ``.<active_model>.safetensors`` cache. Returns immediately;
        progress is surfaced via ``GET /pocket_tts/status``.
        """
        if not self.pocket_tts.settings.enable or not self.pocket_tts.settings.run_locally:
            return {"started": False, "reason": "pocket_tts unavailable", "total": 0}
        if not self.pocket_tts.model:
            return {"started": False, "reason": "model not loaded", "total": 0}
        if self.pocket_tts._precompute_running:
            return {
                "started": False,
                "reason": "already running",
                "total": self.pocket_tts._precompute_total,
            }

        targets = self.pocket_tts.list_custom_voices_needing_precompute()
        if not targets:
            return {"started": False, "reason": "nothing to do", "total": 0}

        loop = asyncio.get_running_loop()
        # Fire-and-forget: run on the default executor so the HTTP call returns
        # immediately. The method manages its own _precompute_* state for the
        # status poller.
        loop.run_in_executor(None, self.pocket_tts.precompute_custom_voices)
        return {"started": True, "total": len(targets)}

    # POST /pocket_tts/start
    def start_pocket_tts(self):
        self.pocket_tts.load_model()

    # Post /pocket_tts/stop
    def stop_pocket_tts(self):
        try:
            self.pocket_tts.unload_model()
        except Exception as e:
            self.printr.print(
                f"Error stopping PocketTTS: {e}", color=LogType.ERROR, server_only=True
            )

    # GET /pocket_tts/status
    def get_pocket_tts_status(self) -> dict:
        return self.pocket_tts.get_status()

    # GET /pocket_tts/models
    def get_pocket_tts_models(self) -> list[dict]:
        return self.pocket_tts.get_available_models()

    # POST /open-filemanager/pocket-tts-models
    def open_pocket_tts_models_directory(self):
        show_in_file_manager(get_pocket_tts_models_dir())

    # Windows reserved device names (case-insensitive, with or without extension).
    _RESERVED_WINDOWS_NAMES = frozenset(
        ["CON", "PRN", "AUX", "NUL"]
        + [f"COM{i}" for i in range(1, 10)]
        + [f"LPT{i}" for i in range(1, 10)]
    )
    _MAX_VOICE_STEM_LEN = 80

    def _validate_voice_stem(self, stem: str) -> str:
        """Validate a user-supplied voice name for safe filesystem use.

        Rejects empty names, path separators, dot-traversal, control
        characters, Windows reserved names, overly long names, and stems
        that match a known PocketTTS model tag (which would collide with
        the ``<voice>.<model_tag>.safetensors`` cache naming scheme).
        """
        if not stem:
            raise HTTPException(status_code=400, detail="Voice name cannot be empty.")
        if any(c in stem for c in ("/", "\\")) or ".." in stem:
            raise HTTPException(status_code=400, detail="Invalid voice name.")
        if any(ord(c) < 0x20 for c in stem):
            raise HTTPException(status_code=400, detail="Invalid voice name.")
        if len(stem) > self._MAX_VOICE_STEM_LEN:
            raise HTTPException(
                status_code=400,
                detail=f"Voice name exceeds {self._MAX_VOICE_STEM_LEN} characters.",
            )
        if stem.upper() in self._RESERVED_WINDOWS_NAMES:
            raise HTTPException(status_code=400, detail="Invalid voice name.")
        # Disallow stems that shadow a known model tag — would collide with
        # ``<voice>.<model_tag>.safetensors`` cache files on disk.
        if stem in self.pocket_tts._known_model_tags():
            raise HTTPException(
                status_code=400,
                detail=f"Voice name '{stem}' conflicts with a model ID.",
            )
        return stem

    # POST /voices/preprocess
    async def preprocess_custom_voice(
        self,
        file: UploadFile = File(...),
        name: Optional[str] = Form(None),
        max_duration_s: float = Form(20.0),
        overwrite: bool = Form(False),
    ) -> dict:
        """Clean up an uploaded audio clip for PocketTTS voice cloning.

        Converts to mono 24 kHz WAV, trims silence, normalizes peak, caps duration,
        and saves it into the custom voices directory under ``<name>.wav``.
        Returns metadata about the preprocessed clip.
        """
        from services.voice_preprocessing import (
            preprocess_voice_audio,
            supported_input_extensions,
        )

        src_name = file.filename or "upload.wav"
        src_ext = os.path.splitext(src_name)[1].lower()
        if src_ext not in supported_input_extensions():
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unsupported audio format '{src_ext}'. "
                    f"Supported: {sorted(supported_input_extensions())}"
                ),
            )

        stem = (name or os.path.splitext(src_name)[0]).strip()
        stem = self._validate_voice_stem(stem)

        custom_dir = get_custom_voices_dir()
        dst_path = os.path.join(custom_dir, f"{stem}.wav")
        # Verify the resolved destination actually lives inside custom_dir —
        # belt-and-braces protection against creative filenames that slip past
        # the character-level checks on platforms we don't cover (e.g. Windows
        # drive letters, SMB paths).
        abs_custom = os.path.realpath(custom_dir)
        abs_dst = os.path.realpath(dst_path)
        if os.path.commonpath([abs_custom, abs_dst]) != abs_custom:
            raise HTTPException(status_code=400, detail="Invalid voice name.")
        if os.path.exists(dst_path) and not overwrite:
            raise HTTPException(
                status_code=409,
                detail=f"Voice '{stem}' already exists. Pass overwrite=true to replace it.",
            )

        # Stream upload to a unique temp file — concurrent uploads must not collide.
        import tempfile
        fd, tmp_path = tempfile.mkstemp(
            suffix=src_ext,
            prefix="voice_upload_",
            dir=get_writable_dir(RECORDING_PATH),
        )
        try:
            chunk_size = 1024 * 1024
            with os.fdopen(fd, "wb") as f:
                while True:
                    chunk = await file.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)

            try:
                result = preprocess_voice_audio(
                    src_path=tmp_path,
                    dst_path=dst_path,
                    max_duration_s=max_duration_s,
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Preprocessing failed: {e}"
                ) from e
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        # Drop every stale cache (legacy + per-model) for this stem — the audio changed.
        import glob as _glob
        stale_paths = _glob.glob(os.path.join(custom_dir, f"{stem}.safetensors")) + _glob.glob(
            os.path.join(custom_dir, f"{stem}.*.safetensors")
        )
        for stale in stale_paths:
            try:
                os.remove(stale)
            except OSError:
                pass

        # Drop matching entries from the in-memory voice cache — only those
        # that point at this stem's files, not the whole cache.
        cache = self.pocket_tts.voice_cache
        for cached_key in list(cache.keys()):
            if os.path.basename(cached_key).startswith(f"{stem}."):
                cache.pop(cached_key, None)

        return {
            "filename": f"{stem}.wav",
            "path": result.path,
            "sample_rate": result.sample_rate,
            "duration_seconds": result.duration_seconds,
            "channels": result.channels,
            "original_sample_rate": result.original_sample_rate,
            "original_channels": result.original_channels,
            "original_duration_seconds": result.original_duration_seconds,
            "trimmed_silence_ms": result.trimmed_silence_ms,
            "truncated": result.truncated,
        }

    # POST /xvasynth/start
    def start_xvasynth(self):
        self.xvasynth.start_server()

    # POST /xvasynth/stop
    def stop_xvasynth(self):
        try:
            self.xvasynth.stop_server()
        except Exception as e:
            self.printr.print(
                f"Error stopping XVASynth: {e}", color=LogType.ERROR, server_only=True
            )

    def get_xvasynth_model_dirs(self):
        subfolders = []
        try:
            subfolders = [
                dir.name for dir in os.scandir(self.xvasynth.models_dir) if dir.is_dir()
            ]
        except Exception:
            pass

        return subfolders

    def get_xvasynth_voices(self, model_directory: str):
        voices = []
        directory = os.path.join(self.xvasynth.models_dir, model_directory)
        try:
            # listing all files in the directory
            files = [
                f
                for f in os.listdir(directory)
                if os.path.isfile(os.path.join(directory, f))
            ]

            # extracting unique base filenames
            unique_base_filenames = set(os.path.splitext(f)[0] for f in files)
            voices = list(unique_base_filenames)
        except Exception:
            # this can fail:
            # - on MacOS (always)
            # - in Dev mode if the dev hasn't copied the whispercpp-models dir to the repository
            # in these cases, we return an empty list and the client will lock the controls and show a warning.
            pass
        return voices

    # POST /open-filemanager
    def open_file_manager(self, path: str):
        show_in_file_manager(path)

    # POST /open-filemanager/config
    def open_config_directory(self, config_name: str):
        show_in_file_manager(self.config_manager.get_config_dir_path(config_name))

    # POST /open-filemanager/logs
    def open_logs_directory(self):
        show_in_file_manager(get_writable_dir("logs"))

    # POST /open-filemanager/audio-library
    def open_audio_library_directory(self):
        show_in_file_manager(get_audio_library_dir())

    # POST /open-filemanager/custom-voices
    def open_custom_voices_directory(self):
        show_in_file_manager(get_custom_voices_dir())

    # POST /open-filemanager/local-models
    def open_local_models_directory(self):
        show_in_file_manager(get_models_dir())

    # POST /open-filemanager/custom-skills
    def open_custom_skills_directory(self):
        show_in_file_manager(get_custom_skills_dir())

    # GET /models/openrouter
    async def get_openrouter_models(self):
        try:
            response = requests.get(
                url="https://openrouter.ai/api/v1/models", timeout=10
            )
            response.raise_for_status()
            content = response.json()
            return content.get("data", [])
        except Exception as e:
            self.printr.toast_error(f"OpenRouter: \n{str(e)}")
            return []

    # GET /models/openrouter/endpoints
    async def get_openrouter_model_endpoints(self, model_id: str):
        if not model_id:
            return None
        try:
            response = requests.get(
                url=f"https://openrouter.ai/api/v1/models/{model_id}/endpoints",
                timeout=10,
            )
            response.raise_for_status()
            content = response.json()
            result = OpenRouterEndpointResult(**content.get("data", {}))
            return result
        except Exception as e:
            self.printr.toast_error(f"OpenRouter: \n{str(e)}")
            return None

    # GET /models/groq
    async def get_groq_models(self):
        groq_api_key = await self.secret_keeper.retrieve(key="groq", requester="Groq")
        try:
            response = requests.get(
                url="https://api.groq.com/openai/v1/models",
                timeout=10,
                headers={
                    "Authorization": f"Bearer {groq_api_key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            content = response.json()
            return content.get("data", [])
        except Exception as e:
            self.printr.toast_error(f"Groq: \n{str(e)}")
            return []

    async def get_cerebras_models(self):
        cerebras_api_key = await self.secret_keeper.retrieve(
            key="cerebras", requester="Cerebras"
        )
        try:
            response = requests.get(
                url="https://api.cerebras.ai/v1/models",
                timeout=10,
                headers={
                    "Authorization": f"Bearer {cerebras_api_key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            content = response.json()
            return content.get("data", [])
        except Exception as e:
            self.printr.toast_error(f"Cerebras: \n{str(e)}")
            return []

    async def get_xai_models(self):
        xia_api_key = await self.secret_keeper.retrieve(key="xai", requester="XAI")
        try:
            response = requests.get(
                url="https://api.x.ai/v1/models",
                timeout=10,
                headers={
                    "Authorization": f"Bearer {xia_api_key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            content = response.json()
            return content.get("data", [])
        except Exception as e:
            self.printr.toast_error(f"XAI: \n{str(e)}")
            return []

    async def get_mistral_models(self):
        mistral_api_key = await self.secret_keeper.retrieve(
            key="mistral", requester="Mistral"
        )
        try:
            response = requests.get(
                url="https://api.mistral.ai/v1/models",
                timeout=10,
                headers={
                    "Authorization": f"Bearer {mistral_api_key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            content = response.json()
            return content.get("data", [])
        except Exception as e:
            self.printr.toast_error(f"Mistral: \n{str(e)}")
            return []

    async def get_openai_models(self):
        openai_api_key = await self.secret_keeper.retrieve(
            key="openai", requester="OpenAI"
        )
        try:
            response = requests.get(
                url="https://api.openai.com/v1/models",
                timeout=10,
                headers={
                    "Authorization": f"Bearer {openai_api_key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            content = response.json()
            return content.get("data", [])
        except Exception as e:
            self.printr.toast_error(f"OpenAI: \n{str(e)}")
            return []

    async def get_wingman_pro_models(self):
        wingman_pro_token = await self.secret_keeper.retrieve(
            key="wingman_pro", requester="WingmanPro"
        )
        try:
            response = requests.get(
                url=f"{self.settings_service.settings.wingman_pro.base_url}/wingman-pro-models",
                params={"region": self.settings_service.settings.wingman_pro.region},
                timeout=10,
                headers={
                    "Authorization": f"Bearer {wingman_pro_token}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            model_list = response.json()
            return model_list
        except Exception as e:
            self.printr.toast_error(f"Wingman Pro: \n{str(e)}")
            return []

    async def get_wingman_pro_regions(self):
        wingman_pro_token = await self.secret_keeper.retrieve(
            key="wingman_pro", requester="WingmanPro"
        )
        try:
            response = requests.get(
                url=f"{self.settings_service.settings.wingman_pro.base_url}/wingman-pro-regions",
                params={"region": self.settings_service.settings.wingman_pro.region},
                timeout=10,
                headers={
                    "Authorization": f"Bearer {wingman_pro_token}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            model_list = response.json()
            return model_list
        except Exception as e:
            self.printr.toast_error(f"Wingman Pro: \n{str(e)}")
            return []

    # GET /models/elevenlabs
    async def get_elevenlabs_models(self) -> list[ElevenlabsModel]:
        elevenlabs_api_key = await self.secret_keeper.retrieve(
            key="elevenlabs", requester="Elevenlabs"
        )
        try:
            elevenlabs = ElevenLabs(api_key=elevenlabs_api_key, wingman_name="")
            models = elevenlabs.get_available_models()

            convert = lambda model: ElevenlabsModel(
                name=model.name,
                model_id=model.modelID,
                description=model.description,
                max_characters=model.maxCharacters,
                cost_factor=model.costFactor,
                supported_languages=model.supportedLanguages,
                metadata=model.metadata,
            )
            result = [convert(model) for model in models]
            return result
        except Exception as e:
            self.printr.toast_error(f"Elevenlabs: \n{str(e)}")
            return []

    # GET /models/google
    async def get_google_models(self) -> list[types.Model]:
        google_api_key = await self.secret_keeper.retrieve(
            key="google", requester="Google"
        )
        google = GoogleGenAI(api_key=google_api_key)
        try:
            models = google.get_available_models()
            return models
        except Exception as e:
            self.printr.toast_error(f"Google: \n{str(e)}")
            return []
        finally:
            await google.aclose()

    # GET /models/metadata
    async def get_model_metadata_all(self):
        return await self.model_metadata_service.get_all()

    # GET /models/metadata/{model_id}
    async def get_model_metadata(self, model_id: str):
        result = await self.model_metadata_service.get(model_id)
        if result is None:
            return {}
        return result

    # GET /audio-library
    async def get_audio_library(self):
        return self.audio_library.get_audio_files()

    # POST /audio-library/play
    async def play_from_audio_library(
        self, name: str, path: str, volume: Optional[float] = 1.0
    ):
        await self.audio_library.audio_library_toggle_play(
            audio_file=AudioFile(name=name, path=path), volume_modifier=volume
        )

    def on_audio_library_playback_finished(self, audio_file: AudioFile):
        if self._connection_manager:
            command = AudioLibraryPlaybackFinishedCommand(audio_file=audio_file)
            self.ensure_async(self._connection_manager.broadcast(command))

    # ── Local AI Endpoints ────────────────────────────────────────

    # GET /settings/local-ai/status
    async def get_local_ai_status(self) -> dict:
        status = self.local_model_manager.get_status()
        status["is_ready"] = self.local_ai_service.is_ready()
        status["cuda_available"] = self.system_manager.is_cuda_available()
        return status

    # GET /settings/local-ai/backends
    def get_local_ai_backends(self) -> list[str]:
        backends = self.local_model_manager.get_available_backends()
        # Filter CUDA out if not available on this machine
        if not self.system_manager.is_cuda_available():
            backends = [b for b in backends if b != "cuda"]
        return backends

    # GET /settings/local-ai/support-models
    def get_local_ai_support_models(self) -> list[dict]:
        return self.local_model_manager.get_support_models()

    # GET /settings/local-ai/embed-models
    def get_local_ai_embed_models(self) -> list[dict]:
        return self.local_model_manager.get_embed_models()

    # POST /settings/local-ai/download-models
    async def download_local_ai_models(self) -> dict:
        success = await self.local_model_manager.download_models(
            cuda_available=self.system_manager.is_cuda_available()
        )
        if success:
            await self.local_ai_service.initialize()
        return {
            "success": success,
            **self.local_model_manager.get_status(),
        }

    # POST /settings/local-ai/playground/chat
    async def playground_chat(self, request: PlaygroundChatRequest) -> dict:
        """Test the support model with a system + user message.

        When iterations > 1, runs the same prompt multiple times and returns
        all responses so users can evaluate output variety and quality.
        """
        if not self.local_ai_service.is_ready():
            return {
                "success": False,
                "error": "Local AI service is not ready. Make sure models are loaded.",
            }

        iterations = max(1, min(request.iterations, 20))

        def _run():
            benchmark = Benchmark("playground_chat")
            responses = []
            for i in range(iterations):
                label = f"iteration_{i + 1}"
                benchmark.start_snapshot(label)
                result = self.local_ai_service.support(
                    text=request.user_message,
                    system_prompt=request.system_message,
                    temperature=request.temperature,
                    top_p=request.top_p,
                    top_k=request.top_k,
                    presence_penalty=request.presence_penalty,
                    reasoning=request.reasoning,
                )
                snap = benchmark.finish_snapshot()
                elapsed_ms = snap.execution_time_ms if snap else 0
                responses.append({
                    "text": result.text if result.text else "",
                    "reasoning": result.reasoning_content or "",
                    "truncated": result.truncated,
                    "completion_tokens": result.completion_tokens or 0,
                    "time_ms": round(elapsed_ms, 1),
                })
            return responses, benchmark.finish()

        responses, bench_result = await asyncio.to_thread(_run)

        return {
            "success": True,
            "responses": responses,
            # Keep single-response field for backward compat
            "response": responses[0]["text"] if responses else "",
            "benchmark": bench_result.model_dump(),
        }

    # ── Playground lab configuration (single source of truth) ───
    # Maps each prompt to the preset used in production and a realistic
    # example user message that matches the exact format the real code sends.
    PROMPT_LAB_CONFIG: dict[str, dict] = {
        "condense-conversation": {
            "production_preset": "Balanced",
            "production_reasoning": True,
            "example_message": (
                "CONVERSATION TO SUMMARIZE:\n"
                "User: What's the best ship for solo bounty hunting?\n"
                "Assistant: For solo bounty hunting, the Aegis Vanguard Warden is hard to beat. "
                "It has heavy forward firepower, strong shields, and good range. The Drake Cutlass Black "
                "is a more affordable option with decent combat capability plus cargo space.\n"
                "User: I've been flying my Cutlass Black but I keep dying to Hammerheads. Any tips?\n"
                "Assistant: Hammerheads are tough targets for a solo pilot. Focus on hit-and-run attacks "
                "— approach fast, unload on one shield face, then boost away before turrets track you. "
                "Aim for the engines to reduce their mobility. Consider upgrading to Size 3 gimballed "
                "weapons for better sustained DPS.\n"
                "User: Good advice. My org is planning a group bounty night on Saturday, maybe I'll "
                "save the Hammerheads for that.\n"
                "Assistant: That's a smart plan! With a wing of 3-4 fighters, you can coordinate "
                "shield-face attacks and take down Hammerheads much more efficiently. Have someone fly "
                "an ERT-capable ship to pull the contracts.\n"
                "\n---\n"
                "Now list every fact from the conversation above as bullet points.\n"
                "Start from the FIRST message, end at the LAST. Include all secrets, names, "
                "preferences, and creative content:"
            ),
        },
        "extract-memories": {
            "production_preset": "Precise",
            "production_reasoning": True,
            "example_message": (
                "user: Hey, can you check the trade prices for laranite at Lorville?\n"
                "assistant: Laranite is currently buying at 31.26 aUEC per unit at the TDD in Lorville. "
                "The sell price at Port Tressler is around 33.10 aUEC, so you'd make about 1.84 per "
                "unit profit on that route.\n"
                "user: Nice, I'll load up my C2 Hercules. It can carry 696 SCU so that should be a "
                "decent run. My buddy Marcus and I have been grinding trade runs all week to save up "
                "for an Idris.\n"
                "assistant: That's ambitious! An Idris is a serious investment. With 696 SCU of "
                "laranite per run, you're looking at about 1,280 aUEC profit per run. How much have "
                "you saved so far?\n"
                "user: We're at about 12 million, still a long way to go. Oh, I also joined the org "
                '"Stellar Logistics Corp" last week, they do coordinated trade convoys which should help.'
            ),
        },
        "greeting-default": {
            "production_preset": "Balanced",
            "example_message": "Generate your greeting.",
        },
        "greeting-returning": {
            "production_preset": "Creative",
            "example_message": "Generate your greeting.",
        },
        # enhance-backstory: uses the conversation LLM, not the support model — not listed here
        "radio-chatter": {
            "production_preset": None,  # uses main LLM, not support model
            "example_message": (
                "Generate radio chatter between 3 pilots approaching a space station. "
                "5 messages total. They should be requesting landing clearance, commenting "
                "on traffic, and coordinating their approach vectors."
            ),
        },
        "support-default": {
            "production_preset": "Balanced",
            "example_message": (
                "The Aegis Gladius is a light fighter originally developed for the UEE Navy as a "
                "patrol and intercept craft. It features a sleek, angular design optimized for speed "
                "and agility in dogfighting scenarios. The ship has three weapon hardpoints — two "
                "Size 3 on the wings and one Size 3 on the nose — making it a potent threat despite "
                "its small size. It lacks any cargo capacity, reinforcing its pure combat role. The "
                "Gladius has been a mainstay of military and civilian combat pilots since its "
                "introduction, valued for its excellent maneuverability and reliable power plant."
            ),
        },
        "support-tool-response": {
            "production_preset": "Precise",
            "example_message": (
                "DATA TO SUMMARIZE:\n"
                '{"status": "success", "data": {"ship": "Constellation Andromeda", '
                '"manufacturer": "RSI", "role": "Multi-crew explorer", "crew": {"min": 1, "max": 4}, '
                '"cargo_scu": 96, "price_auec": 3250000, "weapons": [{"mount": "Turret", "size": 4, '
                '"count": 2}, {"mount": "Fixed", "size": 5, "count": 2}, {"mount": "Missile", '
                '"size": 2, "count": 28}], "shields": [{"type": "FR-76", "size": "L", "count": 2}], '
                '"quantum_drive": "Odyssey", "status": "Flight Ready", "last_updated": "2954-03-15"}}'
                "\n\n---\n"
                "Summarize the above data. Preserve all key facts, numbers, names, IDs, and status values:"
            ),
        },
        "tts-test-praise": {
            "production_preset": "Precise",
            "example_message": "Generate a sentence.",
        },
    }

    async def playground_list_prompts(self) -> list[dict]:
        """List available prompt templates for the playground."""
        from services.file import get_prompt
        import os

        prompts_dir = os.path.join(
            os.path.abspath(os.path.dirname(__file__)), "prompts"
        )
        results = []
        for filename in sorted(os.listdir(prompts_dir)):
            if filename.endswith(".md"):
                name = filename[:-3]
                content = get_prompt(name)
                first_line = content.split("\n")[0].strip()
                lab_config = self.PROMPT_LAB_CONFIG.get(name, {})
                results.append({
                    "name": name,
                    "label": first_line[:60] + ("…" if len(first_line) > 60 else ""),
                    "content": content,
                    "production_preset": lab_config.get("production_preset"),
                    "production_reasoning": lab_config.get("production_reasoning", False),
                    "example_message": lab_config.get("example_message"),
                })
        return results

    async def playground_list_presets(self) -> list[dict]:
        """List sampling presets from the SamplingPreset enum."""
        from services.skill_local_ai import SamplingPreset

        return [
            {
                "name": preset.name.capitalize(),
                "temperature": preset.temperature,
                "top_p": preset.top_p,
                "top_k": preset.top_k,
                "presence_penalty": preset.presence_penalty,
            }
            for preset in SamplingPreset
        ]

    # POST /settings/local-ai/detect-context-size
    async def detect_remote_context_size(
        self, request: DetectContextSizeRequest
    ) -> dict:
        """Detect a remote llama.cpp support server's context window via /props.

        Lets users point Wingman at a powerful self-hosted model and have all
        the auto-sized budgets scale to its real context window.
        """
        n_ctx = await asyncio.to_thread(
            LlamaCppRemote.detect_context_size, request.host, request.port
        )
        if n_ctx:
            return {"success": True, "n_ctx": n_ctx}
        return {
            "success": False,
            "error": (
                "Could not read context size. Make sure the host/port point at a "
                "reachable llama.cpp server that exposes /props."
            ),
        }

    # GET /settings/local-ai/playground/memory-scenarios
    async def playground_list_memory_scenarios(self) -> list[dict]:
        """List the simulated conversations the Persistent Memory test suite can run."""
        from evals.memory_suite.scenarios import SCENARIOS

        return [
            {
                "id": s.id,
                "title": s.title,
                "category": s.category,
                "message_count": len(s.messages),
                "expected_fact_count": len(s.expect_facts),
                "recall_probe_count": len(s.recall),
            }
            for s in SCENARIOS
        ]

    # POST /settings/local-ai/playground/memory-suite
    async def playground_run_memory_scenario(
        self, request: MemorySuiteRequest
    ) -> dict:
        """Run one Persistent Memory scenario end-to-end against the loaded models
        and return a scorecard (extraction facts, recall probes, greeting).

        This drives the REAL pipeline (extract -> store -> recall) on a throwaway
        database, so it never touches the user's actual memories.
        """
        if not self.local_ai_service.is_ready():
            return {
                "success": False,
                "error": "Local AI service is not ready. Make sure the models are loaded.",
            }

        from evals.memory_suite.harness import run_scenario
        from evals.memory_suite.profiles import DEFAULT
        from evals.memory_suite.scenarios import get_scenarios

        matches = get_scenarios(ids=[request.scenario_id]) if request.scenario_id else []
        if not matches:
            return {"success": False, "error": f"Unknown scenario '{request.scenario_id}'."}

        scenario = matches[0]
        samples = max(1, min(request.samples, 5))
        result = await asyncio.to_thread(
            run_scenario, self.local_ai_service, scenario, DEFAULT, samples
        )
        # Include the conversation so the UI can show what was fed in.
        result["messages"] = scenario.messages
        return {"success": True, "result": result}

    # POST /settings/local-ai/playground/embed
    async def playground_embed(self, texts: list[str] = Body(...)) -> dict:
        """Test the embedding model with one or more texts."""
        if not self.local_ai_service.is_ready():
            return {
                "success": False,
                "error": "Local AI service is not ready. Make sure models are loaded.",
            }

        def _run():
            benchmark = Benchmark("playground_embed")
            benchmark.start_snapshot("inference")
            result = self.local_ai_service.embed(texts)
            benchmark.finish_snapshot()
            return result, benchmark.finish()

        result, bench_result = await asyncio.to_thread(_run)

        if result is None:
            return {"success": False, "error": "Embedding returned no result."}

        return {
            "success": True,
            "embeddings": [
                {"text": t, "dimensions": len(e), "preview": e[:8]}
                for t, e in zip(texts, result)
            ],
            "benchmark": bench_result.model_dump(),
        }

    # POST /settings/local-ai/playground/benchmark
    async def playground_benchmark(
        self,
        iterations: int = 3,
    ) -> dict:
        """Run an automated benchmark suite over both models."""
        if not self.local_ai_service.is_ready():
            return {
                "success": False,
                "error": "Local AI service is not ready. Make sure models are loaded.",
            }

        iterations = max(1, min(iterations, 20))

        return await asyncio.to_thread(self._run_benchmark_sync, iterations)

    def _run_benchmark_sync(self, iterations: int) -> dict:
        """Blocking benchmark loop — runs in a thread to keep the event loop free."""
        benchmark = Benchmark("full_benchmark")
        results = {"support_runs": [], "embed_runs": []}

        # Support model benchmark
        test_texts = [
            "The quick brown fox jumps over the lazy dog. This is a short test sentence.",
            "Artificial intelligence is transforming how we interact with technology. Large language models can understand and generate human-like text, while embedding models convert text into numerical vectors that capture semantic meaning. These capabilities enable powerful applications like semantic search, text summarization, and conversational AI assistants.",
            "In a galaxy far, far away, there existed a civilization that had mastered the art of faster-than-light travel. Their ships could traverse the vast emptiness between star systems in mere hours. The key to their technology was a crystal found only in the deepest mines of their home world. This crystal, when properly refined and charged, could bend the fabric of spacetime itself, creating tunnels through which spacecraft could pass almost instantaneously. However, the supply of this precious mineral was dwindling, and the civilization faced an existential crisis as they searched for alternatives.",
        ]

        # Cycle through SamplingPreset enum (single source of truth)
        from services.skill_local_ai import SamplingPreset
        all_presets = list(SamplingPreset)

        for i in range(iterations):
            preset = all_presets[i % len(all_presets)]
            for j, text in enumerate(test_texts):
                label = f"support_iter{i+1}_text{j+1}_{len(text)}chars"
                benchmark.start_snapshot(label)
                res = self.local_ai_service.support(
                    text=text,
                    preset=preset,
                )
                benchmark.finish_snapshot()

                # Compute tokens/sec from the snapshot we just finished
                snap = benchmark.snapshots[-1] if benchmark.snapshots else None
                elapsed_sec = (snap.execution_time_ms / 1000.0) if snap else 0
                completion_tokens = (
                    res.completion_tokens if res.completion_tokens else 0
                )
                tokens_per_sec = (
                    completion_tokens / elapsed_sec
                    if elapsed_sec > 0 and completion_tokens > 0
                    else 0
                )

                results["support_runs"].append(
                    {
                        "iteration": i + 1,
                        "input_length": len(text),
                        "output_length": len(res.text) if res.text else 0,
                        "prompt_tokens": res.prompt_tokens if res.prompt_tokens else 0,
                        "completion_tokens": completion_tokens,
                        "tokens_per_sec": round(tokens_per_sec, 1),
                        "label": label,
                        "preset": preset.name,
                        "temperature": preset.temperature,
                        "top_p": preset.top_p,
                        "top_k": preset.top_k,
                        "presence_penalty": preset.presence_penalty,
                    }
                )

        # Embed benchmark
        embed_inputs = [
            ["Hello world"],
            ["The quick brown fox", "jumps over the lazy dog"],
            [
                "Artificial intelligence",
                "machine learning",
                "deep neural networks",
                "natural language processing",
            ],
        ]

        for i in range(iterations):
            for j, texts in enumerate(embed_inputs):
                label = f"embed_iter{i+1}_batch{j+1}_{len(texts)}texts"
                benchmark.start_snapshot(label)
                res = self.local_ai_service.embed(texts)
                benchmark.finish_snapshot()
                results["embed_runs"].append(
                    {
                        "iteration": i + 1,
                        "num_texts": len(texts),
                        "dimensions": len(res[0]) if res else 0,
                        "label": label,
                    }
                )

        bench_result = benchmark.finish()
        snapshots = bench_result.snapshots or []

        # Calculate averages
        sum_times = [
            s.execution_time_ms for s in snapshots if s.label.startswith("support_")
        ]
        emb_times = [
            s.execution_time_ms for s in snapshots if s.label.startswith("embed_")
        ]

        # Tokens/sec stats from support runs
        tps_values = [
            r["tokens_per_sec"]
            for r in results["support_runs"]
            if r["tokens_per_sec"] > 0
        ]
        avg_tokens_per_sec = (
            round(sum(tps_values) / len(tps_values), 1) if tps_values else 0
        )

        return {
            "success": True,
            "iterations": iterations,
            "total_time_ms": bench_result.execution_time_ms,
            "formatted_total_time": bench_result.formatted_execution_time,
            "support_avg_ms": sum(sum_times) / len(sum_times) if sum_times else 0,
            "embed_avg_ms": sum(emb_times) / len(emb_times) if emb_times else 0,
            "avg_tokens_per_sec": avg_tokens_per_sec,
            "snapshots": [s.model_dump() for s in snapshots],
            "runs": results,
        }

    # POST /settings/test/whispercpp
    async def test_whispercpp(self) -> TestConnectionResult:
        """Test the whisper.cpp server by sending a short audio file for transcription."""
        settings = self.settings_service.settings.voice_activation.whispercpp
        try:
            response = requests.get(
                url=f"{settings.host}:{settings.port}",
                timeout=5,
            )
            if response.ok:
                return TestConnectionResult(success=True, provider="whispercpp")
            return TestConnectionResult(
                success=False,
                provider="whispercpp",
                error=f"Server returned status {response.status_code}",
            )
        except requests.ConnectionError:
            return TestConnectionResult(
                success=False,
                provider="whispercpp",
                error=f"Could not connect to {settings.host}:{settings.port}. Is the server running?",
            )
        except Exception as e:
            return TestConnectionResult(
                success=False, provider="whispercpp", error=str(e)
            )

    # POST /settings/test/parakeet
    async def test_parakeet(self) -> TestConnectionResult:
        """Test Parakeet by transcribing a short audio sample (locally or remotely)."""
        settings = self.settings_service.settings.voice_activation.parakeet

        stt_provider = self.settings_service.settings.voice_activation.stt_provider
        if stt_provider != VoiceActivationSttProvider.PARAKEET:
            return TestConnectionResult(
                success=False,
                provider="parakeet",
                error="Parakeet is not the active STT provider.",
            )

        wav_path = os.path.join(self.app_root_path, "audio_samples", "beep.wav")
        config = ParakeetSttConfig(temperature=0.0)

        if settings.run_locally:
            if self.parakeet._loading:
                return TestConnectionResult(
                    success=False,
                    provider="parakeet",
                    error="Parakeet model is still loading. Please wait and try again.",
                )
            if not self.parakeet.model:
                return TestConnectionResult(
                    success=False,
                    provider="parakeet",
                    error="Parakeet model is not loaded. Check STT settings.",
                )

        try:
            result = self.parakeet.transcribe(config=config, filename=wav_path)
            if result and result.text is not None:
                return TestConnectionResult(success=True, provider="parakeet")
            return TestConnectionResult(
                success=False,
                provider="parakeet",
                error="Transcription returned no result.",
            )
        except Exception as e:
            return TestConnectionResult(
                success=False, provider="parakeet", error=str(e)
            )

    # POST /settings/test/xvasynth
    async def test_xvasynth(self) -> TestConnectionResult:
        """Test the XVASynth server connection."""
        settings = self.settings_service.settings.xvasynth
        try:
            response = requests.get(
                url=f"{settings.host}:{settings.port}",
                timeout=10,
            )
            if response.ok:
                return TestConnectionResult(success=True, provider="xvasynth")
            return TestConnectionResult(
                success=False,
                provider="xvasynth",
                error=f"Server returned status {response.status_code}",
            )
        except requests.ConnectionError:
            return TestConnectionResult(
                success=False,
                provider="xvasynth",
                error=f"Could not connect to {settings.host}:{settings.port}. Is the server running?",
            )
        except Exception as e:
            return TestConnectionResult(
                success=False, provider="xvasynth", error=str(e)
            )

    # POST /settings/test/local-ai/support
    async def test_local_ai_support(self) -> TestConnectionResult:
        """Test the local AI support model."""
        if not self.local_ai_service.is_ready():
            return TestConnectionResult(
                success=False,
                provider="local_ai_support",
                error="Local AI service is not ready. Make sure models are loaded.",
            )
        try:
            result = self.local_ai_service.support(
                text="The quick brown fox jumps over the lazy dog.",
            )
            if result and result.text:
                return TestConnectionResult(success=True, provider="local_ai_support")
            return TestConnectionResult(
                success=False,
                provider="local_ai_support",
                error="Support model returned no result.",
            )
        except Exception as e:
            return TestConnectionResult(
                success=False, provider="local_ai_support", error=str(e)
            )

    # POST /settings/test/local-ai/embed
    async def test_local_ai_embed(self) -> TestConnectionResult:
        """Test the local AI embedding model."""
        if not self.local_ai_service.is_ready():
            return TestConnectionResult(
                success=False,
                provider="local_ai_embed",
                error="Local AI service is not ready. Make sure models are loaded.",
            )
        try:
            result = self.local_ai_service.embed(["hello world"])
            if result and len(result) > 0:
                return TestConnectionResult(success=True, provider="local_ai_embed")
            return TestConnectionResult(
                success=False,
                provider="local_ai_embed",
                error="Embedding returned no result.",
            )
        except Exception as e:
            return TestConnectionResult(
                success=False, provider="local_ai_embed", error=str(e)
            )

    # POST /settings/test/hud-server
    async def test_hud_server(self) -> TestConnectionResult:
        """Test the HUD server connection via its health endpoint."""
        settings = self.settings_service.settings.hud_server
        try:
            host = settings.host or "127.0.0.1"
            port = settings.port or 7862
            # Ensure host has a scheme
            if not host.startswith("http"):
                host = f"http://{host}"
            response = requests.get(
                url=f"{host}:{port}/health",
                timeout=5,
            )
            if response.ok:
                data = response.json()
                if data.get("status") == "healthy":
                    return TestConnectionResult(success=True, provider="hud_server")
                return TestConnectionResult(
                    success=False,
                    provider="hud_server",
                    error=f"HUD server responded but status is '{data.get('status', 'unknown')}'",
                )
            return TestConnectionResult(
                success=False,
                provider="hud_server",
                error=f"Server returned status {response.status_code}",
            )
        except requests.ConnectionError:
            return TestConnectionResult(
                success=False,
                provider="hud_server",
                error=f"Could not connect to HUD server. Is it running?",
            )
        except Exception as e:
            return TestConnectionResult(
                success=False, provider="hud_server", error=str(e)
            )

    # POST /settings/test/pocket-tts
    async def test_pocket_tts(self) -> TestConnectionResult:
        """Test PocketTTS: check local model is loaded or remote server is reachable."""
        settings = self.settings_service.settings.pocket_tts
        if not settings.enable:
            return TestConnectionResult(
                success=False,
                provider="pocket_tts",
                error="PocketTTS is not enabled.",
            )

        if settings.run_locally:
            if self.pocket_tts.model is not None:
                return TestConnectionResult(success=True, provider="pocket_tts")
            return TestConnectionResult(
                success=False,
                provider="pocket_tts",
                error="PocketTTS model is not loaded. Try toggling PocketTTS off and on.",
            )

        # Remote mode — hit the server's health endpoint
        try:
            base = PocketTTS.normalize_remote_url(settings.host, settings.port)
            response = requests.get(
                url=f"{base}/health",
                timeout=5,
            )
            if response.ok:
                return TestConnectionResult(success=True, provider="pocket_tts")
            return TestConnectionResult(
                success=False,
                provider="pocket_tts",
                error=f"Server returned status {response.status_code}",
            )
        except requests.ConnectionError:
            return TestConnectionResult(
                success=False,
                provider="pocket_tts",
                error=f"Could not connect to PocketTTS server at {base}. Is it running?",
            )
        except Exception as e:
            return TestConnectionResult(
                success=False, provider="pocket_tts", error=str(e)
            )

    # POST /settings/test/openai-compatible-tts
    async def test_openai_compatible_tts(
        self,
        base_url: str = Body(..., embed=True),
    ) -> TestConnectionResult:
        """Test an OpenAI-compatible TTS server by probing known endpoints."""
        if not base_url:
            return TestConnectionResult(
                success=False,
                provider="openai_compatible_tts",
                error="No base URL configured.",
            )
        url = base_url.rstrip("/")
        # Try endpoints in order: /health, /audio/speech (GET → 405 still proves liveness), root
        probe_paths = ["/health", "/audio/speech", ""]
        try:
            for path in probe_paths:
                try:
                    response = requests.get(url=f"{url}{path}", timeout=10)
                    # 2xx or 405 (method not allowed) both prove the server is alive
                    if response.ok or response.status_code == 405:
                        return TestConnectionResult(
                            success=True, provider="openai_compatible_tts"
                        )
                except requests.ConnectionError:
                    continue
            return TestConnectionResult(
                success=False,
                provider="openai_compatible_tts",
                error=f"Could not connect to {base_url}. Is the server running?",
            )
        except Exception as e:
            return TestConnectionResult(
                success=False, provider="openai_compatible_tts", error=str(e)
            )

    # POST /local-ai/support
    async def api_support(
        self,
        text: str = Body(..., embed=True),
        system_prompt: str = Body(
            "",
            embed=True,
        ),
    ) -> dict:
        """Public API: Process text using the local AI support model.

        Output token budget is computed automatically from the context window.
        """
        if not self.local_ai_service.is_ready():
            raise HTTPException(
                status_code=503,
                detail="Local AI service is not ready. Make sure models are loaded.",
            )
        result = self.local_ai_service.support(
            text=text, system_prompt=system_prompt
        )
        if result.text is None:
            raise HTTPException(status_code=500, detail="Support model call failed.")
        return {"result": result.text}

    # POST /local-ai/enhance-backstory
    async def api_enhance_backstory(
        self,
        wingman_name: str = Body(...),
        backstory: str = Body(...),
    ) -> dict:
        """Enhance a wingman backstory using that wingman's conversation LLM.

        Uses the specific wingman's conversation provider (OpenAI, Azure, etc.)
        — not the local support model — because backstory enhancement requires
        a capable model that can follow complex prompt-engineering rules.
        """
        from wingmen.open_ai_wingman import OpenAiWingman

        wingman = self.tower.get_wingman_by_name(wingman_name) if self.tower else None
        if not wingman or not isinstance(wingman, OpenAiWingman):
            raise HTTPException(
                status_code=404,
                detail=f"Wingman '{wingman_name}' not found or has no conversation provider.",
            )

        MAX_BACKSTORY_TOKENS = 2048
        backstory_tokens = count_tokens(backstory)
        if backstory_tokens > MAX_BACKSTORY_TOKENS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Backstory too long: ~{backstory_tokens} tokens "
                    f"(max {MAX_BACKSTORY_TOKENS}). "
                    f"Consider shortening your backstory."
                ),
            )

        system_prompt = get_prompt("enhance-backstory")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": backstory},
        ]

        try:
            completion = await wingman.actual_llm_call(messages)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"LLM call failed: {e}",
            )

        if not completion or not completion.choices:
            raise HTTPException(
                status_code=500,
                detail="Backstory enhancement failed — no response from LLM.",
            )

        result_text = completion.choices[0].message.content
        if not result_text:
            raise HTTPException(
                status_code=500,
                detail="Backstory enhancement failed — empty response.",
            )

        # Parse JSON response: {"backstory": "...", "summary": "..."}
        # Strip markdown code fences if the model wrapped the JSON
        import re as _re
        import json as _json
        stripped = result_text.strip()
        fence_match = _re.match(r"^```(?:json)?\s*\n?([\s\S]*?)\n?```\s*$", stripped)
        if fence_match:
            stripped = fence_match.group(1).strip()
        try:
            parsed = _json.loads(stripped)
            enhanced = parsed.get("backstory", result_text)
            summary = parsed.get("summary", "")
        except (_json.JSONDecodeError, AttributeError):
            # Model didn't return valid JSON — use raw text as backstory
            enhanced = result_text
            summary = ""

        raw_model = getattr(completion, "model", None) or ""
        # Strip date suffixes like "-2025-04-14" for a friendlier display name
        model_name = _re.sub(r"-\d{4}-\d{2}-\d{2}$", "", raw_model)
        usage = getattr(completion, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        return {
            "result": enhanced,
            "summary": summary,
            "model": model_name,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }

    # GET /local-ai/enhance-backstory-budget
    async def api_enhance_backstory_budget(self) -> dict:
        """Return the max backstory tokens for enhancement.

        Since this now uses the conversation LLM (not the local support model),
        the budget is simply the hard cap.
        """
        MAX_BACKSTORY_TOKENS = 2048
        return {
            "max_backstory_tokens": MAX_BACKSTORY_TOKENS,
        }

    # POST /local-ai/embed
    async def api_embed(self, texts: list[str] = Body(...)) -> dict:
        """Public API: Generate embeddings using the local AI service."""
        if not self.local_ai_service.is_ready():
            raise HTTPException(
                status_code=503,
                detail="Local AI service is not ready. Make sure models are loaded.",
            )
        result = self.local_ai_service.embed(texts)
        if result is None:
            raise HTTPException(status_code=500, detail="Embedding failed.")
        return {"embeddings": result}

    # POST /elevenlabs/generate-sfx
    async def generate_sfx_elevenlabs(
        self,
        prompt: str,
        path: str,
        name: str,
        duration_seconds: Optional[float] = None,
        prompt_influence: Optional[float] = None,
    ):
        elevenlabs_api_key = await self.secret_keeper.retrieve(
            key="elevenlabs", requester="Elevenlabs"
        )
        elevenlabs = ElevenLabs(api_key=elevenlabs_api_key, wingman_name="")
        try:
            audio_bytes = await elevenlabs.generate_sound_effect(
                prompt=prompt,
                duration_seconds=duration_seconds,
                prompt_influence=prompt_influence,
            )

            if not name.endswith(".mp3"):
                name += ".mp3"

            directory = os.path.join(get_audio_library_dir(), path)
            os.makedirs(directory, exist_ok=True)

            if os.path.exists(os.path.join(directory, name)):

                def get_unique_filename(directory: str, filename: str) -> str:
                    base, extension = os.path.splitext(filename)
                    counter = 1
                    while os.path.exists(os.path.join(directory, filename)):
                        filename = f"{base}-{counter}{extension}"
                        counter += 1
                    return filename

                name = get_unique_filename(directory, name)

            with open(os.path.join(directory, name), "wb") as f:
                f.write(audio_bytes)

            await self.audio_library.start_playback(
                audio_file=AudioFile(name=name, path=path)
            )
        except ValueError as e:
            self.printr.toast_error(f"Elevenlabs: \n{str(e)}")
            return False

        return True

    # GET /elevenlabs/subscription-data
    async def get_elevenlabs_subscription_data(self):
        elevenlabs_api_key = await self.secret_keeper.retrieve(
            key="elevenlabs", requester="Elevenlabs"
        )
        elevenlabs = ElevenLabs(api_key=elevenlabs_api_key, wingman_name="")
        try:
            # Run the synchronous method in a separate thread
            loop = asyncio.get_running_loop()
            with ThreadPoolExecutor() as pool:
                data = await loop.run_in_executor(
                    pool, elevenlabs.get_subscription_data
                )
            return data
        except ValueError as e:
            self.printr.toast_error(f"Elevenlabs: \n{str(e)}")

    async def shutdown(self):
        await self.set_core_state(CoreState.SHUTTING_DOWN)

        # Stop HUD Server
        await self._stop_hud_server()

        if self.settings_service.settings.xvasynth.enable:
            self.stop_xvasynth()
        if self.settings_service.settings.pocket_tts.enable:
            self.stop_pocket_tts()

        # Stop managed llama-server processes
        self.llama_cpp_provider.unload_models()

        await self.unload_tower()

        self.printr.print(
            "Core shutdown.",
            server_only=True,
            color=LogType.SYSTEM,
        )

    # GET /memories/{wingman_name}
    def get_memories(self, wingman_name: str):
        wingman = self.tower.get_wingman_by_name(wingman_name)
        if not wingman or not hasattr(wingman, "ensure_memory_initialized"):
            return []
        wingman.ensure_memory_initialized()
        if not wingman.persistent_memory_service:
            return []
        entries = wingman.persistent_memory_service.get_all()
        return [
            MemoryEntryResponse(
                id=e.id,
                collection=e.collection,
                entry_type=e.entry_type,
                content=e.content,
                source_wingman=e.source_wingman,
                session_id=e.session_id,
                created_at=e.created_at,
                updated_at=e.updated_at,
            )
            for e in entries
        ]

    # PUT /memories/{entry_id}
    async def update_memory(self, entry_id: int, request: MemoryUpdateRequest):
        for wingman in self.tower.wingmen:
            if hasattr(wingman, "persistent_memory_service") and wingman.persistent_memory_service:
                entries = wingman.persistent_memory_service.get_all()
                if any(e.id == entry_id for e in entries):
                    await wingman.persistent_memory_service.update_memory(entry_id, request.content)
                    return True
        return False

    # DELETE /memories/{entry_id}
    def delete_memory(self, entry_id: int):
        for wingman in self.tower.wingmen:
            if hasattr(wingman, "persistent_memory_service") and wingman.persistent_memory_service:
                entries = wingman.persistent_memory_service.get_all()
                if any(e.id == entry_id for e in entries):
                    wingman.persistent_memory_service.delete_memory(entry_id)
                    return True
        return False

    # DELETE /memories/{wingman_name}/all
    def clear_memories(self, wingman_name: str):
        wingman = self.tower.get_wingman_by_name(wingman_name)
        if wingman and hasattr(wingman, "persistent_memory_service") and wingman.persistent_memory_service:
            wingman.persistent_memory_service.clear_collection()
            self.printr.toast(f"All memories cleared for {wingman_name}.")
            return True
        return False

    # POST /memories/{wingman_name}/test-extraction
    async def test_memory_extraction(
        self,
        wingman_name: str,
        messages: list[dict] = Body(...),
    ):
        """Test memory extraction with a canned conversation.

        Send a list of messages like:
        [
            {"role": "user", "content": "I was born in 1986."},
            {"role": "assistant", "content": "Noted! I'll remember that."},
            {"role": "user", "content": "I fly a Constellation Taurus."},
            ...
        ]

        Returns the raw extraction result (facts + summary) without storing anything.
        """
        wingman = self.tower.get_wingman_by_name(wingman_name)
        if not wingman or not hasattr(wingman, "ensure_memory_initialized"):
            raise HTTPException(404, f"Wingman '{wingman_name}' not found")

        wingman.ensure_memory_initialized()
        svc = wingman.persistent_memory_service
        if not svc:
            raise HTTPException(400, f"Persistent memory not enabled for '{wingman_name}'")

        from services.file import get_prompt

        # Format messages the same way extract_memories does
        text_parts = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if content and role in ("user", "assistant"):
                text_parts.append(f"{role}: {content}")

        if not text_parts:
            raise HTTPException(400, "No valid user/assistant messages provided")

        from services.skill_local_ai import SamplingPreset

        conversation_text = "\n".join(text_parts)
        system_prompt = get_prompt("extract-memories")

        # Call the support model (sync, run in thread)
        result = await asyncio.to_thread(
            svc.local_ai_service.support,
            text=conversation_text,
            system_prompt=system_prompt,
            preset=SamplingPreset.PRECISE,
        )

        if not result or not result.text:
            return {"raw_response": None, "parsed": None, "error": "No response from support model"}

        # Parse JSON (with repair for small-model quirks)
        parsed = svc._parse_json_response(result.text)

        return {
            "raw_response": result.text,
            "parsed": parsed,
            "message_count": len(messages),
            "conversation_length": len(conversation_text),
        }
