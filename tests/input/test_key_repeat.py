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



def test_a_short_tap_of_the_global_key_stays_out_of_the_client(monkeypatch):
    """The default global key is the period, which people type. A tap must not
    show a recording or a "no speech" warning in the client."""
    import threading

    import wingman_core
    from services.audio import ANY_WINGMAN

    printed = []
    core = WingmanCore.__new__(WingmanCore)
    core.printr = SimpleNamespace(print=lambda text, **kw: printed.append((text, kw)))
    core.listen_controller = SimpleNamespace(
        held_source=None,
        held_wingman=None,
        ptt_down=lambda source, wingman: setattr(core.listen_controller, "held_source", source)
        or setattr(core.listen_controller, "held_wingman", wingman)
        or True,
        ptt_up=lambda source: True,
    )
    core.voice_gate = SimpleNamespace(last_peak=0.0, last_best_score=0.0, params=SimpleNamespace(threshold=0.5))
    core._global_ptt_timer = None
    core._global_ptt_announced = False
    monkeypatch.setattr(wingman_core, "GLOBAL_PTT_ANNOUNCE_S", 60)

    core._global_ptt_down("key:52:0")
    core._ptt_up("key:52:0")
    core._on_ptt_dropped(ANY_WINGMAN)
    assert all(kw.get("server_only") for _, kw in printed)

    # Held long enough: announced, and its end shows too.
    printed.clear()
    core._global_ptt_down("key:52:0")
    core._announce_global_ptt("key:52:0")
    core._ptt_up("key:52:0")
    assert [t for t, kw in printed if not kw.get("server_only")] == ["Recording started", "Recording stopped ()"]
