"""3.2.13: Jev gets a switch per place it decides, and keys bound twice go
back to their default.

The new Jev switches start on, so whoever had Jev on keeps every decision.
A key used by two owners fired only one of them: a Wingman's push-to-talk on
the global push-to-talk key won, and the global key did nothing."""

import os
from os import path
from types import SimpleNamespace

import pytest

from services.migrations.migration_3212_to_3213 import Migration3212To3213
from tests.support import REPO_ROOT, read_yaml, write_yaml


def key(name: str) -> dict:
    return {"device": "keyboard", "keys": [{"name": name, "scan_code": None, "extended": False}]}


PERIOD = [key(".")]
SHIFT_Y = [{"device": "keyboard", "keys": [
    {"name": "shift", "scan_code": None, "extended": False},
    {"name": "y", "scan_code": None, "extended": False},
]}]


def settings(global_ptt=None, shut_up=None, mute=None) -> dict:
    return {
        "system_one": {"enabled": True, "commands": False},
        "global_ptt_bindings": global_ptt if global_ptt is not None else list(PERIOD),
        "cancel_tts_bindings": shut_up if shut_up is not None else list(SHIFT_Y),
        "voice_activation": {"mute_toggle_bindings": mute if mute is not None else []},
    }


@pytest.fixture
def old_configs(users_dir):
    """Writes the 3.2.12 configs: {"Config/Wingman": [bindings]}."""

    def write(settings_yaml: dict, wingmen: dict[str, list]):
        root = path.join(users_dir, "3_2_12", "configs")
        os.makedirs(root, exist_ok=True)
        write_yaml(path.join(root, "settings.yaml"), settings_yaml)
        write_yaml(path.join(root, "defaults.yaml"), {})
        for name, bindings in wingmen.items():
            config_dir, wingman = name.split("/")
            os.makedirs(path.join(root, config_dir), exist_ok=True)
            write_yaml(
                path.join(root, config_dir, f"{wingman}.yaml"),
                {"name": wingman, "record_bindings": bindings},
            )
        return root

    return write


def migration() -> Migration3212To3213:
    service = SimpleNamespace(
        config_manager=SimpleNamespace(read_config=read_yaml),
        system_manager=None,
        templates_dir=path.join(REPO_ROOT, "templates"),
        log=lambda *_: None,
        log_highlight=lambda *_: None,
        log_warning=lambda *_: None,
        err=lambda *_: None,
        current_wingman=None,
    )
    return Migration3212To3213(service)


def run(root: str, wingmen: list[str]) -> tuple[dict, dict[str, list]]:
    """Settings first, then each Wingman, like the migration service."""
    step = migration()
    migrated = step.migrate_settings(read_yaml(path.join(root, "settings.yaml")))
    keys = {}
    for name in wingmen:
        config_dir, wingman = name.split("/")
        step.service.current_wingman = (config_dir, f"{wingman}.yaml")
        out = step.migrate_wingman(read_yaml(path.join(root, config_dir, f"{wingman}.yaml")))
        keys[name] = out["record_bindings"]
    return migrated, keys


# ── Jev ─────────────────────────────────────────────────────────────


def test_the_new_switches_start_on(old_configs):
    root = old_configs(settings(), {})
    migrated, _ = run(root, [])
    assert migrated["system_one"] == {
        "enabled": True,
        "commands": False,
        "wingman_choice": True,
        "vocabulary": True,
        "skills": True,
    }


def test_a_switch_that_is_there_is_kept(old_configs):
    old = settings()
    old["system_one"]["skills"] = False
    migrated, _ = run(old_configs(old, {}), [])
    assert migrated["system_one"]["skills"] is False


# ── keys bound twice ────────────────────────────────────────────────


def test_a_global_key_a_wingman_also_has_goes_back_to_the_period(old_configs):
    """The case from the field: the global key on End, which the Computer
    Wingman already used. Both go back: the global key to the period, the
    Wingman to the key it ships with."""
    root = old_configs(
        settings(global_ptt=[key("end")]),
        {"Star Citizen/Computer": [key("end")], "Star Citizen/ATC": [key("delete")]},
    )

    migrated, keys = run(root, ["Star Citizen/Computer", "Star Citizen/ATC"])

    assert migrated["global_ptt_bindings"] == PERIOD
    shipped = read_yaml(
        path.join(REPO_ROOT, "templates", "configs", "Star Citizen", "Computer.template.yaml")
    )["record_bindings"]
    assert keys["Star Citizen/Computer"] == shipped
    assert keys["Star Citizen/ATC"] == [key("delete")]


def test_keys_bound_once_stay_as_they_are(old_configs):
    root = old_configs(
        settings(global_ptt=[key("f1")], shut_up=[key("f2")], mute=[key("f3")]),
        {"Mine/Bob": [key("f4")], "Mine/Alice": [key("f5")]},
    )

    migrated, keys = run(root, ["Mine/Bob", "Mine/Alice"])

    assert migrated["global_ptt_bindings"] == [key("f1")]
    assert migrated["cancel_tts_bindings"] == [key("f2")]
    assert migrated["voice_activation"]["mute_toggle_bindings"] == [key("f3")]
    assert keys == {"Mine/Bob": [key("f4")], "Mine/Alice": [key("f5")]}


def test_two_wingmen_of_one_config_on_one_key_both_lose_it(old_configs):
    root = old_configs(settings(), {"Mine/Bob": [key("f4")], "Mine/Alice": [key("f4")]})

    _, keys = run(root, ["Mine/Bob", "Mine/Alice"])

    assert keys == {"Mine/Bob": [], "Mine/Alice": []}


def test_the_same_key_in_two_configs_is_fine(old_configs):
    """Only one config runs at a time."""
    root = old_configs(settings(), {"One/Bob": [key("f4")], "Two/Alice": [key("f4")]})

    _, keys = run(root, ["One/Bob", "Two/Alice"])

    assert keys == {"One/Bob": [key("f4")], "Two/Alice": [key("f4")]}


def test_shut_up_and_mute_on_one_key_go_back_to_their_defaults(old_configs):
    root = old_configs(settings(shut_up=[key("f2")], mute=[key("f2")]), {})

    migrated, _ = run(root, [])

    assert migrated["cancel_tts_bindings"] == SHIFT_Y
    assert migrated["voice_activation"]["mute_toggle_bindings"][0]["keys"][1]["name"] == "x"


def test_a_default_that_meets_a_key_bound_once_stays_empty(old_configs):
    """The global key clashes with shut up, but its default, the period, is a
    Wingman's own key: the Wingman keeps it, the global key gets none."""
    root = old_configs(
        settings(global_ptt=[key("f2")], shut_up=[key("f2")]),
        {"Mine/Bob": [key(".")]},
    )

    migrated, keys = run(root, ["Mine/Bob"])

    assert migrated["global_ptt_bindings"] == []
    assert migrated["cancel_tts_bindings"] == SHIFT_Y
    assert keys["Mine/Bob"] == [key(".")]
