"""Migration from version 3.0.1 to 3.1.0."""

from services.migrations.base_migration import BaseMigration


class Migration301To310(BaseMigration):
    """Migration from 3.0.1 to 3.1.0."""

    old_version = "3_0_1"
    new_version = "3_1_0"
