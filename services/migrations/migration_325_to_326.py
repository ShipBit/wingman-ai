"""Migration from version 3.2.5 to 3.2.6.

3.2.5 is out with testers, so the next change to a user's config needs its own
step. This one starts empty: nothing in 3.2.6 changes a config yet, and the
features of the release add their steps here as they land.
"""

from services.migrations.base_migration import BaseMigration


class Migration325To326(BaseMigration):
    """Migration from 3.2.5 to 3.2.6."""

    old_version = "3_2_5"
    new_version = "3_2_6"
