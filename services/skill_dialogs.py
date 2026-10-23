"""Remembers which skill dialogs with a `once` key were already shown.

A skill shows a dialog with `self.wingman.ui.show_dialog(..., once="key")`
when the user should see it a single time, not on every start. The keys live
in one small file next to the versioned folders, so an update does not show
them again.
"""

import json
from os import path

from services.file import get_users_dir

FILE_NAME = "shown_dialogs.json"


def _file() -> str:
    return path.join(get_users_dir(), FILE_NAME)


def was_shown(key: str) -> bool:
    try:
        with open(_file(), encoding="utf-8") as f:
            return key in json.load(f)
    except (OSError, ValueError, TypeError):
        return False


def mark_shown(key: str) -> None:
    try:
        with open(_file(), encoding="utf-8") as f:
            keys = json.load(f)
        if not isinstance(keys, list):
            keys = []
    except (OSError, ValueError):
        keys = []
    if key not in keys:
        keys.append(key)
        with open(_file(), "w", encoding="utf-8") as f:
            json.dump(keys, f)
