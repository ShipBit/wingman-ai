"""The Star Citizen Events skill on top of Core's log reader and telemetry.

The Wingman must stay quiet about the log's history, react to what happens
now, stop after the set number of reactions until the user speaks, and answer
questions about the state in a few short lines.
"""

import asyncio
from os import path
from types import SimpleNamespace

import yaml

from api.interface import SkillConfig
from tests.star_citizen.gamelog import ARMISTICE, CONTRACT, FIRST, LOGIN, until, write_game_log
from tests.support import REPO_ROOT
from services.sc_telemetry.events import make_event
from tests.star_citizen.telemetry import load_frames, replay
from wingmen.facade import SkillScGameLog, SkillScTelemetry

CONFIG = path.join(REPO_ROOT, "skills", "sc_game_events", "default_config.yaml")


class FakeAudio:
    """What the tests set is an answer playing: important enough to wait for."""

    is_playing = False

    def is_playing_at_least(self, priority):
        return self.is_playing


class FakeWingman:
    def __init__(self, loaded_skills=()):
        self.name = "Computer"
        self.said: list[str] = []
        self.shown: list[str] = []
        self.history: list[str] = []
        self.prompts: list[tuple[str, str]] = []
        self.on_hud: list[str] = []
        self.sc_gamelog = SkillScGameLog()
        self.sc_telemetry = SkillScTelemetry()
        self.language = SimpleNamespace(name="German")
        self.config = SimpleNamespace(prompts=SimpleNamespace(backstory="A calm ship AI."))

        async def generate(text, system="", preset=None):
            self.prompts.append((system, text))
            return '"Armistice, keep your weapons cold."'

        async def speak(text, interrupt=True, priority=None):
            self.said.append(text)
            return True

        async def show(text, skill_name=""):
            self.shown.append(text)

        async def add_note(text):
            self.history.append(text)

        async def show_message(title, text, duration=10.0, color=None):
            self.on_hud.append(text)
            return True

        self.hud = SimpleNamespace(show_message=show_message)
        self.skills = SimpleNamespace(has=lambda name: name in loaded_skills)
        self.local_ai = SimpleNamespace(available=True, generate=generate)
        self.ai = SimpleNamespace(generate=generate)
        self.tts = SimpleNamespace(speak=speak)
        self.audio = FakeAudio()
        self.conversation = SimpleNamespace(show=show, add_note=add_note, user_busy=False)


def _skill(wingman, **values):
    from skills.sc_game_events.main import ScGameEvents

    raw = yaml.safe_load(open(CONFIG, encoding="utf-8"))
    for prop in raw["custom_properties"]:
        if prop["id"] in values:
            prop["value"] = values[prop["id"]]
    return ScGameEvents(SkillConfig(**raw), SimpleNamespace(), wingman)


def test_reacts_to_live_events_only(reader, tmp_path):
    log = write_game_log(tmp_path, FIRST, LOGIN, ARMISTICE)
    wingman = FakeWingman()

    async def run():
        await reader.start(str(tmp_path / "game"))
        skill = _skill(wingman)
        await skill.prepare()
        await until(lambda: reader.state() is not None)
        await asyncio.sleep(0.2)
        assert wingman.said == []  # The armistice zone in the history stays quiet.

        with log.open("a") as stream:
            stream.write(ARMISTICE.replace("10:00:02", "10:05:00"))
        await until(lambda: wingman.said)
        await skill.unload()
        await reader.stop()

    asyncio.run(run())
    assert wingman.said == ["Armistice, keep your weapons cold."]
    assert wingman.shown == wingman.said == wingman.on_hud
    system, text = wingman.prompts[0]
    assert "German" in system and "A calm ship AI." in system
    assert "armistice" in text.lower() and text.endswith("in German:")


def test_stops_after_the_set_number_until_the_user_speaks(reader, tmp_path):
    log = write_game_log(tmp_path, FIRST, LOGIN)
    wingman = FakeWingman()

    async def run():
        await reader.start(str(tmp_path / "game"))
        skill = _skill(wingman, max_unanswered=1)
        await skill.prepare()
        await until(lambda: reader.state() is not None)
        with log.open("a") as stream:
            stream.write(ARMISTICE)
        await until(lambda: len(wingman.said) == 1)
        with log.open("a") as stream:
            stream.write(CONTRACT)
        await asyncio.sleep(0.3)
        assert len(wingman.said) == 1

        await skill.on_add_user_message("what now?")
        with log.open("a") as stream:
            stream.write(CONTRACT.replace("abc-123", "def-456").replace("Big", "Small"))
        await until(lambda: len(wingman.said) == 2)
        await skill.unload()
        await reader.stop()

    asyncio.run(run())


