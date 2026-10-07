"""Shipped Wingmen follow the spoken language while they have a default voice."""

import os

import pytest
import yaml

from services.wingman_default_voices import (
    AZURE_DEFAULTS_FILE,
    DEFAULTS_FILE,
    INWORLD_DEFAULTS_FILE,
    azure_voice_for_inworld,
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


# ── Inworld voices (subscription or own key) ──

INWORLD_TABLE = "ATC\tlegacy\tClive\nATC\ten\tEdward\nATC\tde\tMatthias\nATC\t*\tEdward\n"


def inworld(folder, name):
    return (yaml.safe_load((folder / f"{name}.yaml").read_text()).get("inworld") or {}).get("voice_id")


def test_the_inworld_voice_follows_the_language_and_a_picked_one_stays(tmp_path):
    app, cm, folder = setup(tmp_path, {
        "ATC": {"inworld": {"voice_id": "Clive", "temperature": 1.1}},
        "Clippy": {"inworld": {"voice_id": "Clive"}},
    })
    (tmp_path / "app" / os.path.dirname(INWORLD_DEFAULTS_FILE)).mkdir(parents=True)
    (tmp_path / "app" / INWORLD_DEFAULTS_FILE).write_text(
        INWORLD_TABLE + "Clippy\tlegacy\tAlex\nClippy\t*\tEdward\n", encoding="utf-8"
    )
    apply_default_voices(cm, app, "de")
    assert inworld(folder, "ATC") == "Matthias"
    assert yaml.safe_load((folder / "ATC.yaml").read_text())["inworld"]["temperature"] == 1.1
    # Clive is not Clippy's legacy voice: the user picked it.
    assert inworld(folder, "Clippy") == "Clive"
    apply_default_voices(cm, app, "en")
    assert inworld(folder, "ATC") == "Edward"
    apply_default_voices(cm, app, "it")
    assert inworld(folder, "ATC") == "Edward"


PLAN_VOICES = {
    # The two voices each plan with locks includes per language (2026-10-07):
    # Free for Azure, Pro for Inworld. (female, male)
    AZURE_DEFAULTS_FILE: {
        "en": ("en-US-JennyMultilingualNeural", "en-US-AndrewMultilingualNeural"),
        "de": ("de-DE-KatjaNeural", "de-DE-ConradNeural"),
        "fr": ("fr-FR-DeniseNeural", "fr-FR-HenriNeural"),
        "es": ("es-ES-ElviraNeural", "es-ES-AlvaroNeural"),
    },
    INWORLD_DEFAULTS_FILE: {
        "en": ("Ashley", "Edward"),
        "de": ("Johanna", "Matthias"),
        "fr": ("Hélène", "Alain"),
        "es": ("Mercedes", "Alvaro"),
    },
}


@pytest.mark.parametrize("file, voice_path", [
    (AZURE_DEFAULTS_FILE, ("wingman_pro", "azure", "voice")),
    (INWORLD_DEFAULTS_FILE, ("inworld", "voice_id")),
])
def test_the_shipped_wingmen_speak_with_the_plan_voices(file, voice_path):
    """Computer the female voice, ATC and Clippy the male one, in every language."""
    table = load_default_voices(REPO_ROOT, file)
    for language, (female, male) in PLAN_VOICES[file].items():
        assert table["Computer"][language] == female
        assert table["ATC"][language] == male
        assert table["Clippy"][language] == male
    # The template's voice is the English row of the table, so an English
    # Wingman is not rewritten on its first start.
    for name, folder in (("Computer", "Star Citizen"), ("ATC", "Star Citizen"), ("Clippy", "General")):
        shipped = template(f"{folder}/{name}.template.yaml")
        for key in voice_path:
            shipped = shipped[key]
        assert table[name]["en"] == table[name]["*"] == shipped


def test_the_defaults_speak_with_a_voice_pro_includes():
    assert template("defaults.yaml")["inworld"]["voice_id"] == PLAN_VOICES[INWORLD_DEFAULTS_FILE]["en"][0]


def test_the_azure_counterpart_of_each_inworld_default_matches_the_azure_table():
    azure = load_default_voices(REPO_ROOT, AZURE_DEFAULTS_FILE)
    inworld_table = load_default_voices(REPO_ROOT, INWORLD_DEFAULTS_FILE)
    for name in ("Computer", "ATC", "Clippy"):
        for language in ("en", "de", "fr", "es", "legacy"):
            assert azure_voice_for_inworld(inworld_table[name][language]) == azure[name][language]
