"""Setting a language beyond the six Wingman supports end to end.

Three steps, each as far as the providers allow:

1. Name it. The user types what they call it ("Holländisch"); the list in
   services/other_languages.py finds most, the support model names the rest.
   It only turns the input into a name and a code: whether a provider
   supports the language comes from our own data, never from the model.
2. Check it. Parakeet transcribes 25 languages (the subscription's cloud
   transcription detects any); Inworld has voices for a language or not,
   which its voice list says.
3. Switch. Wingmen on Pocket TTS, which has no model for such a language,
   move to Inworld through the subscription or the user's own key, with a
   voice in that language. What was switched is noted, and switching back
   to one of the six languages restores it.
"""

import json
import os
import re
from typing import Awaitable, Callable, Optional

from api.interface import OtherLanguageOption, OtherLanguageReport, OtherLanguageSetting, VoiceInfo
from services.other_languages import ALIASES, BY_CODE, OTHER_LANGUAGES, PARAKEET_LANGUAGES
from services.file import get_prompt
from services.printr import Printr

RECORD_FILE = ".other_language_switch.json"
"""In the configs folder: the Wingmen moved off Pocket TTS, to move back."""

_CODE = re.compile(r"^[a-z]{2,3}$")


def options() -> list[OtherLanguageOption]:
    return [
        OtherLanguageOption(
            **vars(language),
            aliases=list(ALIASES.get(language.code, ())),
            parakeet=language.code in PARAKEET_LANGUAGES,
        )
        for language in OTHER_LANGUAGES
    ]


def _fold(text: str) -> str:
    return text.strip().lower()


def find(text: str) -> Optional[OtherLanguageSetting]:
    """The list entry ``text`` names, in any of its names or by code."""
    wanted = _fold(text)
    if not wanted:
        return None
    for language in OTHER_LANGUAGES:
        names = (language.code, language.native, language.en, language.de, language.fr, language.es)
        names += ALIASES.get(language.code, ())
        if any(_fold(name) == wanted for name in names):
            return OtherLanguageSetting(code=language.code, name=language.native, english_name=language.en)
    return None


async def resolve(
    text: str, ask_support_model: Optional[Callable[[str, str], Awaitable[Optional[str]]]]
) -> Optional[OtherLanguageSetting]:
    """The language ``text`` names: from the list, else from the support
    model. None when it names no language."""
    found = find(text)
    if found or not ask_support_model:
        return found
    try:
        answer = await ask_support_model(get_prompt("other-language-name"), f"Input: {text.strip()[:60]}")
        match = re.search(r"\{.*\}", answer or "", re.S)
        data = json.loads(match.group(0)) if match else {}
    except Exception as e:
        Printr().print(f"Could not name the language {text!r}: {e}", server_only=True)
        return None
    name, english = data.get("name"), data.get("english_name")
    if not name or not english:
        return None
    code = str(data.get("code") or "").lower() or None
    if code and not _CODE.match(code):
        code = None
    if code in BY_CODE:
        listed = BY_CODE[code]
        return OtherLanguageSetting(code=code, name=listed.native, english_name=listed.en)
    return OtherLanguageSetting(code=code, name=str(name)[:40], english_name=str(english)[:40])


def inworld_speaks(voices: list[VoiceInfo], code: Optional[str]) -> list[VoiceInfo]:
    """Inworld voices for the language ``code``."""
    if not code:
        return []
    return [v for v in voices if any((lang or "").lower().split("-")[0] == code for lang in (v.languages or []))]


def switch_wingmen(
    config_manager,
    defaults_tts_provider: str,
    language: OtherLanguageSetting,
    provider: str,
    voices: list[VoiceInfo],
) -> list[str]:
    """Move every Wingman speaking through Pocket TTS to ``provider``
    ("wingman_pro" or "inworld") with one of ``voices``, each Wingman its own
    where there are enough. Notes what it did for restore_wingmen."""
    record_path = os.path.join(config_manager.config_dir, RECORD_FILE)
    record = _read(record_path)
    switched = []
    for index, (path, label, config) in enumerate(_pocket_wingmen(config_manager, defaults_tts_provider)):
        voice = voices[index % len(voices)].id
        features = config.setdefault("features", {})
        features["tts_provider"] = provider
        if provider == "wingman_pro":
            config.setdefault("wingman_pro", {})["tts_provider"] = "inworld"
        config.setdefault("inworld", {})["voice_id"] = voice
        if config_manager.write_config(path, config):
            record[path] = {"voice_id": voice, "provider": provider}
            switched.append(label)
    _write(record_path, record)
    return switched


def restore_wingmen(config_manager) -> list[str]:
    """Move the Wingmen switch_wingmen moved back to Pocket TTS, unless the
    user has changed their provider or voice since."""
    record_path = os.path.join(config_manager.config_dir, RECORD_FILE)
    record = _read(record_path)
    restored, retry = [], {}
    for path, done in record.items():
        if not os.path.exists(path):
            continue
        try:
            config = config_manager.read_config(path) or {}
        except Exception:
            retry[path] = done
            continue
        features = config.get("features") or {}
        if features.get("tts_provider") != done["provider"]:
            continue
        if (config.get("inworld") or {}).get("voice_id") != done["voice_id"]:
            continue
        features["tts_provider"] = "pocket_tts"
        config["features"] = features
        if config_manager.write_config(path, config):
            restored.append(path)
        else:
            retry[path] = done
    # Wingmen that could not be read or written are tried again next time.
    if os.path.exists(record_path):
        os.remove(record_path)
    _write(record_path, retry)
    return restored


def _pocket_wingmen(config_manager, defaults_tts_provider: str):
    for config_dir in config_manager.get_config_dirs():
        for wingman in config_manager.get_wingmen_configs(config_dir):
            path = os.path.join(config_manager.config_dir, config_dir.directory, wingman.file)
            try:
                config = config_manager.read_config(path) or {}
            except Exception:
                continue
            provider = (config.get("features") or {}).get("tts_provider") or defaults_tts_provider
            if provider == "pocket_tts":
                yield path, f"{config_dir.name}/{wingman.name}", config


def report(
    language: OtherLanguageSetting,
    stt_provider: str,
    inworld_supported: bool,
    tts_provider: Optional[str],
    switched: list[str],
) -> OtherLanguageReport:
    stt_supported = stt_provider == "wingman_pro" or (language.code or "") in PARAKEET_LANGUAGES
    return OtherLanguageReport(
        language=language,
        stt_provider=stt_provider,
        stt_supported=stt_supported,
        inworld_supported=inworld_supported,
        tts_provider=tts_provider,
        switched_wingmen=switched,
    )


def _read(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: str, data: dict) -> None:
    if not data:
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
