"""Migration from version 3.2.9 to 3.2.10.

Nothing changes in a user's config yet. 3.2.10 starts with a dependency fix
(edge-tts), which needs no config step.

Every `migrate_*` method is optional: the base class returns the config
unchanged, so an empty migration is a valid one. Override only what you need.
"""

from services.migrations.base_migration import BaseMigration


class Migration329To3210(BaseMigration):
    """Migration from 3.2.9 to 3.2.10."""

    old_version = "3_2_9"
    new_version = "3_2_10"
