"""The bridge picks the HUD backend for the OS Core runs on."""

import sys

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
        ("Windows", OsFamily.WINDOWS),
        ("Linux", OsFamily.LINUX),
        ("Darwin", OsFamily.MACOS),
        ("FreeBSD", None),
    ],
)
def test_the_os_is_recognised(monkeypatch, system, expected):
    monkeypatch.setattr(hud_platform.platform, "system", lambda: system)

    assert current_os() == expected


def test_linux_has_a_backend_that_keeps_the_hud_off():
    backend = create_backend(OsFamily.LINUX)

    assert not backend.supported
    assert backend.os == OsFamily.LINUX
    assert backend.unsupported_reason
    assert backend.create_window("HUD", 0, 0, 100, 100) is None
    with pytest.raises(HudPlatformError):
        backend.start()


def test_the_macos_backend_runs_only_on_macos():
    backend = create_backend(OsFamily.MACOS)

    assert backend.os == OsFamily.MACOS
    assert backend.supported == (sys.platform == "darwin")


def test_an_unknown_os_has_no_hud(monkeypatch):
    monkeypatch.setattr(hud_platform.platform, "system", lambda: "FreeBSD")

    backend = create_backend()

    assert not backend.supported
    assert "FreeBSD" in backend.unsupported_reason


def test_a_backend_that_fails_to_load_turns_the_hud_off_instead_of_failing(monkeypatch):
    monkeypatch.setitem(
        hud_platform.BACKENDS, OsFamily.LINUX, ("hud_server.platform.not_there", "Backend")
    )

    backend = create_backend(OsFamily.LINUX)

    assert not backend.supported
    assert "failed to load" in backend.unsupported_reason


def test_the_windows_backend_runs_only_on_windows():
    assert create_backend(OsFamily.WINDOWS).supported == (sys.platform == "win32")


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
