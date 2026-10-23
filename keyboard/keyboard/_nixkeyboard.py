# -*- coding: utf-8 -*-
import struct
import traceback
from time import time as now
from collections import namedtuple
from ._keyboard_event import KeyboardEvent, KEY_DOWN, KEY_UP
from ._canonical_names import all_modifiers, normalize_name
from ._nixcommon import EV_KEY, aggregate_devices

# TODO: start by reading current keyboard state, as to not missing any already pressed keys.
# See: http://stackoverflow.com/questions/3649874/how-to-get-keyboard-state-in-linux

def cleanup_key(name):
    """ Formats a dumpkeys format to our standard. """
    name = name.lstrip('+')
    is_keypad = name.startswith('KP_')
    for mod in ('Meta_', 'Control_', 'dead_', 'KP_'):
        if name.startswith(mod):
            name = name[len(mod):]

    # Dumpkeys is weird like that.
    if name == 'Remove':
        name = 'Delete'
    elif name == 'Delete':
        name = 'Backspace'

    if name.endswith('_r'):
        name = 'right ' + name[:-2]
    if name.endswith('_l'):
        name = 'left ' + name[:-2]


    return normalize_name(name), is_keypad

def cleanup_modifier(modifier):
    modifier = normalize_name(modifier)
    if modifier in all_modifiers:
        return modifier
    if modifier[:-1] in all_modifiers:
        return modifier[:-1]
    raise ValueError('Unknown modifier {}'.format(modifier))

"""
Use `dumpkeys --keys-only` to list all scan codes and their names. We
then parse the output and built a table. For each scan code and modifiers we
have a list of names and vice-versa.
"""
from subprocess import check_output, CalledProcessError, PIPE
from collections import defaultdict
import re

to_name = defaultdict(list)
from_name = defaultdict(list)
keypad_scan_codes = set()

def register_key(key_and_modifiers, name):
    if name not in to_name[key_and_modifiers]:
        to_name[key_and_modifiers].append(name)
    if key_and_modifiers not in from_name[name]:
        from_name[name].append(key_and_modifiers)

def build_tables():
    if to_name and from_name: return

    modifiers_bits = {
        'shift': 1,
        'alt gr': 2,
        'ctrl': 4,
        'alt': 8,
    }
    keycode_template = r'^keycode\s+(\d+)\s+=(.*?)$'
    try:
        dump = check_output(['dumpkeys', '--keys-only'], universal_newlines=True, stderr=PIPE)
    except (CalledProcessError, OSError) as e:
        # dumpkeys reads the keymap of a Linux text console. A desktop session
        # (Wayland above all) has none, so it fails there even for users in the
        # "tty" group, and some distros do not install it at all.
        print('Keyboard: dumpkeys failed ({}), using the built-in US key names.'.format(e))
        register_fallback_tables()
        return

    for str_scan_code, str_names in re.findall(keycode_template, dump, re.MULTILINE):
        scan_code = int(str_scan_code)
        for i, str_name in enumerate(str_names.strip().split()):
            modifiers = tuple(sorted(modifier for modifier, bit in modifiers_bits.items() if i & bit))
            name, is_keypad = cleanup_key(str_name)
            register_key((scan_code, modifiers), name)
            if is_keypad:
                keypad_scan_codes.add(scan_code)
                register_key((scan_code, modifiers), 'keypad ' + name)

    # dumpkeys consistently misreports the Windows key, sometimes
    # skipping it completely or reporting as 'alt. 125 = left win,
    # 126 = right win.
    if (125, ()) not in to_name or to_name[(125, ())] == ['alt']:
        to_name[(125, ())].clear()
        if (125, ()) in from_name['alt']:
            from_name['alt'].remove((125, ()))
        register_key((125, ()), 'windows')
    if (126, ()) not in to_name or to_name[(126, ())] == ['alt']:
        to_name[(126, ())].clear()
        if (126, ()) in from_name['alt']:
            from_name['alt'].remove((126, ()))
        register_key((126, ()), 'windows')

    # The menu key is usually skipped altogether, so we also add it manually.
    if (127, ()) not in to_name:
        register_key((127, ()), 'menu')

    synonyms_template = r'^(\S+)\s+for (.+)$'
    try:
        dump = check_output(['dumpkeys', '--long-info'], universal_newlines=True, stderr=PIPE)
    except (CalledProcessError, OSError):
        return
    for synonym_str, original_str in re.findall(synonyms_template, dump, re.MULTILINE):
        synonym, _ = cleanup_key(synonym_str)
        original, _ = cleanup_key(original_str)
        if synonym != original:
            from_name[original].extend(from_name[synonym])
            from_name[synonym].extend(from_name[original])

