import os
import numpy
import sounddevice
import soundfile
from services.printr import Printr

RECORDING_PATH = "audio_output"
RECORDING_FILE: str = "recording.wav"

printr = Printr()


class AudioRecorder:
    def __init__(
        self,
        app_root_path: str,
        samplerate: int = 44100,
        channels: int = 1,
    ):
        self.recording_path: str = os.path.join(app_root_path, RECORDING_PATH)
        self.recording_file = os.path.join(self.recording_path, RECORDING_FILE)
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

    def start_recording(self):
        if self.is_recording:
            return

        self.recstream.start()
        self.is_recording = True
        printr.print("Recording started", tags="grey")

    def stop_recording(self) -> None | str:
        self.recstream.stop()
        self.is_recording = False
        printr.print("Recording stopped", tags="grey")

        if not os.path.exists("audio_output"):
            os.makedirs("audio_output")

        if self.recording is None:
            printr.print("Ignored empty recording", tags="warn")
            return None
        if (len(self.recording) / self.samplerate) < 0.15:
            printr.print("Recording was too short to be handled by the AI", tags="warn")
            return None

        try:
            soundfile.write(self.recording_file, self.recording, self.samplerate)
            self.recording = None
            return self.recording_file
        except IndexError:
            printr.print("Ignored empty recording", tags="warn")
            return None
