"""
Skill Registry with Progressive Tool Disclosure

This module implements MCP-inspired progressive tool disclosure to reduce token usage.
Instead of sending all tools to the LLM on every call, we send lightweight meta-tools
that allow the LLM to discover and activate skills on-demand.

Key concepts:
- SkillManifest: Lightweight metadata about a skill (name, description, tags)
- SkillRegistry: Central registry that tracks all skills and their manifests
- Meta-tools: search_skills and activate_skill - the only tools sent to LLM initially
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional
from api.enums import LogType
from services.printr import Printr

if TYPE_CHECKING:
    from skills.skill_base import Skill

printr = Printr()


@dataclass
class SkillManifest:
    """Lightweight metadata about a skill for progressive disclosure."""

    name: str
    """Internal skill class name (e.g., 'TimeAndDateRetriever')"""

    display_name: str
    """Human-readable name (e.g., 'Time and Date')"""

    description: str
    """What the skill does - used for semantic search"""

    tags: list[str] = field(default_factory=list)
    """Searchable tags like ['time', 'date', 'clock', 'calendar']"""

    tool_names: list[str] = field(default_factory=list)
    """Names of tools this skill provides"""

    tool_summaries: list[str] = field(default_factory=list)
    """One-line descriptions of each tool"""

    @classmethod
    def from_skill(cls, skill: "Skill") -> "SkillManifest":
        """Create a manifest from a Skill instance."""
        # Get tool info
        tool_names = []
        tool_summaries = []
        for tool_name, tool_def in skill.get_tools():
            tool_names.append(tool_name)
            # Extract description from tool definition
            if isinstance(tool_def, dict):
                func_def = tool_def.get("function", tool_def)
                desc = func_def.get("description", "No description")
                # Truncate to one line
                tool_summaries.append(desc.split("\n")[0][:100])
            else:
                tool_summaries.append("No description")

        return cls(
            name=skill.name,
            display_name=skill.config.display_name,
            description=skill.config.description.en if skill.config.description else "",
            tags=skill.config.tags or [],
            tool_names=tool_names,
            tool_summaries=tool_summaries,
        )

    def matches_query(self, query: str) -> float:
        """
        Returns a relevance score (0-1) for how well this skill matches the query.
        Simple keyword matching - could be enhanced with embeddings later.
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())

        score = 0.0

        # Check display name (high weight)
        if query_lower in self.display_name.lower():
            score += 0.4

        # Check description (medium weight)
        if query_lower in self.description.lower():
            score += 0.3

        # Check tags (medium weight)
        for tag in self.tags:
            if query_lower in tag.lower() or tag.lower() in query_lower:
                score += 0.2
                break

        # Check tool names (low weight)
        for tool_name in self.tool_names:
            tool_words = set(tool_name.lower().replace("_", " ").split())
            if query_words & tool_words:
                score += 0.1
                break

        # Check tool summaries
        for summary in self.tool_summaries:
            if any(word in summary.lower() for word in query_words):
                score += 0.1
                break

        return min(score, 1.0)

    def to_summary(self) -> str:
        """Returns a compact string representation for LLM context."""
        tools_str = ", ".join(self.tool_names) if self.tool_names else "No tools"
        tags_str = ", ".join(self.tags) if self.tags else "No tags"
        return f"**{self.display_name}** (id: {self.name})\n  {self.description}\n  Tools: {tools_str}\n  Tags: {tags_str}"


