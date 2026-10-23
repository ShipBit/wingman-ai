"""The info panel tools every Wingman with the HUD's info switch on has."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from hud_server.constants import GROUP_INFO
from services.hud_service import HudService
from services.hud_tools import run_hud_tool


@pytest.fixture
def hud(monkeypatch):
    service = MagicMock(available=True)
    service.info_items.return_value = [{"title": "Mining Yield", "description": "", "added_at": 1}]
    monkeypatch.setattr(HudService, "_instance", service)
    return service


def _run(name, **args):
    return asyncio.run(run_hud_tool(SimpleNamespace(name="Computer", jev=None), name, args))


def test_reading_shows_every_panel_with_its_state(hud, monkeypatch):
    monkeypatch.setattr("services.hud_tools.time.time", lambda: 1000.0)
    hud.info_items.return_value = [
        {"title": "Cargo", "description": "| Gold | 12 SCU |", "added_at": 900, "added_by": "Computer"},
        {"title": "Quantum", "description": "", "added_at": 950, "is_progress": True,
         "is_timer": True, "timer_start": 990, "timer_duration": 30, "added_by": "ATC"},
        {"title": "Mining", "description": "Rock 3", "added_at": 960, "is_progress": True,
         "progress_current": 65, "progress_maximum": 100},
    ]

    answer = _run("hud_read_info")

    assert answer == (
        "3 panel(s) on the HUD info panel, oldest first:\n\n"
        "### Cargo (added by you)\n| Gold | 12 SCU |\n\n"
        "### Quantum (countdown: 20 s of 30 s left, added by ATC)\n\n"
        "### Mining (progress: 65 of 100)\nRock 3"
    )


def test_reading_one_panel_by_its_title(hud):
    hud.info_items.return_value = [
        {"title": "Cargo", "description": "Gold", "added_at": 1},
        {"title": "Mining Yield", "description": "Rock 3", "added_at": 2},
    ]

    answer = _run("hud_read_info", title="mining yield")

    assert "Rock 3" in answer and "Gold" not in answer


def test_a_huge_panel_is_cut(hud):
    hud.info_items.return_value = [{"title": "Routes", "description": "x" * 10_000, "added_at": 1}]

    answer = _run("hud_read_info")

    assert answer.endswith("… (cut)") and len(answer) < 3000


def test_set_info_puts_a_panel_on_the_shared_info_panel(hud):
    _run("hud_set_info", title="Cargo", markdown="| A | B |", duration_seconds=0)

    hud.add_info.assert_called_once_with(GROUP_INFO, "Cargo", "| A | B |", duration=None, added_by="Computer")


def test_a_countdown_wins_over_a_progress_bar(hud):
    _run("hud_show_progress", title="Quantum", timer_seconds=30, current=5)

    hud.show_timer.assert_called_once_with(GROUP_INFO, "Quantum", 30.0, text="", added_by="Computer")
    hud.show_progress.assert_not_called()


def test_removing_an_unknown_panel_names_the_ones_there(hud):
    answer = _run("hud_remove_info", title="Fuel")

    assert "Mining Yield" in answer
    hud.remove_info.assert_not_called()


def test_removing_another_wingmans_panel_says_whose_it_was(hud):
    hud.info_items.return_value = [{"title": "Cargo", "description": "", "added_at": 1, "added_by": "ATC"}]

    assert _run("hud_remove_info", title="Cargo") == "Removed 'Cargo' from the HUD. ATC had added it."


def test_the_tools_say_so_when_the_hud_is_off(hud):
    hud.available = False

    assert _run("hud_set_info", title="Cargo", markdown="x") == "The HUD is not running."
    hud.add_info.assert_not_called()
