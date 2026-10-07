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

from api.enums import TtsVoiceGender
from api.interface import VoiceInfo
from services.config_manager import ConfigManager
from services.printr import Printr

DEFAULTS_FILE = os.path.join("templates", "pocket_tts", "default_voices.tsv")
RECORD_FILE = ".default_voices.json"
"""In the configs folder: the voice Wingman last gave each Wingman."""


# The subscription's Azure voices a plan always includes: one female and one
# male per main market (German, French, Spanish) and the two multilingual
# ones for everything else. Same list as `plan_voices` for Free (2026-10-07).
AZURE_FEMALE_VOICE = "en-US-JennyMultilingualNeural"
AZURE_MALE_VOICE = "en-US-AndrewMultilingualNeural"
AZURE_VOICES_BY_LANGUAGE = {
    "de": ("de-DE-KatjaNeural", "de-DE-ConradNeural"),
    "fr": ("fr-FR-DeniseNeural", "fr-FR-HenriNeural"),
    "es": ("es-ES-ElviraNeural", "es-ES-AlvaroNeural"),
}

# Male Inworld voices, lowercased. Inworld names carry no gender, so it is
# looked up here; a name not listed counts as female, like the template default.
INWORLD_MALE_VOICES = frozenset(
    {
        "alex", "blake", "carter", "clive", "craig", "dennis", "dominus",
        "edward", "hades", "mark", "ronald", "shaun", "theodore", "timothy",
        "matthias", "alain", "mathieu", "etienne", "diego", "miguel", "rafael",
        "gianni", "dmitry", "nikolai", "heitor", "szymon", "wojciech", "erik",
        "lennart", "yichen", "satoshi", "hyunwoo", "seojun",
        "alvaro",
        "bastian", "borja", "bruno", "cuauhtemoc", "curro", "fabian", "gonzalo",
        "hendrik", "ignacio", "inigo", "joaquin", "josef", "kilian", "mateo",
        "mauricio", "maximiliano", "nacho", "reinhard", "ruben", "salvador", "sergio",
        "tobias", "étienne",
    }
)

# Inworld voices made for one of our main markets, lowercased (live list of
# 2026-10-07). A German Wingman keeps a German voice when it moves to Azure.
INWORLD_VOICES_BY_LANGUAGE = {
    "de": frozenset({
        "annika", "bastian", "birgit", "carina", "fabian", "franziska", "heidi",
        "heike", "hendrik", "johanna", "josef", "kilian", "matthias", "reinhard",
        "sabine", "steffi", "tobias",
    }),
    "fr": frozenset({
        "alain", "hélène", "helene", "mathieu", "étienne", "etienne",
    }),
    "es": frozenset({
        "alvaro", "borja", "bruno", "camila", "citlali", "cuauhtemoc", "curro", "diego",
        "gonzalo", "guadalupe", "ignacio", "inigo", "inmaculada", "itzel", "joaquin",
        "lupita", "marta", "mateo", "mauricio", "maximiliano", "mayte", "mercedes",
        "miguel", "nacho", "paloma", "pilar", "rafael", "rocio", "ruben", "salvador",
        "sergio", "sofia", "ximena", "xochitl",
    }),
}


def azure_voice_for_inworld(voice_id) -> str:
    """The Azure voice closest to the Inworld voice ``voice_id``: same language
    when it is one of our main markets, same gender, Jenny for the unknown."""
    name = str(voice_id).strip().lower() if voice_id else ""
    male = name in INWORLD_MALE_VOICES
    for language, names in INWORLD_VOICES_BY_LANGUAGE.items():
        if name in names:
            female_voice, male_voice = AZURE_VOICES_BY_LANGUAGE[language]
            return male_voice if male else female_voice
    return AZURE_MALE_VOICE if male else AZURE_FEMALE_VOICE


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
    # The 3.2.6 migration already wrote the Azure counterpart of each Wingman's
    # Inworld voice, and a user may have picked one since; both are kept. Only
    # a Wingman without a voice of its own gets one derived now, so a male
    # Wingman inheriting the defaults does not end up with the defaults' Jenny.
    if not azure.get("voice"):
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


def _base_language(language) -> str:
    """"de-DE", "de_DE" and "DE" all become "de"."""
    return str(language).replace("_", "-").split("-")[0].strip().lower()


