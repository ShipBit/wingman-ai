# Star Citizen Keybindings - Utility Scripts

This directory contains utility scripts to help you manage and understand Star Citizen keybindings for the Wingman AI system.

Version directories such as `R4_100/` are generated runtime caches and are not stored
in Git. Reusable voice phrases live in the tracked `command_phrase_knowledge.json`.
If no version is passed to a utility, it automatically uses the newest local cache.

## Available Utilities

### 1. `check_command_status.py` - Inspect Individual Commands

Check the status and details of any keybinding command.

**Usage:**
```bash
python check_command_status.py <command_name> [version]
python check_command_status.py --list [version]
python check_command_status.py --list-all [version]
```

**Examples:**
```bash
# Check a specific command
python check_command_status.py v_toggle_mining_mode

# Check a command in a different version
python check_command_status.py v_invoke_quantum_drive R4_61

# List all active commands
python check_command_status.py --list

# List ALL commands (including inactive)
python check_command_status.py --list-all
```

**Output Example:**
```
======================================================================
  Command: v_toggle_mining_mode
======================================================================

📋 Basic Information:
   Category:     seat_general
   Label (EN):   Mining Mode Toggle
   Description:  Mining Mode Toggle
   Activation:   press

⌨️  Keybindings:
   Current:      m
   Default:      m

🤖 AI Status:
   Status:       ✅ ACTIVE
   Has Keybinding:   ✅
   Has Phrases:      ✅
   Custom Config:    ❌
   Activation OK:    ✅

💬 Command Phrases:
   en:
      - "mining mode"
      - "toggle mining"
      - "activate mining"
      ... and 2 more
```

---

### 2. `list_commands.py` - Browse and Search Commands

List, filter, and search through all commands with various options.

**Usage:**
```bash
python list_commands.py [options] [version]
```

**Options:**
- `--by-category` - List commands grouped by category (default)
- `--active-only` - Show only active commands (default)
- `--all` - Show all commands including inactive
- `--no-binding` - Show only commands without keybindings
- `--custom` - Show only commands with custom keybindings
- `--search <term>` - Search for commands containing term
- `--stats` - Show statistics

**Examples:**
```bash
# List all active commands by category
python list_commands.py

# List all commands (including inactive)
python list_commands.py --all

# Show commands without keybindings
python list_commands.py --no-binding

# Show commands with custom keybindings
python list_commands.py --custom

# Search for quantum-related commands
python list_commands.py --search quantum

# Show comprehensive statistics
python list_commands.py --stats

# List commands for a different version
python list_commands.py --active-only R4_61
```

**Statistics Output Example:**
```
📊 Overall:
   Total Commands:           847
   Active for AI:            412 (48.6%)
   Inactive:                 435 (51.4%)

⌨️  Keybindings:
   With Keybinding:          623
   Without Keybinding:       224
   Custom Keybindings:       15

💬 Command Phrases:
   With Phrases Generated:   412
   Without Phrases:          435

❌ Inactive Reasons:
   no_keybinding                    224
   category_excluded                156
   unsupported_activation            55
```

---

### 3. `migrate_keybindings.py` - Migrate to New Format

Migrate existing keybindings to the new unified format with metadata.

**Usage:**
```bash
python migrate_keybindings.py [version] [--backup]
```

**Examples:**
```bash
# Migrate with automatic backup
python migrate_keybindings.py R4_60 --backup

# Migrate without backup
python migrate_keybindings.py
```

**What It Does:**
1. Creates a backup of the original file (if `--backup` specified)
2. Loads existing `sc_all_keybindings.json`
3. Adds `ai_status` metadata to each command
4. Marks default vs custom keybindings
5. Preserves existing command phrases
6. Shows migration statistics
7. Saves updated file