def test_a_switched_off_type_stays_quiet_while_its_group_reacts(reader, tmp_path):
    log = write_game_log(tmp_path, FIRST, LOGIN)
    wingman = FakeWingman()

    async def run():
        await reader.start(str(tmp_path / "game"))
        skill = _skill(wingman, react_armistice_zone=False)
        await skill.prepare()
        await until(lambda: reader.state() is not None)
        with log.open("a") as stream:
            stream.write(ARMISTICE)
        await asyncio.sleep(0.3)
        assert wingman.said == []

        with log.open("a") as stream:  # The same group, another type.
            stream.write(
                ARMISTICE.replace("Entering Armistice Zone", "Entered Monitored Space")
                .replace("10:00:02", "10:06:00")
            )
        await until(lambda: wingman.said)
        await skill.unload()
        await reader.stop()

    asyncio.run(run())
    assert len(wingman.prompts) == 1
    assert "monitored space" in wingman.prompts[0][1].lower()


def test_a_purchase_gets_one_reaction_once_it_is_confirmed(reader, tmp_path):
    from tests.star_citizen.test_item_names import BUY, DONE

    log = write_game_log(tmp_path, FIRST, LOGIN)
    wingman = FakeWingman()

    async def run():
        await reader.start(str(tmp_path / "game"))
        skill = _skill(wingman)
        await skill.prepare()
        await until(lambda: reader.state() is not None)
        with log.open("a") as stream:
            stream.write(BUY)
        await asyncio.sleep(0.3)
        assert wingman.said == []  # Only requested so far.
        with log.open("a") as stream:
            stream.write(DONE)
        await until(lambda: wingman.said)
        await asyncio.sleep(0.2)
        await skill.unload()
        await reader.stop()

    asyncio.run(run())
    assert len(wingman.prompts) == 1
    report = wingman.prompts[0][1]
    assert "confirmed" in report and "-17" in report
    assert "Food_burrito_01_a" not in report  # The in-game name, not the class.


def test_every_type_of_event_has_a_switch():
    from skills.sc_game_events.main import SWITCHES
    from skills.sc_game_events.notifications import _TEMPLATES, NOTIFICATION_OPTIONS

    raw = yaml.safe_load(open(CONFIG, encoding="utf-8"))
    ids = {prop["id"] for prop in raw["custom_properties"]}
    assert {f"react_{switch}" for switch in SWITCHES} <= ids
    covered = {kind for kinds in NOTIFICATION_OPTIONS.values() for kind in kinds}
    assert covered == set(_TEMPLATES)


def test_the_tool_answers_in_short_lines(reader, tmp_path):
    write_game_log(tmp_path, FIRST, LOGIN, ARMISTICE, CONTRACT)
    wingman = FakeWingman()

    async def run():
        await reader.start(str(tmp_path / "game"))
        skill = _skill(wingman)
        await until(lambda: reader.recent(5, {"mission_accepted"}))
        answers = {
            topic: await skill.star_citizen_status(topic)
            for topic in ("overview", "missions", "recent_events")
        }
        await reader.stop()
        answers["off"] = await skill.star_citizen_status("overview")
        return answers

    answers = asyncio.run(run())
    assert "Player: TestPilot" in answers["overview"]
    assert "armistice zone" in answers["overview"]
    assert "Big Delivery" in answers["missions"]
    assert "Mission accepted: Big Delivery" in answers["recent_events"]
    assert "switched off" in answers["off"]
    assert all(len(answer) < 600 for answer in answers.values())


def test_the_lines_go_into_the_history_as_a_note_before_the_user_speaks(reader, tmp_path):
    """As the Wingman's own messages they came back appended to its answers."""
    log = write_game_log(tmp_path, FIRST, LOGIN)
    wingman = FakeWingman()

    async def run():
        await reader.start(str(tmp_path / "game"))
        skill = _skill(wingman)
        await skill.prepare()
        await until(lambda: reader.state() is not None)
        with log.open("a") as stream:
            stream.write(ARMISTICE)
        await until(lambda: wingman.said)
        assert wingman.history == []
        await skill.on_add_user_message("land us")
        await skill.on_add_user_message("and now?")
        await skill.unload()
        await reader.stop()

    asyncio.run(run())
    assert len(wingman.history) == 1
    assert "Armistice, keep your weapons cold." in wingman.history[0]