# Key names by evdev key code, for when dumpkeys cannot run. The codes are the
# kernel's (linux/input-event-codes.h), the same on every distro and the same
# numbers listen() reads from /dev/input. The names follow a US layout: a code
# is a physical key, so on a German keyboard code 21 ("y") is the key labelled
# Z. Hotkeys work either way, only keys that differ between layouts carry the
# US name. Entries: code -> (plain, with shift).
FALLBACK_KEYS = {
    1: ('esc',), 14: ('backspace',), 15: ('tab',), 28: ('enter',), 57: ('space',),
    29: ('ctrl',), 97: ('ctrl',), 42: ('shift',), 54: ('shift',),
    56: ('alt',), 100: ('alt gr',), 125: ('windows',), 126: ('windows',), 127: ('menu',),
    58: ('caps lock',), 69: ('num lock',), 70: ('scroll lock',),
    99: ('print screen',), 119: ('pause',),
    102: ('home',), 103: ('up',), 104: ('page up',), 105: ('left',), 106: ('right',),
    107: ('end',), 108: ('down',), 109: ('page down',), 110: ('insert',), 111: ('delete',),
    113: ('volume mute',), 114: ('volume down',), 115: ('volume up',),
    163: ('next track',), 164: ('play/pause media',), 165: ('previous track',), 166: ('stop media',),
    2: ('1', '!'), 3: ('2', '@'), 4: ('3', '#'), 5: ('4', '$'), 6: ('5', '%'),
    7: ('6', '^'), 8: ('7', '&'), 9: ('8', '*'), 10: ('9', '('), 11: ('0', ')'),
    12: ('-', '_'), 13: ('=', '+'), 26: ('[', '{'), 27: (']', '}'), 39: (';', ':'),
    40: ("'", '"'), 41: ('`', '~'), 43: ('\\', '|'), 51: (',', '<'), 52: ('.', '>'),
    53: ('/', '?'), 86: ('<', '>'),
    16: ('q', 'Q'), 17: ('w', 'W'), 18: ('e', 'E'), 19: ('r', 'R'), 20: ('t', 'T'),
    21: ('y', 'Y'), 22: ('u', 'U'), 23: ('i', 'I'), 24: ('o', 'O'), 25: ('p', 'P'),
    30: ('a', 'A'), 31: ('s', 'S'), 32: ('d', 'D'), 33: ('f', 'F'), 34: ('g', 'G'),
    35: ('h', 'H'), 36: ('j', 'J'), 37: ('k', 'K'), 38: ('l', 'L'),
    44: ('z', 'Z'), 45: ('x', 'X'), 46: ('c', 'C'), 47: ('v', 'V'), 48: ('b', 'B'),
    49: ('n', 'N'), 50: ('m', 'M'),
}
FALLBACK_KEYS.update({58 + i: ('f{}'.format(i),) for i in range(1, 11)})
FALLBACK_KEYS.update({87: ('f11',), 88: ('f12',)})
FALLBACK_KEYS.update({182 + i: ('f{}'.format(12 + i),) for i in range(1, 13)})
# Keypad, registered as "7" and as "keypad 7" like dumpkeys' KP_ names are.
FALLBACK_KEYPAD = {
    71: '7', 72: '8', 73: '9', 75: '4', 76: '5', 77: '6', 79: '1', 80: '2', 81: '3',
    82: '0', 83: '.', 55: '*', 74: '-', 78: '+', 98: '/', 96: 'enter',
}

def register_fallback_tables():
    for scan_code, names in FALLBACK_KEYS.items():
        register_key((scan_code, ()), normalize_name(names[0]))
        if len(names) > 1:
            register_key((scan_code, ('shift',)), normalize_name(names[1]))
    for scan_code, name in FALLBACK_KEYPAD.items():
        keypad_scan_codes.add(scan_code)
        register_key((scan_code, ()), normalize_name(name))
        register_key((scan_code, ()), 'keypad ' + normalize_name(name))

device = None
init_error = None

def build_device():
    global device
    if device: return
    device = aggregate_devices('kbd')

def init():
    global init_error
    try:
        build_device()
        build_tables()
    except (PermissionError, ValueError, FileNotFoundError, OSError) as e:
        init_error = str(e)
        print(
            "Warning: Keyboard hooking failed: {}. "
            "Add your user to the 'input' group: "
            "'sudo usermod -a -G input $USER' then log out/in.".format(e)
        )

pressed_modifiers = set()

def listen(callback):
    try:
        build_device()
        build_tables()
    except (PermissionError, ValueError, FileNotFoundError, OSError):
        return

    if device is None:
        return

    while True:
        time, type, code, value, device_id = device.read_event()
        if type != EV_KEY:
            continue

        scan_code = code
        event_type = KEY_DOWN if value else KEY_UP # 0 = UP, 1 = DOWN, 2 = HOLD

        pressed_modifiers_tuple = tuple(sorted(pressed_modifiers))
        names = to_name[(scan_code, pressed_modifiers_tuple)] or to_name[(scan_code, ())] or ['unknown']
        name = names[0]
            
        if name in all_modifiers:
            if event_type == KEY_DOWN:
                pressed_modifiers.add(name)
            else:
                pressed_modifiers.discard(name)

        is_keypad = scan_code in keypad_scan_codes
        callback(KeyboardEvent(event_type=event_type, scan_code=scan_code, name=name, time=time, device=device_id, is_keypad=is_keypad, modifiers=pressed_modifiers_tuple))

def direct_event(scan_code, event_type):
    write_event(scan_code, event_type == 0 or event_type == 1)

def write_event(scan_code, is_down):
    build_device()
    device.write_event(EV_KEY, scan_code, int(is_down))

def map_name(name):
    build_tables()
    for entry in from_name[name]:
        yield entry

    parts = name.split(' ', 1)
    if len(parts) > 1 and parts[0] in ('left', 'right'):
        for entry in from_name[parts[1]]:
            yield entry

def press(scan_code):
    write_event(scan_code, True)

def release(scan_code):
    write_event(scan_code, False)

def type_unicode(character):
    codepoint = ord(character)
    hexadecimal = hex(codepoint)[len('0x'):]

    for key in ['ctrl', 'shift', 'u']:
        scan_code, _ = next(map_name(key))
        press(scan_code)

    for key in hexadecimal:
        scan_code, _ = next(map_name(key))
        press(scan_code)
        release(scan_code)

    for key in ['ctrl', 'shift', 'u']:
        scan_code, _ = next(map_name(key))
        release(scan_code)

if __name__ == '__main__':
    def p(e):
        print(e)
    listen(p)
