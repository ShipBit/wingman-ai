"""Shipped Wingmen follow the spoken language while they have a default voice."""

import os

import yaml

from services.wingman_default_voices import (
    AZURE_DEFAULTS_FILE,
    DEFAULTS_FILE,
    apply_default_voices,
    load_default_voices,
)
from tests.support import REPO_ROOT, FakeConfigManager, template


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


# ── Azure voices (subscription) ──

AZURE_TABLE = (
    "Computer\tlegacy\tjenny\nComputer\ten\tjenny\nComputer\tde\tkatja\nComputer\t*\tjenny\n"
    "ATC\tlegacy\tandrew\nATC\ten\tguy\nATC\tde\tconrad\nATC\t*\tandrew\n"
)


def setup_azure(tmp_path, wingmen):
    app, cm, folder = setup(tmp_path, wingmen)
    (tmp_path / "app" / os.path.dirname(AZURE_DEFAULTS_FILE)).mkdir(parents=True)
    (tmp_path / "app" / AZURE_DEFAULTS_FILE).write_text(AZURE_TABLE, encoding="utf-8")
    return app, cm, folder


def azure(folder, name):
    config = yaml.safe_load((folder / f"{name}.yaml").read_text())
    return ((config.get("wingman_pro") or {}).get("azure") or {}).get("voice")


def test_the_azure_voice_follows_the_language_like_the_pocket_voice(tmp_path):
    app, cm, folder = setup_azure(tmp_path, {
        "ATC": {"pocket_tts": {"voice": "azelma"}, "wingman_pro": {"azure": {"voice": "andrew", "output_streaming": True}}},
        "Computer": {"name": "Computer"},
    })
    assert apply_default_voices(cm, app, "de") == ["Star Citizen/ATC", "Star Citizen/Computer"]
    assert (azure(folder, "ATC"), voice(folder, "ATC")) == ("conrad", "de-julia")
    assert azure(folder, "Computer") == "katja"
    assert yaml.safe_load((folder / "ATC.yaml").read_text())["wingman_pro"]["azure"]["output_streaming"]
    apply_default_voices(cm, app, "en")
    assert (azure(folder, "ATC"), azure(folder, "Computer")) == ("guy", "jenny")


def test_a_language_without_a_row_gets_the_multilingual_voice(tmp_path):
    app, cm, folder = setup_azure(tmp_path, {"ATC": {"wingman_pro": {"azure": {"voice": "andrew"}}}})
    apply_default_voices(cm, app, "de")
    apply_default_voices(cm, app, "it")
    assert azure(folder, "ATC") == "andrew"


def test_an_azure_voice_the_user_picked_stays_while_the_pocket_voice_moves(tmp_path):
    app, cm, folder = setup_azure(tmp_path, {
        "ATC": {"pocket_tts": {"voice": "azelma"}, "wingman_pro": {"azure": {"voice": "katja"}}},
    })
    assert apply_default_voices(cm, app, "de") == ["Star Citizen/ATC"]
    assert (azure(folder, "ATC"), voice(folder, "ATC")) == ("katja", "de-julia")


def test_the_shipped_wingmen_have_three_different_azure_voices():
    voices = [
        template("Star Citizen/Computer.template.yaml")["wingman_pro"]["azure"]["voice"],
        template("Star Citizen/ATC.template.yaml")["wingman_pro"]["azure"]["voice"],
        template("General/Clippy.template.yaml")["wingman_pro"]["azure"]["voice"],
    ]
    assert len(set(voices)) == 3
    # The template's voice is the English row of the table, so an English
    # Wingman is not rewritten on its first start.
    table = load_default_voices(REPO_ROOT, AZURE_DEFAULTS_FILE)
    for name, shipped in zip(("Computer", "ATC", "Clippy"), voices):
        assert (table[name].get("en") or table[name]["*"]) == shipped
    for language in ("de", "fr", "es"):
        assert table["Computer"][language] != table["ATC"][language]
