import random
from edge_tts import Communicate, VoicesManager
from api.enums import LogType
from services.printr import Printr

printr = Printr()
# List available voices in your terminal using 'edge-tts --list-voices'.
#
# Examples:
#   Name: en-GB-SoniaNeural, Gender: Female
#   Name: de-DE-KillianNeural, Gender: Male


class EdgeTTS:
    def __init__(self):
        self.random_voices = {}

    async def generate_speech(
        self,
        text: str,
        filename: str = "",
        voice: str = "en-US-GuyNeural",
        rate: str = "+0%",
    ):
        if not text:
            return

        communicate = Communicate(text, voice, rate=rate)
        await communicate.save(filename)

        return communicate

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

        printr.print(
            f"   Your random EdgeTTS voice: '{random_voice}'.", color=LogType.INFO
        )

        return random_voice
