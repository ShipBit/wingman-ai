"""
MCP (Model Context Protocol) Client Service

This module provides client functionality for connecting to MCP servers
using various transport types (stdio, HTTP, SSE).

MCP servers expose tools that can be used by the LLM, similar to skills.

ARCHITECTURE NOTE:
The MCP SDK uses anyio task groups internally for its transports. The context
managers (streamablehttp_client, etc.) spawn background tasks for reading/writing.
These tasks must remain active while the session is in use.

For SSE transport specifically:
- The SSE client runs an anyio task group with a reader task that continuously
  listens for server-sent events. This can interfere with the main event loop
  if not properly isolated.
- We run SSE connections in a dedicated background thread with its own event loop
  to completely isolate them from the main application event loop (keyboard, etc.)
- Tool calls are executed via thread-safe communication with the SSE thread

For HTTP/STDIO:
- HTTP: Per-call connections (stateless)
- STDIO: Per-call connections (local process, to avoid anyio task group issues)
"""

import asyncio
import concurrent.futures
import json
import logging
import threading
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

    # Suppress verbose INFO logs from MCP SDK and its dependencies
    logging.getLogger("mcp").setLevel(logging.WARNING)
    logging.getLogger("mcp.client.sse").setLevel(logging.WARNING)
    logging.getLogger("mcp.client.streamable_http").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
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
    session: Optional[Any] = None  # ClientSession when connected (STDIO/SSE)
    tools: list[McpToolInfo] = field(default_factory=list)
    is_connected: bool = False
    error: Optional[str] = None

    # HTTP/SSE connections store merged headers for per-call connections
    merged_headers: dict[str, str] = field(default_factory=dict)

    # Connection resources that need cleanup (for STDIO only - HTTP uses per-call)
    read_stream: Any = None
    write_stream: Any = None
    context_manager: Any = None
    session_context: Any = None

    # SSE-specific: dedicated thread with its own event loop
    sse_thread: Optional[threading.Thread] = None
    sse_loop: Optional[asyncio.AbstractEventLoop] = None
    sse_shutdown_event: Optional[threading.Event] = None
    sse_ready_event: Optional[threading.Event] = None
    sse_error: Optional[str] = None
    sse_connection_alive: bool = False  # True when SSE stream is actually open


