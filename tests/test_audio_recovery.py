"""Failure injection for routing, worker isolation, capture and playback."""

import asyncio
from concurrent.futures import Future
from copy import deepcopy
import io
import os
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

from api.interface import AudioSettings, AudioDeviceSettings, SoundConfig
from services import audio_backend as backend
from services.audio_worker import resolve, open_stream
from services.audio_player import AudioPlayer
from services.audio_recorder import AudioRecorder
from tools import managed_launch


def device(index, name, direction, hostapi=0):
    return dict(index=index, name=name, hostapi=hostapi, hostapi_name="MME",
                max_input_channels=int(direction == "input"), max_output_channels=int(direction == "output"),
                default_samplerate=48000)


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.mic = device(1, "Preferred", "input")
        self.other = device(2, "Default", "input")
        self.output = device(3, "Speakers", "output")
        self.snapshot = dict(devices=[self.mic, self.other, self.output], defaults=[2, 3])
        self.manager = backend.AudioSupervisor(probe=lambda: deepcopy(self.snapshot))
        self.manager.report = Mock()
        self.manager.reconcile()
        self.manager.configure({"input": backend.identity(self.mic)})

    def test_preferred_fallback_return_without_losing_preference(self):
        stream = Mock(direction="input")
        self.manager.streams.add(stream)
        self.snapshot["devices"].remove(self.mic)
        self.manager.reconcile()
        chosen, fallback = resolve(**{k: self.snapshot[k] for k in ("devices", "defaults")},
                                   preference=self.manager.preferences["input"], direction="input")
        self.assertEqual("Default", chosen["name"])
        self.assertTrue(fallback)
        stream.invalidate.assert_called_once()
        returned = dict(self.mic, index=9)
        self.snapshot["devices"].append(returned)
        self.manager.reconcile()
        chosen, fallback = resolve(self.snapshot["devices"], self.snapshot["defaults"],
                                   self.manager.preferences["input"], "input")
        self.assertEqual(9, chosen["index"])
        self.assertFalse(fallback)
        self.assertEqual("Preferred", self.manager.preferences["input"]["name"])

    def test_default_change_invalidates_only_affected_direction(self):
        self.manager.configure({})
        capture, playback = Mock(direction="input"), Mock(direction="output")
        self.manager.streams.update([capture, playback])
        self.snapshot["defaults"][0] = 1
        self.manager.reconcile()
        capture.invalidate.assert_called_once()
        playback.invalidate.assert_not_called()

    def test_no_devices_and_missing_default_do_not_pick_arbitrary_microphone(self):
        selected, _ = resolve([self.mic], [-1, -1], None, "input")
        self.assertIsNone(selected)
        self.snapshot = {"devices": [], "defaults": [-1, -1]}
        self.manager.reconcile()
        self.assertEqual("Preferred", self.manager.preferences["input"]["name"])

    def test_explicit_selection_overrides_pending_return(self):
        self.manager.configure({"input": backend.identity(self.other)})
        self.assertEqual("Default", self.manager.preferences["input"]["name"])
        self.manager.reconcile()
        self.assertEqual("Default", self.manager.preferences["input"]["name"])

    def test_duplicate_names_do_not_select_ambiguous_endpoint(self):
        duplicate = dict(self.mic, index=8)
        chosen, fallback = resolve([self.mic, duplicate, self.other], [2, -1],
                                   backend.identity(self.mic), "input")
        self.assertEqual(2, chosen["index"])
        self.assertTrue(fallback)

    def test_probe_failure_preserves_preferences(self):
        self.manager.probe = Mock(side_effect=backend.AudioUnavailable("driver busy"))
        with self.assertRaises(backend.AudioUnavailable):
            self.manager.reconcile()
        self.assertEqual("Preferred", self.manager.preferences["input"]["name"])


