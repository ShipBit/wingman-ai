"""A language beyond the six: named, checked, and the Wingmen switched and back."""

import asyncio
import os

import yaml

from api.interface import OtherLanguageSetting, VoiceInfo
from services import other_language
from tests.support import FakeConfigManager


def test_the_list_finds_a_language_by_any_of_its_names():
    for text in ("Polnisch", "polish", "Polski", " PL ", "polonais"):
        found = other_language.find(text)
        assert (found.code, found.name, found.english_name) == ("pl", "Polski", "Polish")
    # Dutch is a spoken language of its own since pocket-tts 3.3.
    assert other_language.find("Nederlands") is None
    assert other_language.find("Klingonisch") is None


def test_the_support_model_names_what_the_list_does_not_know():
    async def ask(system, user):
        assert "Klingonisch" in user
        return 'Sure: {"code": "tlh", "name": "tlhIngan Hol", "english_name": "Klingon"}'

    found = asyncio.run(other_language.resolve("Klingonisch", ask))
    assert (found.code, found.name, found.english_name) == ("tlh", "tlhIngan Hol", "Klingon")


def test_no_language_and_a_broken_answer_give_none():
    async def nothing(system, user):
        return '{"code": null, "name": null, "english_name": null}'

    async def broken(system, user):
        return "no idea"

    assert asyncio.run(other_language.resolve("Pizza", nothing)) is None
    assert asyncio.run(other_language.resolve("Pizza", broken)) is None


def test_inworld_voices_are_matched_by_primary_language():
    voices = [VoiceInfo(id="a", languages=["nl-NL"]), VoiceInfo(id="b", languages=["en"]), VoiceInfo(id="c", languages=["nl"])]
    assert [v.id for v in other_language.inworld_speaks(voices, "nl")] == ["a", "c"]
    assert other_language.inworld_speaks(voices, None) == []


def test_switch_and_restore(tmp_path):
    folder = tmp_path / "configs" / "Star Citizen"
    folder.mkdir(parents=True)
    (folder / "ATC.yaml").write_text(yaml.safe_dump({"name": "ATC"}))  # Pocket TTS from the defaults
    (folder / "Computer.yaml").write_text(yaml.safe_dump({"features": {"tts_provider": "elevenlabs"}}))
    (folder / "Clippy.yaml").write_text(yaml.safe_dump({"features": {"tts_provider": "pocket_tts"}}))
    cm = FakeConfigManager(tmp_path)
    dutch = OtherLanguageSetting(code="nl", name="Nederlands", english_name="Dutch")
    voices = [VoiceInfo(id="Anke", languages=["nl"]), VoiceInfo(id="Joep", languages=["nl"])]

    switched = other_language.switch_wingmen(cm, "pocket_tts", dutch, "wingman_pro", voices)
    assert switched == ["Star Citizen/ATC", "Star Citizen/Clippy"]
    atc = yaml.safe_load((folder / "ATC.yaml").read_text())
    assert atc["features"]["tts_provider"] == "wingman_pro"
    assert atc["wingman_pro"]["tts_provider"] == "inworld" and atc["inworld"]["voice_id"] == "Anke"
    assert yaml.safe_load((folder / "Clippy.yaml").read_text())["inworld"]["voice_id"] == "Joep"
    assert yaml.safe_load((folder / "Computer.yaml").read_text())["features"]["tts_provider"] == "elevenlabs"

    # The user picks another Inworld voice for Clippy: it stays on Inworld.
    clippy = yaml.safe_load((folder / "Clippy.yaml").read_text())
    clippy["inworld"]["voice_id"] = "Mine"
    (folder / "Clippy.yaml").write_text(yaml.safe_dump(clippy))

    restored = other_language.restore_wingmen(cm)
    assert [os.path.basename(p) for p in restored] == ["ATC.yaml"]
    assert yaml.safe_load((folder / "ATC.yaml").read_text())["features"]["tts_provider"] == "pocket_tts"
    assert yaml.safe_load((folder / "Clippy.yaml").read_text())["features"]["tts_provider"] == "wingman_pro"
    assert not (tmp_path / "configs" / other_language.RECORD_FILE).exists()


def test_the_report_says_what_works():
    dutch = OtherLanguageSetting(code="nl", name="Nederlands", english_name="Dutch")
    klingon = OtherLanguageSetting(code="tlh", name="tlhIngan Hol", english_name="Klingon")
    assert other_language.report(dutch, "parakeet", True, "wingman_pro", ["x"]).stt_supported
    assert not other_language.report(klingon, "parakeet", False, None, []).stt_supported
    assert other_language.report(klingon, "wingman_pro", False, None, []).stt_supported


def test_dutch_set_as_another_language_becomes_dutch(tmp_path):
    from types import SimpleNamespace
    from api.enums import SpokenLanguage
    from api.interface import OtherLanguageSetting

    saved = []
    cm = SimpleNamespace(
        config_dir=str(tmp_path),
        settings_config=SimpleNamespace(
            spoken_language=SpokenLanguage.OTHER,
            other_language=OtherLanguageSetting(code="nl", name="Nederlands", english_name="Dutch"),
        ),
        save_settings_config=lambda: saved.append(True),
    )
    assert other_language.promote_to_supported(cm) == "nl"
    assert cm.settings_config.spoken_language == SpokenLanguage.NL
    assert cm.settings_config.other_language is None and saved

    cm.settings_config.spoken_language = SpokenLanguage.OTHER
    cm.settings_config.other_language = OtherLanguageSetting(code="pl", name="Polski", english_name="Polish")
    assert other_language.promote_to_supported(cm) is None
