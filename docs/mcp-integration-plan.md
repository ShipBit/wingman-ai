# MCP Integration Plan - Skill System Overhaul

## Overview

This document outlines the plan to modernize Wingman AI's skill system with:

1. Progressive tool disclosure (search-on-demand instead of all tools upfront)
2. Simplified skill distribution (no more template duplication)
3. Opt-out skill model (all skills available by default)
4. Auto-generated prompts from `@tool` decorators

---

## Phase 1 Status: ✅ COMPLETE

### What Was Implemented

#### Core Progressive Disclosure System

- ✅ `ToolRegistry` with meta-tools (`search_skills`, `activate_skill`, `list_active_skills`)
- ✅ Skills registered with manifests for searchable metadata (name, description, tags)
- ✅ LLM receives only meta-tools initially, activates skills on-demand
- ✅ Logging for tool discovery flow (`[Tool Discovery]` messages)

#### Lazy Skill Validation

- ✅ All skills loaded for all Wingmen at startup (pending validation)
- ✅ Skills only validated/prepared when first activated
- ✅ `is_validated`, `is_prepared`, `needs_activation()`, `ensure_activated()` added to Skill base class
- ✅ Hooks (`on_add_user_message`, etc.) only fire for prepared skills
- ✅ `unload()` only called for prepared skills

#### Platform Filtering

- ✅ `platforms` field added to `SkillConfig` (e.g., `platforms: [windows]`)
- ✅ Skills filtered by platform during `init_skills()`
- ✅ Applied to: `control_windows`, `ats_telemetry`, `msfs2020_control`

#### Config System Changes

- ✅ `skills` array in Wingman config now holds **user overrides only**
- ✅ Skills auto-loaded from discovery, user configs merged on top
- ✅ Migration service updated to preserve user skill configs

#### Context Optimization

- ✅ `get_context()` only includes prompts from **activated** skills
- ✅ Skill prompts NOT included until skill is activated (token savings)

#### Prompt Consolidation (@tool descriptions)

- ✅ Enhanced `@tool` descriptions with prompt-like context in 17 skills
- ✅ Commented out redundant `prompt` fields in `default_config.yaml` for 16 skills:
  - TimeAndDateRetriever, VisionAI, GoogleSearch, AskPerplexity
  - TypingAssistant, WebSearch, ImageGeneration, AutoScreenshot
  - Timer, FileManager, NMSAssistant, RadioChatter (no top-level prompt)
  - ControlWindows, Spotify, APIRequest
  - MSFS2020Control, ATSTelemetry (simplified from 600+ lines to pattern hints)
  - StarHead (migrated from dynamic enums to lookup tools)
- ✅ MSFS2020Control: Reduced from 637→67 lines (89% reduction)
  - SimConnect events/variables now documented via pattern hints in `@tool` descriptions
  - Examples: "Use TOGGLE\_ prefix for switches, :index suffix for multi-engine"
- ✅ ATSTelemetry: Simplified with wildcard patterns (fuel*, cargo*, city\*)
- ✅ StarHead: Migrated from dynamic enums to **lookup tool pattern**
  - Added 3 lookup tools: `get_available_ships`, `get_available_locations`, `get_available_shops`
  - LLM calls lookup tools first, then fuzzy-matches voice input to valid names
  - Solves speech-to-text spelling errors (e.g., "Houston" → "Hurston", "Catapiller" → "Caterpillar")
  - Lookup tools don't require waiting response (cached data, instant)
- ✅ All skills with tools now use `@tool` description as **single source of truth**

### What Was NOT Changed (Intentional Decisions)

- ❌ Did NOT remove `skills` property from WingmanConfig (still needed for user overrides)

### Disabled Skills (Opt-Out Model) - ✅ IMPLEMENTED

- ✅ Added `disabled_skills: list[str]` to `WingmanConfig`
- ✅ Blacklist approach: skills not listed are enabled by default
- ✅ New skills automatically available without config changes
- ✅ Disabled skills are skipped in `init_skills()` before loading
- ✅ Disabled skills not registered with ToolRegistry (invisible to LLM)

**Example Usage:**

```yaml
# Star Citizen wingman - disable racing game skills
disabled_skills:
  - iRacing
  - ATSTelemetry
  - MSFS2020Control
```

**Benefits:**

- Minimal config: only list what you DON'T want
- Future-proof: new skills work automatically
- Per-wingman: each wingman can have different disabled skills
- Clean UI: show all skills with checkboxes, unchecked = disabled

### Skills Not Using `@tool` Decorator (Intentional)

