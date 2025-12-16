# Config Migration System

This directory contains the modular migration system for Wingman AI config files. The system automatically discovers and chains migrations to upgrade user configs from older versions to the latest version.

## Architecture Overview

The migration system consists of three main components:

### 1. Auto-Discovery (`__init__.py`)

- Automatically scans this directory for `migration_*.py` files
- Extracts migration classes that inherit from `BaseMigration`
- Sorts migrations by version order
- Returns a chain of migrations from oldest to newest

### 2. Base Migration Class (`base_migration.py`)

- Abstract base class providing common utilities for all migrations
- Defines the migration interface that all migrations must implement
- Provides decorators for logging and error handling
- Offers helper methods for accessing service utilities

### 3. Individual Migrations (`migration_XXX_to_YYY.py`)

- Each file handles one version transition (e.g., 1.7.0 → 1.8.0)
- Implements specific transformation logic for that version bump
- Contains version-specific helper methods when needed
- Auto-discovered and executed in version order

## Migration Chain

Current migration chain (executed sequentially):

```
1.7.0 → 1.8.0 → 1.8.1 → 1.8.2 → 1.9.0
```

The system automatically finds the user's current version and executes all migrations needed to reach the latest version.

## How Migrations Work

### Execution Flow

1. **Discovery**: System scans for user's existing version directories
2. **Chain Building**: Auto-discovery finds all available migrations
3. **Sequential Execution**: Each migration transforms configs step-by-step
4. **Validation**: Configs are validated using Pydantic models
5. **Rollback Safety**: Original configs preserved in versioned directories

### What Gets Migrated

Each migration can transform five types of files:

- **settings.yaml**: Global application settings
- **defaults.yaml**: Default provider configurations
- **wingmen configs**: Individual wingman YAML files
- **secrets.yaml**: API keys and sensitive data (optional)
- **mcp.yaml**: Model Context Protocol configuration (optional)

### Migration Methods

Each migration class can override these methods:

```python
def migrate_settings(self, old: dict, new: dict) -> dict:
    """Transform settings.yaml from old version to new version."""

def migrate_defaults(self, old: dict, new: dict) -> dict:
    """Transform defaults.yaml from old version to new version."""

def migrate_wingman(self, old: dict, new: Optional[dict]) -> dict:
    """Transform individual wingman config from old version to new version."""

def migrate_secrets(self, old: dict) -> dict:
    """Transform secrets.yaml from old version to new version."""

def migrate_mcp(self, old: dict, new: dict) -> dict:
    """Transform mcp.yaml from old version to new version."""
```

**Note**: You only need to override methods that actually change configs. Methods return the old config unchanged by default.

## Adding a New Migration

### Step 1: Create the Migration File

Create a new file following the naming convention:

```bash
migration_XXX_to_YYY.py
```

Where:

- `XXX` = old version (e.g., `190` for 1.9.0)
- `YYY` = new version (e.g., `200` for 2.0.0)

Example: `migration_190_to_200.py`

### Step 2: Implement the Migration Class

```python
"""Migration from version 1.9.0 to 2.0.0.

Major changes:
- Brief bullet points describing what this migration does
- Keep this updated - it helps future maintainers understand the changes
"""

from services.migrations.base_migration import BaseMigration


class Migration190To200(BaseMigration):
    """Migration from 1.9.0 to 2.0.0."""

    old_version = "1_9_0"
    new_version = "2_0_0"

    def migrate_settings(self, old: dict, new: dict) -> dict:
        """Migrate settings.yaml from 1.9.0 to 2.0.0."""
        # Add new settings
        old["new_feature_enabled"] = True
        self.log("- added new_feature_enabled setting")

        # Update existing settings
        if "old_setting" in old:
            old["new_setting"] = old.pop("old_setting")
            self.log("- migrated old_setting to new_setting")

        return old

    def migrate_defaults(self, old: dict, new: dict) -> dict:
        """Migrate defaults.yaml from 1.9.0 to 2.0.0."""
        # Add new provider defaults
        old["new_provider"] = new["new_provider"]
        self.log("- added new_provider configuration")

        return old

    def migrate_wingman(self, old: dict, new: Optional[dict]) -> dict:
        """Migrate wingman configs from 1.9.0 to 2.0.0."""
        # Update wingman-specific settings
        if "deprecated_field" in old:
            del old["deprecated_field"]
            self.log("- removed deprecated_field")

        return old
```

### Step 3: Test Your Migration

The migration will be **automatically discovered** on next run. No registration needed!

Test by:

1. Creating test config files at the old version
2. Running the migration
3. Verifying the output matches expectations
4. Checking the migration log file for any errors

### Step 4: Document Breaking Changes

Update the main docstring with:

- What changed and why
- Any breaking changes users should know about
- Manual steps required (if any)

## Best Practices

### DO ✅

- **Use descriptive logging**: Call `self.log()` for each significant change
- **Keep helpers in migration files**: Version-specific logic stays with the migration
- **Preserve old configs**: Never modify in-place; always work with copies
- **Handle missing keys gracefully**: Use `.get()` with defaults for optional keys
- **Document your changes**: Update the docstring with what changed
- **Test thoroughly**: Migrations are critical - they must work correctly

### DON'T ❌

