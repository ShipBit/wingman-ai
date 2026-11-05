"""One input, one job.

A key, mouse button or joystick button that two things use fires only one of
them: a Wingman's own push-to-talk wins over the global one, and the user
never learns why the other does nothing. So the binding the user records last
wins, and every other owner loses it. The client says so in a toast.

Owners are the three settings lists (push-to-talk for all Wingmen, shut up,
mute) and the push-to-talk of every Wingman. The settings ones are global, so
a binding recorded there is taken from the Wingmen of every config. A
Wingman's binding only clashes with the Wingmen of its own config.
"""

from typing import Optional

from api.enums import CommandTag, LogType
from api.interface import InputBinding, SettingsConfig
from services.input_bindings import describe_binding, without_bindings
from services.printr import Printr

printr = Printr()

GLOBAL_PTT = "global_ptt"
SHUT_UP = "shut_up"
MUTE = "mute"


def get_slot(settings: SettingsConfig, slot: str) -> list[InputBinding]:
    if slot == GLOBAL_PTT:
        return settings.global_ptt_bindings or []
    if slot == SHUT_UP:
        return settings.cancel_tts_bindings or []
    return settings.voice_activation.mute_toggle_bindings or []


def _set(settings: SettingsConfig, slot: str, bindings: list[InputBinding]) -> None:
    if slot == GLOBAL_PTT:
        settings.global_ptt_bindings = bindings
    elif slot == SHUT_UP:
        settings.cancel_tts_bindings = bindings
    else:
        settings.voice_activation.mute_toggle_bindings = bindings


SETTINGS_SLOTS = (GLOBAL_PTT, SHUT_UP, MUTE)

def settings_owner(slot: str) -> dict:
    return {"kind": slot}


def wingman_owner(wingman: str, config: Optional[str] = None) -> dict:
    return {"kind": "wingman", "wingman": wingman, "config": config}


def take_from_settings(
    settings: SettingsConfig, taken: list[InputBinding], keep: Optional[str] = None
) -> list[tuple[dict, InputBinding]]:
    """Removes the bindings from every settings list but `keep`. Returns who
    lost which binding."""
    lost = []
    for slot in SETTINGS_SLOTS:
        if slot == keep:
            continue
        kept, removed = without_bindings(get_slot(settings, slot), taken)
        if removed:
            _set(settings, slot, kept)
            lost += [(settings_owner(slot), binding) for binding in removed]
    return lost


def announce(new_owner: dict, lost: list[tuple[dict, InputBinding]]) -> None:
    """Tells the client which bindings moved, one message per binding. The
    client shows the toast in the user's language and reloads what it shows."""
    for owner, binding in lost:
        text = describe_binding(binding)
        printr.print(
            f"'{text}' now belongs to {_name(new_owner)}, taken from {_name(owner)}.",
            color=LogType.INFO,
            command_tag=CommandTag.BINDING_UNBOUND,
            additional_data={"binding": text, "owner": new_owner, "taken_from": owner},
        )


def _name(owner: dict) -> str:
    if owner["kind"] == "wingman":
        return f"{owner['wingman']}'s push-to-talk"
    return {
        GLOBAL_PTT: "push-to-talk for all Wingmen",
        SHUT_UP: "the shut up key",
        MUTE: "the mute key",
    }[owner["kind"]]
