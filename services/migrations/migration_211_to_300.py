"""Migration from version 2.1.1 to 3.0.0."""

from services.migrations.base_migration import BaseMigration


class Migration211To300(BaseMigration):
    """Migration from 2.1.1 to 3.0.0."""

    old_version = "2_1_1"
    new_version = "3_0_0"

    def migrate_settings(self, old: dict, new: dict) -> dict:
        """Migrate settings.yaml from 2.1.1 to 3.0.0."""
        # Add Local AI (llama.cpp) settings
        if "llama_cpp" not in old and "llama_cpp" in new:
            old["llama_cpp"] = new["llama_cpp"]
            self.log("- added new setting: llama_cpp (local AI)")

        # Upgrade default summarize model from 0.8B to 2B
        llama = old.get("llama_cpp", {})
        if llama.get("summarize_model") == "Qwen3.5-0.8B-Q4_K_M.gguf":
            llama["summarize_model"] = "Qwen3.5-2B-Q4_K_M.gguf"
            self.log("- upgraded summarize model: Qwen3.5-0.8B → Qwen3.5-2B")

        # Rename summarize_* fields to support_*
        if "summarize_model" in llama:
            llama["support_model"] = llama.pop("summarize_model")
            self.log("- renamed llama_cpp.summarize_model → support_model")
        if "summarize_remote_host" in llama:
            llama["support_remote_host"] = llama.pop("summarize_remote_host")
            self.log("- renamed llama_cpp.summarize_remote_host → support_remote_host")
        if "summarize_remote_port" in llama:
            llama["support_remote_port"] = llama.pop("summarize_remote_port")
            self.log("- renamed llama_cpp.summarize_remote_port → support_remote_port")

        # Add Parakeet STT settings
        va = old.get("voice_activation", {})
        new_va = new.get("voice_activation", {})
        if "parakeet" not in va and "parakeet" in new_va:
            va["parakeet"] = new_va["parakeet"]
            self.log("- added new voice activation setting: parakeet")
        if "parakeet_config" not in va and "parakeet_config" in new_va:
            va["parakeet_config"] = new_va["parakeet_config"]
            self.log("- added new voice activation setting: parakeet_config")

        # Ensure existing Parakeet configs have the run_locally field
        parakeet = va.get("parakeet", {})
        if parakeet and "run_locally" not in parakeet:
            parakeet["run_locally"] = True
            self.log("- added parakeet.run_locally = true")

        # Ensure existing PocketTTS configs have run_locally, host, port fields
        pocket_tts = old.get("pocket_tts", {})
        if pocket_tts:
            if "run_locally" not in pocket_tts:
                pocket_tts["run_locally"] = True
                self.log("- added pocket_tts.run_locally = true")
            if "host" not in pocket_tts:
                pocket_tts["host"] = "localhost"
                self.log("- added pocket_tts.host = localhost")
            if "port" not in pocket_tts:
                pocket_tts["port"] = 5002
                self.log("- added pocket_tts.port = 5002")

        return old

    def migrate_defaults(self, old: dict, new: dict) -> dict:
        """Migrate defaults.yaml from 2.1.1 to 3.0.0."""
        # Add per-wingman Parakeet STT config
        if "parakeet" not in old and "parakeet" in new:
            old["parakeet"] = new["parakeet"]
            self.log("- added new default: parakeet (STT config)")

        # Add conversation optimization features
        features = old.setdefault("features", {})
        if "condense_conversation" not in features:
            features["condense_conversation"] = True
            self.log("- added new feature: condense_conversation = true")
        if "compress_tool_responses" not in features:
            features["compress_tool_responses"] = True
            self.log("- added new feature: compress_tool_responses = true")

        # Add persistent memory (enabled by default)
        if "persistent_memory" not in old:
            old["persistent_memory"] = True
            self.log("- added new default: persistent_memory = true")

        return old

    def migrate_wingman(self, old: dict, new: dict) -> dict:
        """Migrate wingman configs from 2.1.1 to 3.0.0."""
        # Add conversation optimization features if wingman has feature overrides
        features = old.get("features")
        if features is not None:
            if "condense_conversation" not in features:
                features["condense_conversation"] = True
                self.log("- added new feature: condense_conversation = true")
            if "compress_tool_responses" not in features:
                features["compress_tool_responses"] = True
                self.log("- added new feature: compress_tool_responses = true")

        # Add persistent memory (enabled by default)
        if "persistent_memory" not in old:
            old["persistent_memory"] = True
            self.log("- added new setting: persistent_memory = true")

        return old
