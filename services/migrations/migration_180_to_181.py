"""Migration from version 1.8.0 to 1.8.1.

This is a no-op migration that maintains chain continuity.
No config changes are required for this version bump.
"""

from services.migrations.base_migration import BaseMigration


class Migration180To181(BaseMigration):
    """No-op migration from 1.8.0 to 1.8.1.

    This migration exists to maintain the migration chain for users
    who have version 1.8.0 installed. All configs pass through unchanged.
    """

    old_version = "1_8_0"
    new_version = "1_8_1"

    # All methods use default implementations that return configs unchanged