def _burst(log, count, minute=20):
    """`count` different contracts, one right after the other."""
    with log.open("a") as stream:
        for n in range(count):
            stream.write(
                CONTRACT.replace("10:00:03", f"10:{minute}:{n:02d}")
                .replace("abc-123", f"burst-{minute}-{n}")
                .replace("Big Delivery", f"Delivery {minute} {n}")
            )


def test_the_next_reaction_sees_the_last_ones(reader, tmp_path):
    """Without its last lines the model makes the same joke on every event."""
    log = write_game_log(tmp_path, FIRST, LOGIN)
    wingman = FakeWingman()

    async def run():
        await reader.start(str(tmp_path / "game"))
        skill = _skill(wingman, max_unanswered=0)
        await skill.prepare()
        await until(lambda: reader.state() is not None)
        _burst(log, 1, minute=20)
        await until(lambda: len(wingman.said) == 1)
        _burst(log, 1, minute=30)
        await until(lambda: len(wingman.said) == 2)
        await skill.unload()
        await reader.stop()

    asyncio.run(run())
    (first_system, first_text), (second_system, second_text) = wingman.prompts
    assert "Your last lines" not in first_text
    assert "Your last lines:\n- Armistice, keep your weapons cold." in second_text
    assert first_system == second_system  # The same every time, so it can be cached.
    angle = lambda text: text.split("This time: ")[1].splitlines()[0]
    assert angle(first_text) != angle(second_text)


def test_quiet_while_the_user_talks_to_a_wingman(reader, tmp_path):
    log = write_game_log(tmp_path, FIRST, LOGIN)
    wingman = FakeWingman()
    wingman.conversation.user_busy = True  # A push-to-talk key is down.

    async def run():
        await reader.start(str(tmp_path / "game"))
        skill = _skill(wingman, max_unanswered=0)
        await skill.prepare()
        await until(lambda: reader.state() is not None)
        _burst(log, 2, minute=20)
        await asyncio.sleep(0.5)
        await skill.unload()
        await reader.stop()

    asyncio.run(run())
    assert wingman.said == []


# ── what comes while the Wingman is busy, and what comes again ─────────────


def _event(kind, **data):
    return SimpleNamespace(type=kind, status="observed", data=data, environment="LIVE", catching_up=False)


ARRIVAL = (
    _event("armistice_zone", action="entered"),
    _event("jurisdiction_change", jurisdiction="UEE"),
    _event("location_arrived", location_name="Baijini Point"),
)


def _clocked(monkeypatch):
    from skills.sc_game_events import main

    clock = [1000.0]
    monkeypatch.setattr(main, "_now", lambda: clock[0])
    return clock


def test_what_comes_while_the_wingman_speaks_goes_into_the_next_line(monkeypatch):
    clock = _clocked(monkeypatch)
    wingman = FakeWingman()
    wingman.audio.is_playing = True  # Still answering the pilot.

    async def run():
        skill = _skill(wingman, react_location=True, max_unanswered=0)
        for event in ARRIVAL:  # An arrival logs all three within seconds.
            skill._on_event(event)
            clock[0] += 1
        await asyncio.sleep(0.3)
        assert wingman.said == []  # Never over the Wingman's voice.
        wingman.audio.is_playing = False
        await until(lambda: wingman.said)
        await skill.unload()

    asyncio.run(run())
    assert len(wingman.prompts) == 1
    report = wingman.prompts[0][1]
    assert "armistice" in report.lower() and "UEE" in report and "Baijini Point" in report


def test_what_is_stale_by_then_is_dropped(monkeypatch):
    clock = _clocked(monkeypatch)
    wingman = FakeWingman()
    wingman.audio.is_playing = True

    async def run():
        skill = _skill(wingman, react_location=True, max_unanswered=0)
        skill._on_event(ARRIVAL[2])
        await asyncio.sleep(0.3)
        clock[0] += 60  # The pilot talked for a minute.
        await asyncio.sleep(0.4)
        wingman.audio.is_playing = False
        await asyncio.sleep(0.4)
        await skill.unload()

    asyncio.run(run())
    assert wingman.said == []


