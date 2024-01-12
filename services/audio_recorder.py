from os import path
import numpy
import sounddevice
import soundfile
from api.enums import CommandTag, LogType
from services.printr import Printr
from services.file import get_writable_dir


RECORDING_PATH = "audio_output"
RECORDING_FILE: str = "recording.wav"

printr = Printr()


class AudioRecorder:
    def __init__(
        self,
        samplerate: int = 16000,
        channels: int = 1,
    ):
        self.file_path = path.join(get_writable_dir(RECORDING_PATH), RECORDING_FILE)
        self.samplerate = samplerate
        self.is_recording = False
        self.recording = None

        self.recstream = sounddevice.InputStream(
            callback=self.__handle_input_stream,
            channels=channels,
            samplerate=samplerate,
        )

    def __handle_input_stream(self, indata, _frames, _time, _status):
        if self.is_recording:
            if self.recording is None:
                self.recording = indata.copy()
            else:
                self.recording = numpy.concatenate((self.recording, indata.copy()))

    def start_recording(self, wingman_name: str):
        if self.is_recording:
            return

        self.recstream.start()
        self.is_recording = True
        printr.print(
            f"Recording started ({wingman_name})",
            source_name=wingman_name,
            command_tag=CommandTag.RECORDING_STARTED,
        )

    def stop_recording(self, wingman_name) -> None | str:
        self.recstream.stop()
        self.is_recording = False
        printr.print(
            f"Recording stopped ({wingman_name})",
            source_name=wingman_name,
            command_tag=CommandTag.RECORDING_STOPPED,
        )

        if self.recording is None:
            printr.print(
                f"Ignored empty recording ({wingman_name})",
                color=LogType.WARNING,
                source_name=wingman_name,
                command_tag=CommandTag.IGNORED_RECORDING,
            )
            return None
        if (len(self.recording) / self.samplerate) < 0.15:
            printr.print(
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
            printr.print(
                "Ignored empty recording",
                color=LogType.WARNING,
                source_name=wingman_name,
                command_tag=CommandTag.IGNORED_RECORDING,
            )
            return None
