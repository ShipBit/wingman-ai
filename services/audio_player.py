import io
from pydub import AudioSegment
from pydub.playback import play


class AudioPlayer:
    def stream(self, stream: bytes):
        # Convert the binary response content to a byte stream
        byte_stream = io.BytesIO(stream)
        # Read the audio data from the byte stream
        audio = AudioSegment.from_file(byte_stream, format="mp3")
        play(audio)

    def play(self, filename: str):
        audio = None
        if filename.endswith(".wav"):
            audio = AudioSegment.from_wav(filename)
        elif filename.endswith(".mp3"):
            audio = AudioSegment.from_mp3(filename)

        if audio:
            play(audio)