class McpClient:
    """
    Client for connecting to and interacting with MCP servers.

    Supports three transport types:
    - HTTP: For hosted MCP servers (like Context7, Svelte MCP)
      Uses per-call connections since HTTP is stateless.
    - SSE: For Server-Sent Events based servers
      Runs in a dedicated background thread with its own event loop to avoid
      blocking the main event loop (keyboard handling, etc.)
    - STDIO: For local processes (like Docker MCP)
      Maintains persistent connections since local process overhead is minimal.

    Usage:
        client = McpClient(wingman_name="MyWingman")
        connection = await client.connect(config)
        if connection.is_connected:
            tools = connection.tools
            result = await client.call_tool(connection, "tool_name", {"arg": "value"})
        await client.disconnect(connection)
    """

    def __init__(self, wingman_name: str = ""):
        self._connections: dict[str, McpConnection] = {}
        self._wingman_name = wingman_name

    @staticmethod
    def _format_auth_error(config: McpServerConfig, exception: Exception) -> str:
        """
        Format authentication errors with clear instructions.

        Checks if the exception is a 401 authentication error and returns
        a user-friendly message with instructions on how to add the required secret.

        Args:
            config: The MCP server configuration
            exception: The exception that occurred

        Returns:
            Formatted error message
        """
        # Check if this is an ExceptionGroup (from anyio TaskGroup)
        # and extract nested exceptions
        exceptions_to_check = [exception]

        if hasattr(exception, "exceptions"):
            # This is an ExceptionGroup, get the nested exceptions
            exceptions_to_check.extend(exception.exceptions)

        # Check all exceptions for 401/auth errors
        for exc in exceptions_to_check:
            error_str = str(exc).lower()

            # Check for 401 in string representation
            if (
                "401" in error_str
                or "unauthorized" in error_str
                or "authentication" in error_str
            ):
                return f"MCP server '{config.display_name}' requires authentication. Please add a secret called mcp_{config.name}."

            # Check if it's an httpx.HTTPStatusError with 401 status code
            if hasattr(exc, "response"):
                response = getattr(exc, "response", None)
                if (
                    response
                    and hasattr(response, "status_code")
                    and response.status_code == 401
                ):
                    return f"MCP server '{config.display_name}' requires authentication. Please add a secret called mcp_{config.name}."

        # Return original error for non-auth issues
        return str(exception)

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
                    color=LogType.MCP,
                    source_name=self._wingman_name if self._wingman_name else None,
                    server_only=True,
                )
                # Note: State change notification is handled by McpRegistry after
                # it has updated its own state

        except Exception as e:
            # Format error with special handling for authentication errors
            connection.error = self._format_auth_error(config, e)
            connection.is_connected = False
            await printr.print_async(
                f"MCP connection failed ({config.display_name}): {connection.error}",
                color=LogType.ERROR,
                source_name=self._wingman_name if self._wingman_name else None,
                server_only=False,
            )

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
        connection.merged_headers = headers

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

            connection.context_manager = context_manager
            connection.read_stream = read_stream
            connection.write_stream = write_stream

            # Create and initialize session
            session = ClientSession(read_stream, write_stream)
            session_context = await session.__aenter__()
            connection.session_context = session

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
        """
        Connect using SSE (Server-Sent Events) transport.

        SSE connections run in a dedicated background thread with their own event loop.
        This completely isolates them from the main event loop, preventing any
        interference with keyboard handling and other async operations.

        The thread maintains a persistent connection and handles tool calls via
        thread-safe futures.
        """
        config = connection.config
        if not config.url:
            connection.error = "URL is required for SSE transport"
            return

        # Store headers for later use
        connection.merged_headers = headers

        # Create thread synchronization primitives
        connection.sse_shutdown_event = threading.Event()
        connection.sse_ready_event = threading.Event()
        connection.sse_error = None
        connection.sse_connection_alive = False

        # Storage for the session (will be set by the SSE thread)
        sse_session_holder: dict[str, Any] = {"session": None, "loop": None}

        def run_sse_event_loop():
            """Run SSE connection in a dedicated thread with its own event loop."""

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            connection.sse_loop = loop

            async def maintain_sse_connection():
                try:
                    async with sse_client(
                        url=config.url,
                        headers=headers if headers else None,
                        timeout=30,
                        sse_read_timeout=300,  # 5 min keep-alive
                    ) as (read_stream, write_stream):
                        async with ClientSession(read_stream, write_stream) as session:
                            await session.initialize()

                            # Fetch tools
                            tools_response = await session.list_tools()
                            connection.tools = []

                            for tool in tools_response.tools:
                                prefixed_name = f"mcp_{connection.config.name}_{tool.name}"
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

                            # Store session reference for tool calls
                            sse_session_holder["session"] = session
                            sse_session_holder["loop"] = loop
                            connection.session = session
                            connection.is_connected = True
                            connection.sse_connection_alive = True

                            # Signal that we're ready
                            connection.sse_ready_event.set()

                            # Keep the connection alive until shutdown is requested
                            while not connection.sse_shutdown_event.is_set():
                                await asyncio.sleep(1.0)

                except Exception as e:
                    connection.sse_error = str(e)
                    connection.is_connected = False
                finally:
                    # Mark connection as no longer alive when SSE stream closes
                    connection.sse_connection_alive = False
                    connection.is_connected = False
                    connection.sse_ready_event.set()  # Unblock waiting caller
                    sse_session_holder["session"] = None
                    connection.session = None

            try:
                loop.run_until_complete(maintain_sse_connection())
            finally:
                loop.close()
                connection.sse_loop = None

        # Start the SSE thread
        connection.sse_thread = threading.Thread(
            target=run_sse_event_loop,
            name=f"MCP-SSE-{config.name}",
            daemon=True,
        )
        connection.sse_thread.start()

        # Wait for the connection to be ready (with timeout)
        ready = connection.sse_ready_event.wait(timeout=35)
        if not ready:
            connection.sse_shutdown_event.set()
            connection.error = "SSE connection timeout"
            await self._cleanup_connection(connection)
            raise TimeoutError("SSE connection timeout")

        if connection.sse_error:
            await self._cleanup_connection(connection)
            raise Exception(connection.sse_error)

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
            prefix = f"[{self._wingman_name}] " if self._wingman_name else ""
            printr.print(
                f"{prefix}MCP disconnected: {connection.config.display_name}",
                color=LogType.MCP,
                source_name=self._wingman_name if self._wingman_name else None,
                server_only=True,
            )
            # Note: State change notification is handled by McpRegistry

    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers in parallel."""
        connections = list(self._connections.values())
        if connections:
            await asyncio.gather(*[self.disconnect(conn) for conn in connections])

    async def _cleanup_connection(self, connection: McpConnection) -> None:
        """Clean up connection resources with timeouts to prevent blocking."""
        connection.is_connected = False

        # Handle SSE thread cleanup
        if connection.sse_shutdown_event:
            connection.sse_shutdown_event.set()

        if connection.sse_thread and connection.sse_thread.is_alive():
            # Run thread.join in executor to avoid blocking the event loop
            def join_thread():
                if connection.sse_thread:
                    connection.sse_thread.join(timeout=3.0)

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, join_thread)

            # if the thread is still alive after join timeout, we will issue a warning
            if connection.sse_thread and connection.sse_thread.is_alive():
                printr.print(
                    f"SSE thread for {connection.config.name} did not stop within timeout",
                    color=LogType.WARNING,
                    server_only=True,
                )

            connection.sse_thread = None

        connection.sse_loop = None
        connection.sse_shutdown_event = None
        connection.sse_ready_event = None
        connection.sse_error = None
        connection.sse_connection_alive = False

        # Close session with timeout (for STDIO)
        if connection.session_context:
            try:
                await asyncio.wait_for(
                    connection.session_context.__aexit__(None, None, None),
                    timeout=5.0,
                )
            except (asyncio.TimeoutError, Exception):
                # the error during session cleanup is ignored - connection will be closed anyway
                pass
            connection.session_context = None

        connection.session = None

        # Close transport context with timeout (for STDIO)
        if connection.context_manager:
            try:
                await asyncio.wait_for(
                    connection.context_manager.__aexit__(None, None, None),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                # Timeout is acceptable during cleanup - the process will still be terminated
                printr.print(
                    f"Timeout closing STDIO connection for {connection.config.name}",
                    color=LogType.WARNING,
                    server_only=True,
                )
            except Exception as e:
                # Log other errors during cleanup but do not propagate
                printr.print(
                    f"Error closing STDIO connection for {connection.config.name}: {e}",
                    color=LogType.WARNING,
                    server_only=True,
                )
            connection.context_manager = None

        connection.read_stream = None
        connection.write_stream = None

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
            headers=connection.merged_headers if connection.merged_headers else None,
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

    async def _call_tool_sse(
        self,
        connection: McpConnection,
        tool_name: str,
        arguments: dict[str, Any],
        timeout: float = 60.0,
        _retry_on_closed: bool = True,
    ) -> str:
        """
        Call a tool on an SSE MCP server using the persistent connection.

        The SSE connection runs in a dedicated thread. We submit the tool call
        to that thread's event loop and wait for the result via a thread-safe
        future.

        If the connection has been closed (e.g., due to inactivity timeout),
        we automatically attempt to reconnect before making the call.
        """
        # Proactive check: if the SSE thread has exited, the connection is dead
        if connection.sse_thread and not connection.sse_thread.is_alive():
            connection.sse_connection_alive = False
            connection.is_connected = False

        # Check if SSE connection is still alive, attempt reconnect if not
        if not connection.sse_connection_alive or not connection.sse_loop or not connection.session:
            # Retry with exponential backoff
            max_retries = 3
            base_delay = 0.5
            last_error = None

            for attempt in range(max_retries):
                if attempt > 0:
                    delay = base_delay * (2 ** (attempt - 1))
                    printr.print(
                        f"SSE reconnect to {connection.config.display_name} failed, retrying in {delay}s (attempt {attempt + 1}/{max_retries})...",
                        color=LogType.WARNING,
                        server_only=True,
                    )
                    await asyncio.sleep(delay)

                # Clean up the old connection
                await self._cleanup_connection(connection)
                # Attempt reconnect
                try:
                    await self._connect_sse(connection, connection.merged_headers)
                except Exception as e:
                    last_error = e
                    continue

                # Check if reconnect succeeded
                if connection.sse_connection_alive and connection.sse_loop and connection.session:
                    printr.print(
                        f"SSE connection to {connection.config.display_name} reconnected successfully",
                        color=LogType.INFO,
                        server_only=True,
                    )
                    break
            else:
                # All retries exhausted
                raise RuntimeError(
                    f"Failed to reconnect SSE connection to {connection.config.display_name} after {max_retries} attempts: {last_error}"
                )

        # Create a future to get the result from the SSE thread
        loop = asyncio.get_event_loop()

        async def call_in_sse_thread():
            result = await connection.session.call_tool(tool_name, arguments)
            return self._parse_tool_result(result)

        # Schedule the coroutine in the SSE thread's event loop
        future = asyncio.run_coroutine_threadsafe(
            call_in_sse_thread(),
            connection.sse_loop,
        )

        try:
            # Wait for the result with timeout
            result = await asyncio.wait_for(
                loop.run_in_executor(None, future.result, timeout),
                timeout=timeout + 5,
            )
            return result
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise asyncio.TimeoutError(f"SSE tool call timed out: {tool_name}")
        except Exception as e:
            # Check if this is a ClosedResourceError or similar connection issue.
            # Note: anyio.ClosedResourceError has an empty str() representation,
            # so we must also check the exception type name.
            error_str = str(e).lower()
            error_type = type(e).__name__.lower()
            if "closedresource" in error_type or "closed" in error_str:
                # Mark connection as no longer alive
                connection.sse_connection_alive = False
                connection.is_connected = False

                # Retry once after reconnect if enabled
                if _retry_on_closed:
                    printr.print(
                        f"SSE connection closed during tool call, will reconnect and retry...",
                        color=LogType.WARNING,
                        server_only=True,
                    )
                    # Recursive call with retry disabled to avoid infinite loops
                    return await self._call_tool_sse(
                        connection, tool_name, arguments, timeout, _retry_on_closed=False
                    )
            raise

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
        # SSE has its own reconnection logic in _call_tool_sse, so let it through
        if not connection.is_connected and connection.config.type != McpTransportType.SSE:
            return f"Error: Not connected to MCP server {connection.config.name}"

        try:
            # HTTP/STDIO: per-call connections to avoid anyio task group issues
            # SSE: uses persistent connection in dedicated thread (thread-safe)
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
            elif connection.config.type == McpTransportType.SSE:
                result_str = await asyncio.wait_for(
                    self._call_tool_sse(connection, tool_name, arguments, timeout),
                    timeout=timeout + 5,
                )
            else:
                return f"Error: Unknown transport type {connection.config.type}"

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
                await self._connect_http(connection, connection.merged_headers)
            else:
                await self._fetch_tools(connection)
