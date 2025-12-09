"""
MCP Registry with Enum-Based Tool Discovery

This module manages MCP server connections and their tools.
It uses enum-based progressive disclosure where MCP servers are activated via
a constrained enum parameter (no fuzzy search needed).
"""

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

from api.enums import LogType
from api.interface import McpServerConfig, McpToolInfo
from services.mcp_client import McpClient, McpConnection
from services.printr import Printr

if TYPE_CHECKING:
    pass

printr = Printr()


@dataclass
class McpServerManifest:
    """Lightweight metadata about an MCP server for enum-based discovery."""

    name: str
    """Internal server name (e.g., 'wingman_websearch')"""

    display_name: str
    """Human-readable name (e.g., 'Wingman Web Search')"""

    description: str
    """What the server provides - shown in enum tool description"""

    tool_names: list[str] = field(default_factory=list)
    """Names of tools this server provides (prefixed)"""

    tool_summaries: list[str] = field(default_factory=list)
    """One-line descriptions of each tool"""

    is_connected: bool = False
    """Whether the server is currently connected"""

    @classmethod
    def from_connection(cls, connection: McpConnection) -> "McpServerManifest":
        """Create a manifest from an MCP connection."""
        tool_names = [t.prefixed_name for t in connection.tools]
        tool_summaries = [t.description[:100] for t in connection.tools]

        return cls(
            name=connection.config.name,
            display_name=connection.config.display_name,
            description=connection.config.description
            or f"MCP server: {connection.config.display_name}",
            tool_names=tool_names,
            tool_summaries=tool_summaries,
            is_connected=connection.is_connected,
        )

    def get_short_description(self, max_length: int = 80) -> str:
        """Get a shortened description for enum display."""
        if len(self.description) <= max_length:
            return self.description
        return self.description[: max_length - 3] + "..."

    def to_summary(self) -> str:
        """Returns a compact string representation for LLM context."""
        status = "🟢 Connected" if self.is_connected else "⚪ Available"
        tools_str = (
            ", ".join(self.tool_names[:5]) if self.tool_names else "No tools loaded"
        )
        if len(self.tool_names) > 5:
            tools_str += f", and {len(self.tool_names) - 5} more"
        return f"**{self.display_name}** (id: {self.name}) [{status}]\n  {self.description}\n  Tools: {tools_str}"


