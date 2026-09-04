# Star Citizen Keybindings System - Design Documentation

## Overview
This document describes the improved, unified keybindings system that simplifies management and configuration of Star Citizen voice commands.

## Problem Statement
The previous system had several issues:
1. **Multiple files with overlapping information**: `sc_all_keybindings.json`, `keybindings_existing_knowledge.json`, `keybindings_missing_knowledge.json`
2. **Unclear status tracking**: Hard to know which commands are active and why
3. **Difficult to reference**: Unclear how to reference commands in config.yaml
4. **Complex updates**: When SC updates or user changes keybinds, regeneration was confusing
5. **Split knowledge**: Information about a command was spread across multiple files

## Solution: Unified Keybindings Structure

### Single Source of Truth: `sc_all_keybindings.json`

This file now contains ALL information about keybindings in one place with enhanced metadata:

```json
{
  "v_toggle_mining_mode": {
    // ─── Basic SC Information ───
    "category": "seat_general",
    "actionname": "v_toggle_mining_mode",
    "activationMode": "press",
    
    // ─── Keybinding Information ───
    "keyboard-mapping": "m",              // Current active keybinding (default or custom)
    "keyboard-mapping-default": "m",      // SC default keybinding (from defaultProfile.xml)
    "keyboard-mapping-custom": null,      // User override (from exported keybindings), null if none
    
    // ─── Localization ───
    "action-label-en": "Mining Mode Toggle",
    "action-description-en": "Mining Mode Toggle",
    "keyboard-mapping-en": "M",
    "action-label-de_DE": "Bergbaumodus (umschalten)",
    "keyboard-mapping-de_DE": "M",
    // ... other languages
    
    // ─── AI Status Metadata (NEW) ───
    "ai_status": {
      "is_active": true,                  // Is this command available to AI?
      "inactive_reason": null,            // If not active, why? (see reasons below)
      "has_keybinding": true,             // Does it have a keyboard mapping?
      "has_command_phrases": true,        // Has AI command phrases been generated?
      "is_custom_configured": false,      // Is it manually configured in config.yaml?
      "activation_supported": true        // Is the activation mode supported?
    },
    
    // ─── AI Command Phrases ───
    "command-phrases": {
      "en": ["mining mode", "toggle mining", "activate mining", "mining"],
      "de_DE": ["bergbaumodus", "bergbau aktivieren", "mining modus"]
    },
    
    // ─── UI Reference Keys ───
    "keyboard-mapping-ui": "@input_key_keyboard_m",
    "label-ui": "@ui_CIMiningMode",
    "description-ui": "@ui_CIMiningModeDesc"
  }
}
```

### AI Status Metadata Explained

#### `is_active` (boolean)
- `true`: Command is available to the AI system
- `false`: Command is filtered out and won't be used

#### `inactive_reason` (string or null)
Possible values when `is_active = false`:
- `"no_keybinding"`: No keyboard mapping assigned (default or custom)
- `"category_excluded"`: Category is in `keybind_categories_to_ignore` config
- `"unsupported_activation"`: Activation mode is "hold" or "hold_toggle" (not supported)
- `"explicitly_excluded"`: In `ignored_actionnames` config
- `null`: Command is active

#### `has_keybinding` (boolean)
- `true`: Has a keyboard-mapping value (either default or custom)
- `false`: No keybinding assigned

#### `has_command_phrases` (boolean)
- `true`: AI command phrases have been generated
- `false`: Needs command phrase generation (or is inactive)

#### `is_custom_configured` (boolean)
- `true`: Command is manually configured in config.yaml with custom settings
- `false`: Uses automatic/generated settings

#### `activation_supported` (boolean)
- `true`: Activation mode is supported (tap, press, etc.)
- `false`: Activation mode not supported (hold, hold_toggle) - these require continuous keypress

## File Structure (Simplified)

### Required Files:
```
star_citizen_data/keybindings/R4_60/
├── sc_all_keybindings.json          # SINGLE SOURCE OF TRUTH - all keybindings with metadata
├── defaultProfile.xml                # SC default keybindings (from game files)
├── keybinding_localization.xml       # Key name translations (from game files)
├── global_en_GB.ini                  # English translations (from game files)
├── global_de_DE.ini                  # German translations (from game files)
├── global_fr_FR.ini                  # French translations (from game files)
└── global.ini                        # Base translations (from game files)
```

### Deprecated Files (can be removed after migration):
- `keybindings_existing_knowledge.json` → merged into `sc_all_keybindings.json`
- `keybindings_missing_knowledge.json` → merged into `sc_all_keybindings.json`

### Generated Files (optional, for debugging):
- `completion_message_command_phrases_*.json` - OpenAI generation results
- `raw_response_*.json` - Raw API responses

## How It Works

### 1. Initial Generation
```
Parse defaultProfile.xml → Load user custom keybinds → Merge → 
Add localizations → Calculate AI status → Generate command phrases → 
Save to sc_all_keybindings.json
```

