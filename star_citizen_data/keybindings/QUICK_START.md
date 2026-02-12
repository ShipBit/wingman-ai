# Quick Start Guide - Improved Keybindings System

This is a 5-minute guide to get started with the improved Star Citizen keybindings system.

## What You Need to Know

**The Big Change:** Everything about keybindings is now in ONE file (`sc_all_keybindings.json`) with clear status information.

**New Tools:** Python utilities to help you understand and manage keybindings.

**Your Config:** No changes required unless you want to use new features.

## 5-Minute Getting Started

### Step 1: Check Current Status (1 minute)

```bash
cd star_citizen_data/keybindings
python list_commands.py --stats
```

**What this shows:**
- Total commands available
- How many are active for AI
- Why some are inactive
- Statistics about your keybindings

### Step 2: Migrate to New Format (2 minutes)

```bash
# This adds helpful metadata to your keybindings
python migrate_keybindings.py R4_60 --backup

# Verify it worked
python check_command_status.py v_toggle_mining_mode
```

**What this does:**
- Creates automatic backup
- Adds `ai_status` metadata to each command
- Preserves all existing data
- Shows migration statistics

### Step 3: Try the Utilities (2 minutes)

```bash
# See all active commands by category
python list_commands.py

# Search for specific commands
python list_commands.py --search "quantum"

# Check a specific command
python check_command_status.py v_invoke_quantum_drive

# See commands you've customized
python list_commands.py --custom
```

**That's it!** You now have:
✅ Better organized keybindings
✅ Clear status tracking
✅ Easy-to-use utilities
✅ Your existing setup still works

## Common Tasks

### Task: Add a new voice command

**Before (hard way):**
```
1. Guess the command name from XML files
2. Hope you got it right
3. Test in-game
4. Repeat if wrong
```

**Now (easy way):**
```bash
# 1. Search for what you want
python list_commands.py --search "mining"

# 2. Check the command details
python check_command_status.py v_toggle_mining_mode

# 3. Copy the actionname to config.yaml
```

```yaml
commands:
  - name: toggle_mining
    sc_commands:
      - sc_command: v_toggle_mining_mode  # ← Found easily!
```

### Task: Fix a command that's not working

```bash
# 1. Check why it's not working
python check_command_status.py v_self_destruct

# 2. Output shows:
#    AI Status: ❌ INACTIVE
#    Reason: explicitly_excluded

# 3. Fix in config.yaml if you want to include it
```

```yaml
ignored_actionnames:
  # - v_self_destruct  # ← Remove or comment out
```

### Task: Update after new Star Citizen release

```bash
# 1. Extract new SC files to R4_61/ folder
# 2. Update config.yaml
```

```yaml
sc-keybind-mappings:
  sc_channel_version: R4_61  # ← Change version
```

```bash
# 3. Set update mode in config.yaml
```

```yaml
update_keybindings: true  # ← Enable updates
```

```bash
# 4. Restart Wingman AI
# 5. Done! Your command phrases are preserved
```

## Cheat Sheet

```bash
# INSPECT COMMANDS
python check_command_status.py <name>     # Check one command
python list_commands.py --stats           # Show statistics
python list_commands.py --search <term>   # Search commands
python list_commands.py --active-only     # List active commands
python list_commands.py --custom          # Show custom keybinds

# MANAGE
python migrate_keybindings.py --backup    # Migrate to new format
python list_commands.py --no-binding      # Find unbound commands

# HELP
python check_command_status.py --help
python list_commands.py --help
python migrate_keybindings.py --help
```

## Files to Know

```
star_citizen_data/keybindings/
├── R4_60/
│   └── sc_all_keybindings.json      ← MAIN FILE (everything is here)
├── check_command_status.py          ← Tool: Check a command
├── list_commands.py                 ← Tool: Browse commands
├── migrate_keybindings.py           ← Tool: Migrate format
├── KEYBINDINGS_DESIGN.md            ← Full documentation
├── README.md                        ← Detailed user guide
├── IMPROVEMENTS.md                  ← What's new
└── QUICK_START.md                   ← This file
```

## Example Workflows

### "I want to add quantum jump command"

```bash
# Find it
$ python list_commands.py --search quantum

# Output shows:
✅ v_invoke_quantum_drive [b] Engage Quantum Drive

# Add to config.yaml:
```

```yaml
commands:
  - name: quantum
    instant_activation: ["quantum jump", "engage quantum"]
    sc_commands:
      - sc_command: v_invoke_quantum_drive
```

### "Why isn't my command working?"

```bash
# Check it
$ python check_command_status.py v_toggle_mining_mode

# Shows:
AI Status: ✅ ACTIVE
Has Keybinding: ✅
Has Phrases: ✅

# If ❌, shows why (no keybinding, excluded, etc.)
```

### "What commands can I use?"

```bash
# See all active commands
$ python list_commands.py --active-only

# Or by category
$ python list_commands.py --by-category

# Or statistics
$ python list_commands.py --stats
```

## Need More Help?

- **Quick overview:** This file
- **Utility usage:** [README.md](README.md)
- **Complete guide:** [KEYBINDINGS_DESIGN.md](KEYBINDINGS_DESIGN.md)
- **What's new:** [IMPROVEMENTS.md](IMPROVEMENTS.md)
- **Discord:** Ask in the project Discord

## FAQ

**Q: Do I need to change my config.yaml?**
A: No, your existing config still works. But new tools make it easier to add commands.

**Q: Will this break my existing commands?**
A: No, all existing data is preserved.

**Q: What if something goes wrong?**
A: Migration creates automatic backups with `--backup` flag.

**Q: Do I have to use the new tools?**
A: No, they're optional helpers. But they make life much easier!

**Q: Can I revert to the old system?**
A: Yes, just restore from backup if you created one.

---

**That's it!** You're ready to use the improved keybindings system. Start with `python list_commands.py --stats` and explore from there.

Happy flying, Commander! o7