class WorkerTests(unittest.TestCase):
    def test_normal_capture_close_does_not_report_device_failure(self):
        reading, released = threading.Event(), threading.Event()
        fake = Mock()
        def call(operation, **kwargs):
            if operation == "read":
                reading.set()
                released.wait(1)
                raise backend.AudioUnavailable("worker closed")
        fake.call.side_effect = call
        fake.close.side_effect = released.set
        with patch.object(backend, "Worker", return_value=fake), patch.object(backend.supervisor, "report") as report:
            stream = backend.InputStream(callback=Mock())
            stream.start()
            self.assertTrue(reading.wait(1))
            stream.close()
            stream.thread.join(timeout=2)
        self.assertFalse(stream.failed)
        report.assert_not_called()

    def test_start_failure_also_tries_system_fallback(self):
        preferred, fallback = device(1, "Preferred", "input"), device(2, "Default", "input")
        sd = Mock()
        sd.PortAudioError = RuntimeError
        sd.query_devices.return_value = [preferred, fallback]
        sd.query_hostapis.return_value = [{"name": "MME"}]
        sd.default.device = [2, -1]
        broken, working = Mock(), Mock()
        broken.start.side_effect = RuntimeError("MME error 6")
        sd.RawInputStream.side_effect = [broken, working]
        result = open_stream(sd, dict(direction="input", preference=backend.identity(preferred), samplerate=16000, channels=1))
        self.assertIs(working, result[0])
        self.assertTrue(result[4])
        broken.close.assert_called_once()
        working.start.assert_called_once()

    def test_busy_preferred_device_falls_back_and_native_rate_is_probed(self):
        preferred = device(1, "Preferred", "input")
        fallback = device(2, "Default", "input")
        sd = Mock()
        sd.PortAudioError = RuntimeError
        sd.query_devices.return_value = [preferred, fallback]
        sd.query_hostapis.return_value = [{"name": "MME"}]
        sd.default.device = [2, -1]
        def check(**kwargs):
            if kwargs["samplerate"] == 16000:
                raise RuntimeError("Unsupported rate")
        sd.check_input_settings.side_effect = check
        sd.RawInputStream.side_effect = [RuntimeError("In use"), Mock()]
        stream, rate, channels, chosen, fell_back = open_stream(sd, dict(
            direction="input", preference=backend.identity(preferred), samplerate=16000, channels=1))
        self.assertEqual(48000, rate)
        self.assertEqual(2, chosen["index"])
        self.assertTrue(fell_back)

    def test_hung_worker_is_killed_with_bounded_wait(self):
        worker = object.__new__(backend.Worker)
        worker.closed = threading.Event()
        worker.requests = queue.Queue(maxsize=1)
        worker.process = Mock()
        worker.process.poll.return_value = None
        with self.assertRaisesRegex(backend.AudioUnavailable, "did not respond"):
            worker.call("read", timeout=0.02, frames=1024)
        worker.process.kill.assert_called_once()
        self.assertTrue(worker.closed.is_set())

    def test_invalidated_stream_cannot_send_stale_audio(self):
        fake = Mock()
        with patch.object(backend, "Worker", return_value=fake):
            stream = backend.RawOutputStream(samplerate=16000, channels=1, dtype="int16")
        stream.invalidate()
        fake.reset_mock()
        with self.assertRaises(backend.AudioUnavailable):
            stream.write(b"\x00\x00")
        fake.call.assert_not_called()

    def test_paused_output_resumes_without_sending_to_stopped_worker(self):
        fake = Mock()
        with patch.object(backend, "Worker", return_value=fake):
            stream = backend.RawOutputStream(samplerate=16000, channels=1, dtype="int16")
            stream.start()
            stream.stop()
            fake.reset_mock()
            done = threading.Event()
            def write():
                stream.write(b"\x00\x00")
                done.set()
            thread = threading.Thread(target=write, daemon=True)
            thread.start()
            self.assertFalse(done.wait(0.03))
            fake.call.assert_not_called()
            stream.start()
            self.assertTrue(done.wait(1))
            stream.close()
            thread.join(timeout=1)

    def test_final_output_block_is_drained_before_worker_closes(self):
        fake = Mock()
        fake.call.return_value = None
        def callback(data, frames, *args):
            data.fill(0.25)
            raise backend.CallbackStop
        with patch.object(backend, "Worker", return_value=fake):
            stream = backend.OutputStream(samplerate=16000, channels=1, callback=callback)
            stream.start()
            stream.thread.join(timeout=2)
        operations = [c.args[0] for c in fake.call.call_args_list]
        self.assertEqual("stop", operations[-1])
        self.assertIn("write", operations)
        self.assertTrue(stream.closed)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch("services.audio_recorder.Printr", return_value=Mock()), patch(
                "services.audio_recorder.get_writable_dir", return_value=self.temp.name):
            self.recorder = AudioRecorder(Mock())
        self.addCleanup(self.recorder.close)

    def test_construction_does_not_open_microphone(self):
        self.assertIsNone(self.recorder.recstream)
        self.assertFalse(self.recorder.is_recording)

    def test_interrupted_ptt_discards_audio_and_requires_new_press(self):
        stream = Mock(failed=True, closed=False)
        self.recorder.recstream = stream
        self.recorder.is_recording = True
        self.recorder.recording_data = [np.zeros((16000, 1))]
        self.assertIsNone(self.recorder.stop_recording("Test"))
        self.assertFalse(self.recorder.is_recording)
        self.assertFalse(Path(self.recorder.file_path).exists())

    def test_completed_recording_written_only_after_release(self):
        self.recorder.recstream = Mock(failed=False, closed=False)
        self.recorder.recording_data = [np.zeros((4000, 1))]
        self.assertEqual(self.recorder.file_path, self.recorder.stop_recording("Test"))
        self.assertTrue(Path(self.recorder.file_path).exists())

    def test_stale_callback_cannot_contaminate_new_recording(self):
        self.recorder.is_recording = True
        self.recorder._ptt_generation = 2
        self.recorder._capture(1, np.zeros((1024, 1)), 1024, None, None)
        self.assertEqual([], self.recorder.recording_data)

    def test_muting_invalidates_pending_transcription(self):
        self.recorder.is_listening_continuously = True
        self.recorder._source = SimpleNamespace(device_stream=Mock(failed=False, closed=False))
        generation = self.recorder._generation
        self.assertTrue(self.recorder.capture_valid(generation))
        self.recorder.stop_continuous_listening()
        self.assertFalse(self.recorder.capture_valid(generation))


class PlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.started, self.finished = AsyncMock(), AsyncMock()
        self.player = AudioPlayer(asyncio.Queue(), self.started, self.finished)
        self.player.set_event_loop(asyncio.get_running_loop())
        self.config = SoundConfig(effects=[], play_beep=False, play_beep_apollo=False, volume=1)

    async def test_output_open_failure_releases_busy_flag_once(self):
        with patch.object(backend, "RawOutputStream", side_effect=backend.AudioUnavailable("unplugged")), patch.object(backend.supervisor, "report"):
            await self.player.stream_with_effects(lambda b: 0, self.config, "Test")
        self.assertFalse(self.player.is_playing)
        self.started.assert_awaited_once()
        self.finished.assert_awaited_once()
        await self.player.stop_playback()
        self.finished.assert_awaited_once()

    async def test_old_completion_cannot_clear_new_playback(self):
        old = await self.player._begin_playback("Old")
        new = await self.player._begin_playback("New")
        await self.player._finish_playback(old, "Old")
        self.assertTrue(self.player.is_playing)
        await self.player._finish_playback(new, "New")
        self.assertFalse(self.player.is_playing)
        self.assertEqual(2, self.finished.await_count)

    async def test_buffered_failure_completes_and_next_reply_can_play(self):
        with patch.object(self.player, "start_playback", side_effect=backend.AudioUnavailable("gone")), patch.object(backend.supervisor, "report"):
            await self.player.play_with_effects((np.zeros(160), 16000), self.config, "Test")
            for _ in range(30):
                if self.finished.await_count:
                    break
                await asyncio.sleep(0.01)
        self.assertFalse(self.player.is_playing)
        self.finished.assert_awaited_once()
        token = await self.player._begin_playback("Next")
        self.assertTrue(self.player.is_playing)
        await self.player._finish_playback(token, "Next")

    async def test_stream_provider_failure_still_finishes(self):
        stream = Mock(closed=False)
        with patch.object(backend, "RawOutputStream", return_value=stream):
            with self.assertRaises(ValueError):
                await self.player.stream_with_effects(Mock(side_effect=ValueError("provider")), self.config, "Test")
        stream.close.assert_called_once()
        self.finished.assert_awaited_once()


@unittest.skipUnless(os.name == "nt", "Windows shortcut/venv integration")
class LauncherTests(unittest.TestCase):
    def test_repeated_launch_reuses_existing_client(self):
        with patch.object(managed_launch, "powershell", return_value={"Id": 123, "Path": str(managed_launch.CLIENT), "MainWindowHandle": 0}), patch.object(managed_launch.subprocess, "Popen") as start:
            self.assertFalse(managed_launch.open_client())
        start.assert_not_called()

    def test_unrelated_core_is_not_reused_or_stopped(self):
        with patch.object(managed_launch, "port_owner", return_value={"CommandLine": "WingmanAiCore.exe"}), patch.object(managed_launch.subprocess, "Popen") as start:
            with self.assertRaisesRegex(RuntimeError, "Another Core"):
                managed_launch.launch()
        start.assert_not_called()

    def test_absolute_checkout_identity_is_required(self):
        command = f'"{managed_launch.PYTHON}" "{managed_launch.ROOT / "main.py"}" --sidecar'
        self.assertTrue(managed_launch.owns_core({"CommandLine": command}))
        self.assertFalse(managed_launch.owns_core({"CommandLine": "python main.py"}))

    def test_windows_venv_base_interpreter_is_recognized(self):
        config = (managed_launch.ROOT / ".venv-core/pyvenv.cfg").read_text()
        interpreter = next(line.split("=", 1)[1].strip() for line in config.splitlines() if line.startswith("executable ="))
        command = f'"{interpreter}" "{managed_launch.ROOT / "main.py"}" --host 127.0.0.1 --port 49111 --sidecar'
        self.assertTrue(managed_launch.owns_core({"CommandLine": command}))
        self.assertFalse(managed_launch.owns_core({"CommandLine": f'"{interpreter}" -c "{managed_launch.ROOT / "main.py"}"'}))


if __name__ == "__main__":
    unittest.main()
