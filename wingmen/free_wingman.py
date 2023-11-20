from wingmen.wingman import Wingman
from services.edge import EdgeTTS
import whisper


class FreeWingman(Wingman):
    async def process(self, _audio_input_wav: str):
        transcript = self._transcribe(_audio_input_wav)
        print(f" >> {transcript}")

        response = self._process_transcript(transcript)
        if response is None:
            return
        print(f" << {response}")

        edge_tts = EdgeTTS()
        random_voice = await edge_tts.get_random_voice()
        await edge_tts.generate_speech(
            response, filename="audio_output/free.mp3", voice=random_voice
        )
        self.audio_player.play("audio_output/free.mp3")

    def _transcribe(self, audio_input_wav: str) -> str:
        super()._transcribe(audio_input_wav)

        model = whisper.load_model("base")
        result = model.transcribe(audio_input_wav, fp16=False)
        print(result["text"])

        return result["text"]

    def _process_transcript(self, transcript: str) -> str:
        instant_activation_command = self._process_instant_activation_command(
            transcript
        )
        if instant_activation_command:
            return self._get_exact_response(instant_activation_command)
        return None
