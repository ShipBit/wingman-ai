"""3.2.6: the hosted Elite Dangerous MCP server joins an existing mcp.yaml."""

from unittest.mock import MagicMock

from services.migrations.migration_325_to_326 import ELITE_SERVER, Migration325To326
from tests.support import template


def migration():
    return Migration325To326(MagicMock())


def test_the_elite_server_is_added_to_an_existing_mcp_yaml():
    old = {"servers": [{"name": "wingman_date_time", "type": "http", "url": "x"}]}
    out = migration().migrate_mcp(old, {})
    assert [s["name"] for s in out["servers"]] == ["wingman_date_time", "wingman_elite_dangerous"]


def test_an_elite_server_the_user_already_has_is_kept_as_it_is():
    mine = {"name": "wingman_elite_dangerous", "url": "https://my.own/elite"}
    out = migration().migrate_mcp({"servers": [mine]}, {})
    assert out["servers"] == [mine]


def test_without_an_mcp_yaml_the_template_is_used():
    new = {"servers": []}
    assert migration().migrate_mcp({}, new) is new


def test_the_elite_entry_matches_the_template():
    entry = next(
        s for s in template("mcp.template.yaml")["servers"]
        if s["name"] == ELITE_SERVER["name"]
    )
    assert entry == ELITE_SERVER
