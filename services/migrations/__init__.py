"""Auto-discovery system for config migrations.

Automatically discovers and registers migration classes from this directory.
"""

import importlib
import inspect
from pathlib import Path
from typing import List, Tuple, Type

from services.migrations.base_migration import BaseMigration


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

                    # Get version properties (they may be properties or class attributes)
                    old_ver = (
                        obj.old_version
                        if isinstance(obj.old_version, str)
                        else obj.old_version.fget(None)
                    )
                    new_ver = (
                        obj.new_version
                        if isinstance(obj.new_version, str)
                        else obj.new_version.fget(None)
                    )

                    migrations.append((old_ver, new_ver, obj))

        except Exception as e:
            # Log warning but don't fail - allows graceful degradation
            print(f"Warning: Failed to load migration {migration_file}: {e}")

    # Sort by old_version to maintain proper migration order
    migrations.sort(key=lambda m: [int(n) for n in m[0].split("_")])

    return migrations
