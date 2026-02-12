# Star Citizen Keybindings System - Improvements Summary

## What Was Improved

The Star Citizen keybindings system has been completely redesigned to be simpler, more maintainable, and easier to configure. Here's what changed:

### Before (Problems)
❌ **Multiple overlapping files**: `sc_all_keybindings.json`, `keybindings_existing_knowledge.json`, `keybindings_missing_knowledge.json`
❌ **Unclear status**: Hard to know why a command is active/inactive
❌ **Difficult referencing**: Unclear how to reference commands in config.yaml  
❌ **Complex updates**: Regenerating after SC updates was confusing
❌ **Split information**: Had to check multiple files to understand one command

### After (Solutions)
✅ **Single source of truth**: `sc_all_keybindings.json` contains everything
✅ **Clear status tracking**: `ai_status` metadata explains exactly why commands are active/inactive
✅ **Easy configuration**: Simple, documented way to reference commands
✅ **Smart updates**: Preserves custom data, only updates what's needed
✅ **Complete information**: All data about a command in one place
✅ **Helper utilities**: Python scripts to inspect and manage keybindings
✅ **Better documentation**: Comprehensive guides and examples

## New Files Created

### Documentation:
1. **KEYBINDINGS_DESIGN.md** - Complete architecture documentation
2. **README.md** - User guide for utilities and configuration
3. **IMPROVEMENTS.md** - This file (migration guide)

### Utilities:
4. **check_command_status.py** - Inspect individual commands
5. **list_commands.py** - Browse/search all commands
6. **migrate_keybindings.py** - Migrate old format to new

### Improved Code:
7. **keybindings_improved.py** - Refactored keybindings class (optional to use)

## New Data Structure

Each command in `sc_all_keybindings.json` now has this structure:

```json
{
  "v_toggle_mining_mode": {
    // Basic SC info
    "category": "seat_general",
    "actionname": "v_toggle_mining_mode",
    "activationMode": "press",
    
    // Keybinding tracking
    "keyboard-mapping": "m",              // Current active
    "keyboard-mapping-default": "m",      // SC default (NEW)
    "keyboard-mapping-custom": null,      // User override (NEW)
    
    // Localization (existing)
    "action-label-en": "Mining Mode Toggle",
    "keyboard-mapping-en": "M",
    // ... other languages
    
    // AI Status (NEW - The main improvement!)
    "ai_status": {
      "is_active": true,                  // Available to AI?
      "inactive_reason": null,            // Why not active?
      "has_keybinding": true,             // Has keyboard mapping?
      "has_command_phrases": true,        // Phrases generated?
      "is_custom_configured": false,      // In config.yaml?
      "activation_supported": true        // Mode supported?
    },
    
    // Command phrases (existing)
    "command-phrases": {
      "en": ["mining mode", "toggle mining"],
      "de_DE": ["bergbaumodus"]
    }
  }
}
```

## How to Migrate

### Option 1: Automatic Migration with Utilities

**Recommended for most users:**

```bash
cd star_citizen_data/keybindings

# 1. Create backup and migrate
python migrate_keybindings.py R4_60 --backup

# 2. Verify migration
python check_command_status.py v_toggle_mining_mode
python list_commands.py --stats

# 3. Done! Your existing config.yaml still works
```

### Option 2: Use Improved Keybindings Class

**For developers wanting the refactored code:**

1. **Backup your current keybindings.py:**
   ```bash
   cp wingmen/star_citizen_services/keybindings.py wingmen/star_citizen_services/keybindings_old.py
   ```

2. **Replace with improved version:**
   ```bash
   cp wingmen/star_citizen_services/keybindings_improved.py wingmen/star_citizen_services/keybindings.py
   ```

3. **Test with your config:**
   ```bash
   python main.py
   ```

4. **If issues occur, restore backup:**
   ```bash
   cp wingmen/star_citizen_services/keybindings_old.py wingmen/star_citizen_services/keybindings.py
   ```

### Option 3: Manual Migration

**For advanced users who want control:**

1. **Add ai_status to each command manually** or use the migration script
2. **Add keyboard-mapping-default and keyboard-mapping-custom fields**
3. **Test with utilities to verify structure**

## Using the New System

### 1. Check Command Status

```bash
# See everything about a command
python check_command_status.py v_toggle_mining_mode

# Output shows:
#   - Current keybinding
#   - Whether it's active for AI
#   - Why it's inactive (if applicable)
#   - Available command phrases
#   - How to reference in config.yaml
```

### 2. Find Commands for config.yaml

