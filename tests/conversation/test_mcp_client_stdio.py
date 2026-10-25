"""STDIO MCP servers get a real file for their stderr, and an MCP server
waiting for the user's authorization is a warning, not an error report.

The MCP SDK hands its ``errlog`` to the subprocess, which needs a file with a
fileno. Its default is ``sys.stderr``, which Printr replaces with a logger
stream that has none: every STDIO server failed to start.
"""

import asyncio
from contextlib import asynccontextmanager

import services.mcp_client as mcp_module
from api.enums import LogType, McpAuthType, McpTransportType
from api.interface import McpServerConfig
from services.mcp_client import McpClient
from services.mcp_oauth import NeedsAuthorization


def _config(**kwargs) -> McpServerConfig:
    values = dict(name="local", display_name="Local Server", type=McpTransportType.STDIO, command="server")
    values.update(kwargs)
    return McpServerConfig(**values)


class Lines:
    def __init__(self):
        self.lines = []

    def print(self, text, color=None, **kwargs):
        self.lines.append((text, color))

    async def print_async(self, text, color=None, **kwargs):
        self.lines.append((text, color))


def _patch(monkeypatch, tmp_path, stdio_client):
    monkeypatch.setattr(mcp_module, "get_writable_dir", lambda sub: str(tmp_path))
    monkeypatch.setattr(mcp_module, "stdio_client", stdio_client)
    monkeypatch.setattr(mcp_module, "MCP_AVAILABLE", True)
    lines = Lines()
    monkeypatch.setattr(mcp_module, "printr", lines)
    return lines


def test_a_failed_start_closes_the_servers_log(monkeypatch, tmp_path):
    errlogs = []

    @asynccontextmanager
    async def stdio_client(server, errlog):
        errlogs.append(errlog)
        errlog.fileno()  # what the subprocess needs
        raise OSError("server not found")
        yield

    lines = _patch(monkeypatch, tmp_path, stdio_client)

    connection = asyncio.run(McpClient().connect(_config()))

    assert not connection.is_connected
    assert errlogs and errlogs[0].closed
    assert (tmp_path / "mcp-local.log").exists()
    # A real failure stays an error.
    assert [color for _text, color in lines.lines] == [LogType.ERROR]


def test_a_tool_call_gives_its_process_a_log_and_closes_it(monkeypatch, tmp_path):
    errlogs = []

    @asynccontextmanager
    async def stdio_client(server, errlog):
        errlogs.append(errlog)
        errlog.fileno()
        yield ("read", "write")

    class Session:
        def __init__(self, read, write):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def initialize(self):
            pass

        async def call_tool(self, name, arguments):
            return "result"

    _patch(monkeypatch, tmp_path, stdio_client)
    monkeypatch.setattr(mcp_module, "ClientSession", Session)
    client = McpClient()
    monkeypatch.setattr(client, "_parse_tool_result", lambda result: result)
    connection = mcp_module.McpConnection(config=_config())

    assert asyncio.run(client._call_tool_stdio(connection, "tool", {})) == "result"
    assert errlogs[0].closed


def test_a_server_waiting_for_authorization_is_a_warning(monkeypatch, tmp_path):
    @asynccontextmanager
    async def stdio_client(server, errlog):
        # anyio wraps the transport's error in a group.
        raise ExceptionGroup("transport", [NeedsAuthorization("Local Server")])
        yield

    lines = _patch(monkeypatch, tmp_path, stdio_client)

    connection = asyncio.run(McpClient().connect(_config(auth=McpAuthType.OAUTH)))

    assert "press Authorize" in connection.error
    assert [color for _text, color in lines.lines] == [LogType.WARNING]
