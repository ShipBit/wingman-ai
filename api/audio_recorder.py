import numpy
import sounddevice
import soundfile


class AudioRecorder:
    def __init__(
        self, filename: str = "output.wav", samplerate: int = 44100, channels: int = 1
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

    def __handle_input_stream(self, indata, frames, time, status):
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
        print("Recording started")

    def stop_recording(self):
        self.recstream.stop()
        self.is_recording = False
        soundfile.write(self.filename, self.recording, self.samplerate)
        self.recording = None
        print("Recording stopped")
        return self.filename
