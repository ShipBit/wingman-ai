"""Migration from version 3.2.9 to 3.2.10.

3.2.10 ships a second pronunciation list, "wingman", for words of no game
in particular ("online", "Wingman" in German). It is switched on for every
user once, like the Star Citizen list was. A user who switches it off later
keeps it off: this step runs only once.

Computer gets the AI sound effect by default. A shipped Wingman without sound
effects of its own takes its template's, so an untouched Computer gets it
too. One with effects the user set keeps them.

Every `migrate_*` method is optional: the base class returns the config
unchanged, so an empty migration is a valid one. Override only what you need.
"""

from services.migrations.base_migration import BaseMigration

WINGMAN_PRESET = "wingman"


class Migration329To3210(BaseMigration):
    """Migration from 3.2.9 to 3.2.10."""

    old_version = "3_2_9"
    new_version = "3_2_10"

    def migrate_wingman(self, old: dict) -> dict:
        template = self.shipped_template()
        if not template or "sound" in old or "sound" not in template:
            return old
        old["sound"] = dict(template["sound"])
        self.log(f"- {old.get('name') or template.get('name')}: sound effects of its template")
        return old

    def migrate_settings(self, old: dict) -> dict:
        pronunciation = old.get("pronunciation")
        if not isinstance(pronunciation, dict):
            # The template's block is filled in at the end of the chain.
            return old
        presets = pronunciation.get("presets")
        if not isinstance(presets, list):
            presets = []
        if WINGMAN_PRESET not in presets:
            pronunciation["presets"] = [WINGMAN_PRESET, *presets]
            self.log(f"- pronunciation: switched on the {WINGMAN_PRESET} list")
        return old