- **Don't modify base_migration.py** unless adding truly generic utilities
- **Don't skip versions**: Every version transition needs a migration (use no-op if needed)
- **Don't make assumptions**: Check for key existence before accessing
- **Don't swallow errors**: Let exceptions bubble up for proper logging
- **Don't hardcode paths**: Use `self.templates_dir` and service utilities

## No-Op Migrations

Sometimes you need a migration that doesn't change anything (version bump only):

```python
"""Migration from version 1.8.0 to 1.8.1.

This is a no-op migration that maintains chain continuity.
No config changes are required for this version bump.
"""

from services.migrations.base_migration import BaseMigration


class Migration180To181(BaseMigration):
    """No-op migration from 1.8.0 to 1.8.1."""

    old_version = "1_8_0"
    new_version = "1_8_1"

    # All methods use default implementations that return configs unchanged
```

This is valid and necessary for maintaining the migration chain!

## Advanced Patterns

### Using Helper Methods

Keep complex logic in private helper methods within your migration:

```python
class Migration190To200(BaseMigration):
    old_version = "1_9_0"
    new_version = "2_0_0"

    def migrate_wingman(self, old: dict, new: Optional[dict]) -> dict:
        # Use helper method for complex transformation
        old["features"] = self._transform_features(old.get("features", []))
        return old

    def _transform_features(self, features: list) -> list:
        """Transform feature list from old format to new format."""
        return [self._upgrade_feature(f) for f in features]

    def _upgrade_feature(self, feature: dict) -> dict:
        """Upgrade individual feature configuration."""
        # Complex transformation logic here
        return feature
```

### Using Decorators

Use the provided decorators for consistent logging and error handling:

```python
from services.migrations.base_migration import BaseMigration, log_step, handle_errors


class Migration190To200(BaseMigration):
    old_version = "1_9_0"
    new_version = "2_0_0"

    @log_step("Migrating provider configurations")
    @handle_errors
    def migrate_defaults(self, old: dict, new: dict) -> dict:
        # This automatically logs "Starting: Migrating provider configurations"
        # and "Completed: Migrating provider configurations"
        # Errors are logged before being re-raised
        old["new_provider"] = new["new_provider"]
        return old
```

### Accessing Service Utilities

The migration has access to all service utilities:

```python
def migrate_settings(self, old: dict, new: dict) -> dict:
    # Access config manager
    template_config = self.config_manager.load_config("template_name")

    # Access system manager
    cuda_available = self.system_manager.has_cuda()

    # Access templates directory
    template_path = path.join(self.templates_dir, "configs", "example.yaml")

    # Use logging methods
    self.log("Normal message")
    self.log_highlight("Important message")
    self.log_warning("Warning message")
    self.err("Error message")

    return old
```

### Handling Secrets and MCP

Only override these if your migration actually changes them:

```python
def migrate_secrets(self, old: dict) -> dict:
    """Only override if secrets structure changes."""
    old["new_api_provider"] = {
        "api_key": ""
    }
    self.log("- added new_api_provider to secrets")
    return old

def migrate_mcp(self, old: dict, new: dict) -> dict:
    """Only override if MCP config needs updates."""
    # Usually you want to force-update MCP to the new template
    return new
```

The base class automatically detects if you've overridden these methods and only calls them if needed.

## Migration Templates

Template configs are stored in `templates/migration/{version}/configs/`:

- Used as reference for new properties
- Provide default values for new settings
- Ensure migrations have access to correct structure

When adding new features, update the template configs for your new version!

## Troubleshooting

### Migration Not Found

If your migration isn't discovered:

- Check filename follows `migration_XXX_to_YYY.py` pattern
- Verify class inherits from `BaseMigration`
- Confirm `old_version` and `new_version` are set correctly
- Check for syntax errors preventing import

### Migration Fails

If a migration fails:

- Check `configs/.migration` log file for detailed error messages
- Verify the user's old config structure matches expectations
- Test with actual user configs, not just synthetic examples
- Use broad exception handling at migration boundaries only

### Changes Not Applied

If changes aren't visible:

- Confirm the migration completed successfully (check logs)
- Verify you're looking at the new version directory
- Check that ConfigManager is loading from the correct location
- Ensure validation didn't reject invalid changes

## Version Numbering

Version strings use underscores instead of dots:

- **Code**: `"1_9_0"` (used in migrations)
- **Display**: `"1.9.0"` (shown to users)

Always use underscore format in migration code.

## File Organization

```
services/migrations/
├── README.md                      # This file
├── __init__.py                    # Auto-discovery system
├── base_migration.py              # Base class and decorators
├── migration_170_to_180.py        # 1.7.0 → 1.8.0
├── migration_180_to_181.py        # 1.8.0 → 1.8.1 (no-op)
├── migration_181_to_182.py        # 1.8.1 → 1.8.2
└── migration_182_to_190.py        # 1.8.2 → 1.9.0
```

Each migration is self-contained with all its logic and helpers.

## Summary

The migration system is designed to be:

- **Automatic**: No manual registration required
- **Safe**: Preserves old configs, validates new ones
- **Modular**: Each version transition in its own file
- **Maintainable**: Clear structure, good documentation
- **Extensible**: Easy to add new migrations

When in doubt, look at existing migrations like [migration_182_to_190.py](migration_182_to_190.py) for complex examples or [migration_180_to_181.py](migration_180_to_181.py) for simple no-ops.

Happy migrating! 🚀
