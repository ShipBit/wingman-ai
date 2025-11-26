# MCP Integration Plan - Skill System Overhaul

## Overview

This document outlines the plan to modernize Wingman AI's skill system with:

1. Progressive tool disclosure (search-on-demand instead of all tools upfront)
2. Simplified skill distribution (no more template duplication)
3. Opt-out skill model (all skills available by default)
4. Auto-generated prompts from `@tool` decorators

## Current Architecture Problems

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CURRENT ARCHITECTURE                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  CONFIG STORAGE (per version)                                                │
│  ├── Windows: %APPDATA%/WingmanAI/1_9_0/                                    │
│  │   ├── configs/Star Citizen/wingman.yaml  ← skill configs here            │
│  │   └── skills/                            ← skill CODE + dependencies     │
│  │                                                                           │
│  └── MacOS: ~/Library/Application Support/WingmanAI/1_9_0/                  │
│                                                                              │
│  SOURCE (dev mode)                                                          │
│  └── /source/skills/                        ← skill CODE executed from here │
│                                                                              │
│  TEMPLATES (bundled with release)                                           │
│  └── _internal/templates/skills/            ← copied to APPDATA on install  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

Pain Points:
1. Triple Maintenance: /skills, /templates/skills, and APPDATA/skills must stay in sync
2. Manual Skill Assignment: Users must explicitly add skills to each Wingman in config
3. Prompt Redundancy: Each skill has a `prompt` field duplicating what @tool descriptions provide
4. Custom Skill Distribution: Users must manually copy skill folders to obscure APPDATA paths
5. Version Migration: Skills are copied per-version, bloating disk and causing sync issues
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

    # In progressive mode: only meta-tools + active skill tools
    # In legacy mode: all skill tools
    if self.tool_registry._progressive_mode:
        # Add meta-tools
        for _, tool_def in self.tool_registry.get_meta_tools():
            tools.append(tool_def)
        # Add active skill tools
        for _, tool_def in self.tool_registry.get_active_tools():
            tools.append(tool_def)
    else:
        # Legacy: all tools
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

### Phase 5: Skill Distribution Simplification (Future)

#### 5.1 New Directory Structure

```
# Built-in skills (read-only, shipped with release)
_internal/skills/           # PyInstaller bundle (release)
/source/skills/             # Dev mode

# Custom skills (read-write, user location, NOT versioned)
APPDATA/WingmanAI/custom_skills/
└── my_custom_skill/
    ├── main.py
    ├── skill.yaml          # Metadata (renamed from default_config.yaml)
    └── dependencies/
```

#### 5.2 Eliminate `/templates/skills/`

- Built-in skill **code** lives in `/skills/` (source) or `_internal/skills/` (release)
- Built-in skill **configs** are bundled in the same location
- **No more copying** skill code to APPDATA for built-in skills
- Custom skills still go to `APPDATA/custom_skills/`

### Phase 6: MCP Client Integration (Future)

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

## Key Files to Modify

1. `api/interface.py` - Add `disabled_skills` to WingmanConfig
2. `skills/skill_base.py` - Add `get_tools_description()` method
3. `wingmen/wingman.py` - Modify `init_skills()` for opt-out model
4. `wingmen/open_ai_wingman.py` - Integrate ToolRegistry, modify `build_tools()`
5. `services/module_manager.py` - Update skill discovery
6. `services/config_migration_service.py` - Add 1.8.x → 1.9.0 migration

## Already Created

- `services/tool_registry.py` - ToolRegistry with progressive disclosure
- `skills/skill_base.py` - `@tool` decorator and base class updates

## Migration Path Summary

```
OLD (1.8.x)                          NEW (1.9.0)
────────────────────────────────────────────────────────────────
wingman.yaml:                        wingman.yaml:
  skills:                              disabled_skills:
    - name: Spotify                      - UEXCorp  # only list what's OFF
      module: skills.spotify.main
    - name: StarHead
      ...

LLM receives:                        LLM receives:
  - ALL skill tools (50+ tools)        - 3 meta-tools (search, activate, list)
  - Full prompt for each skill         - Tool descriptions on-demand

/templates/skills/spotify/           REMOVED (no more duplication)
APPDATA/1_8_x/skills/spotify/        APPDATA/custom_skills/ (custom only)
```