def test_a_flickering_zone_is_said_once_and_does_not_use_up_the_limit(monkeypatch):
    clock = _clocked(monkeypatch)
    wingman = FakeWingman()

    async def run():
        skill = _skill(wingman, max_unanswered=2)
        skill._on_event(ARRIVAL[0])
        await until(lambda: len(wingman.said) == 1)
        for _ in range(3):  # The game logs it again and again.
            clock[0] += 40
            skill._on_event(ARRIVAL[0])
            await asyncio.sleep(0.2)
        assert len(wingman.said) == 1 and skill._unanswered == 1
        # Something new is still said. A mission: a second zone report would
        # wait for the zone group's gap.
        skill._on_event(_event("mission_accepted", mission_name="Big Delivery", mission_id="m-1"))
        await until(lambda: len(wingman.said) == 2)
        await skill.unload()

    asyncio.run(run())


def test_a_line_finished_after_the_user_started_talking_is_dropped(monkeypatch):
    """Spoken late, it lands in the user's transcript or after their answer."""
    _clocked(monkeypatch)
    wingman = FakeWingman()
    original = wingman.local_ai.generate

    async def slow_generate(text, system="", preset=None):
        wingman.conversation.user_busy = True  # Push-to-talk went down meanwhile.
        return await original(text, system=system, preset=preset)

    wingman.local_ai.generate = slow_generate

    async def run():
        skill = _skill(wingman, max_unanswered=1)
        skill._on_event(_event("mission_accepted", mission_name="Big Delivery", mission_id="m-1"))
        await until(lambda: wingman.prompts)
        await asyncio.sleep(0.2)
        assert wingman.said == [] and skill._unanswered == 0
        await skill.unload()

    asyncio.run(run())


def test_a_trip_keeps_its_arrival(monkeypatch):
    clock = _clocked(monkeypatch)
    wingman = FakeWingman()

    async def run():
        skill = _skill(wingman, react_location=True, max_unanswered=0)
        skill._on_event(_event("quantum_route_set"))
        await until(lambda: len(wingman.said) == 1)
        clock[0] += 90  # The jump: its quantum steps stay paced.
        skill._on_event(_event("quantum_calibration_complete"))
        await asyncio.sleep(0.3)
        assert len(wingman.said) == 1
        clock[0] += 60  # Arriving minutes after the route was set is still said.
        skill._on_event(ARRIVAL[2])
        await until(lambda: len(wingman.said) == 2)
        await skill.unload()

    asyncio.run(run())
    assert "Baijini Point" in wingman.prompts[1][1]


# --- telemetry ------------------------------------------------------------------


def _subscribe(event_type, callback):
    return SimpleNamespace(unsubscribe=lambda: None)


def _sources(wingman, log=True, telemetry=True, state=None, status="live"):
    """Which of Core's two sources run, without starting them."""
    wingman.sc_gamelog = SimpleNamespace(available=log, on=_subscribe, state=lambda: None)
    wingman.sc_telemetry = SimpleNamespace(
        available=telemetry, on=_subscribe, state=lambda: state,
        status=SimpleNamespace(state=SimpleNamespace(value=status)),
    )


def test_every_telemetry_event_has_a_switch_and_every_shared_moment_a_choice():
    from services.sc_telemetry.events import BY_ID
    from skills.sc_game_events import telemetry

    raw = yaml.safe_load(open(CONFIG, encoding="utf-8"))
    props = {prop["id"]: prop for prop in raw["custom_properties"]}
    assert {f"react_{switch}" for switch in telemetry.SWITCHES} <= set(props)
    assert {"react_telemetry_ship", "react_telemetry_pilot"} <= set(props)
    covered = {kind for _, kinds in telemetry.SWITCHES.values() for kind in kinds}
    assert covered == set(BY_ID)
    for topic, (default, _, _) in telemetry.SOURCES.items():
        assert [o["value"] for o in props[topic]["options"]] == ["log", "telemetry"]
        assert props[topic]["value"] == default


