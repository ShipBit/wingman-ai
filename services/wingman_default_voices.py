"""The Pocket TTS voice each shipped Wingman gets in each spoken language.

Up to 3.2.3 ATC, Computer and Clippy spoke with English voices in every
language, so a German Computer had an English accent. The list in
templates/pocket_tts/default_voices.tsv names a voice recorded in each
language (wingman, language, voice). A Wingman follows it while it still has
a default voice: none, the one its template had up to 3.2.3 (language
"legacy") or the one Wingman last gave it, noted in RECORD_FILE. A voice the
user picked is never replaced, even one that is another language's default.

The subscription's Azure voice follows the language the same way, from
templates/azure/default_voices.tsv (same format, plus a "*" row per Wingman
for every language without one) and its own record, AZURE_RECORD_FILE.

Pocket TTS stays the default for English. For every other language a Wingman
still on Pocket TTS with a default voice moves to the subscription's Azure
once (switch_to_azure_for_language); switching back to English keeps it there.
"""

import copy
import json
import os
from typing import Optional

import yaml

from api.enums import TtsVoiceGender
from api.interface import VoiceInfo
from services.config_manager import ConfigManager
from services.printr import Printr

DEFAULTS_FILE = os.path.join("templates", "pocket_tts", "default_voices.tsv")
RECORD_FILE = ".default_voices.json"
"""In the configs folder: the voice Wingman last gave each Wingman."""
AZURE_DEFAULTS_FILE = os.path.join("templates", "azure", "default_voices.tsv")
AZURE_RECORD_FILE = ".default_azure_voices.json"
"""In the configs folder: the Azure voice Wingman last gave each Wingman."""
SWITCH_RECORD_FILE = ".azure_language_switch.json"
"""In the configs folder: what switch_to_azure_for_language moved to Azure,
so a Wingman the user puts back on Pocket TTS is not moved a second time."""
TEMPLATE_DEFAULTS_FILE = os.path.join("templates", "configs", "defaults.yaml")
ANY_LANGUAGE = "*"
"""Row of the Azure table for every language without a row of its own."""

TTS_PROVIDER = ("features", "tts_provider")
SUBSCRIPTION_TTS_PROVIDER = ("wingman_pro", "tts_provider")
POCKET_VOICE = ("pocket_tts", "voice")
AZURE_VOICE = ("wingman_pro", "azure", "voice")


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


def load_default_voices(app_root: str, file: str = DEFAULTS_FILE) -> dict[str, dict[str, str]]:
    """{wingman file name: {language: voice}} from ``file`` (Pocket TTS by
    default, AZURE_DEFAULTS_FILE for Azure)."""
    path = os.path.join(app_root, file)
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
    """The voice of ``wingman`` for ``language``, else its "*" row."""
    voices = table.get(wingman, {})
    return voices.get(language) or voices.get(ANY_LANGUAGE)


def is_default_voice(current, voices: dict[str, str], recorded=None) -> bool:
    """A Wingman still has a default voice: none of its own, the one it
    shipped with ("legacy") or the one Wingman last gave it (``recorded``)."""
    return not current or current in (voices.get("legacy"), recorded)


def _get(config: dict, keys: tuple):
    for key in keys:
        if not isinstance(config, dict):
            return None
        config = config.get(key)
    return config


def _set(config: dict, keys: tuple, value) -> None:
    for key in keys[:-1]:
        child = config.get(key)
        if not isinstance(child, dict):
            child = {}
        config[key] = child = dict(child)
        config = child
    config[keys[-1]] = value


