# Wingman AI Development Guidelines

## Critical Rules

### Logging - Never Use `print()`

**ALWAYS use `Printr` class for all output:**

```python
from services.printr import Printr
from api.enums import LogType, LogSource

printr = Printr()

# ✅ Async contexts (preferred when possible)
await printr.print_async("Message", color=LogType.INFO)

# ✅ Sync contexts or server-only logs
printr.print("Message", color=LogType.INFO, server_only=True)

# ✅ In Wingman context - set source_name for UI filtering
await printr.print_async(
    "Action completed",
    color=LogType.INFO,
    source=LogSource.WINGMAN,
    source_name=self.name  # Wingman instance name
)
```

**Parameters:**

- `server_only=True` → Log only in terminal/file, DO NOT send to client UI
- `server_only=False` (default) → Send to client UI
- `color=LogType.{INFO|WARNING|ERROR|SKILL|...}` → Use enum for severity
- `source_name` → Set to Wingman name for proper UI message filtering

**When to use `server_only=True`:**

- Debug/verbose logging
- Internal state changes
- Developer-focused messages
- Avoid spamming the UI

### Skills & Discovery

**Before working on skills or discovery mechanisms:**

1. Read [skills/README.md](../skills/README.md) first
2. Understand progressive tool disclosure, SkillRegistry, CapabilityRegistry
3. Follow metadata guidelines (descriptions, keywords, tags are CRITICAL)
4. Use SecretKeeper for API keys, never custom properties

### Project Structure & Deployment

**Development:**

- Dev/debug primarily on macOS and Windows
- Run from source using Python venv
- Hot reload NOT supported - restart required for config changes

**Production:**

- Bundled with PyInstaller as standalone `.exe`
- Launched as sidecar process by Wingman AI Client
- Client: SvelteKit app bundled with Tauri (Rust)
- Communication: WebSockets + REST API (FastAPI)

**Config locations:**

- Dev: `./configs/`
- Production: `%APPDATA%/ShipBit/WingmanAI/[version]/` (Windows) or `~/Library/Application Support/WingmanAI/` (macOS)

## Code Conventions

### Type Hints

Always use type hints. Use `TYPE_CHECKING` guard for circular imports:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from wingman import Wingman
```

### Async/Await

- Prefer async methods in Wingman and Skill classes
- Use `await` for I/O operations (API calls, file ops, audio)
- Don't block event loop with sync operations

### Configuration

- Never cache config values in skills - retrieve just-in-time
- Use `retrieve_custom_property_value()` in runtime methods
- Validate existence in `validate()`, retrieve fresh values in execution methods

### API Keys & Secrets

Use `SecretKeeper` service:

```python
api_key = await self.retrieve_secret(
    secret_name="service_api_key",
    errors=errors,
    hint="Get your key from https://service.com/api"
)
```

## Documentation

**Primary docs:**

- [Skills Developer Guide](../skills/README.md) - Creating custom skills
- [Development Setup - Windows](../docs/develop-windows.md)
- [Development Setup - macOS](../docs/develop-macos.md)
- [Main README](../README.md) - Project overview

**When editing:**

- Skills → Consult skills/README.md
- Discovery/Registry → Check skill_registry.py, capability_registry.py
- API changes → Update OpenAPI spec will auto-generate from FastAPI decorators

## Architecture Quick Reference

**Core Components:**

- `wingman_core.py` - FastAPI app, WebSocket server, REST endpoints
- `Tower.py` - Wingman factory and lifecycle manager
- `Wingman.py` - Base class for all Wingmen
- `Wingman.py` - Unified Wingman class (formerly split into base Wingman and OpenAiWingman subclass)
- `SkillRegistry` - Progressive tool disclosure for skills
- `CapabilityRegistry` - Unified skills + MCP discovery
- `SecretKeeper` - Secure API key management

**Skills:**

- Inherit from `Skill` base class
- Use `@tool` decorator for auto-schema generation
- Implement hooks for lifecycle events
- Store in `skills/[skill_name]/` with main.py, default_config.yaml, logo.png

**Config files (YAML):**

- Very indentation-sensitive
- No hot reload - restart Core after manual edits
- Use ConfigManager for programmatic access

## Common Patterns

**Benchmarking:**

```python
from services.benchmark import Benchmark
benchmark = Benchmark()
benchmark.start_snapshot("operation_name")
# ... do work
benchmark.finish_snapshot()
```

**PubSub Events:**

```python
from services.pub_sub import PubSub
events = PubSub()
events.subscribe("event_name", callback_function)
await events.publish("event_name", data)
```

**WebSocket Broadcasting:**

```python
from api.commands import SomeCommand
await self._connection_manager.broadcast(SomeCommand(data="value"))
```

## Testing & Debugging

- Check terminal output AND `logs/` directory for errors
- API docs at `http://127.0.0.1:49111/docs` when Core running
- Use `debug_mode: true` in settings.yaml for verbose logging
- Test bundled version separately from dev environment
