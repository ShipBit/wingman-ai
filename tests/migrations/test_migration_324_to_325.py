"""3.2.5: the four settings the fixed context limits needed are removed (the
limits follow the main model's window now, services/context_budget.py), and
the community SC Log Reader skill is retired because Core reads the log.
"""

from unittest.mock import MagicMock

from api.interface import NestedConfig
from services.migrations.migration_324_to_325 import Migration324To325
from tests.support import template

REMOVED = ("compress_tool_responses", "skill_max_input_tokens",
           "condense_keep_recent_tokens", "condense_max_messages")


def migration():
    return Migration324To325(MagicMock())


def old_features():
    return {"condense_conversation": False, "compress_tool_responses": True,
            "skill_max_input_tokens": 16000, "condense_keep_recent_tokens": 8000,
            "condense_max_messages": 150, "tts_provider": "edge_tts"}


def test_defaults_lose_the_four_and_keep_the_switch():
    out = migration().migrate_defaults({"features": old_features()})
    assert not any(k in out["features"] for k in REMOVED)
    assert out["features"]["condense_conversation"] is False
    assert out["features"]["tts_provider"] == "edge_tts"


def test_every_wingman_loses_them_too():
    out = migration().migrate_wingman({"name": "Computer", "features": old_features()})
    assert not any(k in out["features"] for k in REMOVED)


def test_a_wingman_without_features_is_left_alone():
    assert migration().migrate_wingman({"name": "Board"}) == {"name": "Board"}


def test_the_defaults_template_has_none_of_them_and_still_loads():
    data = template("defaults.yaml")
    assert not any(k in data["features"] for k in REMOVED)
    NestedConfig(**data)


# ── the SC Log Reader skill ─────────────────────────────────────────────


def test_reader_05_with_reactions_and_masters():
    wingman = {
        "discoverable_skills": ["SCLogReader", "Timer"],
        "skills": [
            {
                "module": "skills.sc_log_reader.main",
                "custom_properties": [
                    {"id": "react_game_events", "value": True},
                    {"id": "notify_money", "value": False},
                    {"id": "notify_armistice_zone", "value": False},
                    {"id": "notify_restricted_area", "value": False},
                    {"id": "notify_monitored_space", "value": False},
                    {"id": "notify_monitored_space_availability", "value": False},
                    {"id": "notify_jurisdiction_change", "value": False},
                    {"id": "notify_crimestat_increased", "value": False},
                    {"id": "notify_entered_monitored_space", "value": False},
                    {"id": "notify_exited_monitored_space", "value": False},
                    {"id": "notify_monitored_space_down", "value": False},
                    {"id": "notify_monitored_space_restored", "value": False},
                    {"id": "notify_zone_entered_armistice", "value": False},
                    {"id": "notify_zone_left_armistice", "value": False},
                ],
            },
            {"module": "skills.timer.main"},
        ],
    }
    migrated = migration().migrate_wingman(wingman)
    assert migrated["discoverable_skills"] == ["Timer", "ScGameEvents"]
    modules = [s["module"] for s in migrated["skills"]]
    assert modules == ["skills.timer.main", "skills.sc_game_events.main"]
    switches = {p["id"]: p["value"] for p in migrated["skills"][1]["custom_properties"]}
    assert switches["react_money"] is False  # its master was off
    assert switches["react_safety"] is False  # every switch in it was off
    assert switches["react_mission"] is True


def test_reader_enabled_without_reactions_leaves_no_skill_behind():
    wingman = {"discoverable_skills": ["SC_LogReader"]}
    migrated = migration().migrate_wingman(wingman)
    assert migrated["discoverable_skills"] == []
    assert not migrated.get("skills")


def test_a_wingman_without_the_reader_is_untouched():
    wingman = {"discoverable_skills": ["Timer"], "skills": [{"module": "skills.timer.main"}]}
    assert migration().migrate_wingman(dict(wingman)) == wingman
