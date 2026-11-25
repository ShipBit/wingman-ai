"""Migration from version 3.2.15 to 3.3.0.

Nothing in a user's config changes. 3.3.0 adds no setting: holding a key over
several actions, the input helper for games that run as administrator and the
quiet cancel of an ElevenLabs answer all work with the configs as they are. The
step exists so that 3.2.15 configs, and through 3.2.14 -> 3.2.15 the stable
ones, have a path to 3.3.0.
"""

from services.migrations.base_migration import BaseMigration


class Migration3215To330(BaseMigration):
    """Migration from 3.2.15 to 3.3.0."""

    old_version = "3_2_15"
    new_version = "3_3_0"
