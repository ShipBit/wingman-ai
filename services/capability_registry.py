"""
Unified Capability Registry

This module provides a unified discovery interface for both skills and MCP servers.
From the LLM's perspective, both are "capabilities" that provide tools.

The registry delegates all activation/execution to the underlying skill_registry
and mcp_registry, preserving their separate logging, validation, and lifecycle logic.
"""

from services.mcp_registry import McpRegistry
from services.tool_registry import SkillRegistry


class CapabilityRegistry:
    """
    Unified registry for discovering and activating capabilities.

    This is a thin abstraction layer that combines skill and MCP discovery
    into a single LLM-facing interface while preserving all internal separation.
    """

    def __init__(self, skill_registry: SkillRegistry, mcp_registry: McpRegistry):
        self.skill_registry = skill_registry
        self.mcp_registry = mcp_registry

    def get_meta_tools(self) -> list[tuple[str, dict]]:
        """
        Returns unified meta-tools for capability discovery.

        Combines discoverable skills and connected MCP servers into a single
        activate_capability tool with one enum containing all options.

        Skills are listed first (faster/local), then MCPs (network-based).
        """
        skills = self.skill_registry.get_discoverable_skills()
        mcps = self.mcp_registry.get_connected_servers()

        if not skills and not mcps:
            return []  # No capabilities available for discovery

        # Build unified enum
        capability_options = []
        descriptions = []

        # Skills first (local/faster)
        for manifest in skills:
            capability_options.append(manifest.name)
            desc = manifest.get_discovery_description()
            descriptions.append(f"- {manifest.name}: {desc}")

        # MCPs second (network-based)
        for manifest in mcps:
            capability_options.append(manifest.name)
            desc = manifest.get_discovery_description()
            descriptions.append(f"- {manifest.name}: {desc}")

        descriptions_block = "\n".join(descriptions)

        return [
            (
                "activate_capability",
                {
                    "type": "function",
                    "function": {
                        "name": "activate_capability",
                        "description": f"Activate a capability to use its tools. Choose based on what you need:\n\n{descriptions_block}",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "capability_name": {
                                    "type": "string",
                                    "enum": capability_options,
                                    "description": "The capability to activate",
                                },
                            },
                            "required": ["capability_name"],
                        },
                    },
                },
            ),
            (
                "list_active_capabilities",
                {
                    "type": "function",
                    "function": {
                        "name": "list_active_capabilities",
                        "description": "List all currently active capabilities and their available tools.",
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
        Execute a unified meta-tool.

        Routes to the appropriate registry (skill or MCP) based on the capability name.
        This preserves all registry-specific logging, validation, and error handling.

        Returns:
            (result_string, tools_changed) - tools_changed indicates if the LLM
            should receive an updated tool list
        """
        if tool_name == "activate_capability":
            capability_name = parameters.get("capability_name", "")

            # Try skills first (faster, no network calls)
            skill_manifests = {
                m.name: m for m in self.skill_registry.get_discoverable_skills()
            }
            if capability_name in skill_manifests:
                # Delegate to SkillRegistry - preserves [SKILL] logging and validation
                return self.skill_registry.execute_meta_tool(
                    "activate_skill", {"skill_name": capability_name}
                )

            # Try MCPs second
            mcp_manifests = {
                m.name: m for m in self.mcp_registry.get_connected_servers()
            }
            if capability_name in mcp_manifests:
                # Delegate to McpRegistry - preserves [MCP] logging
                return self.mcp_registry.execute_meta_tool(
                    "activate_mcp_server", {"server_name": capability_name}
                )

            # Not found in either
            return (
                f"Capability '{capability_name}' not found. It may have been removed or is not currently available.",
                False,
            )

        elif tool_name == "list_active_capabilities":
            skills_active = self.skill_registry.active_skill_names
            mcps_active = self.mcp_registry.active_server_names

            if not skills_active and not mcps_active:
                return (
                    "No capabilities are currently active. Use activate_capability to enable one.",
                    False,
                )

            parts = [
                f"Currently active capabilities ({len(skills_active) + len(mcps_active)} total):\n"
            ]

            # List skills with clear grouping
            if skills_active:
                parts.append("Skills:")
                for name in sorted(skills_active):
                    manifest = self.skill_registry._manifests.get(name)
                    if manifest:
                        tools = (
                            ", ".join(manifest.tool_names)
                            if manifest.tool_names
                            else "no tools"
                        )
                        auto_tag = " (auto)" if manifest.is_auto_activated else ""
                        parts.append(f"  - {manifest.display_name}{auto_tag}: {tools}")

            # List MCPs with clear grouping
            if mcps_active:
                if skills_active:
                    parts.append("")  # Blank line between groups
                parts.append("MCP Servers:")
                for name in sorted(mcps_active):
                    manifest = self.mcp_registry._manifests.get(name)
                    if manifest:
                        tools = (
                            ", ".join(manifest.tool_names[:5])
                            if manifest.tool_names
                            else "no tools"
                        )
                        if len(manifest.tool_names) > 5:
                            tools += f", +{len(manifest.tool_names) - 5} more"
                        parts.append(f"  - {manifest.display_name}: {tools}")

            return "\n".join(parts), False

        return f"Unknown capability meta-tool: {tool_name}", False

    def is_meta_tool(self, tool_name: str) -> bool:
        """Check if a tool name is a unified capability meta-tool."""
        return tool_name in {"activate_capability", "list_active_capabilities"}

    @property
    def has_capabilities(self) -> bool:
        """Check if any capabilities (skills or MCPs) are available for discovery."""
        return bool(
            self.skill_registry.get_discoverable_skills()
            or self.mcp_registry.get_connected_servers()
        )