def apply_default_voices(config_manager: ConfigManager, app_root: str, language: str) -> list[str]:
    """Give every shipped Wingman that still has a default voice the one for
    ``language``: its Pocket TTS voice and its subscription Azure voice, each
    on its own. Returns "config/wingman" of each Wingman changed."""
    providers = [
        (POCKET_VOICE, load_default_voices(app_root, DEFAULTS_FILE), RECORD_FILE),
        (AZURE_VOICE, load_default_voices(app_root, AZURE_DEFAULTS_FILE), AZURE_RECORD_FILE),
    ]
    records = {
        record_file: _read(os.path.join(config_manager.config_dir, record_file))
        for _, _, record_file in providers
    }
    changed = []
    for config_dir in config_manager.get_config_dirs():
        for wingman in config_manager.get_wingmen_configs(config_dir):
            if not any(wingman.name in table for _, table, _ in providers):
                continue
            key = f"{config_dir.directory}/{wingman.file}"
            path = os.path.join(config_manager.config_dir, config_dir.directory, wingman.file)
            try:
                config = config_manager.read_config(path) or {}
            except Exception as e:
                Printr().print(f"Could not read {path}: {e}", server_only=True)
                continue
            moved = {}
            for voice_path, table, record_file in providers:
                voices = table.get(wingman.name)
                wanted = default_voice_for(table, wingman.name, language)
                if not voices or not wanted:
                    continue
                record = records[record_file]
                current = _get(config, voice_path)
                # No voice of its own: it spoke with the global default (Clippy).
                if not is_default_voice(current, voices, record.get(key)):
                    continue
                if current == wanted:
                    record[key] = wanted
                    continue
                _set(config, voice_path, wanted)
                moved[record_file] = wanted
            if moved and config_manager.write_config(path, config):
                for record_file, wanted in moved.items():
                    records[record_file][key] = wanted
                changed.append(f"{config_dir.name}/{wingman.name}")
    for record_file, record in records.items():
        _write(os.path.join(config_manager.config_dir, record_file), record)
    return changed


def azure_voice_for_language(language: str) -> str:
    """The female Azure voice of ``language``, Jenny where there is none:
    what the defaults speak with once they move to Azure."""
    voices = AZURE_VOICES_BY_LANGUAGE.get(_base_language(language))
    return voices[0] if voices else AZURE_FEMALE_VOICE


def moves_to_azure(language: str) -> bool:
    """Pocket TTS stays the default for English; "other" has its own switch
    (services/other_language.py)."""
    return language not in ("en", "other")


def switch_defaults_to_azure(defaults: dict, template_defaults: dict, language: str) -> bool:
    """Move the raw defaults to the subscription's Azure when they still speak
    through Pocket TTS with the template's voice. The Azure voice becomes the
    female voice of ``language`` unless the user picked one. Returns True
    when ``defaults`` changed."""
    if _get(defaults, TTS_PROVIDER) != "pocket_tts":
        return False
    voice = _get(defaults, POCKET_VOICE)
    if voice and voice != _get(template_defaults, POCKET_VOICE):
        return False
    azure = _get(defaults, AZURE_VOICE)
    if not azure or azure == _get(template_defaults, AZURE_VOICE):
        _set(defaults, AZURE_VOICE, azure_voice_for_language(language))
    _set(defaults, TTS_PROVIDER, "wingman_pro")
    _set(defaults, SUBSCRIPTION_TTS_PROVIDER, "azure")
    return True


def switch_wingman_to_azure(
    config: dict,
    old_defaults: dict,
    defaults_switched: bool,
    default_pocket_voice: bool,
    azure_voice: Optional[str],
) -> str:
    """Move one raw Wingman config to the subscription's Azure for a language
    other than English, or keep it where it is when the defaults moved.

    ``default_pocket_voice``: it is a shipped Wingman whose Pocket TTS voice is
    still a default one. ``azure_voice``: the Azure voice to write, None to
    keep its own. ``old_defaults``: the defaults before they were switched.

    Returns "switched" (written to Azure), "follows" (inherits the switched
    defaults, nothing written), "kept" (pinned to what it inherited, so the
    defaults' switch does not reach it) or "" (nothing to do)."""
    own = _get(config, TTS_PROVIDER)
    if own not in (None, "pocket_tts"):
        # The user moved it to another provider: left alone. When it speaks
        # through the subscription, it keeps the sub-provider and voice it
        # inherited from the defaults.
        if not defaults_switched or own != "wingman_pro":
            return ""
        kept = False
        sub = _get(config, SUBSCRIPTION_TTS_PROVIDER)
        if sub is None:
            sub = _get(old_defaults, SUBSCRIPTION_TTS_PROVIDER)
            _set(config, SUBSCRIPTION_TTS_PROVIDER, sub)
            kept = True
        if sub == "azure" and _get(config, AZURE_VOICE) is None and _get(old_defaults, AZURE_VOICE):
            _set(config, AZURE_VOICE, _get(old_defaults, AZURE_VOICE))
            kept = True
        return "kept" if kept else ""
    if default_pocket_voice:
        _set(config, TTS_PROVIDER, "wingman_pro")
        _set(config, SUBSCRIPTION_TTS_PROVIDER, "azure")
        if azure_voice:
            _set(config, AZURE_VOICE, azure_voice)
        return "switched"
    if not defaults_switched:
        return ""
    if own is None and not _get(config, POCKET_VOICE):
        return "follows"
    if own is None:
        # A voice of its own on Pocket TTS: it keeps speaking with it.
        _set(config, TTS_PROVIDER, "pocket_tts")
        return "kept"
    return ""


