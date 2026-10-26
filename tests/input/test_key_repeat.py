"""Holding a key makes the OS repeat its key-down. A held mute key toggled the
microphone on every repeat."""

from types import SimpleNamespace

from wingman_core import WingmanCore


def key(kind):
    return SimpleNamespace(event_type=kind, scan_code=42, is_extended=False, name="shift")


def test_a_repeated_key_down_presses_once():
    core = WingmanCore.__new__(WingmanCore)
    core.key_events = {}
    presses, releases = [], []
    core.on_press = lambda key=None, **_: presses.append(key)
    core.on_release = lambda key=None, **_: releases.append(key)

    core.on_key(key("down"))
    core.on_key(key("down"))
    core.on_key(key("down"))
    assert len(presses) == 1

    core.on_key(key("up"))
    assert len(releases) == 1 and core.key_events == {}

    core.on_key(key("down"))
    assert len(presses) == 2
