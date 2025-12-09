# Tool Discovery Architecture

This document explains how Wingman AI discovers and activates skills and MCP servers through a progressive disclosure pattern using enum-constrained tool activation.

## Overview

Wingman AI uses a **two-tier tool system**:

1. **Meta-tools**: Built-in tools for discovering and activating capabilities
2. **Feature tools**: Actual functionality provided by skills and MCP servers

The key insight is that LLMs don't need to see all available tools upfront. Instead, they activate capabilities on-demand using enum-constrained selection.

## Architecture Flow

```
User Request
     │
     ▼
┌─────────────────────────────────┐
│  LLM sees meta-tools only:      │
│  • activate_skill               │
│  • activate_mcp_server          │
│  • list_active_skills           │
│  • list_active_mcp_servers      │
└─────────────────────────────────┘
     │
     ▼
LLM chooses from enum (e.g., "FileManager")
     │
     ▼
┌─────────────────────────────────┐
│  Skill/MCP activated            │
│  → Tools injected into context  │
└─────────────────────────────────┘
     │
     ▼
LLM uses feature tools
     │
     ▼
Response to user
```

## Enum-Constrained Activation

### Why Enums?

Previous approaches used fuzzy text search, which had problems:

- Non-English queries broke matching ("datei manager" vs "file manager")
- Smaller models gave inconsistent search queries
- Extra LLM call just to search added latency

The enum approach solves all of these:

- LLM translates user intent to enum value internally
- Works in any language (LLM does the mapping)
- No search step needed - direct activation
- Invalid values impossible (constrained to enum)

### How It Works

The `activate_skill` tool definition includes:

- An enum of all available skill IDs
- Descriptions embedded in the tool definition

```python
{
    "name": "activate_skill",
    "description": "Activate a skill to use its tools. Pick based on what you need:\n\n"
                   "• FileManager - Read, write, list files and directories\n"
                   "• VisionAI - Analyze images and screenshots\n"
                   "• Timer - Set timers and alarms\n"
                   "...",
    "parameters": {
        "properties": {
            "skill_name": {
                "type": "string",
                "enum": ["FileManager", "VisionAI", "Timer", ...]
            }
        },
        "required": ["skill_name"]
    }
}
```

When the user says "analyze this screenshot" (in any language), the LLM:

1. Sees the enum options with descriptions
2. Maps user intent → "VisionAI"
3. Calls `activate_skill(skill_name="VisionAI")`
4. Gets vision tools injected into context
5. Calls the appropriate vision tool

## Meta-Tools Reference

### activate_skill

Activates a skill by name (enum-constrained). After activation, the skill's tools become available.

**Parameters:**

- `skill_name` (enum): One of the available skill IDs

**Returns:** Confirmation message with list of now-available tools

### activate_mcp_server

Activates an MCP server by name (enum-constrained). After activation, the server's tools become available.

**Parameters:**

- `server_name` (enum): One of the connected MCP server names

**Returns:** Confirmation message with list of now-available tools

### list_active_skills

Lists currently active skills and their tools. Useful for checking what's already available.

**Parameters:** None

**Returns:** List of active skills with their tool names

### list_active_mcp_servers

Lists currently active MCP servers and their tools.

**Parameters:** None

**Returns:** List of active MCP servers with their tool names

## Configuration

### Skill Configuration

Skills define their discoverability in `default_config.yaml`:

```yaml
name: FileManager
description: Read, write, list files and directories. Search file contents.
# ... other config
```

The `description` field is critical - it's shown to the LLM in the enum tool definition to help it choose the right skill.

### MCP Server Configuration

MCP servers are configured in `mcp.template.yaml`:

```yaml
- name: context7
  display_name: Context7
  description: Documentation search for programming libraries
  type: http
  url: https://mcp.context7.com/mcp
  enabled: true
```

The `display_name` and `description` fields help the LLM choose the right server.

## Filtering

### Enabled/Disabled

Only enabled skills and connected MCP servers appear in the enum:

- Skills: Filtered by `disabled_skills` list in wingman config
- MCPs: Filtered by `disabled_mcps` list and connection status

### OS Filtering

Skills can specify `supported_os` to limit availability:

```yaml
supported_os:
  - windows
```

Skills not supported on the current OS are excluded from the enum.

## Performance Characteristics

The enum approach reduces LLM calls significantly:

| Scenario          | Old (Search + Activate) | New (Enum Activate) |
| ----------------- | ----------------------- | ------------------- |
| Single skill task | 4 calls                 | 3 calls             |
| Multi-skill task  | 7+ calls                | 4 calls             |

Breakdown for a typical task:

1. **Initial request** → LLM decides what to do
2. **Activation** → LLM picks from enum, skill activated
3. **Tool call** → LLM uses the feature tool
4. **Response** → Final answer to user

## Internationalization

The enum approach is language-agnostic:

1. User speaks German: "Lies die Datei config.yaml"
2. LLM sees enum: `["FileManager", "VisionAI", "Timer", ...]`
3. LLM understands "Datei" = file, picks `FileManager`
4. Activation happens with English enum value
5. Tool executes, result returned
6. LLM responds in German

No translation layer needed - the LLM handles all language mapping internally.

## Troubleshooting

### Skill not appearing in enum

1. Check the skill is not in `disabled_skills`
2. Verify `supported_os` includes current platform
3. Ensure skill's `default_config.yaml` is valid

### MCP server not appearing in enum

1. Check the server is not in `disabled_mcps`
2. Verify the server is actually connected (check logs)
3. Ensure `enabled: true` in config

### LLM picking wrong skill

1. Review skill descriptions - make them more distinct
2. Check for overlapping capabilities between skills
3. Consider whether the task is ambiguous

## Implementation Details

### SkillRegistry (`services/tool_registry.py`)

The `SkillRegistry` class manages skill lifecycle:

- `get_meta_tools()`: Returns enum-constrained activation tools
- `activate_skill()`: Loads skill module and returns its tools
- `get_active_skills()`: Lists currently active skills

### McpRegistry (`services/mcp_registry.py`)

The `McpRegistry` class manages MCP server connections:

- `get_meta_tools()`: Returns enum-constrained activation tools
- `activate_server()`: Marks server as active and returns tools
- `get_connected_servers()`: Lists servers ready for activation

### Tool Injection

When a skill/MCP is activated:

1. Registry marks it as active
2. Tools are returned to the LLM context
3. Subsequent LLM calls include the new tools
4. Skills stay active for the conversation duration
