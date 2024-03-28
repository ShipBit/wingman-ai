from os import path
from threading import Lock
import time
from typing import Callable
import io
import numpy
import sounddevice
import soundfile
import speech_recognition as sr
from speech_recognition import AudioData
from scipy.signal import butter, filtfilt
from api.enums import CommandTag, LogType
from services.printr import Printr
from services.file import get_writable_dir


RECORDING_PATH = "audio_output"
RECORDING_FILE: str = "recording.wav"
CONTINUOUS_RECORDING_FILE: str = "continuous_recording.wav"


class AudioRecorder:
    def __init__(
        self,
        on_speech_recorded: Callable[[str], None],
        samplerate: int = 16000,
        channels: int = 1,
    ):
        self.printr = Printr()
        self.on_speech_recorded = on_speech_recorded
        self.file_path = path.join(get_writable_dir(RECORDING_PATH), RECORDING_FILE)
        self.samplerate = samplerate
        self.channels = channels
        self.is_recording = False
        self.recording_data = None
        self.recstream = None

        self.lock = Lock()
        self.is_listening_continuously = False
        self.microphone = sr.Microphone(sample_rate=samplerate)
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = (
            False  # seems to be causing super long recordings / threading issues
        )
        self.stop_function = None
        # default devices are fixed once this is called
        # so this methods needs to be called every time a new device is configured
        self.update_input_stream()

    def update_input_stream(self):
        if self.recstream is not None:
            self.recstream.close()

        self.recstream = sounddevice.InputStream(
            callback=self.__handle_input_stream,
            channels=self.channels,
            samplerate=self.samplerate,
        )

    def __handle_input_stream(self, indata, _frames, _time, _status):
        if self.is_recording:
            if self.recording_data is None:
                self.recording_data = indata.copy()
            else:
                self.recording_data = numpy.concatenate((self.recording_data, indata))

    # Push to talk:

    def start_recording(self, wingman_name: str):
        if self.is_recording:
            return

        self.recstream.start()
        self.is_recording = True
        self.printr.print(
            f"Recording started ({wingman_name})",
            source_name=wingman_name,
            command_tag=CommandTag.RECORDING_STARTED,
        )

    def stop_recording(self, wingman_name) -> None | str:
        self.recstream.stop()
        self.is_recording = False
        self.printr.print(
            f"Recording stopped ({wingman_name})",
            source_name=wingman_name,
            command_tag=CommandTag.RECORDING_STOPPED,
        )

        if self.recording_data is None:
            self.printr.print(
                f"Ignored empty recording ({wingman_name})",
                color=LogType.WARNING,
                source_name=wingman_name,
                command_tag=CommandTag.IGNORED_RECORDING,
            )
            return None
        if (len(self.recording_data) / self.samplerate) < 0.15:
            self.printr.print(
                f"Recording was too short to be handled by {wingman_name}",
                color=LogType.WARNING,
                source_name=wingman_name,
                command_tag=CommandTag.IGNORED_RECORDING,
            )
            return None

        try:
            soundfile.write(self.file_path, self.recording_data, self.samplerate)
            self.recording_data = None
            return self.file_path
        except IndexError:
            self.printr.print(
                "Ignored empty recording",
                color=LogType.WARNING,
                source_name=wingman_name,
                command_tag=CommandTag.IGNORED_RECORDING,
            )
            return None

    # Continuous listening:

    # def determine_length(self, audio_data: bytes):
    #     with io.BytesIO(audio_data) as audio_file:
    #         with wave.open(audio_file, "rb") as wave_file:
    #             num_frames = wave_file.getnframes()
    #             frame_rate = wave_file.getframerate()
    #             duration_in_seconds = num_frames / float(frame_rate)
    #     return duration_in_seconds
    
    
    def audio_contains_spoken_words(self, audio_bytes, lowcut=85, highcut=250, energy_threshold=0.01):
        def butter_bandpass(lowcut, highcut, fs, order=5):
            nyq = 0.5 * fs
            low = lowcut / nyq
            high = highcut / nyq
            b, a = butter(order, [low, high], btype='band')
            return b, a

        def butter_bandpass_filter(data, lowcut, highcut, fs, order=5):
            b, a = butter_bandpass(lowcut, highcut, fs, order=order)
            y = filtfilt(b, a, data)
            return y

        audio_data, sample_rate = soundfile.read(io.BytesIO(audio_bytes))
        filtered_audio = butter_bandpass_filter(audio_data, lowcut, highcut, sample_rate)
        rms_energy = numpy.sqrt(numpy.mean(filtered_audio ** 2))
        if rms_energy > energy_threshold:
            return True
        return False

    def __handle_continuous_listening(self, _recognizer, audio: AudioData):
        audio_bytes = audio.get_wav_data()

        # duration check
        # duration_in_seconds = self.determine_length(audio_bytes)
        # if duration_in_seconds < 1:
        #     self.printr.print(
        #         "Skipped very short recording during VA",
        #         color=LogType.WARNING,
        #         command_tag=CommandTag.IGNORED_RECORDING,
        #     )
        #     return

        # voice frequency check
        if not self.audio_contains_spoken_words(audio_bytes=audio_bytes):
            self.printr.print(
                "Skipped recording without detected voice during VA",
                color=LogType.WARNING,
                command_tag=CommandTag.IGNORED_RECORDING,
            )
            return

        file_path = path.join(
            get_writable_dir(RECORDING_PATH), CONTINUOUS_RECORDING_FILE
        )
        with open(file_path, "wb") as audio_file:
            audio_file.write(audio_bytes)

        if callable(self.on_speech_recorded):
            self.on_speech_recorded(file_path)

    def adjust_for_ambient_noise(self):
        with self.lock:
            try:
                with self.microphone as mic:
                    self.recognizer.adjust_for_ambient_noise(source=mic, duration=1.5)
                    self.printr.print(
                        "Microphone adjusted for ambient noise.",
                        color=LogType.INFO,
                        server_only=True,
                    )

            except Exception as e:
                self.printr.print(
                    f"Error adjusting for ambient noise: {e}",
                    server_only=True,
                    color=LogType.ERROR,
                )

    def start_continuous_listening(self):
        while True:
            with self.lock:
                if not self.is_listening_continuously and self.stop_function is None:
                    self.is_listening_continuously = True
                    break
            time.sleep(0.1)

        def safe_start():
            with self.lock:
                if self.is_listening_continuously:
                    self.stop_function = self.recognizer.listen_in_background(
                        self.microphone, self.__handle_continuous_listening
                    )
                    self.printr.print(
                        "Continous voice recognition started.",
                        color=LogType.INFO,
                        server_only=True,
                    )

        safe_start()

    def stop_continuous_listening(self):
        if self.is_listening_continuously and self.stop_function:
            self.stop_function(wait_for_stop=True)
            self.stop_function = None
            self.is_listening_continuously = False
            time.sleep(0.1)  # Time might need adjustment based on testing.
            self.printr.print(
                "Continous voice recognition stopped.",
                color=LogType.INFO,
                server_only=True,
            )
