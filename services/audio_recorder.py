import numpy
import sounddevice
import soundfile
from services.printr import Printr
from services.file_creator import FileCreator

RECORDING_PATH = "audio_output"
RECORDING_FILE: str = "recording.wav"

printr = Printr()


class AudioRecorder(FileCreator):
    def __init__(
        self,
        app_root_dir: str,
        samplerate: int = 44100,
        channels: int = 1,
    ):
        super().__init__(app_root_dir, RECORDING_PATH)
        self.file_path = self.get_full_file_path(RECORDING_FILE)

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

        if self.recording is None:
            printr.print("Ignored empty recording", tags="warn")
            return None
        if (len(self.recording) / self.samplerate) < 0.15:
            printr.print("Recording was too short to be handled by the AI", tags="warn")
            return None

        try:
            soundfile.write(self.file_path, self.recording, self.samplerate)
            self.recording = None
            return self.file_path
        except IndexError:
            printr.print("Ignored empty recording", tags="warn")
            return None
