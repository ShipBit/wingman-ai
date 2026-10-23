"""The bridge picks the HUD backend for the OS Core runs on."""

import pytest

import hud_server.platform as hud_platform
from hud_server.platform import (
    HudPlatformError,
    Monitor,
    OsFamily,
    create_backend,
    current_os,
)
from tests.support import FakeHudBackend


@pytest.mark.parametrize(
    "system, expected",
    [
        ("Darwin", OsFamily.MACOS),
        ("FreeBSD", None),
    ],
)
def test_the_os_is_recognised(monkeypatch, system, expected):
    monkeypatch.setattr(hud_platform.platform, "system", lambda: system)

    assert current_os() == expected


def test_linux_without_a_display_keeps_the_hud_off_and_says_why(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)

    backend = create_backend(OsFamily.LINUX)

    assert not backend.supported
    assert backend.os == OsFamily.LINUX
    assert backend.unsupported_reason
    assert backend.create_window("HUD", 0, 0, 100, 100) is None
    with pytest.raises(HudPlatformError):
        backend.start()


def test_a_backend_that_fails_to_load_turns_the_hud_off_instead_of_failing(monkeypatch):
    monkeypatch.setitem(
        hud_platform.BACKENDS, OsFamily.LINUX, ("hud_server.platform.not_there", "Backend")
    )

    backend = create_backend(OsFamily.LINUX)

    assert not backend.supported
    assert "failed to load" in backend.unsupported_reason


def test_the_hud_screen_falls_back_to_the_last_monitor():
    left = Monitor(0, 0, 2560, 1440, True)
    right = Monitor(2560, 0, 1920, 1080)
    backend = FakeHudBackend([left, right])

    assert backend.monitor(1) == left
    assert backend.monitor(2) == right
    assert backend.monitor(3) == right


def test_without_any_monitor_the_hud_still_gets_a_screen():
    monitor = FakeHudBackend([]).monitor(1)

    assert monitor.width > 0 and monitor.height > 0
