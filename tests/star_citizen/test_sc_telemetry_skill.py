"""The skill on recorded frames: frames in, events out, tool answers."""
import asyncio
import types
from pathlib import Path

import pytest

from skills.sc_telemetry.events import EVENTS
from tests.star_citizen.sc_telemetry_support import (
    load_frames,
    make_skill,
)

SKILL_DIR = Path(__file__).resolve().parent.parent


def test_frames_become_events_and_answers():
    skill = make_skill({})
    offered = []
    skill._offer = offered.extend
    skill._loop = types.SimpleNamespace(call_soon_threadsafe=lambda fn, events: fn(events))
    for t, frame in load_frames("combat_2026-10-28.jsonl"):
        skill._on_frame_thread(frame, t)
    found = {event.id for event in offered}
    assert {"shields_down", "under_fire", "powerplant_offline"} <= found
    skill._reader_status = "live"
    ship = asyncio.run(skill.get_ship_status())
    assert ship.startswith("Ship: DRAK Cutter")


def test_every_reaction_is_on_and_only_the_master_mutes():
    """Only two settings are shown (user, 2026-10-29): all reactions on, the proactive master mutes them all."""
    skill = make_skill({"react_ship": False, "react_under_fire": False})  # old switches are ignored
    assert all(skill._event_enabled(spec.id) for spec in EVENTS)
    assert not skill._event_enabled("no_such_event")
    muted = make_skill({"proactive_notifications": False})
    assert not any(muted._event_enabled(spec.id) for spec in EVENTS)


def test_off_windows_the_setting_never_touches_the_system(monkeypatch, tmp_path):
    """Linux players set the variable in Lutris or Steam; the skill only tells them how."""
    from skills.sc_telemetry import enable

    monkeypatch.setattr(enable, "MANAGED", False)
    monkeypatch.setattr(enable, "set_enabled", lambda enabled: pytest.fail("must not switch"))
    skill = make_skill({"enable_telemetry": True})
    skill.get_generated_files_dir = lambda: str(tmp_path)
    skill._apply_enable_setting()
    assert enable.is_enabled() is None
    skill._reader_status = "waiting"
    assert "GRPC_CLIENT_SERVER_ENABLED=true" in skill._health_line()
