"""Migration from version 3.2.7 to 3.2.8.

TODO: say what changes in a user's config, and why. If nothing changes, say that
— an empty migration is a normal thing to ship and the sentence explaining why is
what stops the next person wondering whether it was forgotten.

Every `migrate_*` method is optional: the base class returns the config
unchanged, so an empty migration is a valid one. Override only what you need.
"""

from services.migrations.base_migration import BaseMigration


class Migration327To328(BaseMigration):
    """Migration from 3.2.7 to 3.2.8."""

    old_version = "3_2_7"
    new_version = "3_2_8"
