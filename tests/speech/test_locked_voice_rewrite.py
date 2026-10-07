"""A Wingman set to a subscription voice its plan does not include gets the
closest free voice written into its config at sign-in, so the config shows
what the backend really plays."""

import asyncio
from os import path
from types import SimpleNamespace

import yaml

from api.enums import TtsVoiceGender
from api.interface import VoiceInfo
from services.wingman_default_voices import pick_free_voice, rewrite_locked_voices
from tests.support import FakeConfigManager

MALE, FEMALE = TtsVoiceGender.MALE, TtsVoiceGender.FEMALE


def voice(id, gender, languages, locked=False):
    return VoiceInfo(id=id, name=id, gender=gender, languages=languages, locked=locked)


INWORLD = [
    voice("Clive", MALE, ["en"], locked=True),
    voice("Johanna", FEMALE, ["de"], locked=True),
    voice("Deborah", FEMALE, ["en"]),
    voice("Edward", MALE, ["en"]),
]
AZURE = [
    voice("de-DE-KillianNeural", MALE, ["de-DE"], locked=True),
    voice("en-US-JennyMultilingualNeural", FEMALE, ["en-US"]),
    voice("de-DE-KatjaNeural", FEMALE, ["de-DE"]),
    voice("de-DE-ConradNeural", MALE, ["de-DE"]),
]
VOICES = {"inworld": INWORLD, "azure": AZURE}


def test_pick_prefers_language_and_gender_then_language_then_gender_then_first():
    free = [
        voice("en-f", FEMALE, ["en-US"]),
        voice("de-f", FEMALE, ["de_DE"]),
        voice("fr-m", MALE, ["fr-FR"]),
        voice("de-m", MALE, ["DE-AT"]),
    ]
    assert pick_free_voice(voice("x", MALE, ["de-DE"]), free).id == "de-m"
    assert pick_free_voice(voice("x", MALE, ["de-DE"]), free[:3]).id == "de-f"
    assert pick_free_voice(voice("x", MALE, ["it-IT"]), free).id == "fr-m"
    assert pick_free_voice(voice("x", None, ["it-IT"]), free).id == "en-f"
    assert pick_free_voice(None, free).id == "en-f"
    assert pick_free_voice(voice("x", MALE, ["de"]), []) is None


class RewriteConfigManager(FakeConfigManager):
    def __init__(self, root, defaults):
        super().__init__(root)
        self.default_config_path = path.join(self.config_dir, "defaults.yaml")
        FakeConfigManager.write_config(self, self.default_config_path, defaults)
        self.default_config = None
        self.writes = 0

    def write_config(self, file_path, content):
        self.writes += 1
        return super().write_config(file_path, content)

    def load_defaults_config(self, silent_on_error=False):
        return "reloaded"


def write(folder, name, content):
    (folder / f"{name}.yaml").write_text(yaml.safe_dump(content))


def read(folder, name):
    return yaml.safe_load((folder / f"{name}.yaml").read_text())


def test_locked_voices_are_rewritten_on_disk(tmp_path):
    folder = tmp_path / "configs" / "Star Citizen"
    folder.mkdir(parents=True)
    defaults = {
        "features": {"tts_provider": "wingman_pro"},
        "inworld": {"voice_id": "Clive"},
        "wingman_pro": {"tts_provider": "inworld", "azure": {"voice": "en-US-JennyMultilingualNeural"}},
    }
    # Inherits the defaults' locked Clive: fixed by fixing the defaults.
    write(folder, "ATC", {"name": "ATC"})
    # Its own locked voice, German and female.
    write(folder, "Computer", {"inworld": {"voice_id": "Johanna"}})
    # A locked Azure voice of its own.
    write(folder, "Board", {"wingman_pro": {"tts_provider": "azure", "azure": {"voice": "de-DE-KillianNeural"}}})
    # Free voice, unknown voice, other provider: all untouched.
    write(folder, "Free", {"inworld": {"voice_id": "Deborah"}})
    write(folder, "Unknown", {"inworld": {"voice_id": "Nobody"}})
    write(folder, "Edge", {"features": {"tts_provider": "edge_tts"}, "inworld": {"voice_id": "Johanna"}})
    cm = RewriteConfigManager(tmp_path, defaults)

    changed = rewrite_locked_voices(cm, VOICES)

    assert changed == [
        "defaults: Clive → Edward",
        "Star Citizen/Board: de-DE-KillianNeural → de-DE-ConradNeural",
        "Star Citizen/Computer: Johanna → Deborah",
    ]
    assert yaml.safe_load(open(cm.default_config_path))["inworld"]["voice_id"] == "Edward"
    assert cm.default_config == "reloaded"
    assert read(folder, "ATC") == {"name": "ATC"}
    assert read(folder, "Computer")["inworld"]["voice_id"] == "Deborah"
    assert read(folder, "Board")["wingman_pro"] == {
        "tts_provider": "azure", "azure": {"voice": "de-DE-ConradNeural"}}
    assert read(folder, "Free")["inworld"]["voice_id"] == "Deborah"
    assert read(folder, "Unknown")["inworld"]["voice_id"] == "Nobody"
    assert read(folder, "Edge")["inworld"]["voice_id"] == "Johanna"

    writes = cm.writes
    assert rewrite_locked_voices(cm, VOICES) == []
    assert cm.writes == writes


