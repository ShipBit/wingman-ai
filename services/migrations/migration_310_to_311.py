"""Migration from version 3.1.0 to 3.1.1.

Switches default STT provider from FasterWhisper to Parakeet.
Removes enable flags from FasterWhisper and Parakeet settings.
"""

from services.migrations.base_migration import BaseMigration


class Migration310To311(BaseMigration):
    """Migration from 3.1.0 to 3.1.1."""

    old_version = "3_1_0"
    new_version = "3_1_1"

    def migrate_settings(self, old: dict) -> dict:
        """Switch STT provider to Parakeet and remove enable flags."""
        va = old.get("voice_activation", {})

        # Switch default STT provider
        old_provider = va.get("stt_provider", "fasterwhisper")
        va["stt_provider"] = "parakeet"
        if old_provider != "parakeet":
            self.log(f"- updated stt_provider: {old_provider} → parakeet")

        # Remove enable from fasterwhisper
        fw = va.get("fasterwhisper", {})
        if "enable" in fw:
            del fw["enable"]
            self.log("- removed fasterwhisper.enable flag")

        # Remove enable from parakeet
        pk = va.get("parakeet", {})
        if "enable" in pk:
            del pk["enable"]
            self.log("- removed parakeet.enable flag")

        return old

    def migrate_defaults(self, old: dict) -> dict:
        """Update defaults stt_provider to parakeet."""
        features = old.get("features", {})
        old_provider = features.get("stt_provider", "fasterwhisper")
        if old_provider != "parakeet":
            features["stt_provider"] = "parakeet"
            self.log(f"- updated defaults stt_provider: {old_provider} → parakeet")
        return old
