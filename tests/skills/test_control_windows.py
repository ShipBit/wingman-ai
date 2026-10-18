"""Control Windows on every OS: what does not need a desktop to check."""

from skills.control_windows.desktop.base import half, matches
from skills.control_windows.desktop.linux import _desktop_entry


def test_a_half_of_the_area_for_each_position():
    area = (100, 50, 1001, 801)

    assert half("left", *area) == (100, 50, 500, 801)
    assert half("right", *area) == (600, 50, 501, 801)
    assert half("top", *area) == (100, 50, 1001, 400)
    assert half("bottom", *area) == (100, 450, 1001, 401)


def test_a_name_matches_an_app_or_title_in_part_and_any_case():
    assert matches("calc", "Rechner", "Calculator")
    assert matches(" Steam ", "steam")
    assert not matches("", "anything")
    assert not matches("notes", None, "")


def test_a_menu_entry_gives_its_name_and_command_without_field_codes(tmp_path):
    entry = tmp_path / "game.desktop"
    entry.write_text(
        "[Desktop Entry]\nType=Application\nName=Star Citizen Launcher\n"
        'Exec=env WINEPREFIX="/home/me/wine" launcher --profile main %U\n',
        encoding="utf-8",
    )

    assert _desktop_entry(entry) == (
        "Star Citizen Launcher",
        ["env", "WINEPREFIX=/home/me/wine", "launcher", "--profile", "main"],
    )


def test_hidden_menu_entries_are_not_started(tmp_path):
    entry = tmp_path / "helper.desktop"
    entry.write_text(
        "[Desktop Entry]\nType=Application\nName=Helper\nExec=helper\nNoDisplay=true\n",
        encoding="utf-8",
    )

    assert _desktop_entry(entry) is None
