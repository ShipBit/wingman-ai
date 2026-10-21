"""Where Star Citizen is installed: what a picked folder stands for, what is in
it, and the search that must come back empty, not crash, without the game."""

from services.star_citizen import game_folder
from services.star_citizen.game_folder import (
    find_game_folder,
    inspect_game_folder,
    launcher_log_folders,
    normalize_game_path,
)


def test_an_environment_folder_stands_for_the_folder_above_it():
    assert normalize_game_path("D:\\Games\\StarCitizen\\LIVE") == "D:\\Games\\StarCitizen"
    assert normalize_game_path("/games/StarCitizen/ptu/") == "/games/StarCitizen"


def test_a_game_log_stands_for_the_folder_above_its_environment():
    assert normalize_game_path('"D:\\StarCitizen\\LIVE\\Game.log"') == "D:\\StarCitizen"


def test_a_folder_with_live_in_it_is_the_game(tmp_path):
    (tmp_path / "LIVE").mkdir()
    (tmp_path / "PTU").mkdir()
    folder = inspect_game_folder(str(tmp_path))
    assert folder.exists and folder.environments == ["LIVE", "PTU"]


def test_a_missing_or_empty_path_is_not_found(tmp_path):
    assert not inspect_game_folder(str(tmp_path / "nope")).exists
    assert not inspect_game_folder("").exists


def test_the_launcher_log_names_the_folder_newest_first():
    log = (
        "[Launcher::launch] Launching Star Citizen LIVE from "
        "(C:\\Program Files\\Roberts Space Industries\\StarCitizen\\LIVE)\n"
        '{"info":"installDir","value":"E:\\\\Games\\\\StarCitizen\\\\PTU"}\n'
        "[Launcher::launch] Launching Star Citizen LIVE from "
        "(C:\\Program Files\\Roberts Space Industries\\StarCitizen\\LIVE)\n"
    )
    assert launcher_log_folders(log) == [
        "C:\\Program Files\\Roberts Space Industries\\StarCitizen",
        "E:\\Games\\StarCitizen",
    ]


def test_the_first_candidate_with_the_game_wins(tmp_path, monkeypatch):
    game = tmp_path / "StarCitizen"
    (game / "LIVE").mkdir(parents=True)
    candidates = [str(tmp_path / "missing"), str(tmp_path), str(game)]
    monkeypatch.setattr(game_folder, "_candidates", lambda: iter(candidates))
    assert find_game_folder() == str(game)


def test_windows_without_the_game_or_a_launcher_log_finds_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(game_folder.platform, "system", lambda: "Windows")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(game_folder, "_fixed_drives", lambda: ["C", "D"])
    assert find_game_folder() is None
