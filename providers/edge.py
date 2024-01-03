import random
from edge_tts import Communicate, VoicesManager
from api.interface import EdgeTtsConfig, SoundConfig
from api.enums import TtsVoiceGender, LogType
from services.file_creator import FileCreator
from services.audio_player import AudioPlayer
from services.printr import Printr

RECORDING_PATH = "audio_output"
OUTPUT_FILE: str = "edge_tts.mp3"

printr = Printr()


class Edge(FileCreator):
    def __init__(self, app_root_dir: str):
        super().__init__(app_root_dir, RECORDING_PATH)

        self.random_voices = {}
        self.last_transcript_locale: str = None

    async def play_audio(
        self, text: str, config: EdgeTtsConfig, sound_config: SoundConfig
    ):
        tts_voice = config.tts_voice
        if config.detect_language:
            tts_voice = await self.__get_same_random_voice_for_language(
                gender=config.gender, locale=self.last_transcript_locale
            )

        communicate, output_file = await self.__generate_speech(
            text=text, voice=tts_voice
        )
        audio_player = AudioPlayer()
        audio, sample_rate = audio_player.get_audio_from_file(output_file)

        audio_player.stream_with_effects(
            input_data=(audio, sample_rate), config=sound_config
        )

    async def __generate_speech(
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

    async def __get_random_voice(
        self,
        gender: TtsVoiceGender,
        locale: str = "en-US",
    ) -> str:
        voices = await VoicesManager.create()
        voice = voices.find(Gender=gender.value, Locale=locale)
        random_voice = random.choice(voice)
        return random_voice.get("ShortName")

    async def __get_same_random_voice_for_language(
        self, gender: TtsVoiceGender, locale: str = "en-US"
    ) -> str:
        # if we already have a voice for this language, return it ("cache")
        # Otherwise the voice would change every time we call this function / talk to the AI
        if self.random_voices.get(locale):
            return self.random_voices[locale]

        random_voice = await self.__get_random_voice(
            gender=gender.value,
            locale=locale,
        )
        self.random_voices[locale] = random_voice

        printr.print(f"Your random EdgeTTS voice: '{random_voice}'", color=LogType.INFO)

        return random_voice
