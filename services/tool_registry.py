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
from typing import TYPE_CHECKING, Callable, Any, Optional
import inspect
import json
from pydantic import BaseModel, Field
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

    In progressive mode:
    - Only meta-tools (search_skills, activate_skill) are sent to the LLM
    - Skills are activated on-demand when the LLM calls activate_skill
    - Activated skills' tools are added to the conversation

    In legacy mode:
    - All skill tools are sent to the LLM (current behavior)
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

        self._progressive_mode: bool = False
        """Whether progressive disclosure is enabled"""

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

    def set_progressive_mode(self, enabled: bool) -> None:
        """Enable or disable progressive disclosure mode."""
        self._progressive_mode = enabled
        if not enabled:
            # In legacy mode, all skills are "active"
            self._active_skills = set(self._skills.keys())

    def search_skills(self, query: str, limit: int = 5) -> list[SkillManifest]:
        """
        Search for skills matching the query.
        Returns manifests sorted by relevance.
        """
        scored = []
        for manifest in self._manifests.values():
            score = manifest.matches_query(query)
            if score > 0:
                scored.append((score, manifest))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:limit]]

    def activate_skill(self, skill_name: str) -> tuple[bool, str]:
        """
        Activate a skill, making its tools available to the LLM.

        Returns:
            (success, message) tuple
        """
        if skill_name not in self._skills:
            available = ", ".join(self._manifests.keys())
            return (
                False,
                f"Skill '{skill_name}' not found. Available skills: {available}",
            )

        self._active_skills.add(skill_name)
        manifest = self._manifests[skill_name]
        tools_str = ", ".join(manifest.tool_names)
        return (
            True,
            f"Activated '{manifest.display_name}'. Available tools: {tools_str}",
        )

    def deactivate_skill(self, skill_name: str) -> tuple[bool, str]:
        """Deactivate a skill, removing its tools from availability."""
        if skill_name not in self._active_skills:
            return False, f"Skill '{skill_name}' is not currently active."

        self._active_skills.discard(skill_name)
        return True, f"Deactivated skill '{skill_name}'."

    def get_skill_for_tool(self, tool_name: str) -> Optional["Skill"]:
        """Get the skill that provides a given tool."""
        skill_name = self._tool_to_skill.get(tool_name)
        if skill_name:
            return self._skills.get(skill_name)
        return None

    def get_active_tools(self) -> list[tuple[str, dict]]:
        """
        Get tools from all active skills.

        In progressive mode: only returns tools from explicitly activated skills.
        In legacy mode: returns tools from all skills.
        """
        tools = []
        target_skills = (
            self._active_skills if self._progressive_mode else set(self._skills.keys())
        )

        for skill_name in target_skills:
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
                        "description": f"Search for available skills/capabilities by keyword or description. Use this to find tools that can help with the user's request. Available skills include: {skills_hint}",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Search query - can be keywords, skill name, or description of what you need",
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
        if tool_name == "search_skills":
            query = parameters.get("query", "")
            results = self.search_skills(query)
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
            success, message = self.activate_skill(skill_name)
            # Tools changed if activation was successful
            return message, success

        elif tool_name == "list_active_skills":
            if not self._active_skills:
                return (
                    "No skills are currently active. Use search_skills to find available skills.",
                    False,
                )

            parts = ["Currently active skills:\n"]
            for skill_name in self._active_skills:
                manifest = self._manifests.get(skill_name)
                if manifest:
                    parts.append(
                        f"- {manifest.display_name}: {', '.join(manifest.tool_names)}"
                    )
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
