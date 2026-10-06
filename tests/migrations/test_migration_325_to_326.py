"""3.2.6: the hosted Elite Dangerous and Galactapedia MCP servers join an existing mcp.yaml."""

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
