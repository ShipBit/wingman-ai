"""Shipped Wingmen follow the spoken language while they have a default voice."""

import os

import yaml

from services.wingman_default_voices import DEFAULTS_FILE, apply_default_voices
from tests.support import FakeConfigManager


def setup(tmp_path, wingmen):
    app = tmp_path / "app"
    (app / os.path.dirname(DEFAULTS_FILE)).mkdir(parents=True)
    (app / DEFAULTS_FILE).write_text(
        "ATC\tlegacy\tazelma\nATC\tde\tde-julia\nATC\ten\tanna\nClippy\tlegacy\talba\nClippy\tde\tde-gaby\n",
        encoding="utf-8",
    )
    folder = tmp_path / "configs" / "Star Citizen"
    folder.mkdir(parents=True)
    for name, config in wingmen.items():
        (folder / f"{name}.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    return str(app), FakeConfigManager(tmp_path), folder


def voice(folder, name):
    return (yaml.safe_load((folder / f"{name}.yaml").read_text()).get("pocket_tts") or {}).get("voice")


def test_the_old_template_voice_moves_to_the_language(tmp_path):
    app, cm, folder = setup(tmp_path, {"ATC": {"name": "ATC", "pocket_tts": {"voice": "azelma", "speed": 1.0}}})
    assert apply_default_voices(cm, app, "de") == ["Star Citizen/ATC"]
    assert voice(folder, "ATC") == "de-julia"
    assert yaml.safe_load((folder / "ATC.yaml").read_text())["pocket_tts"]["speed"] == 1.0
    apply_default_voices(cm, app, "en")
    assert voice(folder, "ATC") == "anna"


def test_a_voice_the_user_picked_stays(tmp_path):
    app, cm, folder = setup(tmp_path, {"ATC": {"pocket_tts": {"voice": "eponine"}}})
    assert apply_default_voices(cm, app, "de") == []
    assert voice(folder, "ATC") == "eponine"


def test_no_voice_of_its_own_gets_one_and_unknown_languages_change_nothing(tmp_path):
    app, cm, folder = setup(tmp_path, {"Clippy": {"name": "Clippy"}, "Other": {"pocket_tts": {"voice": "alba"}}})
    assert apply_default_voices(cm, app, "fr") == []
    assert apply_default_voices(cm, app, "de") == ["Star Citizen/Clippy"]
    assert voice(folder, "Clippy") == "de-gaby"
    assert voice(folder, "Other") == "alba"


def test_another_languages_default_the_user_picked_stays(tmp_path):
    app, cm, folder = setup(tmp_path, {"ATC": {"pocket_tts": {"voice": "azelma"}}})
    apply_default_voices(cm, app, "en")
    assert voice(folder, "ATC") == "anna"
    # The user picks the German default while speaking English.
    config = yaml.safe_load((folder / "ATC.yaml").read_text())
    config["pocket_tts"]["voice"] = "de-julia"
    (folder / "ATC.yaml").write_text(yaml.safe_dump(config))
    assert apply_default_voices(cm, app, "en") == []
    assert apply_default_voices(cm, app, "de") == []
    assert voice(folder, "ATC") == "de-julia"
