"""
Helper script to check the status of a specific Star Citizen keybinding command.

Usage:
    python check_command_status.py <actionname> [version]
    
Examples:
    python check_command_status.py v_toggle_mining_mode
    python check_command_status.py v_invoke_quantum_drive R4_61
"""

import json
import sys
from pathlib import Path

try:
    from .version_utils import available_versions, resolve_version
except ImportError:
    from version_utils import available_versions, resolve_version


def check_command(actionname, version=None):
    """Check and display the status of a specific command."""
    # Build path to keybindings file
    script_dir = Path(__file__).parent
    try:
        version = resolve_version(script_dir, version)
    except FileNotFoundError as exc:
        print(f"❌ {exc}")
        return
    kb_file = script_dir / version / 'sc_all_keybindings.json'
    
    if not kb_file.exists():
        print(f"❌ Keybindings file not found: {kb_file}")
        print(f"   Available versions:")
        for available_version in available_versions(script_dir):
            print(f"   - {available_version}")
        return
    
    # Load keybindings
    with open(kb_file, encoding='utf-8') as f:
        kb = json.load(f)
    
    if actionname not in kb:
        print(f"❌ Command '{actionname}' not found in {version}")
        print(f"\n   Did you mean one of these?")
        # Find similar commands
        similar = [k for k in kb.keys() if actionname.lower() in k.lower()][:5]
        for sim in similar:
            print(f"   - {sim}")
        return
    
    cmd = kb[actionname]
    status = cmd.get('ai_status', {})
    
    # Print command information
    print(f"\n{'='*70}")
    print(f"  Command: {actionname}")
    print(f"{'='*70}")
    
    print(f"\n📋 Basic Information:")
    print(f"   Category:     {cmd.get('category', 'N/A')}")
    print(f"   Label (EN):   {cmd.get('action-label-en', 'N/A')}")
    print(f"   Description:  {cmd.get('action-description-en', 'N/A')}")
    print(f"   Activation:   {cmd.get('activationMode', 'N/A')}")
    
    print(f"\n⌨️  Keybindings:")
    kb_current = cmd.get('keyboard-mapping', 'NONE')
    kb_default = cmd.get('keyboard-mapping-default', kb_current)
    kb_custom = cmd.get('keyboard-mapping-custom')
    
    print(f"   Current:      {kb_current}")
    if kb_custom:
        print(f"   Default:      {kb_default}")
        print(f"   Custom:       {kb_custom} ⭐")
    else:
        print(f"   Default:      {kb_default}")
    
    # Localized keybindings
    print(f"\n🌍 Localized:")
    for lang in ['en', 'de_DE', 'fr_FR']:
        kb_loc = cmd.get(f'keyboard-mapping-{lang}')
        if kb_loc:
            print(f"   {lang:8s}  {kb_loc}")
    
    print(f"\n🤖 AI Status:")
    is_active = status.get('is_active', False)
    
    if is_active:
        print(f"   Status:       ✅ ACTIVE")
    else:
        print(f"   Status:       ❌ INACTIVE")
        reason = status.get('inactive_reason', 'Unknown')
        print(f"   Reason:       {reason}")
    
    print(f"   Has Keybinding:   {'✅' if status.get('has_keybinding') else '❌'}")
    print(f"   Has Phrases:      {'✅' if status.get('has_command_phrases') else '❌'}")
    print(f"   Custom Config:    {'✅' if status.get('is_custom_configured') else '❌'}")
    print(f"   Activation OK:    {'✅' if status.get('activation_supported') else '❌'}")
    
    # Command phrases
    phrases = cmd.get('command-phrases', {})
    if phrases:
        print(f"\n💬 Command Phrases:")
        for lang, phrase_list in phrases.items():
            if phrase_list:
                print(f"   {lang}:")
                for phrase in phrase_list[:5]:  # Show max 5
                    print(f"      - \"{phrase}\"")
                if len(phrase_list) > 5:
                    print(f"      ... and {len(phrase_list) - 5} more")
    else:
        print(f"\n💬 Command Phrases:  None generated")
    
    # Config reference
    print(f"\n⚙️  Configuration Reference:")
    print(f"   Use in config.yaml as:")
    print(f"   ```yaml")
    print(f"   commands:")
    print(f"     - name: {actionname}")
    print(f"       sc_commands:")
    print(f"         - sc_command: {actionname}")
    print(f"   ```")
    
    print(f"\n{'='*70}\n")


def list_all_commands(version=None, filter_active=True):
    """List all commands, optionally filtered by active status."""
    script_dir = Path(__file__).parent
    try:
        version = resolve_version(script_dir, version)
    except FileNotFoundError as exc:
        print(f"❌ {exc}")
        return
    kb_file = script_dir / version / 'sc_all_keybindings.json'
    
    if not kb_file.exists():
        print(f"❌ Keybindings file not found: {kb_file}")
        return
    
    with open(kb_file, encoding='utf-8') as f:
        kb = json.load(f)
    
    commands = []
    for actionname, cmd in kb.items():
        status = cmd.get('ai_status', {})
        is_active = status.get('is_active', False)
        
        if filter_active and not is_active:
            continue
        
        commands.append({
            'name': actionname,
            'category': cmd.get('category', ''),
            'label': cmd.get('action-label-en', ''),
            'active': is_active
        })
    
    # Print summary
    print(f"\n{'='*70}")
    if filter_active:
        print(f"  Active Commands in {version} ({len(commands)} total)")
    else:
        print(f"  All Commands in {version} ({len(commands)} total)")
    print(f"{'='*70}\n")
    
    # Group by category
    from collections import defaultdict
    by_category = defaultdict(list)
    for cmd in commands:
        by_category[cmd['category']].append(cmd)
    
    for category in sorted(by_category.keys()):
        print(f"\n📁 {category}:")
        for cmd in sorted(by_category[category], key=lambda x: x['name']):
            status_icon = '✅' if cmd['active'] else '❌'
            label = cmd['label'] or cmd['name']
            print(f"   {status_icon} {cmd['name']:40s} {label}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nExample: Check mining mode command")
        print("-" * 70)
        check_command('v_toggle_mining_mode')
    elif sys.argv[1] == '--list':
        version = sys.argv[2] if len(sys.argv) > 2 else None
        list_all_commands(version, filter_active=True)
    elif sys.argv[1] == '--list-all':
        version = sys.argv[2] if len(sys.argv) > 2 else None
        list_all_commands(version, filter_active=False)
    else:
        actionname = sys.argv[1]
        version = sys.argv[2] if len(sys.argv) > 2 else None
        check_command(actionname, version)