These skills don't have tools or use different patterns:

- `uexcorp` - Complex external tool handler, tools defined in separate handler class
- `audio_device_changer` - No tools
- `quick_commands` - No tools
- `thinking_sound` - No tools (hook-based)
- `voice_changer` - No tools (hook-based)

**Note:** Legacy skills still work! The `get_tools()` method returns tools regardless of whether
they use `@tool` decorator or manual definitions. The ToolRegistry handles both.

---

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CURRENT ARCHITECTURE                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  CONFIG STORAGE (per version)                                                │
│  ├── Windows: %APPDATA%/WingmanAI/1_9_0/                                    │
│  │   ├── configs/Star Citizen/wingman.yaml  ← skill configs here            │
│  │   └── skills/                            ← LEGACY (migrated to custom_skills) │
│  │                                                                           │
│  └── MacOS: ~/Library/Application Support/WingmanAI/1_9_0/                  │
│                                                                              │
│  BUILT-IN SKILLS (bundled, read-only)                                        │
│  ├── Release: _internal/skills/             ← bundled with PyInstaller     │
│  └── Dev: /source/skills/                   ← skill CODE executed from here │
│                                                                              │
│  CUSTOM SKILLS (user-created, NOT versioned)                                │
│  └── APPDATA/WingmanAI/custom_skills/       ← persists across updates!     │
│                                                                              │
│  TEMPLATES (bundled with release)                                           │
│  ├── _internal/templates/configs/           ← config templates only         │
│  └── _internal/templates/migration/         ← migration templates           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

Benefits:
1. No More Duplication: Skills exist in ONE place only (/skills/ in source)
2. Custom Skills Persist: User skills in custom_skills/ survive version updates
3. Reduced Disk Usage: Built-in skills not copied to APPDATA anymore
4. Simpler Distribution: Just drop skill folder into custom_skills/
5. Cleaner Migrations: Only user configs and custom skills need migration
```

## Proposed Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PROPOSED ARCHITECTURE                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  SKILL REGISTRY with Progressive Disclosure                                  │
│  ├── Built-in Skills: Always available, bundled with release                │
│  ├── User Skills: Custom skills in a single, well-known location            │
│  └── MCP Servers: External tools via Model Context Protocol (future)        │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  FILE LOCATIONS                                                              │
│  ├── Built-in Skills (read-only, bundled):                                  │
│  │   ├── Release: _internal/skills/  (PyInstaller bundle)                   │
│  │   └── Dev: /source/skills/                                               │
│  │                                                                           │
│  ├── User Skills (read-write, single location):                             │
│  │   └── APPDATA/WingmanAI/custom_skills/  ← NOT versioned!                 │
│  │                                                                           │
│  └── Wingman Config (what skills to DISABLE):                               │
│      └── APPDATA/.../configs/*/wingman.yaml                                 │
│          └── disabled_skills: ["UEXCorp"]  ← opt-out, not opt-in!           │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  PROGRESSIVE TOOL DISCLOSURE (via ToolRegistry)                              │
│                                                                              │
│  Instead of sending ALL tools to LLM:                                        │
│  1. Send only meta-tools: search_skills, activate_skill, list_active_skills │
│  2. LLM searches for relevant skills when needed                             │
│  3. LLM activates skills, their tools become available                       │
│  4. Dramatically reduces token usage and context pollution                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Implementation Phases

### Phase 1: Core Changes to Skill System

#### 1.1 Modify `SkillConfig` in `api/interface.py`

Add `disabled` field for opt-out model:

```python
class SkillConfig(CustomClassConfig):
    display_name: str
    author: Optional[str] = None
    tags: Optional[list[str]] = None
    description: LocalizedMetadata
    prompt: Optional[str] = None  # Keep for complex skills like UEXCorp
    custom_properties: Optional[list[CustomProperty]] = None
    hint: Optional[LocalizedMetadata] = None
    examples: Optional[list[LocalizedMetadata]] = None
```

#### 1.2 Modify `WingmanConfig` in `api/interface.py`

Change from opt-in to opt-out:

```python
class WingmanConfig(NestedConfig):
    # DEPRECATED - remove after migration
    skills: Optional[list[SkillConfig]] = None

    # NEW - opt-out model
    disabled_skills: Optional[list[str]] = None
