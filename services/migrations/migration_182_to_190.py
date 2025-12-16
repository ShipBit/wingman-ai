"""Migration from version 1.8.2 to 1.9.0.

Major changes:
- CUDA auto-detection for FasterWhisper
- Adds xAI provider
- Disables generic instant responses feature
- Migrates deprecated Wingman Pro models to gpt-4o-mini
- Force-updates system prompts for MCP architecture
- Force-updates TTS prompts (ElevenLabs, Inworld)
- Removes Inworld pitch config
- Clears prompt overrides from wingmen configs
- Removes deprecated skills (google_search, web_search, etc.)
- Merges custom properties with skill defaults and validates them
- Sets discoverable_skills and discoverable_mcps for each wingman
- Handles template vs custom wingmen differently
- Removes per-wingman MCP arrays
- Creates mcp.yaml from template
- Adds local_llm secret
"""

import os
from os import path
from typing import Optional

from pydantic import ValidationError

from api.interface import CustomProperty
from services.file import get_custom_skills_dir
from services.migrations.base_migration import BaseMigration

# Models removed from Wingman Pro - migrate to gpt-4o-mini
REMOVED_WINGMAN_PRO_MODELS = [
    "gpt-4o",
    "mistral-large-latest",
    "llama3-8b",
    "llama3-70b",
]

# Skills removed in 1.9.0 (converted to MCP servers or deprecated)
REMOVED_SKILL_MODULES = {
    "skills.google_search.main",
    "skills.web_search.main",
    "skills.time_and_date_retriever.main",
    "skills.nms_assistant.main",
    "skills.ask_perplexity.main",
}


