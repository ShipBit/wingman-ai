"""The MCP registry only offers what the model may use, and routes calls back.

Tools of an MCP server get a prefixed name so servers cannot clash. The model
sees the tools of a server only after it activated that server, and never sees
a tool the user switched off. A call comes in with the prefixed name, and the
server must receive the original one.

The connections and the client are fakes. No server is started, nothing is
sent over a network.
"""

import asyncio

from api.enums import McpTransportType
from api.interface import McpServerConfig, McpToolInfo
from services.mcp_client import McpConnection
from services.mcp_registry import McpRegistry


def make_connection(name="docs", tools=("search", "fetch"), connected=True, error=None):
    config = McpServerConfig(
        name=name,
        display_name=name.title(),
        description=f"The {name} server",
        type=McpTransportType.HTTP,
        url="http://localhost/mcp",
    )
    infos = [
        McpToolInfo(
            name=tool,
            prefixed_name=f"mcp_{name}_{tool}",
            description=f"Does {tool}",
            server_name=name,
        )
        for tool in tools
    ]
    return McpConnection(config=config, tools=infos, is_connected=connected, error=error)


class FakeClient:
    """Stands in for McpClient: hands out prepared connections, records calls."""

    def __init__(self, *connections):
        self.available = {c.config.name: c for c in connections}
        self.calls = []
        self.disconnected = []

    async def connect(self, config, headers=None, auth=None):
        return self.available[config.name]

    async def disconnect(self, connection):
        self.disconnected.append(connection.config.name)

    def get_tool_definitions(self, connection):
        return [
            (t.prefixed_name, {"type": "function", "function": {"name": t.prefixed_name}})
            for t in connection.tools
            if t.is_enabled
        ]

    async def call_tool(self, connection, tool_name, arguments):
        self.calls.append((connection.config.name, tool_name, arguments))
        return "ok"


def registry_with(*connections):
    client = FakeClient(*connections)
    registry = McpRegistry(client)

    async def register_all():
        for connection in connections:
            await registry.register_server(connection.config)

    asyncio.run(register_all())
    return registry, client


def active_names(registry):
    return {name for name, _ in registry.get_active_tools()}


# ── names ──────────────────────────────────────────────────────────────


def test_a_prefixed_tool_name_maps_back_to_its_original_and_its_server():
    docs = make_connection("docs")
    registry, _ = registry_with(docs, make_connection("maps", tools=("search",)))

    assert registry.get_original_tool_name("mcp_docs_search") == "search"
    assert registry.get_connection_for_tool("mcp_docs_search") is docs
    assert registry.get_connection_for_tool("mcp_maps_search").config.name == "maps"
    assert registry.get_original_tool_name("search") is None


def test_call_tool_hands_the_original_name_to_the_server():
    registry, client = registry_with(make_connection("docs"))

    result = asyncio.run(registry.call_tool("mcp_docs_fetch", {"url": "x"}))

    assert result == "ok"
    assert client.calls == [("docs", "fetch", {"url": "x"})]


# ── switched off tools ─────────────────────────────────────────────────


def test_a_switched_off_tool_is_not_offered_and_not_callable():
    registry, client = registry_with(make_connection("docs"))
    asyncio.run(registry.activate_server("docs"))

    assert asyncio.run(registry.set_disabled_tools("docs", ["fetch"]))

    assert active_names(registry) == {"mcp_docs_search"}
    assert registry.get_original_tool_name("mcp_docs_fetch") is None
    assert not registry.is_mcp_tool("mcp_docs_fetch")
    assert asyncio.run(registry.call_tool("mcp_docs_fetch", {})).startswith("Error")
    assert client.calls == []
    # The summary the model reads when it picks a server leaves it out too.
    manifest = registry.get_connected_servers()[0]
    assert manifest.tool_names == ["mcp_docs_search"]


def test_switching_a_tool_back_on_offers_it_again():
    registry, _ = registry_with(make_connection("docs"))
    asyncio.run(registry.activate_server("docs"))
    asyncio.run(registry.set_disabled_tools("docs", ["fetch"]))

    asyncio.run(registry.set_disabled_tools("docs", []))

    assert active_names(registry) == {"mcp_docs_search", "mcp_docs_fetch"}
    assert registry.get_original_tool_name("mcp_docs_fetch") == "fetch"


# ── progressive disclosure ─────────────────────────────────────────────


def test_tools_are_offered_only_after_the_server_is_activated():
    registry, _ = registry_with(make_connection("docs"))

    assert registry.get_active_tools() == []

    ok, _message = asyncio.run(registry.activate_server("docs"))

    assert ok
    assert active_names(registry) == {"mcp_docs_search", "mcp_docs_fetch"}


def test_tools_disappear_on_deactivate_reset_and_unregister():
    registry, client = registry_with(make_connection("docs"), make_connection("maps", tools=("route",)))

    asyncio.run(registry.activate_server("docs"))
    registry.deactivate_server("docs")
    assert registry.get_active_tools() == []

    asyncio.run(registry.activate_server("docs"))
    asyncio.run(registry.activate_server("maps"))
    registry.reset_activations()
    assert registry.get_active_tools() == []
    assert registry.active_server_count == 0

    asyncio.run(registry.activate_server("docs"))
    asyncio.run(registry.unregister_server("docs"))
    assert registry.get_active_tools() == []
    assert registry.get_connection_for_tool("mcp_docs_search") is None
    assert client.disconnected == ["docs"]


# ── errors and meta tools ──────────────────────────────────────────────


def test_a_server_with_an_error_reports_it_and_cannot_be_activated():
    broken = make_connection("docs", connected=False, error="timed out")
    registry = McpRegistry(FakeClient(broken))
    registry._connections["docs"] = broken  # as it stands after a failed reconnect

    assert registry.get_server_error("docs") == "timed out"
    ok, _message = asyncio.run(registry.activate_server("docs"))
    assert not ok

    registry.set_server_error("docs", "refused")
    assert registry.get_server_error("docs") == "refused"


def test_a_server_that_never_connected_still_reports_why():
    """The server list in the UI asks the registry. A server whose first
    connect failed or timed out used to show no error at all."""
    refused = make_connection("docs", connected=False, error="401 Unauthorized")
    registry = McpRegistry(FakeClient(refused))

    asyncio.run(registry.register_server(refused.config))
    assert registry.get_server_error("docs") == "401 Unauthorized"

    registry.set_server_error("maps", "Connection timed out (10s).")
    assert registry.get_server_error("maps") == "Connection timed out (10s)."

    # A later successful connect clears it.
    registry._client.available["docs"] = make_connection("docs")
    asyncio.run(registry.register_server(refused.config))
    assert registry.get_server_error("docs") is None


def test_the_meta_tools_list_the_servers_that_can_be_activated():
    registry, _ = registry_with(make_connection("docs"), make_connection("maps", tools=("route",)))

    tools = dict(registry.get_meta_tools())
    enum = tools["activate_mcp_server"]["function"]["parameters"]["properties"]["server_name"]["enum"]

    assert sorted(enum) == ["docs", "maps"]
    assert registry.is_meta_tool("activate_mcp_server")

    # Nothing is active yet, then the listing names the activated server's tools.
    text, changed = asyncio.run(registry.execute_meta_tool("list_active_mcp_servers", {}))
    assert "No MCP servers" in text and not changed

    _text, changed = asyncio.run(
        registry.execute_meta_tool("activate_mcp_server", {"server_name": "docs"})
    )
    assert changed
    text, _ = asyncio.run(registry.execute_meta_tool("list_active_mcp_servers", {}))
    assert "mcp_docs_search" in text and "mcp_maps_route" not in text