**Output Example:**
```
====================================================================
  Migrating Keybindings to Unified Format: R4_60
====================================================================

✅ Backup created: sc_all_keybindings.backup_20260212_153045.json
📖 Loading keybindings...
   Found 847 commands

🔄 Adding ai_status metadata...
   ✅ Migrated 847 commands

📊 Migration Statistics:
   Total:           847
   Active:          412 (48.6%)
   Inactive:        435 (51.4%)
   Has Keybinding:  623
   Has Phrases:     412

✨ Migration Complete!
```

---

### 4. `export_command_phrase_knowledge.py` - Persist Reviewed Phrases

Merge generated command phrases from a local runtime cache into the small,
version-independent file tracked by Git:

```bash
python export_command_phrase_knowledge.py R4_100
```

Extracted bindings, translations, debug responses, and backups remain local.

---

## Quick Start Guide

### First Time Setup

1. **Enable automatic detection/extraction** and configure `sc_unp4k_install_dir`.

2. **Start Wingman once**, then verify the generated current cache:
   ```bash
    python check_command_status.py v_toggle_mining_mode
    python list_commands.py --stats
   ```

3. **Browse available commands:**
   ```bash
   python list_commands.py --active-only
   ```

The migration utility is retained only for old local cache formats.

### Common Workflows

**Find a command to use in config.yaml:**
```bash
# Search for what you want to do
python list_commands.py --search "mining"

# Check the command details
python check_command_status.py v_toggle_mining_mode

# Use the actionname in config.yaml
```

**Debug why a command isn't working:**
```bash
# Check the command status
python check_command_status.py <command_name>

# Look for the "AI Status" section to see why it's inactive
```

**See what commands you've customized:**
```bash
python list_commands.py --custom
```

**Get overview of all keybindings:**
```bash
python list_commands.py --stats
```

---

## Understanding Command Status

### Active Commands ✅
Commands that are available to the AI system have:
- Valid keybinding (default or custom)
- Supported activation mode
- Not in excluded categories
- Has command phrases generated

### Inactive Commands ❌
Commands may be inactive for these reasons:
- `no_keybinding` - No keyboard mapping assigned
- `category_excluded` - Category filtered in config
- `unsupported_activation` - Hold/hold_toggle not supported
- `explicitly_excluded` - In ignored_actionnames list

### Custom Status Icons
- ✅ Active for AI
- ❌ Inactive
- 💬 Has command phrases
- ⭐ Custom keybinding
- 🔧 Custom configuration

---

## Integration with config.yaml

### Example: Using Command Names

```yaml
commands:
  # Single command with custom phrases
  - name: v_toggle_mining_mode
    instant_activation:
      - "start mining now"
    sc_commands:
      - sc_command: v_toggle_mining_mode
    
  # Macro combining multiple commands
  - name: prepare_quantum
    instant_activation:
      - "prepare quantum jump"
    sc_commands:
      - sc_command: v_power_throttle_max
        sleep: 0.5
      - sc_command: v_invoke_quantum_drive
```

### Finding Command Names

Use `list_commands.py --search` to find the exact actionname:

```bash
$ python list_commands.py --search "quantum drive"

Search Results for 'quantum drive' (1 found)
============================================================

✅ v_invoke_quantum_drive
   Category:    spaceship_quantum
   Label:       Engage Quantum Drive
   Keybinding:  b
```

Then use `v_invoke_quantum_drive` as the `sc_command` value in config.yaml.

---

## File Locations

```
star_citizen_data/keybindings/
├── command_phrase_knowledge.json    # Tracked, version-independent voice phrases
├── R4_100/                          # Generated and ignored runtime cache
│   ├── sc_all_keybindings.json      # Runtime source of truth
│   ├── defaultProfile.xml           # Extracted SC default keybindings
│   ├── keybinding_localization.xml  # Extracted key translations
│   └── global_*.ini                 # Extracted language files
├── check_command_status.py          # Utility: Check command details
├── list_commands.py                 # Utility: List/search commands
├── migrate_keybindings.py           # Utility: Migrate to new format
├── export_command_phrase_knowledge.py # Promote local phrases into the tracked seed
├── KEYBINDINGS_DESIGN.md            # Complete design documentation
└── README.md                        # This file
```

