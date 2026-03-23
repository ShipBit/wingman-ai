"""Migration from version 2.1.0 to 2.1.1.

Major changes:
- Migrates Wingman Subscription (Pro & Ultra) conversation model from
  gpt-4o-mini / gpt-5-mini to gpt-4.1-mini (Azure deprecation of 4o-mini,
  4.1-mini outperforms both previous options)
- Migrates OpenAI conversation model from gpt-4o-mini to gpt-4.1-mini
"""

from typing import Optional

from services.migrations.base_migration import BaseMigration

# Models being replaced for Wingman Pro subscribers
DEPRECATED_WINGMAN_PRO_MODELS = [
    "gpt-4o-mini",
    "gpt-5-mini",
]

NEW_PRO_MODEL_FALLBACK = "gpt-4.1-mini"
NEW_OPENAI_MODEL_FALLBACK = "gpt-4.1-mini"


class Migration210To211(BaseMigration):
    """Migration from 2.1.0 to 2.1.1."""

    old_version = "2_1_0"
    new_version = "2_1_1"

    def __init__(self, service):
        super().__init__(service)
        self._new_pro_model = NEW_PRO_MODEL_FALLBACK
        self._new_openai_model = NEW_OPENAI_MODEL_FALLBACK

    def migrate_defaults(self, old: dict, new: dict) -> dict:
        """Migrate defaults.yaml from 2.1.0 to 2.1.1."""
        new_pro_model = new.get("wingman_pro", {}).get(
            "conversation_deployment",
            self._new_pro_model,
        )
        new_openai_model = new.get("openai", {}).get(
            "conversation_model",
            self._new_openai_model,
        )

        # Migrate Wingman Pro default conversation model
        if "wingman_pro" in old and "conversation_deployment" in old["wingman_pro"]:
            current_model = old["wingman_pro"]["conversation_deployment"]
            if current_model in DEPRECATED_WINGMAN_PRO_MODELS:
                old["wingman_pro"]["conversation_deployment"] = new_pro_model
                self.log(
                    f"- migrated wingman_pro.conversation_deployment from '{current_model}' to '{new_pro_model}'"
                )

        # Migrate OpenAI default conversation model
        if "openai" in old and "conversation_model" in old["openai"]:
            current_model = old["openai"]["conversation_model"]
            if current_model == "gpt-4o-mini":
                old["openai"]["conversation_model"] = new_openai_model
                self.log(
                    f"- migrated openai.conversation_model from '{current_model}' to '{new_openai_model}'"
                )

        # Store for use in migrate_wingman (which doesn't receive defaults as `new`)
        self._new_pro_model = new_pro_model
        self._new_openai_model = new_openai_model

        return old

    def migrate_wingman(self, old: dict, new: Optional[dict]) -> dict:
        """Migrate wingman configs from 2.1.0 to 2.1.1."""
        # Only migrate wingmen that have an explicit wingman_pro conversation model override.
        # Wingmen without this override inherit from defaults (already migrated above).
        if "wingman_pro" in old and "conversation_deployment" in old["wingman_pro"]:
            current_model = old["wingman_pro"]["conversation_deployment"]
            if current_model in DEPRECATED_WINGMAN_PRO_MODELS:
                old["wingman_pro"]["conversation_deployment"] = self._new_pro_model
                self.log(
                    f"- migrated wingman_pro.conversation_deployment from '{current_model}' to '{self._new_pro_model}'"
                )

        # Migrate OpenAI conversation model override if present
        if "openai" in old and "conversation_model" in old["openai"]:
            current_model = old["openai"]["conversation_model"]
            if current_model == "gpt-4o-mini":
                old["openai"]["conversation_model"] = self._new_openai_model
                self.log(
                    f"- migrated openai.conversation_model from '{current_model}' to '{self._new_openai_model}'"
                )

        return old
