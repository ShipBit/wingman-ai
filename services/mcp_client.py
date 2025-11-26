"""
MCP (Model Context Protocol) Client Service

This module provides client functionality for connecting to MCP servers
using various transport types (stdio, HTTP, SSE).

MCP servers expose tools that can be used by the LLM, similar to skills.

ARCHITECTURE NOTE:
The MCP SDK uses anyio task groups internally for its transports. The context
managers (streamablehttp_client, etc.) spawn background tasks for reading/writing.
These tasks must remain active while the session is in use. We use two strategies:

1. For HTTP transport: Make per-call connections since HTTP is stateless anyway
2. For STDIO/SSE: Keep a background task running that manages the session lifecycle
"""

import asyncio
import json
import traceback
from dataclasses import dataclass, field
from typing import Any, Optional

from api.enums import LogType, McpTransportType
from api.interface import McpServerConfig, McpToolInfo
from services.printr import Printr

printr = Printr()

# Check if MCP SDK is available
try:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client, StdioServerParameters
    from mcp.client.streamable_http import streamablehttp_client
    from mcp.client.sse import sse_client

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    printr.print(
        "MCP SDK not installed. Run 'pip install mcp' to enable MCP support.",
        color=LogType.WARNING,
        server_only=True,
    )


@dataclass
class McpConnection:
    """Represents an active connection to an MCP server."""

    config: McpServerConfig
    session: Optional[Any] = None  # ClientSession when connected (not used for HTTP)
    tools: list[McpToolInfo] = field(default_factory=list)
    is_connected: bool = False
    error: Optional[str] = None

    # HTTP connections store merged headers for per-call connections
    _merged_headers: dict[str, str] = field(default_factory=dict)

    # Connection resources that need cleanup (for STDIO/SSE only)
    _read_stream: Any = None
    _write_stream: Any = None
    _context_manager: Any = None
    _session_context: Any = None


