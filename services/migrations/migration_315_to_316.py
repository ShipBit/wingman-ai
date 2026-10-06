"""Migration from version 3.1.5 to 3.1.6.

No config changes. 3.1.6 is a migration hotfix release: packaged 3.1.5 builds
shipped without the stdlib module 'filecmp', so migration_313_to_314 failed to
load and the 3.1.3 -> 3.1.5 migration aborted after deleting the template
configs - leaving users with a template-only, marker-less 3_1_5 directory.
This release re-runs the chain from the last completed version (3_1_3 for
affected users, since marker-less interrupted artifacts are skipped as
migration source).
"""

from services.migrations.base_migration import BaseMigration


class Migration315To316(BaseMigration):
    """Migration from 3.1.5 to 3.1.6."""

    old_version = "3_1_5"
    new_version = "3_1_6"
