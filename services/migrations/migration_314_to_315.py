"""Migration from version 3.1.4 to 3.1.5.

No config changes. 3.1.5 is a packaging fix release: the 3.1.4 Windows build
shipped an incomplete PyAV bundle (av 18 failed to import on the CI runner)
and the installer never cleaned stale files in _internal.
"""

from services.migrations.base_migration import BaseMigration


class Migration314To315(BaseMigration):
    """Migration from 3.1.4 to 3.1.5."""

    old_version = "3_1_4"
    new_version = "3_1_5"
