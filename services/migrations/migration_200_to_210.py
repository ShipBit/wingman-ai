"""Migration from version 2.0.0 to 2.1.0.

Major changes:
- Refactored provider architecture (BaseProvider pattern)
- Image generation as proper provider capability
- Benchmark helpers moved to Benchmark class
- Unified provider registry with image generation support
"""

from services.migrations.base_migration import BaseMigration


class Migration200To210(BaseMigration):
    """Migration from 2.0.0 to 2.1.0."""

    old_version = "2_0_0"
    new_version = "2_1_0"

    def migrate_settings(self, old: dict, new: dict) -> dict:
        """Migrate settings.yaml from 2.0.0 to 2.1.0.

        No breaking changes in settings for this version.
        Provider architecture changes are backward compatible.

        Args:
            old: Old settings dictionary
            new: New settings dictionary (template)

        Returns:
            Migrated settings dictionary
        """
        # No changes needed - all provider refactoring is backward compatible
        return old

    def migrate_defaults(self, old: dict, new: dict) -> dict:
        """Migrate defaults.yaml from 2.0.0 to 2.1.0.

        No breaking changes in defaults for this version.

        Args:
            old: Old defaults dictionary
            new: New defaults dictionary (template)

        Returns:
            Migrated defaults dictionary
        """
        # No changes needed - config structure remains the same
        return old

    def migrate_wingman_config(self, wingman_name: str, old: dict, new: dict) -> dict:
        """Migrate individual wingman config from 2.0.0 to 2.1.0.

        No breaking changes in wingman configs for this version.

        Args:
            wingman_name: Name of the wingman being migrated
            old: Old wingman config dictionary
            new: New wingman config dictionary (template)

        Returns:
            Migrated wingman config dictionary
        """
        # No changes needed - wingman config structure remains the same
        return old