def test_a_telemetry_event_is_said_like_a_log_event(monkeypatch):
    _clocked(monkeypatch)
    wingman = FakeWingman()
    _sources(wingman)

    async def run():
        skill = _skill(wingman)
        await skill.prepare()
        skill._on_telemetry(make_event("shields_down", 1.0))
        await until(lambda: wingman.said)
        await skill.unload()

    asyncio.run(run())
    assert "The shields are down." in wingman.prompts[0][1]


def test_a_moment_both_sources_see_is_said_once_from_the_picked_one(monkeypatch):
    """A reward shows in the log (with its amount) and as a wallet change in the telemetry."""
    reward = _event("reward_earned", amount_auec=12500, mission_name="Big Delivery")
    wallet = make_event("uec_changed", 1.0, delta="+12,500", balance="37,500")

    def said_reports(**values):
        _clocked(monkeypatch)
        wingman = FakeWingman()
        _sources(wingman)

        async def run():
            skill = _skill(wingman, max_unanswered=0, **values)
            skill._on_event(reward)
            skill._on_telemetry(wallet)
            await until(lambda: wingman.said)
            await asyncio.sleep(0.2)
            await skill.unload()

        asyncio.run(run())
        return " ".join(text for _, text in wingman.prompts)

    by_default = said_reports()
    assert "Big Delivery" in by_default and "wallet" not in by_default
    picked = said_reports(source_money="telemetry")
    assert "wallet changed by +12,500" in picked and "Big Delivery" not in picked


def test_the_other_source_speaks_while_the_picked_one_is_off(monkeypatch):
    _clocked(monkeypatch)
    wingman = FakeWingman()
    _sources(wingman, telemetry=False)

    async def run():
        skill = _skill(wingman, source_money="telemetry")
        skill._on_event(_event("reward_earned", amount_auec=500, mission_name="Small Delivery"))
        await until(lambda: wingman.said)
        await skill.unload()

    asyncio.run(run())
    assert "Small Delivery" in wingman.prompts[0][1]


def test_a_fight_does_not_repeat_the_same_report(monkeypatch):
    """Telemetry shows hits every few seconds in a fight; one line per cooldown."""
    clock = _clocked(monkeypatch)
    wingman = FakeWingman()
    _sources(wingman)

    async def run():
        skill = _skill(wingman, max_unanswered=0)
        skill._on_telemetry(make_event("under_fire", 1.0))
        await until(lambda: wingman.said)
        for _ in range(5):
            clock[0] += 5
            skill._on_telemetry(make_event("under_fire", 1.0))
        await asyncio.sleep(0.3)
        assert len(wingman.said) == 1
        clock[0] += 90
        skill._on_telemetry(make_event("under_fire", 1.0))
        await until(lambda: len(wingman.said) == 2)
        await skill.unload()

    asyncio.run(run())


def test_switched_off_telemetry_stays_quiet(monkeypatch):
    _clocked(monkeypatch)
    wingman = FakeWingman()
    _sources(wingman)

    async def run():
        skill = _skill(wingman, react_telemetry_ship=False, react_tm_health=False)
        skill._on_telemetry(make_event("shields_down", 1.0))
        skill._on_telemetry(make_event("health_low", 1.0, percent=20))
        skill._on_telemetry(make_event("exhausted", 1.0))
        await until(lambda: wingman.said)
        await asyncio.sleep(0.2)
        await skill.unload()

    asyncio.run(run())
    reports = " ".join(text for _, text in wingman.prompts)
    assert "out of breath" in reports and "shields" not in reports and "health" not in reports


def test_the_tool_answers_about_the_ship_and_the_pilot():
    handler, _, _ = replay(load_frames("combat_2026-10-28.jsonl"))
    wingman = FakeWingman()
    _sources(wingman, state=handler.state)
    skill = _skill(wingman)

    ship = asyncio.run(skill.star_citizen_status("ship"))
    pilot = asyncio.run(skill.star_citizen_status("pilot"))
    assert ship.startswith("Ship: DRAK Cutter (Drake)") and "Warnings:" in ship
    assert "Wallet" in pilot and "aUEC" in pilot
    assert len(ship) < 800 and len(pilot) < 800

    _sources(wingman, state=None, status="game_without_telemetry")
    assert "RSI Launcher" in asyncio.run(skill.star_citizen_status("ship"))
    _sources(wingman, telemetry=False)
    assert "switched off" in asyncio.run(skill.star_citizen_status("pilot"))
