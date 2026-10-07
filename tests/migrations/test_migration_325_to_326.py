"""3.2.6: the hosted Elite Dangerous and Galactapedia MCP servers join an existing
mcp.yaml, and every Wingman on the subscription gets an Azure voice of its Inworld
voice's gender."""

from unittest.mock import MagicMock

import pytest

from services.migrations.migration_325_to_326 import (
    ELITE_SERVER,
    GALACTAPEDIA_SERVER,
    Migration325To326,
)
from tests.support import REPO_ROOT, template


def migration():
    return Migration325To326(MagicMock())


def test_both_servers_are_added_to_an_existing_mcp_yaml():
    old = {"servers": [{"name": "wingman_date_time", "type": "http", "url": "x"}]}
    out = migration().migrate_mcp(old, {})
    assert [s["name"] for s in out["servers"]] == [
        "wingman_date_time",
        "wingman_elite_dangerous",
        "wingman_galactapedia",
    ]


def test_an_elite_server_the_user_already_has_is_kept_as_it_is():
    mine = {"name": "wingman_elite_dangerous", "url": "https://my.own/elite"}
    out = migration().migrate_mcp({"servers": [mine]}, {})
    assert out["servers"] == [mine, GALACTAPEDIA_SERVER]


def test_a_galactapedia_server_the_user_already_has_is_kept_as_it_is():
    mine = {"name": "wingman_galactapedia", "url": "https://my.own/galactapedia"}
    out = migration().migrate_mcp({"servers": [mine]}, {})
    assert out["servers"] == [mine, ELITE_SERVER]


def test_without_an_mcp_yaml_the_template_is_used():
    new = {"servers": []}
    assert migration().migrate_mcp({}, new) is new


@pytest.mark.parametrize("server", [ELITE_SERVER, GALACTAPEDIA_SERVER])
def test_the_entry_matches_the_template(server):
    entry = next(
        s for s in template("mcp.template.yaml")["servers"]
        if s["name"] == server["name"]
    )
    assert entry == server


# ── Azure voice per Wingman ──


def test_a_male_inworld_voice_gets_andrew_and_a_female_one_jenny():
    m = migration()
    clive = m.migrate_wingman(
        {"name": "ATC", "features": {"tts_provider": "wingman_pro"}, "inworld": {"voice_id": "Clive"}}
    )
    olivia = m.migrate_wingman(
        {"name": "Computer", "features": {"tts_provider": "wingman_pro"}, "inworld": {"voice_id": "Olivia"}}
    )
    assert clive["wingman_pro"]["azure"]["voice"] == "en-US-AndrewMultilingualNeural"
    assert olivia["wingman_pro"]["azure"]["voice"] == "en-US-JennyMultilingualNeural"
    # Nobody is switched to Azure by the migration.
    assert "tts_provider" not in clive["wingman_pro"]


def test_an_unknown_voice_gets_jenny_and_the_defaults_keep_streaming_on():
    out = migration().migrate_defaults(
        {"features": {"tts_provider": "wingman_pro"}, "inworld": {"voice_id": "Somebody"},
         "wingman_pro": {"tts_provider": "inworld"}}
    )
    assert out["wingman_pro"]["azure"] == {
        "voice": "en-US-JennyMultilingualNeural", "output_streaming": True,
    }
    assert out["wingman_pro"]["tts_provider"] == "inworld"


def test_a_wingman_on_another_provider_or_inheriting_everything_is_left_alone():
    m = migration()
    edge = {"name": "A", "features": {"tts_provider": "edge_tts"}, "inworld": {"voice_id": "Clive"}}
    bare = {"name": "B"}
    assert m.migrate_wingman(dict(edge)) == edge
    assert m.migrate_wingman(dict(bare)) == bare


def test_an_azure_voice_already_set_is_kept():
    config = {"name": "C", "features": {"tts_provider": "wingman_pro"}, "inworld": {"voice_id": "Clive"},
              "wingman_pro": {"azure": {"voice": "de-DE-KatjaNeural"}}}
    assert migration().migrate_wingman(config)["wingman_pro"]["azure"]["voice"] == "de-DE-KatjaNeural"


