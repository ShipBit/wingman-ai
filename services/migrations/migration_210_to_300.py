"""Migration from version 2.1.0 to 3.0.0."""

from services.migrations.base_migration import BaseMigration


class Migration210To300(BaseMigration):
    """Migration from 2.1.0 to 3.0.0."""

    old_version = "2_1_0"
    new_version = "3_0_0"

    def migrate_settings(self, old: dict, new: dict) -> dict:
        """Migrate settings.yaml from 2.1.0 to 3.0.0."""
        # Add Local AI (llama.cpp) settings
        if "llama_cpp" not in old and "llama_cpp" in new:
            old["llama_cpp"] = new["llama_cpp"]
            self.log("- added new setting: llama_cpp (local AI)")

        # Upgrade default summarize model from 0.8B to 2B
        llama = old.get("llama_cpp", {})
        if llama.get("summarize_model") == "Qwen3.5-0.8B-Q4_K_M.gguf":
            llama["summarize_model"] = "Qwen3.5-2B-Q4_K_M.gguf"
            self.log("- upgraded summarize model: Qwen3.5-0.8B → Qwen3.5-2B")

        # Add Parakeet STT settings
        va = old.get("voice_activation", {})
        new_va = new.get("voice_activation", {})
        if "parakeet" not in va and "parakeet" in new_va:
            va["parakeet"] = new_va["parakeet"]
            self.log("- added new voice activation setting: parakeet")
        if "parakeet_config" not in va and "parakeet_config" in new_va:
            va["parakeet_config"] = new_va["parakeet_config"]
            self.log("- added new voice activation setting: parakeet_config")

        return old

    def migrate_defaults(self, old: dict, new: dict) -> dict:
        """Migrate defaults.yaml from 2.1.0 to 3.0.0."""
        # Add per-wingman Parakeet STT config
        if "parakeet" not in old and "parakeet" in new:
            old["parakeet"] = new["parakeet"]
            self.log("- added new default: parakeet (STT config)")

        return old

    def migrate_wingman(self, old: dict, new: dict) -> dict:
        """Migrate wingman configs from 2.1.0 to 3.0.0."""
        return old