### 2. Update Process (when SC releases new version or user changes keybinds)
```
Load existing sc_all_keybindings.json → 
Parse new defaultProfile.xml → 
Load new user custom keybinds → 
Merge (preserving existing command phrases) → 
Update AI status → 
Generate command phrases only for NEW commands → 
Save updated sc_all_keybindings.json
```

### 3. AI Usage
```
Load sc_all_keybindings.json → 
Filter: where ai_status.is_active == true → 
Build AI tools/commands from command-phrases → 
Execute keybindings when commanded
```

## Configuration in config.yaml

### Referencing Commands

All commands use their `actionname` as the reference key:

```yaml
# Example 1: Override an auto-detected command
commands:
  - name: v_toggle_mining_mode  # Use the actionname from sc_all_keybindings.json
    instant_activation:
      - "start mining"
      - "begin mining operation"
    sc_commands:
      - sc_command: v_toggle_mining_mode
    responses:
      - "Mining mode activated"

# Example 2: Create a macro (chain multiple commands)
commands:
  - name: prepare_for_quantum_jump
    instant_activation:
      - "prepare quantum jump"
      - "ready for quantum"
    sc_commands:
      - sc_command: v_power_throttle_max    # Set throttle to max
        sleep: 0.5
      - sc_command: v_invoke_quantum_drive  # Engage quantum
    responses:
      - "Quantum drive engaged"

# Example 3: Exclude a command that would normally be active
ignored_actionnames:
  - v_self_destruct  # Prevent accidental self-destruct

# Example 4: Include a command from an excluded category
include_actions:
  - pc_conversation_option1  # Include even though category might be excluded
```

### Finding the Right Command Name

**Method 1: Search in `sc_all_keybindings.json`**
- Open the file and search for the action you want
- Use the `actionname` field value

**Method 2: Look at the descriptions**
```json
// Search by what you want to do:
"action-description-en": "Mining Mode Toggle" → actionname: "v_toggle_mining_mode"
"action-label-en": "Quantum Drive" → actionname: "v_invoke_quantum_drive"
```

**Method 3: Check `ai_status`**
```python
# Python helper to list all active commands
import json
with open('sc_all_keybindings.json') as f:
    kb = json.load(f)
    active = [k for k, v in kb.items() if v['ai_status']['is_active']]
    print('\n'.join(sorted(active)))
```

### Filter Configuration

```yaml
# Categories to completely ignore (won't be available to AI)
keybind_categories_to_ignore:
  - spectator
  - social
  - default

# Specific actions to include even from ignored categories
include_actions:
  - pc_interaction_mode  # Include this specific action

# Specific actions to exclude even if normally included
ignored_actionnames:
  - v_self_destruct
  - v_eject
```

## Update Workflow

### Scenario 1: New Star Citizen Release (e.g., R4_61)

1. **Enable automatic version management**:
   ```yaml
   sc-keybind-mappings:
     auto_detect_version: true
     auto_extract_game_files: true
     sc_unp4k_install_dir: C:/Tools/unp4k-suite
   ```

2. **Restart Wingman**. It reads the active channel's `build_manifest.id`, maps the
   release branch to a version directory, and compares the build ID with
   `.sc-extraction.json`.

3. **Automatic extraction**:
   - `unp4k` extracts `defaultProfile.xml`, `keybinding_localization.xml`, and translations.
   - `unforge` converts the extracted CryXML files to normal XML.
   - The validated files are written to the detected version directory.

4. **Keep user custom keybinds**:
   - Export your keybindings in-game
   - Place in configured location

5. **What happens**:
   - Loads command phrases from the newest prior `sc_all_keybindings.json`
   - Parses the newly extracted `defaultProfile.xml` and translations
   - Merges data, preserving existing command phrases
   - Generates phrases only for NEW commands
   - Saves to the automatically selected version directory

### Scenario 2: Changed Custom Keybindings

1. **Export new keybindings** from Star Citizen
2. **Place in configured location**
3. **Run update**: Set `update_keybindings: true`
4. **Result**: Custom keybindings update, command phrases preserved

### Scenario 3: Regenerate All Command Phrases

```yaml
# In config.yaml:
regenerate_all_instant_commands: true
update_keybindings: true
```

This will re-generate ALL command phrases (useful if you changed languages or want better phrases).

## Helper Tools