def test_a_german_inworld_voice_gets_a_german_azure_voice():
    from services.migrations.migration_325_to_326 import azure_voice_for_inworld

    assert azure_voice_for_inworld("Johanna") == "de-DE-KatjaNeural"
    assert azure_voice_for_inworld("Matthias") == "de-DE-ConradNeural"
    assert azure_voice_for_inworld("Alain") == "fr-FR-HenriNeural"
    assert azure_voice_for_inworld("Mercedes") == "es-ES-ElviraNeural"


# ── Azure instead of Pocket TTS for a spoken language other than English ──


POCKET_DEFAULTS = {
    "features": {"tts_provider": "pocket_tts"},
    "pocket_tts": {"voice": "alba"},
    "inworld": {"voice_id": "Deborah"},
    "wingman_pro": {"tts_provider": "inworld"},
}


def migration_in(language):
    service = MagicMock()
    service.templates_dir = f"{REPO_ROOT}/templates"
    service.config_manager.read_config.side_effect = lambda file: (
        {"spoken_language": language} if file.endswith("settings.yaml") else template("defaults.yaml")
    )
    return Migration325To326(service)


def shipped(name, folder):
    config = template(f"{folder}/{name}.template.yaml")
    config.pop("wingman_pro", None)  # 3.2.5 had no Azure voice in the template
    return config


def test_german_users_move_from_pocket_to_azure():
    m = migration_in("de")
    defaults = m.migrate_defaults(dict(POCKET_DEFAULTS))
    assert defaults["features"]["tts_provider"] == "wingman_pro"
    assert defaults["wingman_pro"]["tts_provider"] == "azure"
    assert defaults["wingman_pro"]["azure"]["voice"] == "de-DE-KatjaNeural"
    # A shipped Wingman on the German default voice switches; its Azure voice
    # follows the language at the next start (apply_default_voices).
    atc = shipped("ATC", "Star Citizen")
    atc["pocket_tts"]["voice"] = "de-julia"
    atc = m.migrate_wingman(atc)
    assert atc["features"]["tts_provider"] == "wingman_pro"
    assert atc["wingman_pro"]["tts_provider"] == "azure"
    assert atc["wingman_pro"]["azure"]["voice"] == "en-US-AndrewMultilingualNeural"
    clippy = m.migrate_wingman(shipped("Clippy", "General"))
    assert clippy["features"]["tts_provider"] == "wingman_pro"


def test_a_voice_of_its_own_keeps_pocket_and_english_users_are_untouched():
    m = migration_in("de")
    m.migrate_defaults(dict(POCKET_DEFAULTS))
    computer = shipped("Computer", "Star Citizen")
    computer["pocket_tts"]["voice"] = "eponine"
    assert m.migrate_wingman(computer)["features"]["tts_provider"] == "pocket_tts"

    english = migration_in("en")
    defaults = english.migrate_defaults(dict(POCKET_DEFAULTS))
    assert defaults["features"]["tts_provider"] == "pocket_tts"
    atc = english.migrate_wingman(shipped("ATC", "Star Citizen"))
    assert "features" not in atc or "tts_provider" not in atc["features"]


# ── The defaults' Inworld voice ──


def test_the_defaults_move_from_deborah_to_ashley_and_keep_a_voice_of_their_own():
    m = migration()
    out = m.migrate_defaults({"inworld": {"voice_id": "Deborah", "temperature": 1.1}})
    assert out["inworld"] == {"voice_id": "Ashley", "temperature": 1.1}
    assert out["wingman_pro"]["azure"]["voice"] == "en-US-JennyMultilingualNeural"
    assert migration().migrate_defaults({"inworld": {"voice_id": "Johanna"}})["inworld"]["voice_id"] == "Johanna"


def test_a_legacy_inworld_voice_is_left_for_the_next_start():
    """apply_default_voices moves it at the next start and records it; written
    here, it would no longer count as a default voice. Its Azure counterpart
    is the one of the new default already."""
    out = migration().migrate_wingman(
        {"name": "ATC", "features": {"tts_provider": "wingman_pro"}, "inworld": {"voice_id": "Clive"}}
    )
    assert out["inworld"]["voice_id"] == "Clive"
    assert out["wingman_pro"]["azure"]["voice"] == "en-US-AndrewMultilingualNeural"
