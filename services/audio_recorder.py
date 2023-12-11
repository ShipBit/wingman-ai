import os
import numpy
import sounddevice
import soundfile
from services.enums import LogType
from services.printr import Printr


printr = Printr()


class AudioRecorder:
    def __init__(
        self,
        filename: str = "audio_output/output.wav",
        samplerate: int = 44100,
        channels: int = 1,
    ):
        self.filename = filename
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
        printr.print("Recording started")

    def stop_recording(self) -> None | str:
        self.recstream.stop()
        self.is_recording = False
        printr.print("Recording stopped")

        if not os.path.exists("audio_output"):
            os.makedirs("audio_output")

        if self.recording is None:
            printr.print("Ignored empty recording", color=LogType.WARNING)
            return None
        if (len(self.recording) / self.samplerate) < 0.15:
            printr.print(
                "Recording was too short to be handled by the AI", color=LogType.WARNING
            )
            return None

        try:
            soundfile.write(self.filename, self.recording, self.samplerate)
            self.recording = None
            return self.filename
        except IndexError:
            printr.print("Ignored empty recording", color=LogType.WARNING)
            return None
