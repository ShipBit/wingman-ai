"""Migration from version 3.2.11 to 3.2.12.

3.2.12 changes nothing in a user's config so far. The step exists so the
version chain stays unbroken.

Every `migrate_*` method is optional: the base class returns the config
unchanged, so an empty migration is a valid one. Override only what you need.
"""

from services.migrations.base_migration import BaseMigration


class Migration3211To3212(BaseMigration):
    """Migration from 3.2.11 to 3.2.12."""

    old_version = "3_2_11"
    new_version = "3_2_12"
