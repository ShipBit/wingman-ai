"""The Pocket TTS voice each shipped Wingman gets in each spoken language.

Up to 3.2.3 ATC, Computer and Clippy spoke with English voices in every
language, so a German Computer had an English accent. The list in
templates/pocket_tts/default_voices.tsv names a voice recorded in each
language (wingman, language, voice). A Wingman follows it while it still has
a default voice: none, the one its template had up to 3.2.3 (language
"legacy") or the one Wingman last gave it, noted in RECORD_FILE. A voice the
user picked is never replaced, even one that is another language's default.
"""

import json
import os
from typing import Optional

from services.config_manager import ConfigManager
from services.printr import Printr

DEFAULTS_FILE = os.path.join("templates", "pocket_tts", "default_voices.tsv")
RECORD_FILE = ".default_voices.json"
"""In the configs folder: the voice Wingman last gave each Wingman."""


def load_default_voices(app_root: str) -> dict[str, dict[str, str]]:
    """{wingman file name: {language: voice}}."""
    path = os.path.join(app_root, DEFAULTS_FILE)
    table: dict[str, dict[str, str]] = {}
    if not os.path.isfile(path):
        return table
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            cells = [c.strip() for c in line.rstrip("\n").split("\t")]
            if len(cells) >= 3 and all(cells[:3]):
                table.setdefault(cells[0], {})[cells[1]] = cells[2]
    return table


def default_voice_for(table: dict[str, dict[str, str]], wingman: str, language: str) -> Optional[str]:
    return table.get(wingman, {}).get(language)


def apply_default_voices(config_manager: ConfigManager, app_root: str, language: str) -> list[str]:
    """Give every shipped Wingman that still has a default voice the one for
    ``language``. Returns "config/wingman" of each Wingman changed."""
    table = load_default_voices(app_root)
    record_path = os.path.join(config_manager.config_dir, RECORD_FILE)
    record = _read(record_path)
    changed = []
    for config_dir in config_manager.get_config_dirs():
        for wingman in config_manager.get_wingmen_configs(config_dir):
            voices = table.get(wingman.name)
            wanted = voices.get(language) if voices else None
            if not wanted:
                continue
            key = f"{config_dir.directory}/{wingman.file}"
            path = os.path.join(config_manager.config_dir, config_dir.directory, wingman.file)
            try:
                config = config_manager.read_config(path) or {}
            except Exception as e:
                Printr().print(f"Could not read {path}: {e}", server_only=True)
                continue
            pocket = config.get("pocket_tts") or {}
            current = pocket.get("voice")
            # No voice of its own: it spoke with the global default (Clippy).
            if current and current not in (voices.get("legacy"), record.get(key)):
                continue
            if current == wanted:
                record[key] = wanted
                continue
            config["pocket_tts"] = {**pocket, "voice": wanted}
            if config_manager.write_config(path, config):
                record[key] = wanted
                changed.append(f"{config_dir.name}/{wingman.name}")
    _write(record_path, record)
    return changed


def _read(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: str, data: dict) -> None:
    if not data or _read(path) == data:
        return
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        Printr().print(f"Could not write {path}: {e}", server_only=True)
