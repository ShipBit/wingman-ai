"""Migration from version 1.7.0 to 1.8.0.

Major changes:
- Migrates Wingman Pro region to base_url
- Adds OpenAI TTS properties (tts_model, tts_speed)
- Adds Hume AI provider
- Adds openai_compatible_tts provider
- Migrates Perplexity model to "sonar"
- Resets Voice Activation and FasterWhisper hotwords
- Removes skill property overrides (description, examples, category, hint)
"""

from typing import Optional

from services.migrations.base_migration import BaseMigration


class Migration170To180(BaseMigration):
    """Migration from 1.7.0 to 1.8.0."""

    old_version = "1_7_0"
    new_version = "1_8_0"

    def migrate_settings(self, old: dict, new: dict) -> dict:
        """Migrate settings.yaml from 1.7.0 to 1.8.0."""
        # Migrate Wingman Pro region to base_url
        old_region = old["wingman_pro"]["region"]
        if old_region == "europe":
            old["wingman_pro"][
                "base_url"
            ] = "https://wingman-api-europe.azurewebsites.net"
        else:
            old["wingman_pro"]["base_url"] = "https://wingman-api-usa.azurewebsites.net"
        self.log(f"- set new base url based on region {old_region}")

        # Reset Voice Activation hotwords
        old["voice_activation"]["fasterwhisper_config"]["hotwords"] = []
        old["voice_activation"]["fasterwhisper_config"]["additional_hotwords"] = []
        self.log("- reset Voice Activation hotwords")

        # Add new cancel TTS key
        old["cancel_tts_key"] = "Shift+y"
        self.log("- set new 'Shut up key' to 'Shift+y'")

        return old

    def migrate_defaults(self, old: dict, new: dict) -> dict:
        """Migrate defaults.yaml from 1.7.0 to 1.8.0."""
        # Add OpenAI TTS properties
        old["openai"]["tts_model"] = "tts-1"
        old["openai"]["tts_speed"] = 1.0
        self.log("- added new properties: openai.tts_model, openai.tts_speed")

        # Add Hume AI provider
        old["hume"] = new["hume"]
        self.log("- added new property: hume")

        # Add OpenAI-compatible TTS
        old["openai_compatible_tts"] = new["openai_compatible_tts"]
        self.log("- added new property: openai_compatible_tts")

        # Migrate Perplexity model
        old["perplexity"]["conversation_model"] = "sonar"
        self.log(
            "- migrated perplexity model to new default (sonar), previous models don't exist anymore"
        )

        # Reset FasterWhisper hotwords
        old["fasterwhisper"]["hotwords"] = []
        old["fasterwhisper"]["additional_hotwords"] = []
        self.log("- reset FasterWhisper hotwords")

        return old

    def migrate_wingman(self, old: dict, new: Optional[dict]) -> dict:
        """Migrate wingman configs from 1.7.0 to 1.8.0."""
        # Remove skill property overrides
        if old.get("skills"):
            for skill in old["skills"]:
                skill.pop("description", None)
                skill.pop("examples", None)
                skill.pop("category", None)
                skill.pop("hint", None)

                skill_module = skill.get("module", "")
                self.log(
                    f"- Skill {skill_module}: removed property overrides: description, examples, category, hint"
                )

        # Migrate Perplexity model
        if old.get("perplexity", {}).get("conversation_model"):
            old["perplexity"]["conversation_model"] = "sonar"
            self.log(
                "- migrated perplexity model to new default (sonar), previous models don't exist anymore"
            )

        # Reset FasterWhisper hotwords
        if old.get("fasterwhisper"):
            old["fasterwhisper"]["hotwords"] = []
            old["fasterwhisper"]["additional_hotwords"] = []
            self.log("- reset FasterWhisper hotwords")

        return old
