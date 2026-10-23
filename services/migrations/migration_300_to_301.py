"""Migration from version 3.0.0 to 3.0.1.

Forces Qwen3.5-recommended sampling parameters for all users.
"""

from services.migrations.base_migration import BaseMigration


class Migration300To301(BaseMigration):
    """Migration from 3.0.0 to 3.0.1."""

    old_version = "3_0_0"
    new_version = "3_0_1"

    def migrate_settings(self, old: dict) -> dict:
        """Force Qwen3.5-recommended sampling defaults on all users."""
        llama = old.get("llama_cpp", {})

        # Force new temperature (was 0.3, Qwen recommends 1.0)
        old_temp = llama.get("temperature")
        llama["temperature"] = 1.0
        if old_temp is not None and old_temp != 1.0:
            self.log(f"- updated llama_cpp.temperature: {old_temp} → 1.0 (Qwen3.5 recommended)")

        # Force top_p to 1.0 (was already 1.0 for most users)
        llama["top_p"] = 1.0

        # Add new sampling params
        llama["top_k"] = 20
        self.log("- added llama_cpp.top_k = 20 (Qwen3.5 recommended)")

        llama["presence_penalty"] = 2.0
        self.log("- added llama_cpp.presence_penalty = 2.0 (Qwen3.5 recommended)")

        return old
