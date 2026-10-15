"""Migration from version 3.2.8 to 3.2.9.

Nothing changes in a user's config so far. 3.2.9 moves the changelog and the
feature requests from Canny to our backend, and neither lives in the config.

Every `migrate_*` method is optional: the base class returns the config
unchanged, so an empty migration is a valid one. Override only what you need.
"""

from services.migrations.base_migration import BaseMigration


class Migration328To329(BaseMigration):
    """Migration from 3.2.8 to 3.2.9."""

    old_version = "3_2_8"
    new_version = "3_2_9"
