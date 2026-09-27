"""Migration from version 3.2.4 to 3.2.5.

Nothing in a user's config changes. 3.2.5 changes how the client installs an
update: a toast with download progress, and a restart once it is installed.
None of that is configured.
"""

from services.migrations.base_migration import BaseMigration


class Migration324To325(BaseMigration):
    """Migration from 3.2.4 to 3.2.5."""

    old_version = "3_2_4"
    new_version = "3_2_5"