---

## Troubleshooting

### "Command not found" Error

**Problem:** Can't find a command you're looking for.

**Solution:**
```bash
# Search for it
python list_commands.py --search "part of name"

# Or list all commands
python list_commands.py --all
```

### Command Isn't Working in AI

**Problem:** Voice command not triggering action.

**Solution:**
```bash
# Check command status
python check_command_status.py <command_name>

# Look at "AI Status" section
# Common issues:
#   - is_active: false (check inactive_reason)
#   - Has Phrases: ❌ (needs phrase generation)
#   - Has Keybinding: ❌ (needs keybind assignment)
```

### Custom Keybinding Not Detected

**Problem:** Changed keybinding in-game but not reflected.

**Solution:**
1. Export keybindings from Star Citizen
2. Place exported file in configured location
3. Set `update_keybindings: true` in config.yaml
4. Restart Wingman AI

---

## Advanced Usage

### Programmatic Access

You can also import and use these utilities in Python:

```python
from pathlib import Path
import json

# Load keybindings
kb_file = Path('R4_60/sc_all_keybindings.json')
with open(kb_file) as f:
    kb = json.load(f)

# Get active commands only
active = {k: v for k, v in kb.items() if v['ai_status']['is_active']}

# Filter by category
mining_commands = {
    k: v for k, v in active.items() 
    if 'mining' in v.get('category', '').lower()
}

# Print command phrases
for name, cmd in mining_commands.items():
    phrases = cmd.get('command-phrases', {}).get('en', [])
    print(f"{name}: {', '.join(phrases)}")
```

---

## Version Updates

When Star Citizen releases a new version (e.g., R4_60 → R4_61):

1. Wingman reads `<SC installation>/<channel>/build_manifest.id` on startup.
2. A changed branch/build ID selects the matching version directory automatically.
3. `unp4k` extracts the default profile, key names, and configured translations; `unforge`
   converts the two CryXML resources into normal XML.
4. Existing command phrases are loaded from `command_phrase_knowledge.json` and, if
   present, the newest local cache. Only newly introduced active actions need phrase
   generation.
5. Export your custom keybindings from the game when your personal mappings change.

Enable this workflow with `auto_detect_version: true` and
`auto_extract_game_files: true` under `sc-keybind-mappings`. Set
`sc_unp4k_install_dir` to a directory containing both `unp4k` and `unforge`.
The configured `sc_channel_version` remains a fallback for installations without a
readable manifest. Set either option to `false` to retain the manual workflow.

After reviewing newly generated phrases, persist them for future clean installations:

```bash
python star_citizen_data/keybindings/export_command_phrase_knowledge.py R4_100
```

The exporter merges phrases into the existing seed, so knowledge for temporarily
removed actions is retained.

See **KEYBINDINGS_DESIGN.md** for detailed update workflows.

---

## Getting Help

- **Design Documentation:** See `KEYBINDINGS_DESIGN.md` for complete architecture
- **Configuration Guide:** See main project README
- **Issue Tracking:** Check status with utilities first
- **Discord:** Ask in project Discord server

---

## Quick Reference Card

```
┌─────────────────────────────────────────────────────────────┐
│  QUICK REFERENCE: Keybindings Utilities                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  CHECK COMMAND:                                             │
│    python check_command_status.py <name>                    │
│                                                             │
│  SEARCH COMMANDS:                                           │
│    python list_commands.py --search <term>                  │
│                                                             │
│  LIST ACTIVE:                                               │
│    python list_commands.py                                  │
│                                                             │
│  SHOW STATS:                                                │
│    python list_commands.py --stats                          │
│                                                             │
│  MIGRATE FORMAT:                                            │
│    python migrate_keybindings.py --backup                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```
