"""Capture through supervised workers; device loss never submits partial speech."""
import asyncio
from os import path
from threading import Event, RLock, Thread
import io
import numpy
import soundfile
import speech_recognition as sr
from scipy.signal import butter, filtfilt
from api.enums import CommandTag, LogType
from services import audio_backend as sounddevice
from services.printr import Printr
from services.file import get_writable_dir

RECORDING_PATH = "audio_output"
RECORDING_FILE = "recording.wav"
CONTINUOUS_RECORDING_FILE = "continuous_recording.wav"


class WorkerMicrophone(sr.AudioSource):
    """PTT and recognition share a backend, with no cross-library device indices."""
    def __init__(self, rate=16000):
        self.SAMPLE_RATE, self.SAMPLE_WIDTH, self.CHUNK = rate, 2, 1024
        self.stream = None
        self.device_stream = None

    def __enter__(self):
        self.device_stream = sounddevice.RawInputStream(samplerate=self.SAMPLE_RATE, channels=1, dtype="int16")
        try:
            self.device_stream.start()
        except Exception:
            self.device_stream.close()
            raise
        self.stream = self
        return self

    def read(self, frames):
        return self.device_stream.read(frames)[0]

    def __exit__(self, *args):
        if self.device_stream:
            self.device_stream.close()
        self.stream = None


class AudioRecorder:
    def __init__(self, on_speech_recorded, samplerate=16000, channels=1):
        self.printr = Printr()
        self.on_speech_recorded = on_speech_recorded
        self.file_path = path.join(get_writable_dir(RECORDING_PATH), RECORDING_FILE)
        self.samplerate, self.channels = samplerate, channels
        self.is_recording = False
        self.recording_data = []
        self.recstream = None
        self.va_settings = None
        self.event_loop = None
        self.lock = RLock()
        self.is_listening_continuously = False
        self.valid_mic = True
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = False
        self._listen_stop = Event()
        self._listen_thread = None
        self._source = None
        self._generation = 0
        self._ptt_generation = 0
        self._recording_frames = 0

    def _log(self, text, wingman_name=None, tag=None):
        values = dict(color=LogType.INFO, source_name=wingman_name, command_tag=tag)
        if self.event_loop and self.event_loop.is_running():
            asyncio.run_coroutine_threadsafe(self.printr.print_async(text, **values), self.event_loop)
        else:
            self.printr.print(text, server_only=True, **values)

    def update_input_stream(self):
        with self.lock:
            self._ptt_generation += 1
            if self.recstream:
                self.recstream.close()
            self.recstream = None
            self.is_recording = False
            self.recording_data = []
            self._recording_frames = 0
        return True  # Open streams only when capture is requested.

    def start_recording(self, wingman_name):
        with self.lock:
            if self.is_recording:
                return
            self.recording_data = []
            self._recording_frames = 0
            try:
                self._ptt_generation += 1
                generation = self._ptt_generation
                self.recstream = sounddevice.InputStream(callback=lambda *args: self._capture(generation, *args),
                    channels=self.channels, samplerate=self.samplerate)
                self.is_recording = True
                self.recstream.start()
                self.valid_mic = True
            except Exception as exc:
                self.update_input_stream()
                self.valid_mic = False
                sounddevice.supervisor.report("input", f"recovering ({exc}); press push-to-talk again when ready")
                return
        self._log(f"Recording started ({wingman_name})", wingman_name, CommandTag.RECORDING_STARTED)

    def _capture(self, generation, indata, frames, _time, _status):
        with self.lock:
            if self.is_recording and generation == self._ptt_generation:
                if self._recording_frames + frames > self.samplerate * 120:
                    self.recstream.invalidate()
                    return
                self.recording_data.append(indata.copy())
                self._recording_frames += frames

    def stop_recording(self, wingman_name):
        with self.lock:
            stream = self.recstream
            self._ptt_generation += 1
            self.is_recording = False
            self.recstream = None
            chunks, self.recording_data = self.recording_data, []
            self._recording_frames = 0
            if not stream:
                return None
            failed = stream.failed or stream.closed
            stream.close()
        self._log(f"Recording stopped ({wingman_name})", wingman_name, CommandTag.RECORDING_STOPPED)
        if failed or not chunks:
            return None
        data = numpy.concatenate(chunks)
        if len(data) / self.samplerate < 0.15:
            return None
        soundfile.write(self.file_path, data, self.samplerate)
        return self.file_path

    def contains_speech(self, audio_bytes, energy_threshold):
        data, rate = soundfile.read(io.BytesIO(audio_bytes))
        if len(data) < 32:
            return False, 0
        b, a = butter(5, [85 / (rate / 2), 500 / (rate / 2)], btype="band")
        filtered = filtfilt(b, a, data)
        energy = numpy.sqrt(numpy.mean(filtered ** 2))
        return energy > energy_threshold, energy

    def adjust_for_ambient_noise(self):
        self._calibrate = True

    def start_continuous_listening(self, va_settings):
        self.va_settings = va_settings
        if self.is_listening_continuously:
            return
        self.is_listening_continuously = True
        self._generation += 1
        generation = self._generation
        stop = self._listen_stop = Event()

        def listen():
            attempts = 0
            while not stop.is_set():
                source = WorkerMicrophone(self.samplerate)
                self._source = source
                try:
                    with source:
                        sounddevice.supervisor.report("capture", "ready")
                        if getattr(self, "_calibrate", False):
                            self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                            self._calibrate = False
                        attempts = 0
                        while not stop.is_set() and generation == self._generation:
                            try:
                                audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=60)
                            except sr.WaitTimeoutError:
                                continue
                            if stop.is_set() or not self.capture_valid(generation):
                                break
                            wav = audio.get_wav_data()
                            speech, _ = self.contains_speech(wav, self.va_settings.energy_threshold)
                            if speech and not stop.is_set():
                                file_path = path.join(get_writable_dir(RECORDING_PATH), CONTINUOUS_RECORDING_FILE)
                                with open(file_path, "wb") as handle:
                                    handle.write(wav)
                                if generation == self._generation and not stop.is_set():
                                    self.on_speech_recorded(file_path)
                except Exception as exc:
                    if not stop.is_set():
                        sounddevice.supervisor.report("capture", f"recovering ({exc})")
                        sounddevice.supervisor.wake.set()
                        stop.wait((1, 2, 5, 10)[min(attempts, 3)])
                        attempts += 1
                finally:
                    if self._source is source:
                        self._source = None

        self._listen_thread = Thread(target=listen, name="voice-capture", daemon=True)
        self._listen_thread.start()

    def stop_continuous_listening(self):
        self.is_listening_continuously = False
        self._generation += 1
        self._listen_stop.set()
        if self._source and self._source.device_stream:
            self._source.device_stream.close()

    def capture_valid(self, generation):
        source = self._source
        return (generation == self._generation and self.is_listening_continuously
                and source is not None and source.device_stream is not None
                and not source.device_stream.failed and not source.device_stream.closed)

    def close(self):
        self.stop_continuous_listening()
        self.update_input_stream()
