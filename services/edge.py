import random
from edge_tts import Communicate, VoicesManager
from services.file_creator import FileCreator
from services.printr import Printr

RECORDING_PATH = "audio_output"
OUTPUT_FILE: str = "edge_tts.mp3"

printr = Printr()
# List available voices in your terminal using 'edge-tts --list-voices'.
#
# Examples:
#   Name: en-GB-SoniaNeural, Gender: Female
#   Name: de-DE-KillianNeural, Gender: Male


class EdgeTTS(FileCreator):
    def __init__(self, app_root_dir: str):
        super().__init__(app_root_dir, RECORDING_PATH)

        self.random_voices = {}

    async def generate_speech(
        self,
        text: str,
        voice: str = "en-US-GuyNeural",
        rate: str = "+0%",
    ):
        if not text:
            return

        communicate = Communicate(text, voice, rate=rate)
        file_path = self.get_full_file_path(OUTPUT_FILE)
        await communicate.save(file_path)

        return communicate, file_path

    async def get_random_voice(
        self, gender: str = "Male", locale: str = "en-US"
    ) -> str:
        voices = await VoicesManager.create()
        voice = voices.find(Gender=gender, Locale=locale)
        random_voice = random.choice(voice)
        return random_voice.get("ShortName")

    async def get_same_random_voice_for_language(
        self, gender="Male", locale: str = "en-US"
    ) -> str:
        # if we already have a voice for this language, return it ("cache")
        # Otherwise the voice would change every time we call this function / talk to the AI
        if self.random_voices.get(locale):
            return self.random_voices[locale]

        random_voice = await self.get_random_voice(
            locale=locale,
            gender=gender,
        )
        self.random_voices[locale] = random_voice

        printr.print(f"   Your random EdgeTTS voice: '{random_voice}'.", tags="info")

        return random_voice
