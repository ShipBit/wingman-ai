"""Migration from version 3.2.6 to 3.2.7.

3.2.6 is out with testers, so the next change to a user's config needs its own
step. This one starts empty: nothing in 3.2.7 changes a config yet, and the
features of the release add their steps here as they land.
"""

from services.migrations.base_migration import BaseMigration


class Migration326To327(BaseMigration):
    """Migration from 3.2.6 to 3.2.7."""

    old_version = "3_2_6"
    new_version = "3_2_7"
