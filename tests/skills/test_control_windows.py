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


def test_an_app_starts_from_its_exec_line_when_gio_cannot_launch_it(tmp_path, monkeypatch):
    from skills.control_windows.desktop import linux

    (tmp_path / "steam.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Steam\nExec=steam %U\n", encoding="utf-8"
    )
    started = []
    monkeypatch.setattr(linux, "_APP_FOLDERS", [str(tmp_path)])
    monkeypatch.setattr(linux.shutil, "which", lambda tool: "/usr/bin/gio")
    monkeypatch.setattr(linux.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 1})())
    monkeypatch.setattr(linux.subprocess, "Popen", lambda command, **k: started.append(command))

    assert linux.LinuxDesktop.open_app(object.__new__(linux.LinuxDesktop), "steam")
    assert started == [["steam"]]