class McpClient:
    """
    Client for connecting to and interacting with MCP servers.

    Supports three transport types:
    - HTTP: For hosted MCP servers (like Context7, Svelte MCP)
      Uses per-call connections since HTTP is stateless.
    - STDIO: For local processes (like Docker MCP)
    - SSE: For Server-Sent Events based servers

    Usage:
        client = McpClient()
        connection = await client.connect(config)
        if connection.is_connected:
            tools = connection.tools
            result = await client.call_tool(connection, "tool_name", {"arg": "value"})
        await client.disconnect(connection)
    """

    def __init__(self):
        self._connections: dict[str, McpConnection] = {}

    @property
    def is_available(self) -> bool:
        """Check if MCP SDK is installed and available."""
        return MCP_AVAILABLE

    def get_connection(self, server_name: str) -> Optional[McpConnection]:
        """Get an existing connection by server name."""
        return self._connections.get(server_name)

    def get_all_connections(self) -> list[McpConnection]:
        """Get all active connections."""
        return list(self._connections.values())

    async def connect(
        self,
        config: McpServerConfig,
        headers: Optional[dict[str, str]] = None,
    ) -> McpConnection:
        """
        Connect to an MCP server.

        Args:
            config: The MCP server configuration
            headers: Optional headers to merge with config headers (for secrets)

        Returns:
            McpConnection with connection state and available tools
        """
        if not MCP_AVAILABLE:
            return McpConnection(
                config=config,
                is_connected=False,
                error="MCP SDK not installed. Run 'pip install mcp' to enable MCP support.",
            )

        # Check if already connected
        if config.name in self._connections:
            existing = self._connections[config.name]
            if existing.is_connected:
                return existing
            # Cleanup failed connection before retry
            await self._cleanup_connection(existing)

        connection = McpConnection(config=config)

        try:
            # Merge headers from config and provided headers
            merged_headers = {}
            if config.headers:
                merged_headers.update(config.headers)
            if headers:
                merged_headers.update(headers)

            if config.type == McpTransportType.HTTP:
                await self._connect_http(connection, merged_headers)
            elif config.type == McpTransportType.STDIO:
                await self._connect_stdio(connection)
            elif config.type == McpTransportType.SSE:
                await self._connect_sse(connection, merged_headers)
            else:
                connection.error = f"Unsupported transport type: {config.type}"

            if connection.is_connected:
                self._connections[config.name] = connection
                printr.print(
                    f"MCP connected: {config.display_name} ({len(connection.tools)} tools)",
                    color=LogType.INFO,
                    server_only=True,
                )

        except Exception as e:
            connection.error = str(e)
            connection.is_connected = False
            printr.print(
                f"MCP connection failed ({config.display_name}): {e}",
                color=LogType.ERROR,
                server_only=True,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

        return connection

    async def _connect_http(
        self, connection: McpConnection, headers: dict[str, str]
    ) -> None:
        """
        Connect using HTTP/Streamable HTTP transport.

        For HTTP transport, we use per-call connections since HTTP is stateless.
        We just validate the connection works and fetch the tools list here.
        The actual tool calls will create fresh connections each time.
        """
        config = connection.config
        if not config.url:
            connection.error = "URL is required for HTTP transport"
            return

        # Store headers for later use in tool calls
        connection._merged_headers = headers

        try:
            # Use proper async with context to verify connection and get tools
            async with streamablehttp_client(
                url=config.url,
                headers=headers if headers else None,
                timeout=30,
                sse_read_timeout=30,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    # Fetch available tools
                    tools_response = await session.list_tools()
                    connection.tools = []

                    for tool in tools_response.tools:
                        prefixed_name = f"mcp_{connection.config.name}_{tool.name}"
                        # Convert input schema to dict if present
                        input_schema = None
                        if tool.inputSchema:
                            # The inputSchema is already a dict-like object
                            input_schema = (
                                dict(tool.inputSchema)
                                if hasattr(tool.inputSchema, "items")
                                else tool.inputSchema
                            )

                        tool_info = McpToolInfo(
                            name=tool.name,
                            prefixed_name=prefixed_name,
                            description=tool.description
                            or f"Tool from {connection.config.display_name}",
                            server_name=connection.config.name,
                            input_schema=input_schema,
                        )
                        connection.tools.append(tool_info)

            # Mark as connected (even though we don't keep a persistent session)
            connection.is_connected = True

        except Exception:
            # No cleanup needed for HTTP - context manager handles it
            raise

    async def _connect_stdio(self, connection: McpConnection) -> None:
        """Connect using STDIO transport (local process)."""
        config = connection.config
        if not config.command:
            connection.error = "Command is required for STDIO transport"
            return

        try:
            # Build server parameters
            server_params = StdioServerParameters(
                command=config.command,
                args=config.args or [],
                env=config.env,
            )

            # Create the stdio client context
            context_manager = stdio_client(server_params)

            # Enter the context to get streams
            streams = await context_manager.__aenter__()
            read_stream, write_stream = streams

            connection._context_manager = context_manager
            connection._read_stream = read_stream
            connection._write_stream = write_stream

            # Create and initialize session
            session = ClientSession(read_stream, write_stream)
            session_context = await session.__aenter__()
            connection._session_context = session

            await session.initialize()
            connection.session = session
            connection.is_connected = True

            # Fetch available tools
            await self._fetch_tools(connection)

        except Exception as e:
            await self._cleanup_connection(connection)
            raise

    async def _connect_sse(
        self, connection: McpConnection, headers: dict[str, str]
    ) -> None:
        """Connect using SSE (Server-Sent Events) transport."""
        config = connection.config
        if not config.url:
            connection.error = "URL is required for SSE transport"
            return

        try:
            # Create the SSE client context
            context_manager = sse_client(
                url=config.url,
                headers=headers if headers else None,
            )

            # Enter the context to get streams
            streams = await context_manager.__aenter__()
            read_stream, write_stream = streams

            connection._context_manager = context_manager
            connection._read_stream = read_stream
            connection._write_stream = write_stream

            # Create and initialize session
            session = ClientSession(read_stream, write_stream)
            session_context = await session.__aenter__()
            connection._session_context = session

            await session.initialize()
            connection.session = session
            connection.is_connected = True

            # Fetch available tools
            await self._fetch_tools(connection)

        except Exception as e:
            await self._cleanup_connection(connection)
            raise

    async def _fetch_tools(self, connection: McpConnection) -> None:
        """Fetch and store available tools from the connected server."""
        if not connection.session:
            return

        try:
            tools_response = await connection.session.list_tools()
            connection.tools = []

            for tool in tools_response.tools:
                # Create prefixed tool name to avoid collisions
                prefixed_name = f"mcp_{connection.config.name}_{tool.name}"
                # Convert input schema to dict if present
                input_schema = None
                if tool.inputSchema:
                    input_schema = (
                        dict(tool.inputSchema)
                        if hasattr(tool.inputSchema, "items")
                        else tool.inputSchema
                    )

                tool_info = McpToolInfo(
                    name=tool.name,
                    prefixed_name=prefixed_name,
                    description=tool.description
                    or f"Tool from {connection.config.display_name}",
                    server_name=connection.config.name,
                    input_schema=input_schema,
                )
                connection.tools.append(tool_info)

        except Exception as e:
            printr.print(
                f"Failed to fetch tools from {connection.config.display_name}: {e}",
                color=LogType.WARNING,
                server_only=True,
            )

    async def disconnect(self, connection: McpConnection) -> None:
        """Disconnect from an MCP server."""
        if connection.config.name in self._connections:
            del self._connections[connection.config.name]

        await self._cleanup_connection(connection)

        if connection.config:
            printr.print(
                f"MCP disconnected: {connection.config.display_name}",
                color=LogType.INFO,
                server_only=True,
            )

    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers."""
        connections = list(self._connections.values())
        for connection in connections:
            await self.disconnect(connection)

    async def _cleanup_connection(self, connection: McpConnection) -> None:
        """Clean up connection resources."""
        connection.is_connected = False

        # Close session
        if connection._session_context:
            try:
                await connection._session_context.__aexit__(None, None, None)
            except Exception:
                pass
            connection._session_context = None

        connection.session = None

        # Close transport context
        if connection._context_manager:
            try:
                await connection._context_manager.__aexit__(None, None, None)
            except Exception:
                pass
            connection._context_manager = None

        connection._read_stream = None
        connection._write_stream = None

    async def _call_tool_http(
        self,
        connection: McpConnection,
        tool_name: str,
        arguments: dict[str, Any],
        timeout: float = 60.0,
    ) -> str:
        """
        Call a tool on an HTTP MCP server using a fresh connection.

        HTTP transport uses per-call connections because:
        1. HTTP is inherently stateless
        2. The MCP SDK's anyio task groups require proper context manager usage
        3. Fresh connections avoid any session state issues
        """
        config = connection.config

        async with streamablehttp_client(
            url=config.url,
            headers=connection._merged_headers if connection._merged_headers else None,
            timeout=timeout,
            sse_read_timeout=timeout,
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                return self._parse_tool_result(result)

    async def _call_tool_stdio(
        self,
        connection: McpConnection,
        tool_name: str,
        arguments: dict[str, Any],
        timeout: float = 60.0,
    ) -> str:
        """
        Call a tool on a STDIO MCP server using a fresh connection per call.

        Like HTTP, we create a fresh connection for each call to avoid
        anyio task group issues that cause blocking.
        """
        config = connection.config

        server_params = StdioServerParameters(
            command=config.command,
            args=config.args or [],
            env=config.env,
        )

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                return self._parse_tool_result(result)

    def _parse_tool_result(self, result) -> str:
        """Parse a tool result into a string."""
        # Parse the result content
        if result.content:
            text_parts = []
            for content in result.content:
                if hasattr(content, "text"):
                    text_parts.append(content.text)
                elif hasattr(content, "data"):
                    text_parts.append(f"[Binary data: {len(content.data)} bytes]")
                else:
                    text_parts.append(str(content))
            return "\n".join(text_parts)

        # Check for structured content
        if hasattr(result, "structuredContent") and result.structuredContent:
            return json.dumps(result.structuredContent, indent=2)

        return "Tool executed successfully (no output)"

    async def call_tool(
        self,
        connection: McpConnection,
        tool_name: str,
        arguments: dict[str, Any],
        timeout: float = 60.0,
    ) -> str:
        """
        Call a tool on the connected MCP server.

        Args:
            connection: The MCP connection
            tool_name: The original tool name (without mcp_ prefix)
            arguments: Tool arguments
            timeout: Timeout in seconds for the tool call (default 60s)

        Returns:
            The tool result as a string
        """
        if not connection.is_connected:
            return f"Error: Not connected to MCP server {connection.config.name}"

        try:
            # Use per-call connections for both HTTP and STDIO to avoid
            # anyio task group blocking issues
            if connection.config.type == McpTransportType.HTTP:
                result_str = await asyncio.wait_for(
                    self._call_tool_http(connection, tool_name, arguments, timeout),
                    timeout=timeout + 5,
                )
            elif connection.config.type == McpTransportType.STDIO:
                result_str = await asyncio.wait_for(
                    self._call_tool_stdio(connection, tool_name, arguments, timeout),
                    timeout=timeout + 5,
                )
            else:
                # SSE - still uses persistent session (may need similar fix)
                if not connection.session:
                    return f"Error: No session for MCP server {connection.config.name}"
                result = await asyncio.wait_for(
                    connection.session.call_tool(tool_name, arguments),
                    timeout=timeout,
                )
                result_str = self._parse_tool_result(result)

            return result_str

        except asyncio.TimeoutError:
            error_msg = f"Tool call timed out after {timeout}s: {tool_name}"
            printr.print(error_msg, color=LogType.ERROR, server_only=True)
            return f"Error: {error_msg}"
        except Exception as e:
            error_msg = f"Tool call failed ({tool_name}): {e}"
            printr.print(error_msg, color=LogType.ERROR, server_only=True)
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return f"Error: {error_msg}"

    def get_tool_definitions(self, connection: McpConnection) -> list[tuple[str, dict]]:
        """
        Get OpenAI-compatible tool definitions for all tools in a connection.

        Returns:
            List of (prefixed_tool_name, tool_definition) tuples
        """
        if not connection.is_connected:
            return []

        definitions = []
        for tool_info in connection.tools:
            # Build OpenAI-compatible tool definition
            # Use the cached input schema if available
            if tool_info.input_schema:
                parameters = tool_info.input_schema
            else:
                parameters = {
                    "type": "object",
                    "properties": {},
                }

            tool_def = {
                "type": "function",
                "function": {
                    "name": tool_info.prefixed_name,
                    "description": f"[MCP: {connection.config.display_name}] {tool_info.description}",
                    "parameters": parameters,
                },
            }

            definitions.append((tool_info.prefixed_name, tool_def))

        return definitions

    async def refresh_tools(self, connection: McpConnection) -> None:
        """Refresh the list of available tools from the server."""
        if connection.is_connected:
            if connection.config.type == McpTransportType.HTTP:
                # For HTTP, reconnect to refresh tools
                await self._connect_http(connection, connection._merged_headers)
            else:
                await self._fetch_tools(connection)
