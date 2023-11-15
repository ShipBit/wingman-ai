import io
from pydub import AudioSegment
from pydub.playback import play


class AudioPlayer:
    def __init__(self):
        pass

    def stream(self, stream):
        # Convert the binary response content to a byte stream
        byte_stream = io.BytesIO(stream)

        # Read the audio data from the byte stream
        audio = AudioSegment.from_file(byte_stream, format="mp3")

        play(audio)
