from edge_tts import Communicate

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
