"""Base migration class for config migrations.

Provides common utilities and decorators for migration implementations.
"""

from abc import ABC, abstractmethod
from functools import wraps
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from services.config_migration_service import ConfigMigrationService


def log_step(step_name: str):
    """Decorator to log migration step execution.

    Args:
        step_name: Name of the migration step being executed
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            self.log(f"Starting: {step_name}")
            result = func(self, *args, **kwargs)
            self.log(f"Completed: {step_name}")
            return result

        return wrapper

    return decorator


def handle_errors(func: Callable) -> Callable:
    """Decorator to log errors before re-raising them.

    Ensures migration errors are captured in the migration log file.
    """

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception as e:
            self.err(f"Error in {func.__name__}: {str(e)}")
            raise

    return wrapper


class BaseMigration(ABC):
    """Abstract base class for config migrations.

    Provides access to service utilities and common patterns for migrations.
    Each migration should implement the migrate_* methods for transforming configs.
    """

    def __init__(self, service: "ConfigMigrationService"):
        """Initialize migration with reference to main service.

        Args:
            service: The main ConfigMigrationService instance
        """
        self.service = service
        self.config_manager = service.config_manager
        self.system_manager = service.system_manager
        self.templates_dir = service.templates_dir

    # Version identifiers - implement as class attributes in subclasses
    # Example: old_version = "1_8_0"
    old_version: str
    new_version: str

    def migrate_settings(self, old: dict, new: dict) -> dict:
        """Transform settings.yaml from old to new version.

        Args:
            old: Old version settings config
            new: New version template settings config

        Returns:
            Migrated settings config
        """
        return old

    def migrate_defaults(self, old: dict, new: dict) -> dict:
        """Transform defaults.yaml from old to new version.

        Args:
            old: Old version defaults config
            new: New version template defaults config

        Returns:
            Migrated defaults config
        """
        return old

    def migrate_wingman(self, old: dict, new: Optional[dict]) -> dict:
        """Transform wingman config from old to new version.

        Args:
            old: Old version wingman config
            new: New version template wingman config (if available)

        Returns:
            Migrated wingman config
        """
        return old

    def migrate_secrets(self, old: dict) -> dict:
        """Transform secrets.yaml from old to new version.

        Override this method if secrets need migration.

        Args:
            old: Old version secrets config

        Returns:
            Migrated secrets config
        """
        return old

    def migrate_mcp(self, old: dict, new: dict) -> dict:
        """Transform mcp.yaml from old to new version.

        Override this method if MCP config needs migration.

        Args:
            old: Old version MCP config
            new: New version template MCP config

        Returns:
            Migrated MCP config
        """
        return new

    def has_secrets_migration(self) -> bool:
        """Check if this migration has custom secrets logic.

        Returns:
            True if migrate_secrets is overridden
        """
        return type(self).migrate_secrets is not BaseMigration.migrate_secrets

    def has_mcp_migration(self) -> bool:
        """Check if this migration has custom MCP logic.

        Returns:
            True if migrate_mcp is overridden
        """
        return type(self).migrate_mcp is not BaseMigration.migrate_mcp

    def execute(self) -> None:
        """Execute this migration."""
        self.service.migrate(
            old_version=self.old_version,
            new_version=self.new_version,
            migrate_settings=self.migrate_settings,
            migrate_defaults=self.migrate_defaults,
            migrate_wingman=self.migrate_wingman,
            migrate_secrets=(
                self.migrate_secrets if self.has_secrets_migration() else None
            ),
            migrate_mcp=self.migrate_mcp if self.has_mcp_migration() else None,
        )

    # Logging utilities (delegated to service)

    def log(self, message: str) -> None:
        """Log a normal message."""
        self.service.log(message)

    def log_highlight(self, message: str) -> None:
        """Log a highlighted message."""
        self.service.log_highlight(message)

    def log_warning(self, message: str) -> None:
        """Log a warning message."""
        self.service.log_warning(message)

    def err(self, message: str) -> None:
        """Log an error message."""
        self.service.err(message)

    # Utility methods

    @staticmethod
    def no_op(old: dict, new: dict = None) -> dict:
        """Identity function for no-op transformations.

        Args:
            old: Config to pass through unchanged
            new: Ignored

        Returns:
            The old config unchanged
        """
        return old
