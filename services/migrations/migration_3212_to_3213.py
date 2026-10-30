"""Migration from version 3.2.12 to 3.2.13.

Jev, the decision model, gets a switch per place it decides: commands (there
already), the Wingman for the global push-to-talk key, names in speech
recognition, and skills. The three new ones start on, so whoever had Jev on
keeps every decision it took before.

A key also gets one owner. Two owners of one key fired only one of them: a
Wingman's push-to-talk on the key of the global push-to-talk won silently, and
the global key looked broken. From 3.2.13 on, recording a key takes it from
its old owner. Keys that are already bound twice are put back to their
default here, only the ones that are bound twice. Every other binding stays
as it is.

Which keys meet: the global push-to-talk, shut up and mute keys work in every
config, so they meet every Wingman. A Wingman's push-to-talk only meets the
Wingmen of its own config.

Core also reads Star Citizen's own telemetry now (settings.sc_telemetry). It
starts on, like the log reader, and runs only for someone who said they play
Star Citizen. On Windows it then sets the variable that switches telemetry on
in the game, which only Star Citizen reads.
"""

from os import listdir, path
from typing import Optional

from pydantic import ValidationError

from api.interface import InputBinding
from services.file import get_users_dir
from services.input_bindings import describe_binding, same_input
from services.migrations.base_migration import BaseMigration, strip_legacy_prefixes

NEW_SYSTEM_ONE_SWITCHES = ("wingman_choice", "vocabulary", "skills")

SETTINGS_KEYS = {
    "global_ptt": "Push-to-Talk for all Wingmen",
    "shut_up": "the shut up key",
    "mute": "the mute key",
}

Owner = tuple
"""("settings", slot) or ("wingman", config dir, file name)."""


def _settings_bindings(settings: dict, slot: str) -> list:
    if slot == "global_ptt":
        return settings.get("global_ptt_bindings") or []
    if slot == "shut_up":
        return settings.get("cancel_tts_bindings") or []
    return (settings.get("voice_activation") or {}).get("mute_toggle_bindings") or []


def _set_settings_bindings(settings: dict, slot: str, bindings: list) -> None:
    if slot == "global_ptt":
        settings["global_ptt_bindings"] = bindings
    elif slot == "shut_up":
        settings["cancel_tts_bindings"] = bindings
    else:
        settings.setdefault("voice_activation", {})["mute_toggle_bindings"] = bindings


def _parsed(bindings: list) -> list[InputBinding]:
    parsed = []
    for binding in bindings or []:
        try:
            parsed.append(InputBinding(**binding))
        except (TypeError, ValidationError):
            continue
    return parsed


def _meet(a: Owner, b: Owner) -> bool:
    """Whether the two can fire in the same config."""
    if a[0] == "settings" or b[0] == "settings":
        return True
    return a[1] == b[1]


def _name(owner: Owner) -> str:
    if owner[0] == "settings":
        return SETTINGS_KEYS[owner[1]]
    return f"{owner[1]}/{owner[2].removesuffix('.yaml')}"


def double_bound(bindings: dict[Owner, list]) -> dict[Owner, set[Owner]]:
    """For every owner whose keys another owner also uses, those others."""
    parsed = {owner: _parsed(raw) for owner, raw in bindings.items()}
    clashes: dict[Owner, set[Owner]] = {}
    owners = list(parsed)
    for i, a in enumerate(owners):
        for b in owners[i + 1 :]:
            if not _meet(a, b):
                continue
            if any(same_input(x, y) for x in parsed[a] for y in parsed[b]):
                clashes.setdefault(a, set()).add(b)
                clashes.setdefault(b, set()).add(a)
    return clashes


def resolve(bindings: dict[Owner, list], defaults: dict[Owner, list]) -> dict[Owner, list]:
    """The new bindings of every owner that was bound twice: its default, or
    nothing where the default would clash again."""
    clashing = double_bound(bindings)
    if not clashing:
        return {}
    changed = {owner: defaults.get(owner, []) for owner in clashing}
    after = {**bindings, **changed}
    # A default can meet a key that was never bound twice, or another reset
    # owner's default. The untouched binding keeps its key.
    for owner in double_bound(after):
        if owner in changed:
            changed[owner] = []
    return changed