def switch_to_azure_for_language(config_manager: ConfigManager, app_root: str, language: str) -> list[str]:
    """For a spoken language other than English: the defaults and every
    Wingman still on Pocket TTS with a default voice move to the
    subscription's Azure, with the Azure voice of their language. Run after
    apply_default_voices, so the default voices are already the new
    language's. A Wingman the user moved to another provider, or put back on
    Pocket TTS after an earlier switch, is left alone; nothing moves back for
    English. Returns "defaults" and "config/wingman" of what now speaks
    with Azure."""
    if not moves_to_azure(language):
        return []
    try:
        defaults = config_manager.read_config(config_manager.default_config_path) or {}
    except Exception as e:
        Printr().print(f"Could not read the defaults: {e}", server_only=True)
        return []
    if _get(defaults, TTS_PROVIDER) != "pocket_tts":
        return []
    template_defaults = _read_yaml(os.path.join(app_root, TEMPLATE_DEFAULTS_FILE))
    pocket_table = load_default_voices(app_root, DEFAULTS_FILE)
    azure_table = load_default_voices(app_root, AZURE_DEFAULTS_FILE)
    pocket_record = _read(os.path.join(config_manager.config_dir, RECORD_FILE))
    azure_record_path = os.path.join(config_manager.config_dir, AZURE_RECORD_FILE)
    azure_record = _read(azure_record_path)
    switch_record_path = os.path.join(config_manager.config_dir, SWITCH_RECORD_FILE)
    switch_record = _read(switch_record_path)

    old_defaults = copy.deepcopy(defaults)
    switched = []
    defaults_switched = "defaults" not in switch_record and switch_defaults_to_azure(
        defaults, template_defaults, language
    )
    if defaults_switched:
        if not config_manager.write_config(config_manager.default_config_path, defaults):
            return []
        config_manager.default_config = config_manager.load_defaults_config(silent_on_error=True)
        switch_record["defaults"] = language
        switched.append("defaults")

    for config_dir in config_manager.get_config_dirs():
        for wingman in config_manager.get_wingmen_configs(config_dir):
            key = f"{config_dir.directory}/{wingman.file}"
            path = os.path.join(config_manager.config_dir, config_dir.directory, wingman.file)
            try:
                config = config_manager.read_config(path) or {}
            except Exception as e:
                Printr().print(f"Could not read {path}: {e}", server_only=True)
                continue
            pocket_voices = pocket_table.get(wingman.name)
            shipped = bool(pocket_voices) and wingman.name in azure_table and key not in switch_record
            default_pocket = shipped and is_default_voice(
                _get(config, POCKET_VOICE), pocket_voices, pocket_record.get(key)
            )
            azure_voice = None
            if default_pocket and is_default_voice(
                _get(config, AZURE_VOICE), azure_table[wingman.name], azure_record.get(key)
            ):
                azure_voice = default_voice_for(azure_table, wingman.name, language)
            result = switch_wingman_to_azure(config, old_defaults, defaults_switched, default_pocket, azure_voice)
            if result == "follows":
                switched.append(f"{config_dir.name}/{wingman.name}")
            elif result and config_manager.write_config(path, config):
                if result == "switched":
                    switch_record[key] = language
                    if azure_voice:
                        azure_record[key] = azure_voice
                    switched.append(f"{config_dir.name}/{wingman.name}")
    _write(azure_record_path, azure_record)
    _write(switch_record_path, switch_record)
    return switched


def _read_yaml(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


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