class Migration182To190(BaseMigration):
    """Migration from 1.8.2 to 1.9.0."""

    old_version = "1_8_2"
    new_version = "1_9_0"

    def migrate_settings(self, old: dict, new: dict) -> dict:
        """Migrate settings.yaml from 1.8.2 to 1.9.0."""
        # Auto-detect CUDA availability and set FasterWhisper device accordingly
        cuda_available = self.system_manager.is_cuda_available()
        gpu_name = self.system_manager.get_gpu_name()

        device = "cuda" if cuda_available else "cpu"
        compute_type = "auto"

        # Ensure the structure exists
        if "voice_activation" not in old:
            old["voice_activation"] = {}
        if "fasterwhisper" not in old["voice_activation"]:
            old["voice_activation"]["fasterwhisper"] = {}

        old["voice_activation"]["fasterwhisper"]["device"] = device
        old["voice_activation"]["fasterwhisper"]["compute_type"] = compute_type

        self.log(f"- detected GPU: {gpu_name or 'None'}")
        self.log(
            f"- set voice_activation.fasterwhisper.device to '{device}' (CUDA {'available' if cuda_available else 'not available'})"
        )
        self.log(
            f"- set voice_activation.fasterwhisper.compute_type to '{compute_type}'"
        )

        return old

    def migrate_defaults(self, old: dict, new: dict) -> dict:
        """Migrate defaults.yaml from 1.8.2 to 1.9.0."""
        # Add xAI provider
        old["xai"] = new["xai"]
        self.log("- added new property: xai")

        # Disable AI instant responses (feature removed in 1.9)
        if "features" not in old:
            old["features"] = {}
        old["features"]["use_generic_instant_responses"] = False
        self.log("- disabled features.use_generic_instant_responses (feature removed)")

        # Migrate deprecated Wingman Pro conversation models
        if "wingman_pro" in old and "conversation_deployment" in old["wingman_pro"]:
            current_model = old["wingman_pro"]["conversation_deployment"]
            if current_model in REMOVED_WINGMAN_PRO_MODELS:
                old["wingman_pro"]["conversation_deployment"] = "gpt-4o-mini"
                self.log(
                    f"- migrated wingman_pro.conversation_deployment from '{current_model}' to 'gpt-4o-mini' (model removed)"
                )

        # Update default models for various providers
        old["google"]["conversation_model"] = "gemini-flash-latest"
        self.log("- set Google default model to gemini-flash-latest")
        old["mistral"]["conversation_model"] = "mistral-medium-latest"
        self.log("- set Mistral default model to mistral-medium-latest")
        old["cerebras"]["conversation_model"] = "qwen-3-32b"
        self.log("- set Cerebras default model to qwen-3-32b")
        old["openrouter"]["conversation_model"] = "google/gemini-2.5-flash"
        self.log("- set OpenRouter default model to google/gemini-2.5-flash")
        old["groq"]["conversation_model"] = "qwen/qwen3-32b"
        self.log("- set Groq default model to qwen/qwen3-32b")

        # Force override prompts with new MCP-optimized versions
        if "prompts" not in old:
            old["prompts"] = {}
        old["prompts"]["system_prompt"] = new["prompts"]["system_prompt"]
        self.log("- force updated prompts.system_prompt (MCP tool-first architecture)")

        # Force update TTS prompts for ElevenLabs and Inworld
        if "elevenlabs" in new:
            old["elevenlabs"]["tts_prompt"] = new["elevenlabs"]["tts_prompt"]
            self.log("- force updated elevenlabs.tts_prompt (new v3 audio tags)")

        if "inworld" in new:
            old["inworld"]["tts_prompt"] = new["inworld"]["tts_prompt"]
            self.log("- force updated inworld.tts_prompt (new audio markup format)")
            if "audio_config" in old["inworld"]:
                del old["inworld"]["audio_config"]["pitch"]
                self.log("- removed inworld.audio_config.pitch (no longer supported)")
                # Add streaming_sample_rate_hertz for better streaming quality
                old["inworld"]["audio_config"]["streaming_sample_rate_hertz"] = new[
                    "inworld"
                ]["audio_config"]["streaming_sample_rate_hertz"]
                self.log("- added inworld.audio_config.streaming_sample_rate_hertz")

        return old

    def migrate_wingman(self, old: dict, new: Optional[dict]) -> dict:
        """Migrate wingman configs from 1.8.2 to 1.9.0."""
        changes_made = []

        # Migrate deprecated Wingman Pro conversation models
        if "wingman_pro" in old and "conversation_deployment" in old["wingman_pro"]:
            current_model = old["wingman_pro"]["conversation_deployment"]
            if current_model in REMOVED_WINGMAN_PRO_MODELS:
                old["wingman_pro"]["conversation_deployment"] = "gpt-4o-mini"
                changes_made.append(
                    f"wingman_pro.conversation_deployment ('{current_model}' -> 'gpt-4o-mini')"
                )

        # Clear system_prompt override (force use of new default)
        if "prompts" in old:
            if "system_prompt" in old["prompts"]:
                del old["prompts"]["system_prompt"]
                changes_made.append("prompts.system_prompt")
            # Remove prompts dict if empty
            if not old["prompts"]:
                del old["prompts"]

        # Clear ElevenLabs tts_prompt override
        if "elevenlabs" in old and "tts_prompt" in old["elevenlabs"]:
            del old["elevenlabs"]["tts_prompt"]
            changes_made.append("elevenlabs.tts_prompt")
            if not old["elevenlabs"]:
                del old["elevenlabs"]

        # Clear Inworld tts_prompt override
        if "inworld" in old and "tts_prompt" in old["inworld"]:
            del old["inworld"]["tts_prompt"]
            changes_made.append("inworld.tts_prompt")
            if not old["inworld"]:
                del old["inworld"]

        # Clean up skills array - remove deprecated skills and preserve overrides
        if "skills" in old:
            skills_with_overrides = []
            for skill in old["skills"]:
                skill_module = skill.get("module", "")

                # Skip removed skills entirely
                if skill_module in REMOVED_SKILL_MODULES:
                    changes_made.append(
                        f"removed skill config for '{skill_module}' (skill deprecated)"
                    )
                    continue

                has_custom_props = skill.get("custom_properties")
                has_prompt = skill.get("prompt")

                if has_custom_props or has_prompt:
                    stripped_skill = {"module": skill_module}

                    # Keep prompt override if present
                    if has_prompt:
                        stripped_skill["prompt"] = has_prompt

                    # Merge and validate custom properties
                    if has_custom_props:
                        valid_props = self._process_custom_properties(
                            skill_module, has_custom_props
                        )
                        if valid_props:
                            stripped_skill["custom_properties"] = valid_props

                    # Only add skill if it still has overrides
                    if stripped_skill.get("prompt") or stripped_skill.get(
                        "custom_properties"
                    ):
                        skills_with_overrides.append(stripped_skill)

            if skills_with_overrides:
                old["skills"] = skills_with_overrides
                changes_made.append(
                    f"skills (kept {len(skills_with_overrides)} skill(s) with overrides)"
                )
            else:
                del old["skills"]
                changes_made.append("skills (removed - no overrides)")

        # Set discoverable_skills and discoverable_mcps for wingmen
        wingman_name = old.get("name", "")

        # For template wingmen, read from their template.yaml
        # For custom wingmen, build from defaults
        if wingman_name in ("ATC", "Computer", "Clippy"):
            self._set_discoverable_from_template(old, wingman_name, changes_made)
        else:
            self._set_discoverable_for_custom_wingman(old, changes_made)

        # MCP servers are now centralized in mcp.yaml
        if "mcp" in old:
            del old["mcp"]
            changes_made.append("mcp (removed - now centralized in mcp.yaml)")

        # Remove old disabled_skills/disabled_mcps if they exist
        if "disabled_skills" in old:
            del old["disabled_skills"]
        if "disabled_mcps" in old:
            del old["disabled_mcps"]

        if changes_made:
            self.log(f"- cleared/updated: {', '.join(changes_made)}")

        return old

    def migrate_secrets(self, old: dict) -> dict:
        """Migrate secrets.yaml from 1.8.2 to 1.9.0."""
        if "local_llm" not in old:
            old["local_llm"] = "not-set"
            self.log("- added new secret: local_llm")
        return old

    def migrate_mcp(self, old: dict, new: dict) -> dict:
        """Migrate mcp.yaml from 1.8.2 to 1.9.0."""
        # For 1.8.2 -> 1.9.0, we're creating mcp.yaml fresh from template
        return new

    # Helper methods specific to this migration

    def _is_valid_skill_directory(self, skill_path: str) -> bool:
        """Delegate to ConfigMigrationService for skill directory validation."""
        return self.service.is_valid_skill_directory(skill_path)

    def _get_skills_discoverable_by_default(self) -> list[str]:
        """Delegate to ConfigMigrationService for skills discoverable by default."""
        return self.service.get_skills_discoverable_by_default()

    def _get_mcps_discoverable_by_default(self) -> list[str]:
        """Delegate to ConfigMigrationService for MCPs discoverable by default."""
        return self.service.get_mcps_discoverable_by_default()

    def _get_template_path(self, wingman_name: str) -> Optional[str]:
        """Delegate to ConfigMigrationService for template path lookup."""
        return self.service.get_template_path(wingman_name)

    def _get_skill_default_custom_properties(
        self, skill_module: str
    ) -> dict[str, dict]:
        """Delegate to ConfigMigrationService for skill default custom properties."""
        return self.service.get_skill_default_custom_properties(skill_module)

    def _process_custom_properties(self, skill_module: str, custom_props: list) -> list:
        """Merge wingman custom property overrides with skill defaults and validate."""
        valid_props = []
        skill_default_props = self._get_skill_default_custom_properties(skill_module)

        for prop in custom_props:
            prop_id = prop.get("id")
            if not prop_id:
                continue

            # Find the default property with this id
            default_prop = skill_default_props.get(prop_id)
            if default_prop:
                # Merge: start with default, override with wingman values
                merged_prop = default_prop.copy()
                merged_prop.update(prop)
                merged_prop.pop("examples", None)  # Not needed in wingman config

                try:
                    CustomProperty(**merged_prop)
                    valid_props.append(merged_prop)
                except ValidationError:
                    self.log_warning(
                        f"- skipped custom property '{prop_id}' in skill '{skill_module}': validation failed after merge"
                    )
            else:
                # No default found - try to validate as-is
                try:
                    CustomProperty(**prop)
                    valid_props.append(prop)
                except ValidationError:
                    self.log_warning(
                        f"- skipped custom property '{prop_id}' in skill '{skill_module}': no default found and incomplete"
                    )

        return valid_props

    def _set_discoverable_from_template(
        self, old: dict, wingman_name: str, changes_made: list
    ) -> None:
        """Set discoverable skills/mcps from template for known wingmen."""
        from services.module_manager import ModuleManager

        template_path = self._get_template_path(wingman_name)
        if template_path and path.exists(template_path):
            template_config = ModuleManager.read_config(template_path)
            if template_config:
                old["discoverable_skills"] = template_config.get(
                    "discoverable_skills", []
                )
                changes_made.append(
                    f"discoverable_skills ({len(old['discoverable_skills'])} skills from template)"
                )

                old["discoverable_mcps"] = template_config.get("discoverable_mcps", [])
                changes_made.append(
                    f"discoverable_mcps ({len(old['discoverable_mcps'])} MCPs from template)"
                )
            else:
                self.log_warning(
                    f"Could not read template for {wingman_name}, using discoverable defaults"
                )
                self._set_discoverable_defaults(old)
        else:
            self.log_warning(
                f"Could not find template for {wingman_name}, using discoverable defaults"
            )
            self._set_discoverable_defaults(old)

    def _set_discoverable_for_custom_wingman(
        self, old: dict, changes_made: list
    ) -> None:
        """Set discoverable skills/mcps using defaults for custom wingmen."""
        old["discoverable_skills"] = self._get_skills_discoverable_by_default()
        changes_made.append(
            f"discoverable_skills (custom wingman: {len(old['discoverable_skills'])} skills discoverable by default)"
        )

        old["discoverable_mcps"] = self._get_mcps_discoverable_by_default()
        changes_made.append(
            f"discoverable_mcps (custom wingman: {len(old['discoverable_mcps'])} MCPs discoverable by default)"
        )

    def _set_discoverable_defaults(self, old: dict) -> None:
        """Fallback method to set discoverable defaults."""
        old["discoverable_skills"] = self._get_skills_discoverable_by_default()
        old["discoverable_mcps"] = self._get_mcps_discoverable_by_default()
