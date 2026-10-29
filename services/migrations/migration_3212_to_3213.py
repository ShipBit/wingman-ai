"""Migration from version 3.2.12 to 3.2.13.

Jev, the decision model, gets a switch per place it decides: commands (there
already), the Wingman for the global push-to-talk key, names in speech
recognition, and skills. The three new ones start on, so whoever had Jev on
keeps every decision it took before.
"""

from services.migrations.base_migration import BaseMigration

NEW_SYSTEM_ONE_SWITCHES = ("wingman_choice", "vocabulary", "skills")


class Migration3212To3213(BaseMigration):
    """Migration from 3.2.12 to 3.2.13."""

    old_version = "3_2_12"
    new_version = "3_2_13"

    def migrate_settings(self, old: dict) -> dict:
        system_one = old.get("system_one")
        if isinstance(system_one, dict):
            for switch in NEW_SYSTEM_ONE_SWITCHES:
                system_one.setdefault(switch, True)
        return old
