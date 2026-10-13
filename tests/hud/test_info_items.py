"""What the HUD server reports as on the info panel: who added a panel, and
nothing the overlay has already closed."""

import time

from hud_server.hud_manager import HudManager


def test_a_panel_remembers_who_added_it():
    manager = HudManager()
    manager.add_item("wingman_info", "persistent", "Cargo", "Gold", added_by="ATC")
    manager.show_timer("wingman_info", "persistent", "Quantum", 30, added_by="Computer")

    assert [(i["title"], i["added_by"]) for i in manager.get_items("wingman_info", "persistent")] == [
        ("Cargo", "ATC"), ("Quantum", "Computer"),
    ]


def test_a_finished_countdown_that_closes_itself_is_gone():
    manager = HudManager()
    manager.show_timer("wingman_info", "persistent", "Done", 5, initial_progress=10)
    manager.show_timer("wingman_info", "persistent", "Stays", 5, initial_progress=10, auto_close=False)

    assert [i["title"] for i in manager.get_items("wingman_info", "persistent")] == ["Stays"]


def test_a_full_progress_bar_that_closes_itself_is_gone():
    manager = HudManager()
    manager.show_progress("wingman_info", "persistent", "Download", 100, 100, auto_close=True)
    manager.show_progress("wingman_info", "persistent", "Mining", 40, 100, auto_close=True)

    assert [i["title"] for i in manager.get_items("wingman_info", "persistent")] == ["Mining"]


def test_a_running_countdown_is_still_there():
    manager = HudManager()
    manager.show_timer("wingman_info", "persistent", "Quantum", 30)

    [item] = manager.get_items("wingman_info", "persistent")
    assert item["timer_start"] <= time.time()