```bash
# Search for what you want
python list_commands.py --search "quantum"

# Get the actionname and use it:
commands:
  - name: v_invoke_quantum_drive
    sc_commands:
      - sc_command: v_invoke_quantum_drive
```

### 3. Debug Inactive Commands

```bash
# List commands and see their status
python list_commands.py --no-binding

# This shows commands without keybindings
# Fix by assigning keybinding in Star Citizen
```

### 4. View Statistics

```bash
python list_commands.py --stats

# Shows:
#   - How many commands are active/inactive
#   - Reasons for inactivity
#   - Commands by category
#   - Activation modes
```

## Configuration Examples

### Example 1: Simple Command Reference

**Old way (still works):**
```yaml
commands:
  - name: toggle_mining
    instant_activation:
      - "mining mode"
    sc_commands:
      - sc_command: v_toggle_mining_mode  # Had to guess this name
```

**New way (easier to find):**
```bash
# Use utilities to find the right name
$ python list_commands.py --search mining

# Output includes exact actionname to use
```

```yaml
commands:
  - name: toggle_mining
    instant_activation:
      - "mining mode"
    sc_commands:
      - sc_command: v_toggle_mining_mode  # Found via utilities
```

### Example 2: Macro with Multiple Commands

```bash
# Find all commands you need
$ python list_commands.py --search "power"
$ python list_commands.py --search "quantum"
```

```yaml
commands:
  - name: prepare_quantum_jump
    instant_activation:
      - "prepare quantum jump"
    sc_commands:
      - sc_command: v_power_throttle_max    # Max throttle
        sleep: 0.5
      - sc_command: v_invoke_quantum_drive  # Engage quantum
    responses:
      - "Quantum drive engaged"
```

### Example 3: Include Excluded Command

```bash
# Check why a command is inactive
$ python check_command_status.py pc_interaction_mode

# Output shows: inactive_reason: "category_excluded"
```

```yaml
# Include it explicitly
keybind_categories_to_ignore:
  - player  # This category is excluded

include_actions:
  - pc_interaction_mode  # But include this specific one
```

## Troubleshooting

### Problem: Command not working in AI

```bash
# 1. Check the command status
python check_command_status.py <command_name>

# 2. Look at AI Status section:
#    - is_active: false? Check inactive_reason
#    - no_keybinding? Assign in Star Citizen
#    - category_excluded? Add to include_actions
#    - unsupported_activation? Can't use hold/hold_toggle
```

### Problem: Can't find command name

```bash
# Search for it
python list_commands.py --search "<what you want>"

# Browse by category
python list_commands.py --by-category

# List all active commands
python list_commands.py --active-only
```

### Problem: Migration failed

```bash
# Check if you have backup
ls star_citizen_data/keybindings/R4_60/*.backup*

# Restore from backup
cp sc_all_keybindings.backup_TIMESTAMP.json sc_all_keybindings.json

# Try different migration approach
python migrate_keybindings.py R4_60 --backup
```

### Problem: Utilities not working

```bash
# Check Python version (need 3.7+)
python --version

# Install in virtual environment
cd wingman-ai
.venv\Scripts\activate  # Windows
python star_citizen_data/keybindings/check_command_status.py
```

## Benefits Summary

### For Users:
✅ Easier to understand which commands are available
✅ Clear explanation when commands don't work
✅ Simple tools to find and reference commands
✅ Better documentation

### For Configuration:
✅ Easy to reference commands in config.yaml
✅ Clear error messages when commands fail
✅ Simple include/exclude logic
✅ Example-driven documentation

### For Updates:
✅ Preserves custom command phrases during SC updates
✅ Only regenerates what's needed
✅ Clear update process
✅ Backup utilities included

### For Development:
✅ Cleaner code organization
✅ Better separation of concerns
✅ Comprehensive documentation
✅ Testing utilities

## What Stays the Same

✅ **Existing config.yaml works** - No changes required
✅ **Command phrases preserved** - All your existing phrases remain
✅ **Custom keybindings work** - No change to how you export/import
✅ **Backward compatible** - Old system still works during transition

## Next Steps

1. **Read KEYBINDINGS_DESIGN.md** for complete architecture details
2. **Read README.md** for utility usage guide
3. **Run migration** to add new metadata
4. **Try utilities** to explore your keybindings
5. **Update config.yaml** using easier command reference

## Support

- **Documentation**: See KEYBINDINGS_DESIGN.md and README.md
- **Utilities Help**: Run scripts with `--help`
- **Examples**: Check README.md for common workflows
- **Issues**: Use utilities to diagnose problems first

---

**Created:** February 12, 2026
**Version:** Unified Keybindings System v1.0
**Status:** Ready for testing and feedback
