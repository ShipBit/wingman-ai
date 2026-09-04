"""Helpers shared by the standalone keybinding maintenance scripts."""

from pathlib import Path
import re
from typing import Optional


def version_sort_key(version: str) -> tuple[int, int]:
    match = re.fullmatch(r"R(\d+)_(\d+)", version)
    if not match:
        return (-1, -1)
    return int(match.group(1)), int(match.group(2))


def available_versions(script_dir: Path) -> list[str]:
    return sorted(
        (
            item.name
            for item in script_dir.iterdir()
            if item.is_dir()
            and version_sort_key(item.name) != (-1, -1)
            and (item / "sc_all_keybindings.json").is_file()
        ),
        key=version_sort_key,
    )


def resolve_version(script_dir: Path, version: Optional[str] = None) -> str:
    """Return an explicit version or the newest generated local cache."""
    if version:
        return version
    versions = available_versions(script_dir)
    if not versions:
        raise FileNotFoundError(
            "No generated SC keybinding cache found. Start Wingman once to create one."
        )
    return versions[-1]
