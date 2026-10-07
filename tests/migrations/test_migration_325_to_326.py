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
from tests.support import template


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
