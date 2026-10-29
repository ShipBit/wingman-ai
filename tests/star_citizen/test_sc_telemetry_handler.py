"""The Handler replayed on real recorded moments from the field tests (the field-test report, section 5)."""
import itertools
import time

from skills.sc_telemetry.normalize import normalize
from tests.star_citizen.sc_telemetry_support import (
    ids,
    load_frames,
    replay,
)


def _clock(date: str, clock: str) -> float:
    return time.mktime(time.strptime(f"{date} {clock}", "%Y-%m-%d %H:%M:%S"))


# --- normalisation -------------------------------------------------------------------------------------------


def test_missing_fields_read_as_defaults():
    state = normalize({"actor": {"state": {"locomotion": "ACTOR_LOCOMOTION_STATE_ON_FOOT", "uec_balance": "42"}}})
    assert state["player"]["locomotion"] == "on_foot"
    assert state["player"]["uec_balance"] == 42
    assert state["player"]["health"] == 0.0
    assert state["vehicle"] is None


def test_ship_identity_comes_from_name_and_class():
    vehicle = {"state": {"name": "DRAK_Cutter_907038284543", "class_name": "DRAK_Cutter",
                         "type": "VEHICLE_TYPE_SPACESHIP"}}
    ship = normalize({"vehicle": vehicle})["vehicle"]
    assert ship["instance_id"] == "907038284543"
    assert ship["class_name"] == "DRAK_Cutter"
    assert ship["manufacturer"] == "Drake"
    assert ship["power"]["engines"] is False  # missing power flag = off


def test_heading_needs_a_planet_frame():
    space = normalize({"vehicle": {"state": {"flight": {"instruments": {"altitude": 3.4028235e38, "heading": 140}}}}})
    planet = normalize({"vehicle": {"state": {"flight": {"instruments": {"altitude": 1523.4, "heading": 304.28}}}}})
    assert space["derived"]["in_planet_frame"] is False and space["derived"]["heading_valid"] is False
    assert planet["derived"]["in_planet_frame"] is True and planet["derived"]["heading_valid"] is True


def test_radar_altitude_equal_to_altitude_is_no_reading():
    state = normalize({"vehicle": {"state": {"flight": {"instruments": {"altitude": 1606.0,
                                                                         "radar_altitude": 1606.0}}}}})
    assert state["derived"]["radar_valid"] is False


# --- recorded moments --------------------------------------------------------------------------------------------


def test_planet_yaw_heading_follows_the_nose():
    _, _, states = replay(load_frames("planet_yaw_2026-10-26.jsonl"))
    headings = [s["vehicle"]["instruments"]["heading"] for _, s in states if s["derived"]["heading_valid"]]
    assert abs(headings[0] - 304.28) < 0.5
    assert abs(headings[-1] - 40.52) < 0.5


def test_planet_arrival_makes_heading_valid():
    _, _, states = replay(load_frames("planet_arrival_2026-10-26.jsonl"))
    before = [s for t, s in states if t < _clock("2026-10-26", "22:33:30")]
    after = [s for t, s in states if t > _clock("2026-10-26", "22:33:45")]
    assert not any(s["derived"]["heading_valid"] for s in before)
    assert all(s["derived"]["in_planet_frame"] for s in after)


def test_quantum_jump_is_detected_and_heading_is_not_trusted():
    _, events, states = replay(load_frames("vulture_jump_2026-10-27.jsonl"))
    assert ids(events).count("jump_started") == 1
    jumping = [s for _, s in states if s["derived"]["in_jump"]]
    assert jumping and not any(s["derived"]["heading_valid"] for s in jumping)


def test_module_separation_and_docking_change_the_vehicle():
    _, events, _ = replay(load_frames("module_separation_2026-10-27.jsonl"))
    changes = [e.data["vehicle"] for e in events if e.id == "vehicle_changed"]
    assert changes == ["DRAK_Command_Module", "DRAK_Ironclad"]


def test_eva_flicker_at_the_door_is_smoothed():
    _, _, states = replay(load_frames("eva_door_2026-10-27.jsonl"))
    seen = [s["player"]["locomotion"] for _, s in states]
    flips = sum(1 for a, b in itertools.pairwise(seen) if a != b)
    assert flips <= 3  # seated -> on foot -> eva, not dozens of flips
    assert seen[-1] == "eva"


def test_combat_reports_hits_shields_engines_lock_and_powerplant():
    _, events, _ = replay(load_frames("combat_2026-10-28.jsonl"))
    found = ids(events)
    for expected in ("proximity_warning", "locked_on", "under_fire", "shields_down", "engines_damaged",
                     "powerplant_offline"):
        assert expected in found, expected
    assert found.count("under_fire") <= 3  # cooldown, not one per volley


def test_grenade_then_respawn():
    _, events, _ = replay(load_frames("grenade_respawn_2026-10-28.jsonl"))
    found = ids(events)
    assert found.count("health_low") == 1
    assert found.count("player_down") == 1
    assert found.count("respawned") == 1
    assert found.index("health_low") < found.index("player_down") < found.index("respawned")


def test_countermeasure_burst_size_is_learnt():
    recorded = load_frames("countermeasures_2026-10-28.jsonl")
    handler, _, _ = replay(recorded)
    last = {cm["type"]: cm.get("amount", 0) for cm in recorded[-1][1]["weapons"]["countermeasures"]}
    cms = handler.state["weapons"]["countermeasures"]
    assert cms["decoy"]["count"] == last["COUNTERMEASURE_TYPE_DECOY"] < 96 and cms["decoy"]["burst"] == 2
    assert cms["noise"]["count"] == last["COUNTERMEASURE_TYPE_NOISE"] == 4 and cms["noise"]["burst"] == 2


def test_ursa_sends_no_vehicle_frame():
    handler, events, _ = replay(load_frames("ursa_2026-10-28.jsonl"))
    assert handler.state["vehicle"] is None
    assert handler.state["player"]["locomotion"] == "seated"
    assert handler.state["weapons"]["weapons"]
    assert not [e for e in events if e.id == "vehicle_changed"]
    assert [e.data["vehicle"] for e in events if e.id == "ground_vehicle_entered"] == ["RSI Ursa Rover"]


def test_boarding_a_ship_is_not_mistaken_for_a_ground_vehicle():
    # The Ironclad's vehicle frame arrived 6-9 s after sitting down in each seat.
    _, events, _ = replay(load_frames("module_separation_2026-10-27.jsonl"))
    assert "ground_vehicle_entered" not in ids(events)


def test_sprint_exhaustion():
    _, events, _ = replay(load_frames("sprint_2026-10-27.jsonl"))
    assert ids(events).count("exhausted") == 1


def test_power_restart():
    _, events, _ = replay(load_frames("power_restart_2026-10-27.jsonl"))
    found = ids(events)
    assert "powerplant_offline" in found and "powerplant_online" in found
    assert found.index("powerplant_offline") < found.index("powerplant_online")
