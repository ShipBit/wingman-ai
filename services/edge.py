from edge_tts import Communicate, VoicesManager
import random

# List available voices in your terminal using 'edge-tts --list-voices'.
#
# Examples:
#   Name: en-GB-SoniaNeural, Gender: Female
#   Name: de-DE-KillianNeural, Gender: Male


class EdgeTTS:
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

    async def get_random_voice(self, gender: str = "Male", language: str = "en") -> str:
        voices = await VoicesManager.create()
        voice = voices.find(Gender=gender, Language=language)
        random_voice = random.choice(voice)
        return random_voice.get("Name")