```

#### 1.3 Add Tool Description Auto-Generation to `skill_base.py`

```python
class Skill:
    def get_tools_description(self) -> str:
        """Auto-generate a prompt section describing all tools in this skill."""
        if not self._decorated_tools:
            return ""

        lines = []
        for tool_def in self._decorated_tools.values():
            desc = tool_def.tool_schema["function"]["description"]
            lines.append(f"- {tool_def.tool_name}: {desc}")

        return "\n".join(lines)

    async def get_prompt(self) -> str | None:
        """Returns additional context for this skill."""
        # Start with auto-generated tool descriptions
        auto_prompt = self.get_tools_description()

        # Add custom prompt if defined (for complex skills like UEXCorp)
        custom_prompt = self.config.prompt if self.config.prompt else ""

        if auto_prompt and custom_prompt:
            return f"{auto_prompt}\n\n{custom_prompt}"
        return auto_prompt or custom_prompt or None
```

### Phase 2: Integrate ToolRegistry into OpenAiWingman

#### 2.1 Add ToolRegistry to OpenAiWingman

```python
class OpenAiWingman(Wingman):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tool_registry = ToolRegistry()
        # ... rest of init
```

#### 2.2 Modify `prepare_skill()` to Register with ToolRegistry

```python
async def prepare_skill(self, skill: Skill):
    # Register skill with the registry
    self.tool_registry.register_skill(skill)

    # Set up skill methods
    skill.llm_call = self.actual_llm_call
```

#### 2.3 Modify `build_tools()` to Use Progressive Disclosure

```python
def build_tools(self) -> list[dict]:
    # Commands tool (unchanged)
    tools = [self._build_execute_command_tool()]

    # Progressive disclosure: meta-tools + active skill tools
    # Add meta-tools (search_skills, activate_skill, list_active_skills)
    for _, tool_def in self.tool_registry.get_meta_tools():
        tools.append(tool_def)
    # Add tools from activated skills
    for _, tool_def in self.tool_registry.get_active_tools():
        tools.append(tool_def)

    return tools
```

#### 2.4 Handle Meta-Tool Execution

```python
async def _handle_tool_call(self, tool_call):
    tool_name = tool_call.function.name
    parameters = json.loads(tool_call.function.arguments)

    # Check if it's a meta-tool
    if self.tool_registry.is_meta_tool(tool_name):
        result, tools_changed = self.tool_registry.execute_meta_tool(tool_name, parameters)
        if tools_changed:
            # Re-send tool list to LLM on next call
            pass
        return result, ""

    # Regular tool execution...
```

### Phase 3: Update Wingman Base Class

#### 3.1 Modify `init_skills()` for Opt-Out Model

```python
async def init_skills(self) -> list[WingmanInitializationError]:
    """Load all available skills except those explicitly disabled."""
    # Get all available skills from discovery
    available_skills = ModuleManager.read_available_skills()

    # Get disabled skills from config (new opt-out model)
    disabled_skills = self.config.disabled_skills or []

    for skill_base in available_skills:
        if skill_base.name in disabled_skills:
            continue  # Skip disabled skills

        # Load and validate skill...
```

### Phase 4: Config Migration (1.8.x → 1.9.0)

#### 4.1 Migrate wingman configs

```python
def migrate_wingman(old: dict, new: Optional[dict]) -> dict:
    # Convert opt-in skills list to opt-out disabled_skills
    if old.get("skills"):
        # Get names of currently enabled skills
        enabled_skill_names = [s["name"] for s in old.get("skills", [])]

        # All available skills (from registry)
        all_skill_names = [...]  # Get from skill discovery

        # disabled = all - enabled
        old["disabled_skills"] = [
            name for name in all_skill_names
            if name not in enabled_skill_names
        ]

        # Remove old skills array
        del old["skills"]

    return old
```

### Phase 3: Skill Distribution Simplification - ✅ COMPLETE

#### What Was Implemented

**Simplified Skill Loading:**

- ✅ Built-in skills now loaded directly from bundled location (`_internal/skills/` in release, `./skills/` in dev)
- ✅ Removed `/templates/skills/` directory - no more duplication!
- ✅ `ModuleManager` updated to use `set_bundled_skills_dir()` / `get_bundled_skills_dir()`

**Non-Versioned Custom Skills:**

- ✅ Custom skills now go to `APPDATA/WingmanAI/custom_skills/` (NOT versioned!)
- ✅ Custom skills persist across Wingman AI version updates
- ✅ Added `get_custom_skills_dir()` helper in `services/file.py`

**Build System Updates:**

- ✅ GitHub Actions workflow: `--add-data "skills;skills"` instead of templates
- ✅ `build.py` and `build_macos.py` updated to bundle skills directly
- ✅ Config templates (`templates/configs/`) and migration templates (`templates/migration/`) still bundled

**Migration Service Updates:**

- ✅ `reset_to_fresh_configs()` no longer copies skills to APPDATA
- ✅ `copy_custom_skills()` migrates custom skills to non-versioned `custom_skills/` directory
- ✅ Legacy versioned skills dir (`APPDATA/version/skills/`) still checked for backwards compatibility

**ConfigManager Updates:**

- ✅ `copy_templates()` now skips `skills/` directory entirely
- ✅ Only copies config templates and migration templates

#### New Directory Structure

```text
# Built-in skills (read-only, shipped with release)
_internal/skills/           # PyInstaller bundle (release)
/source/skills/             # Dev mode

