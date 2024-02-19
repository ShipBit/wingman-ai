from datetime import datetime
from os import path
import numpy
import sounddevice
import soundfile
from api.enums import CommandTag, LogType
from api.interface import VoiceActivationSettings
from services.printr import Printr
from services.file import get_writable_dir
from services.pub_sub import PubSub


RECORDING_PATH = "audio_output"
RECORDING_FILE: str = "recording.wav"
CONTINUOUS_RECORDING_FILE: str = "continuous_recording.wav"


class AudioRecorder:
    def __init__(
        self,
        settings: VoiceActivationSettings,
        samplerate: int = 16000,
        channels: int = 1,
    ):
        self.printr = Printr()
        self.settings = settings
        self.file_path = path.join(get_writable_dir(RECORDING_PATH), RECORDING_FILE)
        self.samplerate = samplerate
        self.channels = channels
        self.is_recording = False
        self.recording = None
        self.continuous_listening = False
        self.continuous_recording = None
        self.recstream = None
        self.recording_events = PubSub()
        self.start_time = None
        self.last_sound_time = None

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
        # Handling push to talk
        if self.is_recording:
            if self.continuous_recording is None:
                self.continuous_recording = indata.copy()
            else:
                self.continuous_recording = numpy.concatenate(
                    (self.continuous_recording, indata)
                )

        # Handling continuous listening
        if self.continuous_listening:
            rms = numpy.sqrt(numpy.mean(indata**2))
            if rms > self.settings.threshold:
                if self.start_time is None:
                    self.start_time = datetime.now()
                    self.continuous_recording = indata.copy()
                else:
                    self.continuous_recording = numpy.concatenate(
                        (self.continuous_recording, indata)
                    )
                self.last_sound_time = datetime.now()
            elif (
                self.start_time is not None
                and (datetime.now() - self.last_sound_time).total_seconds()
                > self.settings.silence_threshold
            ):
                if (
                    datetime.now() - self.start_time
                ).total_seconds() >= self.settings.min_speech_length:
                    self.save_continuous_recording()
                self.start_time = None
                self.continuous_recording = None

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

        if self.recording is None:
            self.printr.print(
                f"Ignored empty recording ({wingman_name})",
                color=LogType.WARNING,
                source_name=wingman_name,
                command_tag=CommandTag.IGNORED_RECORDING,
            )
            return None
        if (len(self.recording) / self.samplerate) < 0.15:
            self.printr.print(
                f"Recording was too short to be handled by {wingman_name}",
                color=LogType.WARNING,
                source_name=wingman_name,
                command_tag=CommandTag.IGNORED_RECORDING,
            )
            return None

        try:
            soundfile.write(self.file_path, self.recording, self.samplerate)
            self.recording = None
            return self.file_path
        except IndexError:
            self.printr.print(
                "Ignored empty recording",
                color=LogType.WARNING,
                source_name=wingman_name,
                command_tag=CommandTag.IGNORED_RECORDING,
            )
            return None

    def save_continuous_recording(self):
        file_path = path.join(
            get_writable_dir(RECORDING_PATH), CONTINUOUS_RECORDING_FILE
        )
        soundfile.write(file_path, self.continuous_recording, self.samplerate)
        self.recording_events.publish("speech_recorded", file_path)

    def start_continuous_listening(self):
        self.continuous_listening = True
        self.recstream.start()

    def stop_continuous_listening(self):
        self.continuous_listening = False
        # Final check to save any recordings that meet criteria upon stopping
        if self.start_time is not None:
            if (
                datetime.now() - self.start_time
            ).total_seconds() >= self.settings.min_speech_length:
                self.save_continuous_recording()
        self.recstream.stop()
        self.start_time = None
        self.continuous_recording = None
