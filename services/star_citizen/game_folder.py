"""Where Star Citizen is installed.

The StarCitizen folder holds one folder per environment (LIVE, PTU, ...).
The log reader reads `<folder>/<environment>/Game.log`, and later features
such as the key bindings read from the same place, so the folder is one
setting (`settings.star_citizen.game_path`) and not one per feature.

`find_game_folder()` looks where the game usually is. It reads the RSI
Launcher's log first: the launcher writes the folder it starts the game from,
so it knows an install on another drive. After that it tries the usual
folders on every fixed drive. Every step swallows its own errors: a machine
without the game, without a launcher log or without drive letters (macOS,
Linux) gets None.
"""

from __future__ import annotations

import os
import platform
import re
from pathlib import Path
from typing import Iterable, Optional

from api.interface import StarCitizenGameFolder

DEFAULT_GAME_PATH = "C:\\Program Files\\Roberts Space Industries\\StarCitizen"
ENVIRONMENTS = ("LIVE", "PTU", "EPTU", "HOTFIX", "TECH-PREVIEW")

_LAUNCHER_LOGS = ("rsilauncher/logs/log.log", "rsilauncher/log.log")
_LAUNCHER_LOG_TAIL = 4 * 1024 * 1024
"""The newest bytes of the log are enough, and the log can grow large."""
_ENV_PATTERN = "|".join(re.escape(env) for env in ENVIRONMENTS)
_LOGGED_FOLDER = re.compile(
    rf"([A-Za-z]:[\\/][^\"'<>|\r\n]*?[\\/]StarCitizen)[\\/]+(?:{_ENV_PATTERN})\b",
    re.IGNORECASE,
)
_USUAL_FOLDERS = (
    "Program Files\\Roberts Space Industries\\StarCitizen",
    "Roberts Space Industries\\StarCitizen",
    "Games\\Roberts Space Industries\\StarCitizen",
    "Games\\StarCitizen",
    "StarCitizen",
)
_LINUX_FOLDERS = (
    # The LUG helper's default prefix and a plain Wine prefix.
    "Games/star-citizen/drive_c/Program Files/Roberts Space Industries/StarCitizen",
    ".wine/drive_c/Program Files/Roberts Space Industries/StarCitizen",
)


def normalize_game_path(value: str) -> str:
    """The StarCitizen folder from what a user picked: the folder itself, an
    environment inside it, or a Game.log in one."""
    text = str(value or "").strip().strip('"').rstrip("\\/")
    if not text:
        return ""
    parts = re.split(r"[\\/]", text)
    if parts[-1].lower() == "game.log":
        parts = parts[:-1]
    if len(parts) > 1 and parts[-1].upper() in ENVIRONMENTS:
        parts = parts[:-1]
    return ("\\" if "\\" in text else "/").join(parts)


def inspect_game_folder(game_path: str) -> StarCitizenGameFolder:
    """What is in the folder. Never raises."""
    folder = Path(game_path) if game_path else None
    try:
        exists = bool(folder) and folder.is_dir()
    except OSError:
        exists = False
    environments = []
    if exists:
        for env in ENVIRONMENTS:
            try:
                if (folder / env).is_dir():
                    environments.append(env)
            except OSError:
                continue
    return StarCitizenGameFolder(
        path=game_path, exists=exists, environments=environments
    )


def looks_like_game_folder(game_path: str) -> bool:
    return bool(inspect_game_folder(game_path).environments)


def find_game_folder() -> Optional[str]:
    """The first folder that has at least one environment in it, or None."""
    for candidate in _candidates():
        try:
            if looks_like_game_folder(candidate):
                return candidate
        except Exception:
            continue
    return None


def _candidates() -> Iterable[str]:
    system = platform.system()
    if system == "Windows":
        yield from _launcher_log_folders(os.environ.get("APPDATA"))
        for drive in _fixed_drives():
            for folder in _USUAL_FOLDERS:
                yield f"{drive}:\\{folder}"
    elif system == "Linux":
        home = Path.home()
        for folder in _LINUX_FOLDERS:
            yield str(home / folder)


def _launcher_log_folders(appdata: Optional[str]) -> list[str]:
    """Folders the RSI Launcher started the game from, newest first."""
    if not appdata:
        return []
    found: list[str] = []
    for log in _LAUNCHER_LOGS:
        try:
            path = Path(appdata) / log
            with path.open("rb") as file:
                file.seek(max(0, path.stat().st_size - _LAUNCHER_LOG_TAIL))
                text = file.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        found.extend(launcher_log_folders(text))
    return list(dict.fromkeys(found))


def launcher_log_folders(text: str) -> list[str]:
    """StarCitizen folders named in a launcher log, newest first. JSON in the
    log escapes backslashes, so those are folded first."""
    text = text.replace("\\\\", "\\")
    folders = [
        match.group(1).replace("/", "\\") for match in _LOGGED_FOLDER.finditer(text)
    ]
    return list(dict.fromkeys(reversed(folders)))


def _fixed_drives() -> list[str]:
    """Letters of the local hard drives. Network and removable drives are
    left out: looking at a disconnected network drive can take seconds."""
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        mask = kernel32.GetLogicalDrives()
        drives = []
        for index in range(26):
            if not mask & (1 << index):
                continue
            letter = chr(ord("A") + index)
            if kernel32.GetDriveTypeW(f"{letter}:\\") == 3:  # DRIVE_FIXED
                drives.append(letter)
        return drives
    except Exception:
        return ["C"]
