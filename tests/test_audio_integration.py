"""Core settings/provider contracts, without starting Core or using hardware."""
import asyncio
import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, AsyncMock, patch
import yaml

from api.interface import AudioSettings, AudioDeviceSettings, SettingsConfig, SoundConfig
from services.settings_service import SettingsService
from services.pub_sub import PubSub
from services import audio_backend as backend
from providers.elevenlabs import ElevenLabs


class SettingsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = object.__new__(SettingsService)
        config = SettingsConfig.model_validate(yaml.safe_load(Path("templates/configs/settings.yaml").read_text()))
        config.audio = AudioSettings(input=AudioDeviceSettings(name="Missing mic", hostapi=0))
        self.service.config_manager = SimpleNamespace(settings_config=config, save_settings_config=Mock())
        self.service.settings = config
        self.service.converted_audio_settings = True
        self.service.printr = Mock()
        self.service.settings_events = PubSub()
        self.service.config_service = SimpleNamespace(tower=SimpleNamespace(wingmen=[]))
        for provider in ("whispercpp", "fasterwhisper", "xvasynth", "pocket_tts"):
            setattr(self.service, provider, Mock())

    async def test_get_does_not_replace_saved_missing_identity(self):
        with patch.object(backend, "query_devices", return_value=[]):
            result = self.service.get_settings()
        self.assertIsNone(result.audio.input)
        self.assertEqual("Missing mic", self.service.settings.audio.input.name)
        self.service.config_manager.save_settings_config.assert_not_called()

    async def test_changing_output_preserves_temporarily_missing_microphone(self):
        device = {"index": 3, "name": "Speakers", "hostapi": 0,
                  "max_input_channels": 0, "max_output_channels": 2}
        with patch.object(backend, "query_devices", side_effect=lambda index=None: [device] if index is None else device), patch.object(backend.supervisor, "configure") as configure:
            incoming = self.service.get_settings()
            incoming.audio.output = 3
            await self.service.save_settings(incoming)
        self.assertEqual("Missing mic", self.service.settings.audio.input.name)
        self.assertEqual("Speakers", self.service.settings.audio.output.name)
        configure.assert_called_once()
        self.assertEqual("Missing mic", configure.call_args.args[0].input.name)

    async def test_unrelated_settings_save_does_not_clear_missing_preference(self):
        with patch.object(backend, "query_devices", return_value=[]), patch.object(backend.supervisor, "configure") as configure:
            incoming = self.service.get_settings()
            incoming.debug_mode = not incoming.debug_mode
            await self.service.save_settings(incoming)
        configure.assert_not_called()
        self.assertEqual("Missing mic", self.service.settings.audio.input.name)


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_elevenlabs_stream_uses_core_player_and_closes_response(self):
        provider = object.__new__(ElevenLabs)
        provider.api_key = "test"
        provider.printr = Mock()
        config = SimpleNamespace(model="eleven_turbo_v2", voice_settings=SimpleNamespace(
            stability=0.33, similarity_boost=0.5, style=0, use_speaker_boost=False))
        sound = SoundConfig(play_beep=False, play_beep_apollo=False, effects=[], volume=1)
        response = Mock(status_code=200)
        response.raw.read.return_value = b"\x00\x00"
        player = Mock(stream_with_effects=AsyncMock())
        with patch("providers.elevenlabs.requests.post", return_value=response) as post:
            self.assertTrue(await provider._stream_audio_direct_v3("test", config, "voice", player, "Test", sound))
        player.stream_with_effects.assert_awaited_once()
        self.assertIs(sound, player.stream_with_effects.call_args.args[1])
        self.assertEqual(0.33, post.call_args.kwargs["json"]["voice_settings"]["stability"])
        response.close.assert_called_once()

    async def test_elevenlabs_device_failure_closes_response(self):
        provider = object.__new__(ElevenLabs)
        provider.api_key, provider.printr = "test", Mock()
        config = SimpleNamespace(model="eleven_v3", voice_settings=SimpleNamespace(
            stability=0.5, similarity_boost=0.5, style=0, use_speaker_boost=False))
        response = Mock(status_code=200)
        player = Mock(stream_with_effects=AsyncMock(side_effect=RuntimeError("device lost")))
        with patch("providers.elevenlabs.requests.post", return_value=response):
            with self.assertRaises(RuntimeError):
                await provider._stream_audio_direct_v3("test", config, "voice", player, "Test", Mock())
        response.close.assert_called_once()


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_mute_cancels_automatic_resume(self):
        from wingman_core import WingmanCore
        core = object.__new__(WingmanCore)
        core.was_listening_before_playback = True
        core.was_listening_before_ptt = True
        core._set_voice_recognition = Mock()
        core.start_voice_recognition(mute=True)
        self.assertFalse(core.was_listening_before_playback)
        self.assertFalse(core.was_listening_before_ptt)
        core._set_voice_recognition.assert_called_once_with(True, False)

    async def test_persistent_loop_is_available_during_profile_load(self):
        # Execute the actual startup function with services isolated. Importing
        # main itself would construct Core and write the user's configuration.
        tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
        function = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_main")
        from api.enums import CoreState
        events = []
        player = Mock(set_event_loop=lambda loop: events.append("loop"))
        async def load():
            self.assertEqual(["loop"], events)
            self.assertIs(recorder.event_loop, asyncio.get_running_loop())
            events.append("profile")
        recorder = SimpleNamespace(event_loop=None)
        core = SimpleNamespace(audio_player=player, audio_recorder=recorder, tower_errors=[], startup_errors=[],
            set_core_state=AsyncMock(), config_service=SimpleNamespace(migrate_configs=AsyncMock(), load_config=load),
            startup=AsyncMock(), process_events=AsyncMock())
        env = dict(asyncio=asyncio, core=core, CoreState=CoreState, system_manager=Mock(),
                   uvicorn=SimpleNamespace(Config=Mock(), Server=Mock(return_value=SimpleNamespace(serve=AsyncMock()))), app=Mock())
        exec(compile(ast.Module(body=[function], type_ignores=[]), "main.py", "exec"), env)
        await env["async_main"]("127.0.0.1", 49111, True)
        self.assertEqual(["loop", "profile"], events)
        await asyncio.sleep(0)


if __name__ == "__main__":
    unittest.main()
