"""
Migration utility to convert old keybindings format to the new unified format.

This script will:
1. Load existing sc_all_keybindings.json
2. Add ai_status metadata to each command
3. Preserve existing command phrases
4. Mark default vs custom keybindings
5. Save the updated file

Usage:
    python migrate_keybindings.py [version] [--backup]
    
Examples:
    python migrate_keybindings.py R4_60 --backup
    python migrate_keybindings.py
"""

import json
import sys
from pathlib import Path
from datetime import datetime
import shutil


def backup_file(file_path):
    """Create a backup of the file with timestamp."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = file_path.with_suffix(f'.backup_{timestamp}.json')
    shutil.copy2(file_path, backup_path)
    print(f"✅ Backup created: {backup_path.name}")
    return backup_path


def calculate_ai_status(cmd, config_filters=None):
    """Calculate ai_status metadata for a command.
    
    Args:
        cmd: Command dictionary
        config_filters: Optional dict with configuration filters
            {
                'ignored_categories': set of category names,
                'ignored_actions': set of action names,
                'included_actions': set of action names
            }
    """
    if config_filters is None:
        config_filters = {
            'ignored_categories': set(),
            'ignored_actions': set(),
            'included_actions': set()
        }
    
    status = {
        'is_active': True,
        'inactive_reason': None,
        'has_keybinding': False,
        'has_command_phrases': False,
        'is_custom_configured': False,
        'activation_supported': True
    }
    
    # Check if has keybinding
    kb = cmd.get('keyboard-mapping', '').strip()
    status['has_keybinding'] = bool(kb)
    
    # Check if has command phrases
    phrases = cmd.get('command-phrases', {})
    if phrases:
        # Check if any language has phrases
        status['has_command_phrases'] = any(
            bool(phrase_list) for phrase_list in phrases.values()
        )
    
    # Check activation mode - any mode with "hold" in the name is not supported
    activation_mode = cmd.get('activationMode', '')
    if activation_mode and 'hold' in activation_mode.lower():
        status['activation_supported'] = False
        status['is_active'] = False
        status['inactive_reason'] = 'unsupported_activation'
        return status
    
    # Check if explicitly excluded
    actionname = cmd.get('actionname', '')
    if actionname in config_filters['ignored_actions']:
        # Unless explicitly included
        if actionname not in config_filters['included_actions']:
            status['is_active'] = False
            status['inactive_reason'] = 'explicitly_excluded'
            return status
    
    # Check if category is excluded
    category = cmd.get('category', '')
    if category in config_filters['ignored_categories']:
        # Unless this specific action is included
        if actionname not in config_filters['included_actions']:
            status['is_active'] = False
            status['inactive_reason'] = 'category_excluded'
            return status
    
    # Check if has keybinding
    if not status['has_keybinding']:
        status['is_active'] = False
        status['inactive_reason'] = 'no_keybinding'
        return status
    
    # If we reach here, command is active
    status['is_active'] = True
    status['inactive_reason'] = None
    
    return status


def migrate_keybindings(version='R4_60', create_backup=True, config_filters=None):
    """Migrate keybindings to new unified format."""
    script_dir = Path(__file__).parent
    kb_file = script_dir / version / 'sc_all_keybindings.json'
    kb_existing_file = script_dir / version / 'keybindings_existing_knowledge.json'
    
    if not kb_file.exists():
        print(f"❌ Keybindings file not found: {kb_file}")
        return False
    
    print(f"\n{'='*80}")
    print(f"  Migrating Keybindings to Unified Format: {version}")
    print(f"{'='*80}\n")
    
    # Create backup
    if create_backup:
        backup_file(kb_file)
    
    # Load existing data
    print("📖 Loading keybindings...")
    with open(kb_file, encoding='utf-8') as f:
        kb = json.load(f)
    
    print(f"   Found {len(kb)} commands")
    
    # Load existing knowledge file to get command-phrases
    kb_existing = {}
    if kb_existing_file.exists():
        print("📖 Loading existing command phrases...")
        with open(kb_existing_file, encoding='utf-8') as f:
            kb_existing = json.load(f)
        print(f"   Found {len(kb_existing)} commands with phrases")
        
        # Build lookup by actionname (since keys are different)
        phrases_by_actionname = {}
        for entry in kb_existing.values():
            actionname = entry.get('actionname')
            phrases = entry.get('command-phrases')
            if actionname and phrases:
                phrases_by_actionname[actionname] = phrases
        
        print(f"   Mapped {len(phrases_by_actionname)} command phrases by actionname")
    
    # Check if already migrated
    sample_cmd = next(iter(kb.values()))
    if 'ai_status' in sample_cmd and not kb_existing_file.exists():
        print("⚠️  File appears to already have ai_status metadata")
        response = input("   Continue anyway? (y/n): ")
        if response.lower() != 'y':
            print("   Migration cancelled")
            return False
    
    # Migrate each command
    print("\n🔄 Adding ai_status metadata and command phrases...")
    migrated_count = 0
    phrases_added = 0
    
    for actionname, cmd in kb.items():
        # Preserve keyboard-mapping as both current and default if not already set
        if 'keyboard-mapping-default' not in cmd:
            cmd['keyboard-mapping-default'] = cmd.get('keyboard-mapping', '')
        
        if 'keyboard-mapping-custom' not in cmd:
            cmd['keyboard-mapping-custom'] = None
        
        # Add command phrases from existing knowledge if available
        cmd_actionname = cmd.get('actionname')
        if cmd_actionname and cmd_actionname in phrases_by_actionname:
            if 'command-phrases' not in cmd or not cmd['command-phrases']:
                cmd['command-phrases'] = phrases_by_actionname[cmd_actionname]
                phrases_added += 1
        
        # Calculate and add ai_status
        cmd['ai_status'] = calculate_ai_status(cmd, config_filters)
        
        migrated_count += 1
        if migrated_count % 100 == 0:
            print(f"   Processed {migrated_count}/{len(kb)} commands...")
    
    print(f"   ✅ Migrated {migrated_count} commands")
    if phrases_added > 0:
        print(f"   ✅ Added {phrases_added} command phrase sets")
    
    # Generate statistics
    stats = {
        'active': sum(1 for cmd in kb.values() if cmd['ai_status']['is_active']),
        'inactive': sum(1 for cmd in kb.values() if not cmd['ai_status']['is_active']),
        'has_phrases': sum(1 for cmd in kb.values() if cmd['ai_status']['has_command_phrases']),
        'has_keybinding': sum(1 for cmd in kb.values() if cmd['ai_status']['has_keybinding'])
    }
    
    print(f"\n📊 Migration Statistics:")
    print(f"   Total:           {len(kb)}")
    print(f"   Active:          {stats['active']} ({stats['active']/len(kb)*100:.1f}%)")
    print(f"   Inactive:        {stats['inactive']} ({stats['inactive']/len(kb)*100:.1f}%)")
    print(f"   Has Keybinding:  {stats['has_keybinding']}")
    print(f"   Has Phrases:     {stats['has_phrases']}")
    
    # Count inactive reasons
    from collections import defaultdict
    inactive_reasons = defaultdict(int)
    for cmd in kb.values():
        reason = cmd['ai_status'].get('inactive_reason')
        if reason:
            inactive_reasons[reason] += 1
    
    if inactive_reasons:
        print(f"\n   Inactive Reasons:")
        for reason, count in sorted(inactive_reasons.items(), key=lambda x: -x[1]):
            print(f"      {reason:30s} {count:4d}")
    
    # Save migrated data
    print(f"\n💾 Saving migrated data...")
    with open(kb_file, 'w', encoding='utf-8') as f:
        json.dump(kb, f, indent=4, ensure_ascii=False)
    
    print(f"   ✅ Saved to {kb_file.name}")
    
    print(f"\n✨ Migration Complete!")
    print(f"\nNext steps:")
    print(f"   1. Review the migrated file: {kb_file}")
    print(f"   2. Test with: python check_command_status.py v_toggle_mining_mode {version}")
    print(f"   3. View statistics: python list_commands.py --stats {version}")
    print(f"   4. Update config.yaml if needed")
    
    return True


def load_config_filters_from_yaml(config_path):
    """Load filter configuration from config.yaml."""
    try:
        import yaml
        
        if not config_path.exists():
            print(f"⚠️  Config file not found: {config_path}")
            return None
            
        with open(config_path, encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # Navigate to the star-citizen-ai wingman configuration
        sc_ai = config.get('wingmen', {}).get('star-citizen-ai', {})
        
        filters = {
            'ignored_categories': set(sc_ai.get('keybind_categories_to_ignore', [])),
            'ignored_actions': set(sc_ai.get('ignored_actionnames', [])),
            'included_actions': set(sc_ai.get('include_actions', []))
        }
        
        return filters
        
    except ImportError:
        print(f"⚠️  PyYAML not installed, cannot load config filters")
        print(f"   Install with: pip install pyyaml")
        return None
    except Exception as e:
        print(f"⚠️  Could not load config.yaml filters: {e}")
        print(f"   Continuing with empty filters...")
        return None


def main():
    """Main entry point."""
    version = 'R4_60'
    create_backup = False
    config_filters = None
    
    # Parse arguments
    for arg in sys.argv[1:]:
        if arg.startswith('R'):
            version = arg
        elif arg == '--backup':
            create_backup = True
        elif arg == '--help' or arg == '-h':
            print(__doc__)
            return
    
    # Try to load config filters
    script_dir = Path(__file__).parent
    config_path = script_dir.parent.parent / 'configs' / 'configs' / 'config.yaml'
    
    print(f"📋 Looking for config.yaml at: {config_path}")
    
    if config_path.exists():
        print(f"   ✅ Found config.yaml")
        config_filters = load_config_filters_from_yaml(config_path)
        if config_filters:
            print(f"   ✅ Loaded filters:")
            print(f"      Ignored categories: {len(config_filters['ignored_categories'])}")
            if config_filters['ignored_categories']:
                print(f"         {', '.join(list(config_filters['ignored_categories'])[:5])}")
            print(f"      Ignored actions: {len(config_filters['ignored_actions'])}")
            if config_filters['ignored_actions']:
                print(f"         {', '.join(list(config_filters['ignored_actions'])[:5])}")
            print(f"      Included actions: {len(config_filters['included_actions'])}")
            if config_filters['included_actions']:
                print(f"         {', '.join(list(config_filters['included_actions'])[:5])}")
    else:
        print(f"   ⚠️  Config.yaml not found at expected location")
        print(f"   Continuing with no filters (all commands with keybindings will be active)")
    
    # Run migration (only once!)
    success = migrate_keybindings(version, create_backup, config_filters)
    
    if success:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