### Check Command Status
```python
# star_citizen_data/keybindings/check_command_status.py
import json
import sys

def check_command(actionname):
    with open('R4_60/sc_all_keybindings.json') as f:
        kb = json.load(f)
    
    if actionname not in kb:
        print(f"Command '{actionname}' not found")
        return
    
    cmd = kb[actionname]
    status = cmd['ai_status']
    
    print(f"\nCommand: {actionname}")
    print(f"Category: {cmd['category']}")
    print(f"Label: {cmd.get('action-label-en', 'N/A')}")
    print(f"Keybinding: {cmd.get('keyboard-mapping', 'NONE')}")
    print(f"\nAI Status:")
    print(f"  Active: {status['is_active']}")
    if not status['is_active']:
        print(f"  Reason: {status['inactive_reason']}")
    print(f"  Has Keybinding: {status['has_keybinding']}")
    print(f"  Has Phrases: {status['has_command_phrases']}")
    print(f"  Custom Config: {status['is_custom_configured']}")

if __name__ == '__main__':
    check_command(sys.argv[1] if len(sys.argv) > 1 else 'v_toggle_mining_mode')
```

### List Active Commands by Category
```python
# star_citizen_data/keybindings/list_by_category.py
import json
from collections import defaultdict

with open('R4_60/sc_all_keybindings.json') as f:
    kb = json.load(f)

by_category = defaultdict(list)
for actionname, cmd in kb.items():
    if cmd['ai_status']['is_active']:
        by_category[cmd['category']].append(actionname)

for category in sorted(by_category.keys()):
    print(f"\n{category}:")
    for cmd in sorted(by_category[category]):
        print(f"  - {cmd}")
```

## Migration Guide

### From Old System to New System

**Step 1: Backup existing files**
```bash
cp -r star_citizen_data/keybindings/R4_60 star_citizen_data/keybindings/R4_60_backup
```

**Step 2: Update config.yaml**
```yaml
# Set this to trigger migration
migrate_keybindings_to_unified: true
update_keybindings: false  # Don't update during migration
```

**Step 3: Run migration** (automatic via updated keybindings.py)

**Step 4: Verify** - Check that `sc_all_keybindings.json` has `ai_status` metadata

**Step 5: Clean up** (optional)
- Remove `keybindings_existing_knowledge.json`
- Remove `keybindings_missing_knowledge.json`

## Benefits of New System

1. ✅ **Single source of truth** - All data in one file
2. ✅ **Clear status** - Know exactly why a command is/isn't active
3. ✅ **Easy configuration** - Simple command references in config.yaml
4. ✅ **Better updates** - Preserves custom data, only updates what's needed
5. ✅ **Self-documenting** - Metadata explains everything
6. ✅ **Easy debugging** - Helper tools to inspect commands
7. ✅ **Flexible** - Can filter/customize without losing data

## Configuration Reference

### Full config.yaml Example

```yaml
# SC Keybinding Configuration
sc-keybind-mappings:
  sc_installation_dir: "C:/Program Files/Roberts Space Industries/StarCitizen"
  sc_active_channel: "LIVE"  # or PTU, EPTU
  auto_detect_version: true
  auto_extract_game_files: true
  sc_channel_version: "R4_60"  # fallback when detection is unavailable
  sc_unp4k_install_dir: "C:/Tools/unp4k-suite"
  sc_unp4k_timeout_seconds: 900
  user_keybinding_file_name: "layout_exported_keyboard_joystick.xml"
  keybindings-directory: "/keybindings/"
  sc_unp4k_file_default_keybindings_filter: "defaultProfile.xml"
  sc_unp4k_file_keybinding_localization_filter: "keybinding_localization.xml"
  en_translation_file: "global_en_GB.ini"

# Categories to exclude entirely
keybind_categories_to_ignore:
  - spectator
  - social

# Specific actions to include even from excluded categories
include_actions:
  - pc_interaction_mode

# Specific actions to exclude
ignored_actionnames:
  - v_self_destruct
  - v_eject

# Update behavior
update_keybindings: false  # Set to true to update keybindings
regenerate_all_instant_commands: false  # Set to true to regenerate all phrases

# Language settings
command_languages:
  - de_DE
  - fr_FR
```

## Troubleshooting

### Q: Command not appearing in AI
**A:** Check `sc_all_keybindings.json`:
```json
"your_command": {
  "ai_status": {
    "is_active": false,
    "inactive_reason": "category_excluded"  // ← Here's why
  }
}
```

### Q: How do I force include a command?
**A:** Add to `include_actions` in config.yaml:
```yaml
include_actions:
  - your_actionname_here
```

### Q: Update not working?
**A:** Check config.yaml:
```yaml
update_keybindings: true  # Must be true
sc-keybind-mappings:
  auto_detect_version: true
  auto_extract_game_files: true
  sc_unp4k_install_dir: "C:/Tools/unp4k-suite"
```

### Q: Want to regenerate phrases in different language?
**A:**
```yaml
regenerate_all_instant_commands: true
command_languages:
  - es_ES  # Add your language
```

## Future Enhancements

- [ ] Web UI to browse and configure keybindings
- [ ] Auto-detection of SC installation path
- [ ] Conflict detection (multiple commands with same phrase)
- [ ] Voice command testing tool
- [ ] Export custom command configurations
- [ ] Community sharing of command phrase translations
