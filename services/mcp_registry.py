"""
MCP Registry with Progressive Tool Disclosure

This module manages MCP server connections and their tools, similar to SkillRegistry.
It supports progressive disclosure where MCP servers can be searched and activated on-demand.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from api.enums import LogType
from api.interface import McpServerConfig, McpToolInfo
from services.mcp_client import McpClient, McpConnection
from services.printr import Printr

if TYPE_CHECKING:
    pass

printr = Printr()


@dataclass
class McpServerManifest:
    """Lightweight metadata about an MCP server for progressive disclosure."""

    name: str
    """Internal server name (e.g., 'context7')"""

    display_name: str
    """Human-readable name (e.g., 'Context7 Documentation')"""

    description: str
    """What the server provides - used for semantic search"""

    tool_names: list[str] = field(default_factory=list)
    """Names of tools this server provides (prefixed)"""

    tool_summaries: list[str] = field(default_factory=list)
    """One-line descriptions of each tool"""

    aliases: list[str] = field(default_factory=list)
    """Alternative search terms for this server (from config)"""

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
            aliases=connection.config.aliases or [],
            is_connected=connection.is_connected,
        )

    def matches_query(self, query: str) -> float:
        """
        Returns a relevance score (0-1) for how well this server matches the query.
        Uses word-based matching with alias support for fuzzy search.
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())

        # Check aliases first - if query matches an alias, high score
        for alias in self.aliases:
            alias_lower = alias.lower()
            if alias_lower in query_lower or query_lower in alias_lower:
                return 0.9  # High score for alias match

        # Also check for the full query as a phrase
        name_lower = self.display_name.lower()
        desc_lower = self.description.lower()

        score = 0.0

        # Check display name - word overlap (high weight)
        name_words = set(name_lower.replace("-", " ").replace("_", " ").split())
        name_overlap = query_words & name_words
        if name_overlap:
            score += 0.4 * (len(name_overlap) / len(query_words))

        # Full query in name (bonus)
        if query_lower in name_lower or name_lower in query_lower:
            score += 0.2

        # Check description - word overlap (medium weight)
        desc_words = set(desc_lower.replace("-", " ").replace("_", " ").split())
        desc_overlap = query_words & desc_words
        if desc_overlap:
            score += 0.3 * (len(desc_overlap) / len(query_words))

        # Check tool names (low weight)
        for tool_name in self.tool_names:
            tool_words = set(
                tool_name.lower().replace("_", " ").replace("-", " ").split()
            )
            if query_words & tool_words:
                score += 0.2
                break

        # Check tool summaries
        for summary in self.tool_summaries:
            summary_words = set(summary.lower().split())
            if query_words & summary_words:
                score += 0.1
                break

        return min(score, 1.0)

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
    Central registry for MCP servers with progressive disclosure support.

    Similar to SkillRegistry, but for external MCP servers. Manages connections,
    tracks available tools, and supports search/activate pattern.
    """

    def __init__(self, mcp_client: McpClient):
        self._client = mcp_client
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

    async def clear(self) -> None:
        """Disconnect from all servers and clear the registry."""
        server_names = list(self._connections.keys())
        for server_name in server_names:
            await self.unregister_server(server_name)

    def search_servers(self, query: str, limit: int = 5) -> list[McpServerManifest]:
        """
        Search for MCP servers matching the query.
        Returns manifests sorted by relevance.
        """
        query_lower = query.lower().strip()

        # Special case: list all
        if query_lower in ("all", "*", "list", "list all", "everything", "show all"):
            results = list(self._manifests.values())[:limit]
            if results:
                printr.print(
                    f"🔍 Searching MCP servers... found {len(self._manifests)} available",
                    color=LogType.PURPLE,
                )
            return results

        scored = []
        for manifest in self._manifests.values():
            score = manifest.matches_query(query)
            if score > 0:
                scored.append((score, manifest))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [m for _, m in scored[:limit]]

        # Fallback: If no results, check for servers with discovery tools (mcp-find)
        # These are meta-servers like Docker MCP Gateway that can find other servers
        if not results:
            for manifest in self._manifests.values():
                # Check if any tool contains "mcp-find" (handles prefixed names)
                has_discovery = any(
                    "mcp-find" in name.lower() or "mcp_find" in name.lower()
                    for name in manifest.tool_names
                )
                # Also check description for discovery-related keywords
                desc_lower = manifest.description.lower()
                has_discovery = has_discovery or any(
                    kw in desc_lower
                    for kw in ["mcp-find", "discover", "dynamic", "aggregator"]
                )
                if has_discovery:
                    results = [manifest]
                    printr.print(
                        f"🔍 Searching for '{query}'... using {manifest.display_name} (has discovery tools)",
                        color=LogType.PURPLE,
                    )
                    return results

        if results:
            names = [m.display_name for m in results]
            printr.print(
                f"🔍 Searching for '{query}'... found: {', '.join(names)}",
                color=LogType.PURPLE,
            )
        else:
            printr.print(
                f"🔍 Searching for '{query}'... no matching MCP servers found",
                color=LogType.WARNING,
            )

        return results

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

        printr.print(
            f"🌐 MCP activated: {manifest.display_name}",
            color=LogType.PURPLE,
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

        printr.print(
            f"🔌 MCP deactivated: {display_name}",
            color=LogType.PURPLE,
        )
        return True, f"Deactivated '{display_name}'."

    def reset_activations(self) -> None:
        """Reset all server activations (called on conversation reset)."""
        if self._active_servers:
            count = len(self._active_servers)
            printr.print(
                f"🔄 Conversation reset: deactivating {count} MCP server(s)",
                color=LogType.PURPLE,
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
        Returns meta-tools for MCP progressive disclosure.
        These allow the LLM to discover and activate MCP servers.
        """
        if not self._manifests:
            return []

        # Build servers summary with descriptions for better matching
        server_hints = []
        for m in list(self._manifests.values())[:5]:
            server_hints.append(
                f"{m.display_name} ({m.description[:50]}...)"
                if len(m.description) > 50
                else f"{m.display_name} ({m.description})"
            )
        servers_hint = "; ".join(server_hints)
        if len(self._manifests) > 5:
            servers_hint += f"; and {len(self._manifests) - 5} more"

        return [
            (
                "search_mcp_servers",
                {
                    "type": "function",
                    "function": {
                        "name": "search_mcp_servers",
                        "description": f"Search for MCP servers connected by the user. These provide external capabilities - could be documentation, APIs, local apps, databases, or any other tools. Available: {servers_hint}",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Search query - what you're looking for (e.g., 'Svelte', 'containers', 'documentation')",
                                },
                            },
                            "required": ["query"],
                        },
                    },
                },
            ),
            (
                "activate_mcp_server",
                {
                    "type": "function",
                    "function": {
                        "name": "activate_mcp_server",
                        "description": "Activate an MCP server to access its tools. Use search_mcp_servers first to find the server name.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "server_name": {
                                    "type": "string",
                                    "description": "The internal name (id) of the MCP server to activate",
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
        printr.print(
            f"Meta-tool called: {tool_name}({parameters})",
            color=LogType.INFO,
            server_only=True,
        )

        if tool_name == "search_mcp_servers":
            query = parameters.get("query", "")
            limit = 20 if query.lower() in ("all", "*", "list") else 5
            results = self.search_servers(query, limit=limit)

            if not results:
                return "No MCP servers found matching your query.", False

            parts = [f"Found {len(results)} MCP server(s) matching '{query}':\n"]
            for manifest in results:
                parts.append(manifest.to_summary())
                parts.append("")
            parts.append(
                "\nUse activate_mcp_server with the server id to enable its tools."
            )
            return "\n".join(parts), False

        elif tool_name == "activate_mcp_server":
            server_name = parameters.get("server_name", "")
            success, message = self.activate_server(server_name)
            return message, success

        elif tool_name == "list_active_mcp_servers":
            if not self._active_servers:
                return (
                    "No MCP servers are currently active. Use search_mcp_servers to find available servers.",
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
        return tool_name in {
            "search_mcp_servers",
            "activate_mcp_server",
            "list_active_mcp_servers",
        }

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
