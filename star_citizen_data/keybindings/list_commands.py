"""
Helper script to list Star Citizen keybindings organized by category or other criteria.

Usage:
    python list_commands.py [options] [version]
    
Options:
    --by-category       List commands grouped by category (default)
    --active-only       Show only active commands (default)
    --all               Show all commands including inactive
    --no-binding        Show only commands without keybindings
    --custom            Show only commands with custom keybindings
    --search <term>     Search for commands containing <term>
    --stats             Show statistics
    
Examples:
    python list_commands.py --active-only
    python list_commands.py --no-binding R4_60
    python list_commands.py --search "quantum"
    python list_commands.py --stats
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

try:
    from .version_utils import available_versions, resolve_version
except ImportError:
    from version_utils import available_versions, resolve_version


def load_keybindings(version=None):
    """Load keybindings file for specified version."""
    script_dir = Path(__file__).parent
    try:
        version = resolve_version(script_dir, version)
    except FileNotFoundError as exc:
        print(f"❌ {exc}")
        return None
    kb_file = script_dir / version / 'sc_all_keybindings.json'
    
    if not kb_file.exists():
        print(f"❌ Keybindings file not found: {kb_file}")
        print(f"\nAvailable versions:")
        for available_version in available_versions(script_dir):
            print(f"   - {available_version}")
        return None
    
    with open(kb_file, encoding='utf-8') as f:
        return json.load(f)


def list_by_category(kb, active_only=True):
    """List commands organized by category."""
    by_category = defaultdict(list)
    
    for actionname, cmd in kb.items():
        status = cmd.get('ai_status', {})
        is_active = status.get('is_active', False)
        
        if active_only and not is_active:
            continue
        
        by_category[cmd.get('category', 'unknown')].append({
            'name': actionname,
            'label': cmd.get('action-label-en', ''),
            'keybinding': cmd.get('keyboard-mapping', ''),
            'active': is_active,
            'has_phrases': status.get('has_command_phrases', False)
        })
    
    total = sum(len(cmds) for cmds in by_category.values())
    filter_text = "Active" if active_only else "All"
    
    print(f"\n{'='*80}")
    print(f"  {filter_text} Commands by Category ({total} total)")
    print(f"{'='*80}")
    
    for category in sorted(by_category.keys()):
        commands = by_category[category]
        print(f"\n📁 {category} ({len(commands)} commands)")
        print("-" * 80)
        
        for cmd in sorted(commands, key=lambda x: x['name']):
            status_icon = '✅' if cmd['active'] else '❌'
            phrase_icon = '💬' if cmd['has_phrases'] else '  '
            kb = cmd['keybinding'] or 'NO_BINDING'
            label = cmd['label'] or cmd['name']
            
            print(f"  {status_icon} {phrase_icon} {cmd['name']:40s} [{kb:15s}] {label}")


def list_no_binding(kb):
    """List commands without keybindings."""
    no_binding = []
    
    for actionname, cmd in kb.items():
        status = cmd.get('ai_status', {})
        if not status.get('has_keybinding', True):
            no_binding.append({
                'name': actionname,
                'category': cmd.get('category', ''),
                'label': cmd.get('action-label-en', '')
            })
    
    print(f"\n{'='*80}")
    print(f"  Commands Without Keybindings ({len(no_binding)} total)")
    print(f"{'='*80}\n")
    
    by_category = defaultdict(list)
    for cmd in no_binding:
        by_category[cmd['category']].append(cmd)
    
    for category in sorted(by_category.keys()):
        print(f"\n📁 {category}:")
        for cmd in sorted(by_category[category], key=lambda x: x['name']):
            label = cmd['label'] or cmd['name']
            print(f"   {cmd['name']:40s} {label}")


def list_custom_bindings(kb):
    """List commands with custom keybindings."""
    custom = []
    
    for actionname, cmd in kb.items():
        if cmd.get('keyboard-mapping-custom'):
            custom.append({
                'name': actionname,
                'category': cmd.get('category', ''),
                'default': cmd.get('keyboard-mapping-default', ''),
                'custom': cmd.get('keyboard-mapping-custom', ''),
                'label': cmd.get('action-label-en', '')
            })
    
    print(f"\n{'='*80}")
    print(f"  Commands With Custom Keybindings ({len(custom)} total)")
    print(f"{'='*80}\n")
    
    for cmd in sorted(custom, key=lambda x: x['name']):
        print(f"\n{cmd['name']}")
        print(f"   Label:   {cmd['label']}")
        print(f"   Default: {cmd['default']}")
        print(f"   Custom:  {cmd['custom']} ⭐")


def search_commands(kb, search_term):
    """Search for commands containing the search term."""
    search_lower = search_term.lower()
    results = []
    
    for actionname, cmd in kb.items():
        # Search in action name, label, and description
        if (search_lower in actionname.lower() or
            search_lower in cmd.get('action-label-en', '').lower() or
            search_lower in cmd.get('action-description-en', '').lower()):
            
            status = cmd.get('ai_status', {})
            results.append({
                'name': actionname,
                'category': cmd.get('category', ''),
                'label': cmd.get('action-label-en', ''),
                'description': cmd.get('action-description-en', ''),
                'keybinding': cmd.get('keyboard-mapping', ''),
                'active': status.get('is_active', False)
            })
    
    print(f"\n{'='*80}")
    print(f"  Search Results for '{search_term}' ({len(results)} found)")
    print(f"{'='*80}\n")
    
    for cmd in sorted(results, key=lambda x: x['name']):
        status_icon = '✅' if cmd['active'] else '❌'
        kb = cmd['keybinding'] or 'NO_BINDING'
        
        print(f"\n{status_icon} {cmd['name']}")
        print(f"   Category:    {cmd['category']}")
        print(f"   Label:       {cmd['label']}")
        print(f"   Description: {cmd['description']}")
        print(f"   Keybinding:  {kb}")


def show_statistics(kb):
    """Show statistics about keybindings."""
    stats = {
        'total': len(kb),
        'active': 0,
        'inactive': 0,
        'has_keybinding': 0,
        'no_keybinding': 0,
        'has_phrases': 0,
        'custom_configured': 0,
        'custom_keybinding': 0,
        'unsupported_activation': 0
    }
    
    inactive_reasons = defaultdict(int)
    categories = defaultdict(int)
    activation_modes = defaultdict(int)
    
    for actionname, cmd in kb.items():
        status = cmd.get('ai_status', {})
        
        # Count statuses
        if status.get('is_active', False):
            stats['active'] += 1
        else:
            stats['inactive'] += 1
            reason = status.get('inactive_reason', 'unknown')
            inactive_reasons[reason] += 1
        
        if status.get('has_keybinding', False):
            stats['has_keybinding'] += 1
        else:
            stats['no_keybinding'] += 1
        
        if status.get('has_command_phrases', False):
            stats['has_phrases'] += 1
        
        if status.get('is_custom_configured', False):
            stats['custom_configured'] += 1
        
        if not status.get('activation_supported', True):
            stats['unsupported_activation'] += 1
        
        if cmd.get('keyboard-mapping-custom'):
            stats['custom_keybinding'] += 1
        
        # Count categories and activation modes
        categories[cmd.get('category', 'unknown')] += 1
        activation_modes[cmd.get('activationMode', 'unknown')] += 1
    
    # Print statistics
    print(f"\n{'='*80}")
    print(f"  Keybindings Statistics")
    print(f"{'='*80}")
    
    print(f"\n📊 Overall:")
    print(f"   Total Commands:           {stats['total']}")
    print(f"   Active for AI:            {stats['active']} ({stats['active']/stats['total']*100:.1f}%)")
    print(f"   Inactive:                 {stats['inactive']} ({stats['inactive']/stats['total']*100:.1f}%)")
    
    print(f"\n⌨️  Keybindings:")
    print(f"   With Keybinding:          {stats['has_keybinding']}")
    print(f"   Without Keybinding:       {stats['no_keybinding']}")
    print(f"   Custom Keybindings:       {stats['custom_keybinding']}")
    
    print(f"\n💬 Command Phrases:")
    print(f"   With Phrases Generated:   {stats['has_phrases']}")
    print(f"   Without Phrases:          {stats['total'] - stats['has_phrases']}")
    
    print(f"\n⚙️  Configuration:")
    print(f"   Custom Configured:        {stats['custom_configured']}")
    print(f"   Unsupported Activation:   {stats['unsupported_activation']}")
    
    if inactive_reasons:
        print(f"\n❌ Inactive Reasons:")
        for reason, count in sorted(inactive_reasons.items(), key=lambda x: -x[1]):
            print(f"   {reason:30s} {count:4d}")
    
    print(f"\n📁 Commands by Category:")
    for category, count in sorted(categories.items(), key=lambda x: -x[1])[:10]:
        print(f"   {category:30s} {count:4d}")
    
    print(f"\n🎮 Activation Modes:")
    for mode, count in sorted(activation_modes.items(), key=lambda x: -x[1]):
        print(f"   {mode:30s} {count:4d}")
    
    print()


def main():
    """Main entry point."""
    if '--help' in sys.argv or '-h' in sys.argv:
        print(__doc__)
        return
    
    # Parse arguments
    version = None
    mode = '--by-category'
    active_only = True
    search_term = None
    
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        
        if arg.startswith('R'):
            version = arg
        elif arg == '--by-category':
            mode = arg
        elif arg == '--active-only':
            active_only = True
        elif arg == '--all':
            active_only = False
        elif arg == '--no-binding':
            mode = arg
        elif arg == '--custom':
            mode = arg
        elif arg == '--stats':
            mode = arg
        elif arg == '--search':
            mode = arg
            if i + 1 < len(sys.argv):
                search_term = sys.argv[i + 1]
                i += 1
        
        i += 1
    
    # Load keybindings
    kb = load_keybindings(version)
    if not kb:
        return
    
    # Execute requested mode
    if mode == '--by-category':
        list_by_category(kb, active_only)
    elif mode == '--no-binding':
        list_no_binding(kb)
    elif mode == '--custom':
        list_custom_bindings(kb)
    elif mode == '--search':
        if search_term:
            search_commands(kb, search_term)
        else:
            print("❌ --search requires a search term")
    elif mode == '--stats':
        show_statistics(kb)


if __name__ == '__main__':
    main()
