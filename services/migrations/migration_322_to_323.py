"""Migration from version 3.2.2 to 3.2.3.

Nothing in a user's config changes. 3.2.3 fixes how an existing settings.yaml is
read, not what is written in it: a file that predates the current models is
filled from the shipped template when it is loaded, which needs no migration
step. The step exists so that a 3.2.2 install has an entry in the chain at all.
"""

from services.migrations.base_migration import BaseMigration


class Migration322To323(BaseMigration):
    """Migration from 3.2.2 to 3.2.3."""

    old_version = "3_2_2"
    new_version = "3_2_3"
