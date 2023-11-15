from wingmen.wingman import Wingman
from services.edge import EdgeTTS


class EdgeTTSGroot(Wingman):
    async def process(self, _audio_input_wav: str):
        edge_tts = EdgeTTS()
        await edge_tts.generate_speech("I am Groot", filename="groot.mp3")
        self.audio_player.play("groot.mp3")
