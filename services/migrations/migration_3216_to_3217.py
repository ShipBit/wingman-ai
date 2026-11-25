"""Migration from version 3.2.16 to 3.2.17.

Nothing in a user's config changes. 3.2.16 and 3.2.17 are the same code:
3.2.16 is the stable release, 3.2.17 the unstable one, built for its channel
with Star Citizen telemetry and the input helper for admin games switched on.
The step exists so that unstable 3.2.15 configs, through 3.2.16, have a path
to 3.2.17.
"""

from services.migrations.base_migration import BaseMigration


class Migration3216To3217(BaseMigration):
    """Migration from 3.2.16 to 3.2.17."""

    old_version = "3_2_16"
    new_version = "3_2_17"
