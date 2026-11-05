"""Migration from version 3.2.13 to 3.2.14.

The decision model gets a provider. Until now it was always the one behind
Wingman Pro; from 3.2.14 on it can also be any decision model on OpenRouter,
with the user's own key, or a System One server the user runs, like oMLX.
Existing configs get Wingman Pro, which is what they used.

The block is renamed from `system_one` to `decision_model`, next to the main
model and the support model in Settings. "System One" stays the name of the
request format and of the skill API (`self.wingman.system_one`). The user's
switches move over unchanged.
"""

from services.migrations.base_migration import BaseMigration

PROVIDER_DEFAULTS = {
    "provider": "wingman_pro",
    "openrouter": {"model": "~typesafe/jev-latest"},
    "server": {"endpoint": "", "model": ""},
}


class Migration3213To3214(BaseMigration):
    """Migration from 3.2.13 to 3.2.14."""

    old_version = "3_2_13"
    new_version = "3_2_14"

    def migrate_settings(self, old: dict) -> dict:
        # The load-time repair may already have written a `decision_model`
        # block from the template. The switches in `system_one` are the
        # user's, so they win over it.
        legacy = old.pop("system_one", None)
        block = old.get("decision_model")
        if not isinstance(block, dict):
            block = {}
        if isinstance(legacy, dict):
            block.update(legacy)
            self.log("- system_one: renamed to decision_model, switches kept")
        for key, value in PROVIDER_DEFAULTS.items():
            if isinstance(value, dict):
                existing = block.get(key)
                block[key] = {**value, **existing} if isinstance(existing, dict) else dict(value)
            else:
                block.setdefault(key, value)
        old["decision_model"] = block
        return old
