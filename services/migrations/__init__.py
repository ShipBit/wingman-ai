"""Auto-discovery system for config migrations.

Automatically discovers and registers migration classes from this directory.
"""

import importlib
import inspect
from pathlib import Path
from typing import List, Tuple, Type

from api.enums import LogType
from services.migrations.base_migration import BaseMigration
from services.printr import Printr


def discover_migrations() -> List[Tuple[str, str, Type[BaseMigration]]]:
    """Auto-discover migration classes in migrations/ directory.

    Scans for migration_*.py files and extracts classes that inherit from
    BaseMigration. Migrations are automatically sorted by version order.

    Returns:
        List of tuples: (old_version, new_version, MigrationClass)
        Sorted by version in ascending order
    """
    migrations = []
    migrations_dir = Path(__file__).parent
    printr = Printr()
    failed_migrations = []

    # Find all migration_*.py files (excluding __init__.py and base_migration.py)
    for migration_file in sorted(migrations_dir.glob("migration_*.py")):
        module_name = f"services.migrations.{migration_file.stem}"

        try:
            # Import the migration module
            module = importlib.import_module(module_name)

            # Find classes that inherit from BaseMigration
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(obj, BaseMigration)
                    and obj is not BaseMigration
                    and hasattr(obj, "old_version")
                    and hasattr(obj, "new_version")
                ):
                    # Get version attributes (class attributes, not properties)
                    old_ver = obj.old_version
                    new_ver = obj.new_version

                    migrations.append((old_ver, new_ver, obj))

        except Exception as e:
            error_msg = f"Failed to load migration {migration_file.stem}: {e}"
            printr.print(error_msg, color=LogType.WARNING)
            failed_migrations.append(migration_file.stem)

    # Sort by old_version to maintain proper migration order
    migrations.sort(key=lambda m: [int(n) for n in m[0].split("_")])

    # Validate migration chain integrity
    if failed_migrations:
        if migrations:
            # We have some migrations but some failed - check for broken chains
            printr.print(
                f"Migration chain may be incomplete. Failed migrations: {', '.join(failed_migrations)}",
                color=LogType.ERROR,
            )
            printr.print(
                "User configs may not migrate correctly if they span versions with failed migrations.",
                color=LogType.WARNING,
            )
        else:
            # All migrations failed - critical error
            printr.print(
                f"Critical: All migrations failed to load. Application may not function correctly.",
                color=LogType.ERROR,
            )

    return migrations
