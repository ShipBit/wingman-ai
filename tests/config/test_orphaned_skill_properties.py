"""A saved Wingman stores only `{id, value}` per skill property; the rest of the
property comes from the skill's default_config.yaml. When a skill update drops a
property, the stored entry has nothing left to complete it - and because
parse_config re-raises, that single stale key used to stop Core from starting.

Real case: a user's Wingman carried `debug_file_output` from an older
SC_LogReader; version 4.9.0.0 removed it and Core refused to boot.
"""

from unittest.mock import MagicMock

from services.config_manager import ConfigManager


def _manager() -> ConfigManager:
    manager = ConfigManager.__new__(ConfigManager)
    manager.printr = MagicMock()
    manager.log_source_name = "test"
    return manager


MANIFEST = {
    "module": "skills.sc_log_reader.main",
    "name": "SC_LogReader",
    "custom_properties": [
        {"id": "sc_game_path", "name": "Game path", "value": "", "property_type": "string"},
    ],
}


def test_stale_property_is_dropped():
    manager = _manager()
    wingman_skill = {
        "module": "skills.sc_log_reader.main",
        "custom_properties": [
            {"id": "sc_game_path", "value": "C:/SC"},
            {"id": "debug_file_output", "value": False},
        ],
    }
    out = manager._drop_orphaned_skill_properties(
        "sc_log_reader", MANIFEST, wingman_skill
    )
    assert [p["id"] for p in out["custom_properties"]] == ["sc_game_path"]
    manager.printr.print.assert_called_once()


def test_known_properties_are_untouched():
    manager = _manager()
    wingman_skill = {
        "module": "skills.sc_log_reader.main",
        "custom_properties": [{"id": "sc_game_path", "value": "C:/SC"}],
    }
    out = manager._drop_orphaned_skill_properties(
        "sc_log_reader", MANIFEST, wingman_skill
    )
    assert out is wingman_skill
    manager.printr.print.assert_not_called()


def test_self_sufficient_property_survives():
    """A legacy config that carries the whole property keeps working."""
    manager = _manager()
    wingman_skill = {
        "module": "skills.sc_log_reader.main",
        "custom_properties": [
            {
                "id": "extra_flag",
                "name": "Extra flag",
                "value": True,
                "property_type": "boolean",
            }
        ],
    }
    out = manager._drop_orphaned_skill_properties(
        "sc_log_reader", MANIFEST, wingman_skill
    )
    assert [p["id"] for p in out["custom_properties"]] == ["extra_flag"]


def test_no_properties_is_a_noop():
    manager = _manager()
    wingman_skill = {"module": "skills.sc_log_reader.main"}
    assert (
        manager._drop_orphaned_skill_properties("sc_log_reader", MANIFEST, wingman_skill)
        is wingman_skill
    )