class Migration3212To3213(BaseMigration):
    """Migration from 3.2.12 to 3.2.13."""

    old_version = "3_2_12"
    new_version = "3_2_13"

    _reset: Optional[dict[Owner, list]] = None

    def migrate_settings(self, old: dict) -> dict:
        system_one = old.get("system_one")
        if isinstance(system_one, dict):
            for switch in NEW_SYSTEM_ONE_SWITCHES:
                system_one.setdefault(switch, True)

        for owner, bindings in self._resets(old).items():
            if owner[0] == "settings":
                _set_settings_bindings(old, owner[1], bindings)

        if not isinstance(old.get("sc_telemetry"), dict):
            old["sc_telemetry"] = {"enabled": True}
        return old

    def migrate_wingman(self, old: dict) -> dict:
        current = getattr(self.service, "current_wingman", None)
        if current and self._reset is None:
            # No settings.yaml in the old version: the keys are read from here.
            self._resets({})
        if current and self._reset:
            owner = ("wingman", current[0], current[1])
            if owner in self._reset:
                old["record_bindings"] = self._reset[owner]
        return old

    # ── keys bound twice ────────────────────────────────────────────

    def _resets(self, settings: dict) -> dict[Owner, list]:
        """What to put back, worked out once over every key of the old
        version: settings.yaml runs before any Wingman."""
        if self._reset is not None:
            return self._reset
        bindings, defaults = self._all_bindings(settings)
        self._reset = resolve(bindings, defaults)
        for owner, new in sorted(self._reset.items()):
            old = ", ".join(describe_binding(b) for b in _parsed(bindings[owner]))
            target = (
                ", ".join(describe_binding(b) for b in _parsed(new)) if new else "no key"
            )
            self.log_warning(
                f"{_name(owner)} shared {old} with another key: now {target}."
            )
        return self._reset

    def _all_bindings(self, settings: dict) -> tuple[dict[Owner, list], dict[Owner, list]]:
        bindings: dict[Owner, list] = {}
        defaults: dict[Owner, list] = {}
        template = self._read(path.join(self.templates_dir, "configs", "settings.yaml")) or {}
        for slot in SETTINGS_KEYS:
            bindings[("settings", slot)] = _settings_bindings(settings, slot)
            defaults[("settings", slot)] = _settings_bindings(template, slot)

        configs = path.join(get_users_dir(), self.old_version, "configs")
        if not path.isdir(configs):
            return bindings, defaults
        old_defaults = self._read(path.join(configs, "defaults.yaml")) or {}
        for config_dir in sorted(listdir(configs)):
            folder = path.join(configs, config_dir)
            if config_dir.startswith(".") or not path.isdir(folder):
                continue
            for file_name in sorted(listdir(folder)):
                if not file_name.endswith(".yaml") or file_name.endswith("template.yaml"):
                    continue
                wingman = self._read(path.join(folder, file_name)) or {}
                owner = ("wingman", config_dir, file_name)
                bindings[owner] = wingman.get(
                    "record_bindings", old_defaults.get("record_bindings") or []
                )
                defaults[owner] = self._wingman_default(config_dir, file_name, old_defaults)
        return bindings, defaults

    def _wingman_default(self, config_dir: str, file_name: str, old_defaults: dict) -> list:
        """The key the Wingman ships with, or the defaults' (none)."""
        shipped = self._read(
            path.join(
                self.templates_dir,
                "configs",
                strip_legacy_prefixes(config_dir),
                f"{file_name.removesuffix('.yaml')}.template.yaml",
            )
        )
        if shipped and "record_bindings" in shipped:
            return shipped["record_bindings"] or []
        return old_defaults.get("record_bindings") or []

    def _read(self, file_path: str) -> Optional[dict]:
        if not path.exists(file_path):
            return None
        data = self.config_manager.read_config(file_path)
        return data if isinstance(data, dict) else None
