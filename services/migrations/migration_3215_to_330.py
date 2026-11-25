"""Migration from version 3.2.15 to 3.3.0.

Nothing in a user's config changes. 3.3.0 adds `elevated_input` to
settings.yaml, the switch for the input helper that lets commands and
push-to-talk reach a game running as administrator. A missing value means
"follow the update channel" (on for unstable, off for production), which is
what every existing config should get, so there is nothing to write. The step
exists so that 3.2.15 configs, and through 3.2.14 -> 3.2.15 the stable ones,
have a path to 3.3.0.
"""

from services.migrations.base_migration import BaseMigration


class Migration3215To330(BaseMigration):
    """Migration from 3.2.15 to 3.3.0."""

    old_version = "3_2_15"
    new_version = "3_3_0"