def test_a_wingman_inheriting_a_locked_voice_from_defaults_off_the_subscription(tmp_path):
    folder = tmp_path / "configs" / "Star Citizen"
    folder.mkdir(parents=True)
    defaults = {"features": {"tts_provider": "pocket_tts"}, "inworld": {"voice_id": "Clive"},
                "wingman_pro": {"tts_provider": "inworld"}}
    write(folder, "ATC", {"features": {"tts_provider": "wingman_pro"}})
    cm = RewriteConfigManager(tmp_path, defaults)

    assert rewrite_locked_voices(cm, VOICES) == ["Star Citizen/ATC: Clive → Edward"]
    assert read(folder, "ATC")["inworld"] == {"voice_id": "Edward"}
    assert yaml.safe_load(open(cm.default_config_path))["inworld"]["voice_id"] == "Clive"


def test_an_empty_list_skips_that_provider(tmp_path):
    folder = tmp_path / "configs" / "Star Citizen"
    folder.mkdir(parents=True)
    defaults = {"features": {"tts_provider": "wingman_pro"}, "inworld": {"voice_id": "Clive"},
                "wingman_pro": {"tts_provider": "inworld"}}
    cm = RewriteConfigManager(tmp_path, defaults)

    assert rewrite_locked_voices(cm, {"inworld": [], "azure": AZURE}) == []
    assert cm.writes == 0


def _handler(cm, azure, inworld):
    from services.command_handler import CommandHandler

    lines = []

    async def print_async(text, **kwargs):
        lines.append(text)

    handler = CommandHandler.__new__(CommandHandler)
    handler.source_name = "test"
    handler.core = SimpleNamespace(config_manager=cm)
    handler.printr = SimpleNamespace(print_async=print_async, print=lambda *a, **k: None)

    async def fetch():
        return {"azure": azure, "inworld": inworld}

    handler._fetch_plan_voices = fetch
    return handler, lines


def test_sign_in_step_rewrites_and_reports_once(tmp_path):
    folder = tmp_path / "configs" / "Star Citizen"
    folder.mkdir(parents=True)
    write(folder, "ATC", {"features": {"tts_provider": "wingman_pro"},
                          "wingman_pro": {"tts_provider": "inworld"},
                          "inworld": {"voice_id": "Clive"}})
    cm = RewriteConfigManager(tmp_path, {"features": {"tts_provider": "pocket_tts"}})

    handler, lines = _handler(cm, AZURE, INWORLD)
    assert asyncio.run(handler._rewrite_locked_voices()) is True
    assert lines == ["These voices are not in your plan, so the Wingmen now use free ones: "
                     "Star Citizen/ATC: Clive → Edward"]
    assert read(folder, "ATC")["inworld"]["voice_id"] == "Edward"

    again, again_lines = _handler(cm, AZURE, INWORLD)
    assert asyncio.run(again._rewrite_locked_voices()) is False and again_lines == []


def test_backend_failure_never_blocks_sign_in(tmp_path, monkeypatch):
    import providers.wingman_subscription as subscription

    (tmp_path / "configs").mkdir()
    cm = RewriteConfigManager(tmp_path, {"features": {"tts_provider": "wingman_pro"}})
    cm.settings_config = SimpleNamespace(wingman_pro=SimpleNamespace(base_url="http://invalid"))

    def boom(self, filter_language=None):
        raise RuntimeError("backend down")

    monkeypatch.setattr(subscription.WingmanSubscription, "get_available_azure_voices", boom)
    monkeypatch.setattr(subscription.WingmanSubscription, "get_available_inworld_voices", boom)

    handler, lines = _handler(cm, [], [])
    del handler._fetch_plan_voices
    assert asyncio.run(handler._fetch_plan_voices()) == {"azure": [], "inworld": []}
    assert asyncio.run(handler._rewrite_locked_voices()) is False and lines == []
