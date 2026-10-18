"""Which way a screenshot is taken: the desktop's tool under Wayland, mss
everywhere else. The tools themselves are not run."""

import pytest
from PIL import Image

import services.screen_capture as screen

SHOT = Image.new("RGB", (40, 30), "white")


@pytest.fixture
def wayland(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    used = []
    monkeypatch.setattr(screen, "_with_file", lambda command: used.append(command("/x.png")[0]) or SHOT)
    monkeypatch.setattr(screen, "_portal", lambda: used.append("portal") or SHOT)
    return used


def tools(monkeypatch, *installed):
    monkeypatch.setattr(screen.shutil, "which", lambda name: name if name in installed else None)


def test_kde_takes_the_shot_with_spectacle(monkeypatch, wayland):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    tools(monkeypatch, "spectacle", "grim")

    screen.capture(1)

    assert wayland == ["spectacle"]


def test_wlroots_desktops_take_it_with_grim(monkeypatch, wayland):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "Hyprland")
    tools(monkeypatch, "grim")

    screen.capture(1)

    assert wayland == ["grim"]


@pytest.mark.parametrize("desktop", ["GNOME", "KDE"])
def test_otherwise_the_portal_asks_the_desktop(monkeypatch, wayland, desktop):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", desktop)
    tools(monkeypatch, "grim")

    screen.capture(1)

    assert wayland == ["portal"]


def test_a_region_is_cut_from_the_wayland_shot(monkeypatch, wayland):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")

    image = screen.capture(1, {"left": 10, "top": 5, "width": 20, "height": 15})

    assert image.size == (20, 15)


def test_without_wayland_mss_takes_it(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.setattr(screen, "_mss", lambda display, region: ("mss", display, region))

    assert screen.capture(2) == ("mss", 2, None)
