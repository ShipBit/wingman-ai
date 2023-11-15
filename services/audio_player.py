import io
import os
from pydub import AudioSegment
from pydub.playback import play
from scipy.io import wavfile
import scipy.signal
import numpy


class AudioPlayer:
    def stream(self, stream: bytes):
        audio = self.get_audio_from_stream(stream)
        play(audio)

    def stream_with_effects(self, stream: bytes):
        audio = self.get_audio_from_stream(stream)
        audio.export("output_generated.wav", format="wav")
        audio = self.add_radio_effect_with_beep(
            "output_generated.wav", delete_source=True
        )
        play(audio)

    def get_audio_from_stream(self, stream: bytes) -> AudioSegment:
        byte_stream = io.BytesIO(stream)
        audio = AudioSegment.from_file(byte_stream, format="mp3")
        return audio

    def play(self, filename: str):
        audio = None
        if filename.endswith(".wav"):
            audio = AudioSegment.from_wav(filename)
        elif filename.endswith(".mp3"):
            audio = AudioSegment.from_mp3(filename)

        if audio:
            play(audio)

    def add_radio_effect_with_beep(self, filename: str, delete_source: bool = False):
        file, extension = os.path.splitext(filename)
        wav_file = file + ".wav"

        if extension == ".mp3":
            sound = AudioSegment.from_mp3(filename)
            sound.export(wav_file, format="wav")

        samplerate, data = wavfile.read(wav_file)
        nyquist = 0.5 * samplerate
        low, high = 500 / nyquist, 5000 / nyquist

        b, a = scipy.signal.butter(5, [low, high], btype="band")
        filtered = scipy.signal.lfilter(b, a, data)
        filtered_wav = file + "_filtered.wav"
        wavfile.write(filtered_wav, samplerate, filtered.astype(numpy.int16))
        filtered_sound = AudioSegment.from_wav(filtered_wav)

        noise = AudioSegment.from_mp3("audio_samples/noise.wav")
        noise_sound = noise - 30

        # Calculate the durations
        main_duration = len(filtered_sound)

        # Loop the noise until it matches or exceeds the duration of the main audio
        looped_noise = noise_sound
        while len(looped_noise) < main_duration:
            looped_noise += noise_sound

        # If looped noise is longer than the main audio, cut it down to the correct length
        if len(looped_noise) > main_duration:
            looped_noise = looped_noise[:main_duration]

        filtered_sound = filtered_sound + 10
        combined = filtered_sound.overlay(looped_noise)

        # Load the audio to be added at the beginning and end
        intro_audio = AudioSegment.from_mp3("audio_samples/beep.wav")
        intro_audio = intro_audio + 3

        outro_audio = AudioSegment.from_mp3("audio_samples/beep.wav")

        # Concatenate the audio
        final_audio = intro_audio + combined + outro_audio

        os.remove(filtered_wav)
        if delete_source:
            os.remove(filename)

        return final_audio