# Custom skills (read-write, user location, NOT versioned)
APPDATA/WingmanAI/custom_skills/
└── my_custom_skill/
    ├── main.py
    ├── default_config.yaml
    ├── logo.png
    └── dependencies/
```

### Phase 4: MCP Client Integration (Future)

```yaml
# wingman.yaml
mcp_servers:
  - name: 'filesystem'
    command: 'npx'
    args: ['-y', '@anthropic/mcp-server-filesystem']
  - name: 'postgres'
    url: 'http://localhost:3000/mcp'
```

Skills and MCP servers should be interchangeable from the LLM's perspective - both are just "tools".

---

## Phase 4 Status: 🚧 IN PROGRESS - MCP Client Integration

### What Has Been Implemented

#### Core MCP Infrastructure

- ✅ `api/enums.py` - Added `McpTransportType` enum (HTTP, STDIO, SSE)
- ✅ `api/interface.py` - Added MCP config interfaces:
  - `McpServerConfig` - Configuration for MCP servers (name, type, url, command, args, env, headers)
  - `McpToolInfo` - Tool metadata with prefixed names
  - `McpServerState` - Runtime server state
  - Updated `WingmanConfig` with `mcp: list[McpServerConfig]` and `disabled_mcps: list[str]`

#### MCP Client Service (`services/mcp_client.py`)

- ✅ `McpClient` class for connecting to MCP servers
- ✅ Supports three transport types:
  - **HTTP/SSE**: For hosted MCP servers (Context7, Svelte MCP, etc.)
  - **STDIO**: For local processes (Docker containers, Python scripts)
  - **SSE**: For Server-Sent Events based servers
- ✅ Connection lifecycle management with proper async cleanup
- ✅ `connect()`, `disconnect()`, `list_tools()`, `call_tool()` methods
- ✅ Graceful error handling and timeout management

#### MCP Registry Service (`services/mcp_registry.py`)

- ✅ `McpRegistry` class - similar to `SkillRegistry` but for MCP servers
- ✅ Progressive disclosure with meta-tools:
  - `search_mcp_servers` - Find available MCP servers by keyword
  - `activate_mcp_server` - Activate a server to use its tools
  - `deactivate_mcp_server` - Deactivate a server
  - `list_active_mcp_servers` - Show currently active servers
- ✅ Tool prefixing (`mcp_{server_name}_{tool_name}`) to prevent naming collisions
- ✅ Server manifest generation for LLM discovery
- ✅ `reset_activations()` for conversation reset

#### OpenAiWingman Integration

- ✅ Added `mcp_client` and `mcp_registry` properties
- ✅ `init_mcps()` method - loads and connects to MCP servers from config
- ✅ `unload_mcps()` method - disconnects all MCP servers
- ✅ `build_tools()` updated to include MCP meta-tools and active server tools
- ✅ `execute_command_by_function_call()` updated to handle MCP tool calls
- ✅ `reset_conversation_history()` resets MCP activations

#### Tower/Wingman Lifecycle

- ✅ `services/tower.py` - Calls `init_mcps()` after `init_skills()` during wingman instantiation
- ✅ `wingmen/wingman.py` - `update_config()` and `update_settings()` reload MCPs when skills reload

#### Dependencies

- ✅ `requirements.txt` - Added `mcp>=1.22.0`

### Example Wingman Config

```yaml
# ATC.yaml or Clippy.yaml
mcp:
  # Context7 - SSE-based documentation lookup
  - name: context7
    display_name: Context7 Documentation
    type: sse
    url: https://mcp.context7.com/mcp
    enabled: true

  # Svelte MCP - SSE-based Svelte documentation
  - name: svelte
    display_name: Svelte MCP
    type: sse
    url: https://svelte.dev/mcp
    enabled: true

  # Docker Hub - Local stdio process
  - name: docker
    display_name: Docker Hub
    type: stdio
    command: docker
    args:
      - run
      - -i
      - --rm
      - mcp/dockerhub
    enabled: true

