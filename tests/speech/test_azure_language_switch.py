"""Pocket TTS is the default for English only: for another spoken language the
defaults and the shipped Wingmen still on Pocket TTS with a default voice move
to the subscription's Azure, once, and stay there when English comes back."""

import os
from os import path

import yaml

from services.wingman_default_voices import (
    AZURE_DEFAULTS_FILE,
    DEFAULTS_FILE,
    TEMPLATE_DEFAULTS_FILE,
    apply_default_voices,
    switch_to_azure_for_language,
)
from tests.support import FakeConfigManager

DEFAULTS = {
    "features": {"tts_provider": "pocket_tts"},
    "pocket_tts": {"voice": "alba"},
    "wingman_pro": {"tts_provider": "inworld", "azure": {"voice": "jenny", "output_streaming": True}},
}


class SwitchConfigManager(FakeConfigManager):
    def __init__(self, root, defaults):
        super().__init__(root)
        self.default_config_path = path.join(self.config_dir, "defaults.yaml")
        self.write_config(self.default_config_path, defaults)
        self.default_config = None

    def load_defaults_config(self, silent_on_error=False):
        return "reloaded"


def setup(tmp_path, wingmen, defaults=None):
    app = tmp_path / "app"
    for file, text in (
        (DEFAULTS_FILE, "ATC\tlegacy\tazelma\nATC\tde\tde-julia\nATC\ten\tanna\n"
                        "Clippy\tlegacy\talba\nClippy\tde\tde-gaby\nClippy\ten\tciufi\n"),
        (AZURE_DEFAULTS_FILE, "ATC\tlegacy\tandrew\nATC\ten\tguy\nATC\tde\tconrad\nATC\t*\tandrew\n"
                              "Clippy\tlegacy\tandrew\nClippy\t*\tandrew\n"),
        (TEMPLATE_DEFAULTS_FILE, yaml.safe_dump(DEFAULTS)),
    ):
        (app / os.path.dirname(file)).mkdir(parents=True, exist_ok=True)
        (app / file).write_text(text, encoding="utf-8")
    folder = tmp_path / "configs" / "Star Citizen"
    folder.mkdir(parents=True)
    for name, config in wingmen.items():
        (folder / f"{name}.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    cm = SwitchConfigManager(tmp_path, defaults if defaults is not None else DEFAULTS)
    return str(app), cm, folder


def change_language(cm, app, language):
    """What settings_service does when the spoken language changes."""
    apply_default_voices(cm, app, language)
    return switch_to_azure_for_language(cm, app, language)


def read(folder, name):
    return yaml.safe_load((folder / f"{name}.yaml").read_text())


def tts(config):
    return (
        (config.get("features") or {}).get("tts_provider"),
        (config.get("wingman_pro") or {}).get("tts_provider"),
        ((config.get("wingman_pro") or {}).get("azure") or {}).get("voice"),
    )


def test_german_moves_the_defaults_and_untouched_wingmen_to_azure(tmp_path):
    app, cm, folder = setup(tmp_path, {
        "ATC": {"pocket_tts": {"voice": "azelma"}, "wingman_pro": {"azure": {"voice": "andrew"}}},
        "Clippy": {"name": "Clippy"},
        "Mine": {"name": "Mine"},
    })
    moved = change_language(cm, app, "de")
    assert moved == ["defaults", "Star Citizen/ATC", "Star Citizen/Clippy", "Star Citizen/Mine"]
    assert tts(read(folder, "ATC")) == ("wingman_pro", "azure", "conrad")
    assert tts(read(folder, "Clippy")) == ("wingman_pro", "azure", "andrew")
    # A Wingman of the user's own without a voice follows the defaults.
    assert tts(read(folder, "Mine")) == (None, None, None)
    assert tts(cm.read_config(cm.default_config_path)) == ("wingman_pro", "azure", "de-DE-KatjaNeural")
    assert cm.default_config == "reloaded"


def test_a_wingman_with_its_own_pocket_voice_or_provider_stays(tmp_path):
    app, cm, folder = setup(tmp_path, {
        "ATC": {"pocket_tts": {"voice": "eponine"}},
        "Edge": {"features": {"tts_provider": "edge_tts"}},
        "Pro": {"features": {"tts_provider": "wingman_pro"}},
    })
    assert change_language(cm, app, "de") == ["defaults"]
    # Pinned to what it inherited, so the defaults' switch does not reach it.
    assert tts(read(folder, "ATC"))[0] == "pocket_tts"
    assert read(folder, "Edge") == {"features": {"tts_provider": "edge_tts"}}
    assert tts(read(folder, "Pro"))[:2] == ("wingman_pro", "inworld")


def test_defaults_with_a_voice_the_user_picked_stay_on_pocket(tmp_path):
    defaults = {**DEFAULTS, "pocket_tts": {"voice": "eponine"}}
    app, cm, folder = setup(tmp_path, {"Clippy": {"name": "Clippy"}}, defaults)
    assert change_language(cm, app, "de") == ["Star Citizen/Clippy"]
    assert tts(cm.read_config(cm.default_config_path))[0] == "pocket_tts"
    assert tts(read(folder, "Clippy")) == ("wingman_pro", "azure", "andrew")


def test_nothing_moves_for_english_or_when_the_defaults_are_elsewhere(tmp_path):
    app, cm, folder = setup(tmp_path, {"Clippy": {"name": "Clippy"}})
    assert change_language(cm, app, "en") == []
    cm.write_config(cm.default_config_path, {**DEFAULTS, "features": {"tts_provider": "elevenlabs"}})
    assert change_language(cm, app, "de") == []
    assert tts(read(folder, "Clippy"))[0] is None


def test_not_back_to_pocket_for_english_and_not_twice(tmp_path):
    app, cm, folder = setup(tmp_path, {"ATC": {"pocket_tts": {"voice": "azelma"}}})
    change_language(cm, app, "de")
    assert change_language(cm, app, "en") == []
    # English moves the Azure voice back to English, the provider stays.
    assert tts(read(folder, "ATC")) == ("wingman_pro", "azure", "guy")
    # The user puts ATC and the defaults back on Pocket TTS: French keeps them there.
    config = read(folder, "ATC")
    config["features"]["tts_provider"] = "pocket_tts"
    cm.write_config(str(folder / "ATC.yaml"), config)
    cm.write_config(cm.default_config_path, DEFAULTS)
    assert change_language(cm, app, "fr") == []
    assert tts(read(folder, "ATC"))[0] == "pocket_tts"
