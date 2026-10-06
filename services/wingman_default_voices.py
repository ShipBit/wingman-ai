"""The Pocket TTS voice each shipped Wingman gets in each spoken language.

Up to 3.2.3 ATC, Computer and Clippy spoke with English voices in every
language, so a German Computer had an English accent. The list in
templates/pocket_tts/default_voices.tsv names a voice recorded in each
language (wingman, language, voice). A Wingman follows it while it still has
a default voice: none, the one its template had up to 3.2.3 (language
"legacy") or the one Wingman last gave it, noted in RECORD_FILE. A voice the
user picked is never replaced, even one that is another language's default.
"""

import copy
import json
import os
from typing import Optional

from services.config_manager import ConfigManager
from services.printr import Printr

DEFAULTS_FILE = os.path.join("templates", "pocket_tts", "default_voices.tsv")
RECORD_FILE = ".default_voices.json"
"""In the configs folder: the voice Wingman last gave each Wingman."""


# The subscription's Azure voices. Both are multilingual, so one pair covers
# every language Wingman speaks, and they are the two voices every plan has.
AZURE_FEMALE_VOICE = "en-US-JennyMultilingualNeural"
AZURE_MALE_VOICE = "en-US-AndrewMultilingualNeural"

# Male Inworld voices, lowercased. Inworld names carry no gender, so it is
# looked up here; a name not listed counts as female, like the template default.
INWORLD_MALE_VOICES = frozenset(
    {
        "alex", "blake", "carter", "clive", "craig", "dennis", "dominus",
        "edward", "hades", "mark", "ronald", "shaun", "theodore", "timothy",
        "matthias", "alain", "mathieu", "etienne", "diego", "miguel", "rafael",
        "gianni", "dmitry", "nikolai", "heitor", "szymon", "wojciech", "erik",
        "lennart", "yichen", "satoshi", "hyunwoo", "seojun",
    }
)


def azure_voice_for_inworld(voice_id: Optional[str]) -> str:
    """The Azure voice of the same gender as the Inworld voice ``voice_id``."""
    if voice_id and voice_id.strip().lower() in INWORLD_MALE_VOICES:
        return AZURE_MALE_VOICE
    return AZURE_FEMALE_VOICE


def _effective(config: dict, defaults: dict, section: str, key: str):
    """A value as the Wingman sees it: its own, else the defaults'."""
    own = (config.get(section) or {}).get(key)
    return own if own is not None else (defaults.get(section) or {}).get(key)


def downgrade_config_to_azure(config: dict, defaults: dict) -> bool:
    """Move one raw config (a Wingman, or the defaults with ``defaults={}``)
    that speaks through the subscription's Inworld to its Azure voices.

    The Azure voice follows the Inworld voice's gender, unless the user picked
    an Azure voice of their own. Returns True when ``config`` changed."""
    if _effective(config, defaults, "features", "tts_provider") != "wingman_pro":
        return False
    if _effective(config, defaults, "wingman_pro", "tts_provider") != "inworld":
        return False
    wingman_pro = config.setdefault("wingman_pro", {})
    wingman_pro["tts_provider"] = "azure"
    azure = dict(wingman_pro.get("azure") or {})
    current = azure.get("voice") or ((defaults.get("wingman_pro") or {}).get("azure") or {}).get("voice")
    if not current or current in (AZURE_FEMALE_VOICE, AZURE_MALE_VOICE):
        azure["voice"] = azure_voice_for_inworld(_effective(config, defaults, "inworld", "voice_id"))
    wingman_pro["azure"] = azure
    return True


def downgrade_inworld_to_azure(config_manager: ConfigManager) -> list[str]:
    """For a plan without Inworld: every Wingman that speaks through the
    subscription's Inworld moves to its Azure voices. Never the other way, so
    an upgrade keeps what the user has. Returns what changed, "defaults" or
    "config/wingman"."""
    changed = []
    try:
        defaults = config_manager.read_config(config_manager.default_config_path) or {}
    except Exception as e:
        Printr().print(f"Could not read the defaults: {e}", server_only=True)
        return changed
    # Wingmen inherit from the defaults as they were before this runs.
    original_defaults = copy.deepcopy(defaults)

    for config_dir in config_manager.get_config_dirs():
        for wingman in config_manager.get_wingmen_configs(config_dir):
            path = os.path.join(config_manager.config_dir, config_dir.directory, wingman.file)
            try:
                config = config_manager.read_config(path) or {}
            except Exception as e:
                Printr().print(f"Could not read {path}: {e}", server_only=True)
                continue
            if downgrade_config_to_azure(config, original_defaults) and config_manager.write_config(path, config):
                changed.append(f"{config_dir.name}/{wingman.name}")

    if downgrade_config_to_azure(defaults, {}) and config_manager.write_config(
        config_manager.default_config_path, defaults
    ):
        config_manager.default_config = config_manager.load_defaults_config(silent_on_error=True)
        changed.insert(0, "defaults")
    return changed


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
