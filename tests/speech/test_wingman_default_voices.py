"""Shipped Wingmen follow the spoken language while they have a default voice."""

import os

import pytest
import yaml

from services.wingman_default_voices import (
    AZURE_DEFAULTS_FILE,
    DEFAULTS_FILE,
    INWORLD_DEFAULTS_FILE,
    apply_default_voices,
    default_voice_for,
    is_default_voice,
    load_default_voices,
    restore_tts_sections,
    restore_voice_defaults,
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
    # The voices each plan with locks includes (plan_voices in wingman-backend,
    # 2026-10-19): Free for Azure, Pro for Inworld.
    AZURE_DEFAULTS_FILE: {
        "zh-CN-XiaoyuMultilingualNeural", "en-US-LewisMultilingualNeural",
        "en-US-AndrewMultilingualNeural", "de-DE-ConradNeural", "fr-FR-HenriNeural",
        "es-ES-AlvaroNeural",
    },
    INWORLD_DEFAULTS_FILE: {
        "Deborah", "Sabine", "Hélène", "Mercedes",
        "Brian", "Edward", "Matthias", "Alain", "Alvaro",
    },
}
SHIPPED = (("Computer", "Star Citizen"), ("ATC", "Star Citizen"), ("Clippy", "General"))


@pytest.mark.parametrize("file, voice_path", [
    (AZURE_DEFAULTS_FILE, ("wingman_pro", "azure", "voice")),
    (INWORLD_DEFAULTS_FILE, ("inworld", "voice_id")),
])
def test_the_shipped_wingmen_speak_with_the_plan_voices(file, voice_path):
    """A default voice the plan locks would be swapped right away."""
    table = load_default_voices(REPO_ROOT, file)
    for name, _ in SHIPPED:
        for language, voice in table[name].items():
            if language != "legacy":
                assert voice in PLAN_VOICES[file], (name, language, voice)
    # The template's voice is the English one and one of the legacy voices,
    # so a new Wingman follows the language from its first start.
    for name, folder in SHIPPED:
        shipped = template(f"{folder}/{name}.template.yaml")
        for key in voice_path:
            shipped = shipped[key]
        assert default_voice_for(table, name, "en") == shipped
        assert is_default_voice(shipped, table[name])


def test_restoring_voices_keeps_everything_else():
    config = {
        "name": "ATC",
        "backstory": "mine",
        "features": {"tts_provider": "elevenlabs", "conversation_provider": "openai"},
        "wingman_pro": {"tts_provider": "inworld", "conversation_model": "x"},
        "openai": {"tts_voice": "nova", "conversation_model": "gpt"},
        "elevenlabs": {"voice": {"name": "Adam"}},
        "sound": {"effects": ["AI"]},
    }
    template_config = {
        "pocket_tts": {"voice": "en-barry"},
        "sound": {"effects": ["LOW_QUALITY_RADIO"]},
        "openai": {"tts_voice": "onyx"},
    }

    restored = restore_tts_sections(config, template_config)

    assert restored == {
        "name": "ATC",
        "backstory": "mine",
        "features": {"conversation_provider": "openai"},
        "wingman_pro": {"conversation_model": "x"},
        "openai": {"conversation_model": "gpt", "tts_voice": "onyx"},
        "pocket_tts": {"voice": "en-barry"},
        "sound": {"effects": ["LOW_QUALITY_RADIO"]},
    }


def test_a_restored_wingman_gets_the_voice_of_the_language(tmp_path):
    app, cm, folder = setup(tmp_path, {"ATC": {"name": "ATC", "pocket_tts": {"voice": "eponine"}}})
    shipped = tmp_path / "ATC.template.yaml"
    shipped.write_text(yaml.safe_dump({"pocket_tts": {"voice": "azelma"}}), encoding="utf-8")

    assert restore_voice_defaults(cm, app, str(folder / "ATC.yaml"), str(shipped), "de")
    assert voice(folder, "ATC") == "de-julia"


def test_a_wingman_of_its_own_inherits_the_default_voices_again(tmp_path):
    app, cm, folder = setup(tmp_path, {"Mine": {"name": "Mine", "pocket_tts": {"voice": "eponine"}}})

    assert restore_voice_defaults(cm, app, str(folder / "Mine.yaml"), None, "de")
    assert voice(folder, "Mine") is None
