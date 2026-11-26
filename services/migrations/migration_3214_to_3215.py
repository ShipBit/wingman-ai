"""Migration from version 3.2.14 to 3.2.15.

Nothing in a user's config changes. 3.2.14 is the stable release with Star
Citizen telemetry switched off and 3.2.15 the unstable one with it on, from the
same code; the settings for telemetry are already there since 3.2.13. The step
exists so that both a stable 3.2.14 and an unstable 3.2.13 config have a path
to 3.2.15.
"""

from services.migrations.base_migration import BaseMigration


class Migration3214To3215(BaseMigration):
    """Migration from 3.2.14 to 3.2.15."""

    old_version = "3_2_14"
    new_version = "3_2_15"
