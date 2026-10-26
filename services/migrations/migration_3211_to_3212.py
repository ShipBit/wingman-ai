"""Migration from version 3.2.11 to 3.2.12.

Every key, mouse and joystick binding becomes a list of bindings:

- a wingman's push-to-talk (`record_key`, `record_key_codes`,
  `record_mouse_button`, `record_joystick_button`) -> `record_bindings`
- shut up (`cancel_tts_key`, `cancel_tts_key_codes`,
  `cancel_tts_joystick_button`) -> `cancel_tts_bindings`
- mute (`voice_activation.mute_toggle_key`, `mute_toggle_key_codes`)
  -> `voice_activation.mute_toggle_bindings`
- new: `global_ptt_bindings`, empty

Each key now carries the extended flag that tells left from right Ctrl on
Windows. Old bindings stored scan codes without it, so the flag is guessed
from the key name the recording saved ("right ctrl", "end"); elsewhere it is
always False. Keys saved without codes are kept by name.

Command actions are not touched: they keep playing exactly as before.
"""

import platform

from services.input_bindings import legacy_joystick, legacy_keyboard, legacy_mouse
from services.migrations.base_migration import BaseMigration


def _bindings(*candidates) -> list[dict]:
    return [binding for binding in candidates if binding]


class Migration3211To3212(BaseMigration):
    """Migration from 3.2.11 to 3.2.12."""

    old_version = "3_2_11"
    new_version = "3_2_12"

    # The extended flag only exists on Windows. Tests set it.
    is_windows = platform.system() == "Windows"

    def migrate_settings(self, old: dict) -> dict:
        if "cancel_tts_bindings" not in old:
            old["cancel_tts_bindings"] = _bindings(
                legacy_keyboard(
                    old.get("cancel_tts_key"),
                    old.get("cancel_tts_key_codes"),
                    self.is_windows,
                ),
                legacy_joystick(old.get("cancel_tts_joystick_button")),
            )
        for field in ("cancel_tts_key", "cancel_tts_key_codes", "cancel_tts_joystick_button"):
            old.pop(field, None)

        old.setdefault("global_ptt_bindings", [])

        va = old.get("voice_activation")
        if isinstance(va, dict):
            if "mute_toggle_bindings" not in va:
                va["mute_toggle_bindings"] = _bindings(
                    legacy_keyboard(
                        va.get("mute_toggle_key"),
                        va.get("mute_toggle_key_codes"),
                        self.is_windows,
                    )
                )
            va.pop("mute_toggle_key", None)
            va.pop("mute_toggle_key_codes", None)

        self.log("Converted the shut up and mute keys to bindings.")
        return old

    def migrate_wingman(self, old: dict) -> dict:
        if "record_bindings" not in old:
            old["record_bindings"] = _bindings(
                legacy_keyboard(
                    old.get("record_key"), old.get("record_key_codes"), self.is_windows
                ),
                legacy_mouse(old.get("record_mouse_button")),
                legacy_joystick(old.get("record_joystick_button")),
            )
        for field in (
            "record_key",
            "record_key_codes",
            "record_mouse_button",
            "record_joystick_button",
        ):
            old.pop(field, None)
        return old