class McpRegistry:
    """
    Central registry for MCP servers with enum-based discovery.

    Enum-based discovery:
    - The activate_mcp_server tool has an enum of all connected server IDs
    - LLM sees descriptions in tool definition and picks the right one
    - No fuzzy search needed - works reliably in any language
    """

    def __init__(
        self,
        mcp_client: McpClient,
        wingman_name: str = "",
        on_state_changed: Optional[Callable[[], None]] = None,
    ):
        self._client = mcp_client
        self._wingman_name = wingman_name
        self._on_state_changed = on_state_changed
        """Optional callback when MCP connection state changes (connect/disconnect)."""

        self._connections: dict[str, McpConnection] = {}
        """Active MCP connections by server name"""

        self._manifests: dict[str, McpServerManifest] = {}
        """Server manifests for progressive disclosure"""

        self._active_servers: set[str] = set()
        """Currently activated servers (their tools are available to LLM)"""

        self._tool_to_server: dict[str, str] = {}
        """Maps prefixed tool names to server names"""

        self._prefixed_to_original: dict[str, str] = {}
        """Maps prefixed tool names to original tool names"""

    async def _notify_state_changed(self):
        """Notify listeners that MCP state has changed."""
        if self._on_state_changed:
            # Small delay to ensure state has fully propagated before UI refresh
            await asyncio.sleep(0.3)
            self._on_state_changed()

    @property
    def client(self) -> McpClient:
        """Access the underlying MCP client."""
        return self._client

    def get_connected_server_names(self) -> set[str]:
        """Get the names of all currently connected servers."""
        return {name for name, conn in self._connections.items() if conn.is_connected}

    def get_server_tools(self, server_name: str) -> list[McpToolInfo]:
        """Get the list of tools for a connected server."""
        connection = self._connections.get(server_name)
        if connection and connection.is_connected:
            return connection.tools
        return []

    def get_server_error(self, server_name: str) -> Optional[str]:
        """Get the error message for a server if connection failed."""
        connection = self._connections.get(server_name)
        if connection and not connection.is_connected and connection.error:
            return connection.error
        return None

    def set_server_error(self, server_name: str, error: str) -> None:
        """Set an error message for a server (e.g., on timeout)."""
        connection = self._connections.get(server_name)
        if connection:
            connection.error = error
            connection.is_connected = False

    async def register_server(
        self,
        config: McpServerConfig,
        headers: Optional[dict[str, str]] = None,
        auto_activate: bool = True,
    ) -> McpConnection:
        """
        Register and connect to an MCP server.

        Args:
            config: Server configuration
            headers: Optional headers (e.g., API keys from SecretKeeper)
            auto_activate: Whether to automatically activate the server

        Returns:
            The connection object
        """
        connection = await self._client.connect(config, headers)

        if connection.is_connected:
            self._connections[config.name] = connection
            self._manifests[config.name] = McpServerManifest.from_connection(connection)

            # Map tool names to server
            for tool in connection.tools:
                self._tool_to_server[tool.prefixed_name] = config.name
                self._prefixed_to_original[tool.prefixed_name] = tool.name

            if auto_activate:
                self._active_servers.add(config.name)

            # Notify UI that MCP state has changed (after registry is updated)
            await self._notify_state_changed()

        return connection

    async def unregister_server(self, server_name: str) -> None:
        """Disconnect and remove an MCP server."""
        connection = self._connections.get(server_name)
        if connection:
            # Remove tool mappings
            for tool in connection.tools:
                self._tool_to_server.pop(tool.prefixed_name, None)
                self._prefixed_to_original.pop(tool.prefixed_name, None)

            await self._client.disconnect(connection)
            self._connections.pop(server_name, None)
            self._manifests.pop(server_name, None)
            self._active_servers.discard(server_name)

            # Notify UI that MCP state has changed
            await self._notify_state_changed()

    async def clear(self) -> None:
        """Disconnect from all servers and clear the registry."""
        server_names = list(self._connections.keys())
        for server_name in server_names:
            await self.unregister_server(server_name)

    def get_connected_servers(self) -> list[McpServerManifest]:
        """Get all connected MCP server manifests."""
        return [m for m in self._manifests.values() if m.is_connected]

    def activate_server(self, server_name: str) -> tuple[bool, str]:
        """
        Activate an MCP server, making its tools available to the LLM.

        Returns:
            (success, message) tuple
        """
        if server_name not in self._connections:
            available = ", ".join(self._manifests.keys())
            return (
                False,
                f"MCP server '{server_name}' not found. Available: {available}",
            )

        connection = self._connections[server_name]
        if not connection.is_connected:
            return False, f"MCP server '{server_name}' is not connected."

        self._active_servers.add(server_name)
        manifest = self._manifests[server_name]
        tools_str = ", ".join(manifest.tool_names[:5])
        if len(manifest.tool_names) > 5:
            tools_str += f", +{len(manifest.tool_names) - 5} more"

        prefix = f"[{self._wingman_name}] " if self._wingman_name else ""
        printr.print(
            f"{prefix} MCP activated: {manifest.display_name}",
            color=LogType.MCP,
            source_name=self._wingman_name if self._wingman_name else None,
            # Always show activation in UI - important for users to know
        )
        return (
            True,
            f"Activated '{manifest.display_name}'. Available tools: {tools_str}",
        )

    def deactivate_server(self, server_name: str) -> tuple[bool, str]:
        """Deactivate an MCP server, removing its tools from availability."""
        if server_name not in self._active_servers:
            return False, f"MCP server '{server_name}' is not active."

        self._active_servers.discard(server_name)
        manifest = self._manifests.get(server_name)
        display_name = manifest.display_name if manifest else server_name

        prefix = f"[{self._wingman_name}] " if self._wingman_name else ""
        printr.print(
            f"{prefix}MCP deactivated: {display_name}",
            color=LogType.MCP,
            source_name=self._wingman_name if self._wingman_name else None,
            server_only=True,  # Deactivation is internal, keep in log
        )
        return True, f"Deactivated '{display_name}'."

    def reset_activations(self) -> None:
        """Reset all server activations (called on conversation reset)."""
        if self._active_servers:
            count = len(self._active_servers)
            prefix = f"[{self._wingman_name}] " if self._wingman_name else ""
            printr.print(
                f"{prefix}Conversation reset: deactivating {count} MCP server(s)",
                color=LogType.MCP,
                source_name=self._wingman_name if self._wingman_name else None,
                server_only=True,  # Reset is internal, keep in log
            )
        self._active_servers.clear()

    def get_connection_for_tool(
        self, prefixed_tool_name: str
    ) -> Optional[McpConnection]:
        """Get the connection that provides a given tool."""
        server_name = self._tool_to_server.get(prefixed_tool_name)
        if server_name:
            return self._connections.get(server_name)
        return None

    def get_original_tool_name(self, prefixed_tool_name: str) -> Optional[str]:
        """Get the original tool name from a prefixed name."""
        return self._prefixed_to_original.get(prefixed_tool_name)

    def get_active_tools(self) -> list[tuple[str, dict]]:
        """
        Get tool definitions from all active MCP servers.

        Returns:
            List of (prefixed_tool_name, tool_definition) tuples
        """
        tools = []
        for server_name in self._active_servers:
            connection = self._connections.get(server_name)
            if connection and connection.is_connected:
                tools.extend(self._client.get_tool_definitions(connection))
        return tools

    def get_all_tools(self) -> list[tuple[str, dict]]:
        """
        Get tool definitions from ALL connected MCP servers (regardless of activation).

        Returns:
            List of (prefixed_tool_name, tool_definition) tuples
        """
        tools = []
        for connection in self._connections.values():
            if connection.is_connected:
                tools.extend(self._client.get_tool_definitions(connection))
        return tools

    def get_meta_tools(self) -> list[tuple[str, dict]]:
        """
        Returns meta-tools for enum-based MCP server discovery.
        Uses enum constraint for reliable activation in any language.
        """
        connected = self.get_connected_servers()

        if not connected:
            return []  # No MCP servers connected

        # Build enum values (server IDs)
        server_ids = [m.name for m in connected]

        # Build descriptions for the tool (helps LLM choose correctly)
        server_descriptions = []
        for m in connected:
            short_desc = m.get_short_description(60)
            server_descriptions.append(f"- {m.name}: {short_desc}")

        descriptions_block = "\n".join(server_descriptions)

        return [
            (
                "activate_mcp_server",
                {
                    "type": "function",
                    "function": {
                        "name": "activate_mcp_server",
                        "description": f"Activate an MCP server to use its tools. Pick based on what you need:\n\n{descriptions_block}",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "server_name": {
                                    "type": "string",
                                    "enum": server_ids,
                                    "description": "The MCP server to activate",
                                },
                            },
                            "required": ["server_name"],
                        },
                    },
                },
            ),
            (
                "list_active_mcp_servers",
                {
                    "type": "function",
                    "function": {
                        "name": "list_active_mcp_servers",
                        "description": "List currently activated MCP servers and their available tools.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                        },
                    },
                },
            ),
        ]

    def execute_meta_tool(self, tool_name: str, parameters: dict) -> tuple[str, bool]:
        """
        Execute an MCP meta-tool.

        Returns:
            (result_string, tools_changed) - tools_changed indicates if the LLM
            should receive an updated tool list
        """
        # Debug logging for developers (server-only)
        prefix = f"[{self._wingman_name}] " if self._wingman_name else ""
        printr.print(
            f"{prefix}Meta-tool called: {tool_name}({parameters})",
            color=LogType.MCP,
            source_name=self._wingman_name if self._wingman_name else None,
            server_only=True,
        )

        if tool_name == "activate_mcp_server":
            server_name = parameters.get("server_name", "")
            success, message = self.activate_server(server_name)
            return message, success

        elif tool_name == "list_active_mcp_servers":
            if not self._active_servers:
                return (
                    "No MCP servers are currently active. Use activate_mcp_server to enable one.",
                    False,
                )

            parts = [
                f"Currently active MCP servers ({len(self._active_servers)} total):\n"
            ]
            for server_name in self._active_servers:
                manifest = self._manifests.get(server_name)
                if manifest:
                    tools = (
                        ", ".join(manifest.tool_names)
                        if manifest.tool_names
                        else "no tools"
                    )
                    parts.append(f"- {manifest.display_name}: {tools}")
            return "\n".join(parts), False

        return f"Unknown MCP meta-tool: {tool_name}", False

    def is_meta_tool(self, tool_name: str) -> bool:
        """Check if a tool name is an MCP meta-tool."""
        return tool_name in {"activate_mcp_server", "list_active_mcp_servers"}

    def is_mcp_tool(self, tool_name: str) -> bool:
        """Check if a tool name is from an MCP server."""
        return tool_name in self._tool_to_server

    async def call_tool(
        self,
        prefixed_tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """
        Call an MCP tool by its prefixed name.

        Args:
            prefixed_tool_name: The prefixed tool name (e.g., 'mcp_context7_resolve_library')
            arguments: Tool arguments

        Returns:
            The tool result as a string
        """
        connection = self.get_connection_for_tool(prefixed_tool_name)
        if not connection:
            return f"Error: No MCP server found for tool {prefixed_tool_name}"

        original_name = self.get_original_tool_name(prefixed_tool_name)
        if not original_name:
            return f"Error: Could not resolve tool name {prefixed_tool_name}"

        return await self._client.call_tool(connection, original_name, arguments)

    @property
    def server_count(self) -> int:
        """Number of connected servers."""
        return len(self._connections)

    @property
    def active_server_count(self) -> int:
        """Number of currently active servers."""
        return len(self._active_servers)

    @property
    def active_server_names(self) -> set[str]:
        """Names of currently active servers."""
        return self._active_servers.copy()