def pick_free_voice(
    requested: Optional[VoiceInfo], free: list[VoiceInfo]
) -> Optional[VoiceInfo]:
    """The free voice closest to ``requested``: same language and gender, then
    same language, then same gender, then simply the first free one."""
    if not free:
        return None
    if requested is None:
        return free[0]
    languages = {_base_language(lang) for lang in requested.languages or [] if lang}
    gender = requested.gender

    def same_language(voice: VoiceInfo) -> bool:
        return bool(languages) and any(
            _base_language(lang) in languages for lang in voice.languages or [] if lang
        )

    def same_gender(voice: VoiceInfo) -> bool:
        return gender not in (None, TtsVoiceGender.UNKNOWN) and voice.gender == gender

    for matches in (
        lambda v: same_language(v) and same_gender(v),
        same_language,
        same_gender,
    ):
        for voice in free:
            if matches(voice):
                return voice
    return free[0]


def _subscription_voice(config: dict, defaults: dict) -> tuple[Optional[str], Optional[str]]:
    """(sub-provider, voice id) a config speaks with through the subscription,
    or (None, None) when it does not speak through the subscription."""
    if _effective(config, defaults, "features", "tts_provider") != "wingman_pro":
        return None, None
    provider = _effective(config, defaults, "wingman_pro", "tts_provider")
    if provider == "inworld":
        return provider, _effective(config, defaults, "inworld", "voice_id")
    if provider == "azure":
        own = ((config.get("wingman_pro") or {}).get("azure") or {}).get("voice")
        inherited = ((defaults.get("wingman_pro") or {}).get("azure") or {}).get("voice")
        return provider, own if own is not None else inherited
    return provider, None


def _set_subscription_voice(config: dict, provider: str, voice_id: str) -> None:
    if provider == "inworld":
        config["inworld"] = {**(config.get("inworld") or {}), "voice_id": voice_id}
    else:
        wingman_pro = config.setdefault("wingman_pro", {})
        wingman_pro["azure"] = {**(wingman_pro.get("azure") or {}), "voice": voice_id}


def _replace_locked_voice(
    config: dict, defaults: dict, voices_by_provider: dict[str, list[VoiceInfo]]
) -> Optional[str]:
    """Write a free voice into ``config`` when the subscription voice it speaks
    with is locked for the plan. Returns "old → new", or None when nothing
    changed. A voice missing from the list is left alone: the list may be
    incomplete, and only the backend knows it is locked."""
    provider, voice_id = _subscription_voice(config, defaults)
    voices = voices_by_provider.get(provider or "") or []
    if not voice_id or not voices:
        return None
    wanted = str(voice_id).strip().lower()
    current = next((v for v in voices if (v.id or "").lower() == wanted), None)
    if current is None or not current.locked:
        return None
    replacement = pick_free_voice(current, [v for v in voices if not v.locked and v.id])
    if replacement is None or replacement.id == voice_id:
        return None
    _set_subscription_voice(config, provider, replacement.id)
    return f"{current.name or current.id} → {replacement.name or replacement.id}"


def rewrite_locked_voices(
    config_manager: ConfigManager, voices_by_provider: dict[str, list[VoiceInfo]]
) -> list[str]:
    """Every Wingman that speaks through the subscription with a voice its plan
    does not include gets the closest free voice written into its config, so
    the config shows what the backend really plays. ``voices_by_provider`` maps
    "azure"/"inworld" to the plan's voice list; a missing or empty list skips
    that provider. Returns "defaults: old → new" / "config/wingman: old → new".

    The defaults go first: a Wingman inheriting their voice is fixed with
    them. Wingmen are then checked against the fixed defaults, so only those
    with a locked voice of their own (or a provider the defaults do not use)
    are written."""
    changed = []
    try:
        defaults = config_manager.read_config(config_manager.default_config_path) or {}
    except Exception as e:
        Printr().print(f"Could not read the defaults: {e}", server_only=True)
        return changed

    change = _replace_locked_voice(defaults, {}, voices_by_provider)
    if change and config_manager.write_config(config_manager.default_config_path, defaults):
        config_manager.default_config = config_manager.load_defaults_config(silent_on_error=True)
        changed.append(f"defaults: {change}")

    for config_dir in config_manager.get_config_dirs():
        for wingman in config_manager.get_wingmen_configs(config_dir):
            path = os.path.join(config_manager.config_dir, config_dir.directory, wingman.file)
            try:
                config = config_manager.read_config(path) or {}
            except Exception as e:
                Printr().print(f"Could not read {path}: {e}", server_only=True)
                continue
            change = _replace_locked_voice(config, defaults, voices_by_provider)
            if change and config_manager.write_config(path, config):
                changed.append(f"{config_dir.name}/{wingman.name}: {change}")
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
