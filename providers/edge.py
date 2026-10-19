import re
from os import path
from typing import TYPE_CHECKING
from edge_tts import Communicate, list_voices
from api.enums import TtsProvider, TtsVoiceGender
from api.interface import EdgeTtsConfig, SoundConfig, VoiceInfo
from providers.interfaces import TtsInterface, tts_provider
from services.audio_player import AudioPlayer
from services.file import get_writable_dir
from services.printr import Printr

if TYPE_CHECKING:
    from api.interface import WingmanConfig

RECORDING_PATH = "audio_output"
OUTPUT_FILE: str = "edge_tts.mp3"

printr = Printr()

# Tags almost every Edge voice has: on a tile they would say nothing.
COMMON_TAGS = {"Friendly", "Positive", "General", "Copilot"}


async def get_edge_voices() -> list[VoiceInfo]:
    """Every Edge voice, as Microsoft lists it right now."""
    raw = await list_voices()
    return edge_voice_infos(raw)


def edge_voice_infos(raw: list[dict]) -> list[VoiceInfo]:
    """Microsoft's voice list as picker tiles.

    Edge has no language list per voice. A "Multilingual" voice speaks every
    language, so it gets all languages of the list, its own first.
    """
    all_languages = sorted({v["Locale"].split("-")[0] for v in raw})
    voices = []
    for v in raw:
        locale = v["Locale"]
        own = locale.split("-")[0]
        multilingual = "Multilingual" in v["ShortName"]
        tag = v.get("VoiceTag") or {}
        words = [
            w.strip()
            for w in tag.get("VoicePersonalities", []) + tag.get("ContentCategories", [])
        ]
        description = ", ".join(
            dict.fromkeys(w for w in words if w and w not in COMMON_TAGS)
        )
        voices.append(
            VoiceInfo(
                id=v["ShortName"],
                name=edge_voice_name(v["ShortName"], locale),
                gender=edge_voice_gender(v.get("Gender")),
                locale=locale,
                languages=(
                    [locale] + [l for l in all_languages if l != own]
                    if multilingual
                    else [locale]
                ),
                provider="edge_tts",
                description=description or None,
            )
        )
    return voices


def edge_voice_name(short_name: str, locale: str) -> str:
    """"en-US-AvaMultilingualNeural" -> "Ava Multilingual"."""
    name = short_name[len(locale) + 1 :] if short_name.startswith(locale) else short_name
    name = name.removesuffix("Neural")
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)


def edge_voice_gender(gender: str | None) -> TtsVoiceGender:
    try:
        return TtsVoiceGender(gender)
    except ValueError:
        return TtsVoiceGender.UNKNOWN


class Edge:
    def __init__(self):
        self.random_voices = {}

    async def play_audio(
        self,
        text: str,
        config: EdgeTtsConfig,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
    ):
        communicate, output_file = await self.__generate_speech(
            text=text, voice=config.voice
        )
        audio, sample_rate = audio_player.get_audio_from_file(output_file)

        await audio_player.play_with_effects(
            input_data=(audio, sample_rate),
            config=sound_config,
            wingman_name=wingman_name,
        )

    async def __generate_speech(
        self,
        text: str,
        voice: str = "en-US-GuyNeural",
        rate: str = "+0%",
    ):
        if not text:
            return

        communicate = Communicate(text=text, voice=voice, rate=rate)
        file_path = path.join(get_writable_dir(RECORDING_PATH), OUTPUT_FILE)
        await communicate.save(file_path)

        return communicate, file_path


@tts_provider(TtsProvider.EDGE_TTS)
class EdgeTts(TtsInterface):
    def __init__(self, config: "WingmanConfig"):
        self._edge = Edge()
        self._config = config

    async def play_audio(self, text, sound_config, audio_player, wingman_name):
        await self._edge.play_audio(
            text=text,
            config=self._config.edge_tts,
            sound_config=sound_config,
            audio_player=audio_player,
            wingman_name=wingman_name,
        )