# Optional: disable specific MCP servers for this wingman
disabled_mcps:
  - some_mcp_to_disable
```

### Secret Management

MCP servers can use API keys stored in `secrets.yaml`:

- Key format: `mcp_{server_name}` (e.g., `mcp_context7`)
- Automatically added to `Authorization: Bearer {key}` header if no auth header specified
- Config can specify custom headers that reference secrets

### Current Issues Being Debugged

1. 🔧 **MCP servers not connecting on startup** - Need to verify `init_mcps()` is being called
2. 🔧 **LLM not seeing MCP tools** - Verify `build_tools()` includes MCP meta-tools

### Files Created in Phase 4

- ✅ `services/mcp_client.py` - MCP client with transport support (~350 lines)
- ✅ `services/mcp_registry.py` - MCP registry with progressive disclosure (~500 lines)

### Files Modified in Phase 4

- ✅ `api/enums.py` - Added `McpTransportType`
- ✅ `api/interface.py` - Added MCP config types
- ✅ `wingmen/open_ai_wingman.py` - MCP integration
- ✅ `wingmen/wingman.py` - MCP lifecycle in update methods
- ✅ `services/tower.py` - Call `init_mcps()` on wingman creation
- ✅ `requirements.txt` - Added `mcp>=1.22.0`

---

## Key Files Modified in Phase 1

1. ✅ `api/interface.py` - Added `platforms` to SkillConfig, kept `skills` in NestedConfig
2. ✅ `skills/skill_base.py` - Added `@tool` decorator, `get_tools_description()`, lazy validation state
3. ✅ `wingmen/wingman.py` - Rewrote `init_skills()` for all-skills loading, platform filtering
4. ✅ `wingmen/open_ai_wingman.py` - Integrated ToolRegistry, hook filtering, context optimization
5. ✅ `services/tool_registry.py` - Created ToolRegistry with progressive disclosure
6. ✅ `services/config_migration_service.py` - Updated migration to preserve skills array

## Files Created in Phase 1

- ✅ `services/tool_registry.py` - ToolRegistry with progressive disclosure

## Key Files Modified in Phase 3

1. ✅ `services/module_manager.py` - Added bundled skills dir support, custom skills loading
2. ✅ `services/file.py` - Added `get_custom_skills_dir()` for non-versioned custom skills
3. ✅ `services/config_manager.py` - Updated `copy_templates()` to skip skills directory
4. ✅ `services/config_migration_service.py` - Updated custom skills migration to non-versioned location
5. ✅ `main.py` - Set bundled skills directory on startup
6. ✅ `.github/workflows/release.yml` - Bundle skills directly instead of via templates
7. ✅ `build.py` and `build_macos.py` - Updated PyInstaller data bundling

## Files Removed in Phase 3

- ✅ `/templates/skills/` - Entire directory removed (no longer needed)

---

## Remaining Work (Future Phases)

### Phase 2: Prompt Cleanup (Optional)

Many skills have both `@tool` descriptions AND detailed `prompt` fields in config.
Consider commenting out redundant prompts where tool descriptions are sufficient.

**Candidates for prompt removal:**

- Skills with simple, well-described `@tool` decorators
- Skills where the tool description fully explains when/how to use it

**Keep prompts for:**

- Complex skills with nuanced usage patterns (Spotify, UEXCorp)
- Skills needing execution priority/ordering instructions (TimeAndDateRetriever)
- Skills with extensive parameter guidelines

---

## Current State Summary

```text
OLD (1.8.x)                          NEW (1.9.0 - Phases 1-3 Complete)
────────────────────────────────────────────────────────────────────────
wingman.yaml:                        wingman.yaml:
  skills:                              skills:  # Now for OVERRIDES only
    - name: Spotify                      - name: UEXCorp
      module: skills.spotify.main            custom_properties: [...]
    - name: StarHead                   disabled_skills:  # NEW - opt-out!
      ...                                - iRacing
                                         - ATSTelemetry
                                       # All other skills auto-loaded!

LLM receives:                        LLM receives:
  - ALL skill tools (50+ tools)        - 3 meta-tools initially
  - Full prompt for each skill         - Skill tools after activation
                                       - Prompts only for active skills

/templates/skills/spotify/           REMOVED (bundled in _internal/skills/)
APPDATA/1_8_x/skills/spotify/        Migrated to custom_skills/ if custom
```