class SkillRegistry:
    """
    Central registry for skills with progressive disclosure support.

    Progressive disclosure:
    - Only meta-tools (search_skills, activate_skill, list_active_skills) are sent to the LLM initially
    - Skills are activated on-demand when the LLM calls activate_skill
    - Activated skills' tools are added to the conversation
    """

    def __init__(self):
        self._skills: dict[str, "Skill"] = {}
        """All registered skills by name"""

        self._manifests: dict[str, SkillManifest] = {}
        """Skill manifests for progressive disclosure"""

        self._active_skills: set[str] = set()
        """Currently activated skills (their tools are available to LLM)"""

        self._tool_to_skill: dict[str, str] = {}
        """Maps tool names to skill names"""

    def register_skill(self, skill: "Skill") -> None:
        """Register a skill and create its manifest."""
        self._skills[skill.name] = skill
        self._manifests[skill.name] = SkillManifest.from_skill(skill)

        # Map tool names to this skill
        for tool_name, _ in skill.get_tools():
            self._tool_to_skill[tool_name] = skill.name

    def unregister_skill(self, skill_name: str) -> None:
        """Remove a skill from the registry."""
        if skill_name in self._skills:
            # Remove tool mappings
            manifest = self._manifests.get(skill_name)
            if manifest:
                for tool_name in manifest.tool_names:
                    self._tool_to_skill.pop(tool_name, None)

            self._skills.pop(skill_name, None)
            self._manifests.pop(skill_name, None)
            self._active_skills.discard(skill_name)

    def clear(self) -> None:
        """Clear all registered skills."""
        self._skills.clear()
        self._manifests.clear()
        self._active_skills.clear()
        self._tool_to_skill.clear()

    def search_skills(self, query: str, limit: int = 5) -> list[SkillManifest]:
        """
        Search for skills matching the query.
        Returns manifests sorted by relevance.

        Special queries:
        - "all", "*", "list", "list all" - returns all skills (up to limit)
        """
        query_lower = query.lower().strip()

        # Special case: list all skills
        if query_lower in ("all", "*", "list", "list all", "everything", "show all"):
            results = list(self._manifests.values())[:limit]
            if results:
                skill_names = [m.display_name for m in results]
                printr.print(
                    f"🔍 Searching skills... found {len(self._manifests)} available",
                    color=LogType.PURPLE,
                )
            return results

        scored = []
        for manifest in self._manifests.values():
            score = manifest.matches_query(query)
            if score > 0:
                scored.append((score, manifest))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        results = [m for _, m in scored[:limit]]

        # Log search results - visible to users
        if results:
            skill_names = [m.display_name for m in results]
            printr.print(
                f"🔍 Searching for '{query}'... found: {', '.join(skill_names)}",
                color=LogType.PURPLE,
            )
        else:
            printr.print(
                f"🔍 Searching for '{query}'... no matching skills found",
                color=LogType.WARNING,
            )

        return results

    def activate_skill(self, skill_name: str) -> tuple[bool, str, bool]:
        """
        Activate a skill, making its tools available to the LLM.

        Note: This only marks the skill as active. Lazy validation should be
        performed by calling skill.ensure_activated() before first use.

        Returns:
            (success, message, needs_validation) tuple
            - success: Whether the skill was found and marked active
            - message: Status message
            - needs_validation: Whether the skill needs validation before use
        """
        if skill_name not in self._skills:
            available = ", ".join(self._manifests.keys())
            printr.print(
                f"⚠️ Skill '{skill_name}' not found",
                color=LogType.WARNING,
            )
            return (
                False,
                f"Skill '{skill_name}' not found. Available skills: {available}",
                False,
            )

        skill = self._skills[skill_name]
        needs_validation = skill.needs_activation()

        self._active_skills.add(skill_name)
        manifest = self._manifests[skill_name]
        tools_str = ", ".join(manifest.tool_names)

        if needs_validation:
            printr.print(
                f"🔌 Activating skill: {manifest.display_name} (validating...)",
                color=LogType.PURPLE,
            )
            return (
                True,
                f"Activating '{manifest.display_name}' (validation pending). Tools: {tools_str}",
                True,
            )

        printr.print(
            f"🔧 Skill activated: {manifest.display_name}",
            color=LogType.PURPLE,
        )
        return (
            True,
            f"Activated '{manifest.display_name}'. Available tools: {tools_str}",
            False,
        )

    def deactivate_skill(self, skill_name: str) -> tuple[bool, str]:
        """Deactivate a skill, removing its tools from availability."""
        if skill_name not in self._active_skills:
            return False, f"Skill '{skill_name}' is not currently active."

        self._active_skills.discard(skill_name)
        manifest = self._manifests.get(skill_name)
        display_name = manifest.display_name if manifest else skill_name
        printr.print(
            f"🔌 Skill deactivated: {display_name}",
            color=LogType.PURPLE,
        )
        return True, f"Deactivated skill '{skill_name}'."

    def reset_activations(self) -> None:
        """Reset all skill activations.

        Called when conversation history is reset, since the LLM loses
        all memory of which skills were activated and why.
        """
        if self._active_skills:
            count = len(self._active_skills)
            printr.print(
                f"🔄 Conversation reset: deactivating {count} skill(s)",
                color=LogType.PURPLE,
            )
        self._active_skills.clear()

    def get_skill_for_tool(self, tool_name: str) -> Optional["Skill"]:
        """Get the skill that provides a given tool."""
        skill_name = self._tool_to_skill.get(tool_name)
        if skill_name:
            return self._skills.get(skill_name)
        return None

    def get_skill_for_activation(self, skill_name: str) -> Optional["Skill"]:
        """Get a skill by name for activation purposes."""
        return self._skills.get(skill_name)

    def get_skill_display_name(self, skill_name: str) -> str:
        """Get the display name for a skill, or the skill name if not found."""
        manifest = self._manifests.get(skill_name)
        return manifest.display_name if manifest else skill_name

    def get_active_tools(self) -> list[tuple[str, dict]]:
        """
        Get tools from all active (explicitly activated) skills.
        """
        tools = []
        for skill_name in self._active_skills:
            skill = self._skills.get(skill_name)
            if skill:
                tools.extend(skill.get_tools())
        return tools

    def get_meta_tools(self) -> list[tuple[str, dict]]:
        """
        Returns the meta-tools for progressive disclosure.
        These are the only tools sent to the LLM initially.
        """
        # Build skills summary for the search tool description
        all_skills = [m.display_name for m in self._manifests.values()]
        skills_hint = ", ".join(all_skills[:10])
        if len(all_skills) > 10:
            skills_hint += f", and {len(all_skills) - 10} more"

        return [
            (
                "search_skills",
                {
                    "type": "function",
                    "function": {
                        "name": "search_skills",
                        "description": f"Search for built-in Wingman skills. These are bundled capabilities like game controls, timers, screenshots, image generation, etc. Available: {skills_hint}",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Search query - action or capability needed",
                                },
                            },
                            "required": ["query"],
                        },
                    },
                },
            ),
            (
                "activate_skill",
                {
                    "type": "function",
                    "function": {
                        "name": "activate_skill",
                        "description": "Activate a skill to access its tools. Use search_skills first to find the skill name. Once activated, the skill's tools become available.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "skill_name": {
                                    "type": "string",
                                    "description": "The internal name (id) of the skill to activate, as returned by search_skills",
                                },
                            },
                            "required": ["skill_name"],
                        },
                    },
                },
            ),
            (
                "list_active_skills",
                {
                    "type": "function",
                    "function": {
                        "name": "list_active_skills",
                        "description": "List currently activated skills and their available tools.",
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
        Execute a meta-tool.

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

        if tool_name == "search_skills":
            query = parameters.get("query", "")
            # Use higher limit for "all" type queries
            query_lower = query.lower().strip()
            limit = (
                20
                if query_lower
                in ("all", "*", "list", "list all", "everything", "show all")
                else 5
            )
            results = self.search_skills(query, limit=limit)
            if not results:
                return (
                    "No skills found matching your query. Try different keywords.",
                    False,
                )

            response_parts = [f"Found {len(results)} skill(s) matching '{query}':\n"]
            for manifest in results:
                response_parts.append(manifest.to_summary())
                response_parts.append("")
            response_parts.append(
                "\nUse activate_skill with the skill id to enable its tools."
            )
            return "\n".join(response_parts), False

        elif tool_name == "activate_skill":
            skill_name = parameters.get("skill_name", "")
            success, message, _ = self.activate_skill(skill_name)
            # Return success status and whether tools changed
            # Note: needs_validation is handled async in OpenAiWingman
            return message, success

        elif tool_name == "list_active_skills":
            if not self._active_skills:
                return (
                    "No skills are currently active. Use search_skills to find available skills.",
                    False,
                )

            parts = [f"Currently active skills ({len(self._active_skills)} total):\n"]
            for skill_name in self._active_skills:
                manifest = self._manifests.get(skill_name)
                if manifest:
                    tools = (
                        ", ".join(manifest.tool_names)
                        if manifest.tool_names
                        else "no tools"
                    )
                    parts.append(f"- {manifest.display_name}: {tools}")
            return "\n".join(parts), False

        return f"Unknown meta-tool: {tool_name}", False

    def is_meta_tool(self, tool_name: str) -> bool:
        """Check if a tool name is a meta-tool."""
        return tool_name in {"search_skills", "activate_skill", "list_active_skills"}

    @property
    def skill_count(self) -> int:
        """Number of registered skills."""
        return len(self._skills)

    @property
    def active_skill_count(self) -> int:
        """Number of currently active skills."""
        return len(self._active_skills)

    @property
    def active_skill_names(self) -> set[str]:
        """Names of currently active skills."""
        return self._active_skills.copy()
