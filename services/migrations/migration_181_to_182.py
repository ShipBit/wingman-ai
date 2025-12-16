"""Migration from version 1.8.1 to 1.8.2.

Major changes:
- Adds Inworld AI provider
- Adds ElevenLabs TTS prompt settings
- Adds OpenAI output_streaming property
- Adds openai_compatible_tts output_streaming
"""

from services.migrations.base_migration import BaseMigration


class Migration181To182(BaseMigration):
    """Migration from 1.8.1 to 1.8.2."""

    old_version = "1_8_1"
    new_version = "1_8_2"

    def migrate_defaults(self, old: dict, new: dict) -> dict:
        """Migrate defaults.yaml from 1.8.1 to 1.8.2."""
        # Add Inworld AI provider
        old["inworld"] = new["inworld"]
        self.log("- added new property: inworld")

        # Add ElevenLabs TTS prompt settings
        old["elevenlabs"]["use_tts_prompt"] = False
        old["elevenlabs"]["tts_prompt"] = new["elevenlabs"]["tts_prompt"]
        self.log(
            "- added new property: elevenlabs.use_tts_prompt, elevenlabs.tts_prompt"
        )

        # Add output streaming for OpenAI
        old["openai"]["output_streaming"] = True
        self.log("- added new property: openai.output_streaming")

        # Add output streaming for OpenAI-compatible TTS
        old["openai_compatible_tts"]["output_streaming"] = True
        self.log("- added new property: openai_compatible_tts.output_streaming")

        return old
