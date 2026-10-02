"""The Star Citizen Events skill on top of Core's log reader.

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
from wingmen.facade import SkillScGameLog

CONFIG = path.join(REPO_ROOT, "skills", "sc_game_events", "default_config.yaml")


class FakeWingman:
    def __init__(self, loaded_skills=()):
        self.name = "Computer"
        self.said: list[str] = []
        self.shown: list[str] = []
        self.history: list[str] = []
        self.prompts: list[tuple[str, str]] = []
        self.on_hud: list[str] = []
        self.sc_gamelog = SkillScGameLog()
        self.language = SimpleNamespace(name="German")
        self.config = SimpleNamespace(prompts=SimpleNamespace(backstory="A calm ship AI."))

        async def generate(text, system="", preset=None):
            self.prompts.append((system, text))
            return '"Armistice, keep your weapons cold."'

        async def speak(text, interrupt=True):
            self.said.append(text)

        async def show(text, skill_name=""):
            self.shown.append(text)

        async def add_assistant(text):
            self.history.append(text)

        async def show_message(title, text, duration=10.0, color=None):
            self.on_hud.append(text)
            return True

        self.hud = SimpleNamespace(show_message=show_message)
        self.skills = SimpleNamespace(has=lambda name: name in loaded_skills)
        self.local_ai = SimpleNamespace(available=True, generate=generate)
        self.ai = SimpleNamespace(generate=generate)
        self.tts = SimpleNamespace(speak=speak)
        self.audio = SimpleNamespace(is_playing=False)
        self.conversation = SimpleNamespace(show=show, add_assistant=add_assistant)


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
    assert wingman.shown == wingman.said == wingman.history == wingman.on_hud
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


def test_switched_off_categories_stay_quiet(reader, tmp_path):
    log = write_game_log(tmp_path, FIRST, LOGIN)
    wingman = FakeWingman()

    async def run():
        await reader.start(str(tmp_path / "game"))
        skill = _skill(wingman, react_safety=False)
        await skill.prepare()
        await until(lambda: reader.state() is not None)
        with log.open("a") as stream:
            stream.write(ARMISTICE)
        await asyncio.sleep(0.3)
        await skill.unload()
        await reader.stop()

    asyncio.run(run())
    assert wingman.said == []


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


def test_the_hud_skill_shows_it_so_the_line_is_not_shown_twice(reader, tmp_path):
    log = write_game_log(tmp_path, FIRST, LOGIN)
    wingman = FakeWingman(loaded_skills=("HUD",))

    async def run():
        await reader.start(str(tmp_path / "game"))
        skill = _skill(wingman)
        await skill.prepare()
        await until(lambda: reader.state() is not None)
        with log.open("a") as stream:
            stream.write(ARMISTICE)
        await until(lambda: wingman.said)
        await skill.unload()
        await reader.stop()

    asyncio.run(run())
    assert wingman.history == wingman.said  # The HUD skill picks it up from there.
    assert wingman.on_hud == []


def _burst(log, count, minute=20):
    """`count` different contracts, one right after the other."""
    with log.open("a") as stream:
        for n in range(count):
            stream.write(
                CONTRACT.replace("10:00:03", f"10:{minute}:{n:02d}")
                .replace("abc-123", f"burst-{minute}-{n}")
                .replace("Big Delivery", f"Delivery {minute} {n}")
            )


def test_zero_means_no_limit(reader, tmp_path):
    log = write_game_log(tmp_path, FIRST, LOGIN)
    wingman = FakeWingman()

    async def run():
        await reader.start(str(tmp_path / "game"))
        skill = _skill(wingman, max_unanswered=0)
        await skill.prepare()
        await until(lambda: reader.state() is not None)
        skill._unanswered = 500  # Long past any limit, and the user kept quiet.
        _burst(log, 1)
        await until(lambda: len(wingman.said) == 1)
        await skill.unload()
        await reader.stop()

    asyncio.run(run())


def test_never_talks_over_the_wingman(reader, tmp_path):
    log = write_game_log(tmp_path, FIRST, LOGIN)
    wingman = FakeWingman()
    wingman.audio.is_playing = True  # Answering the user right now.

    async def run():
        await reader.start(str(tmp_path / "game"))
        skill = _skill(wingman, max_unanswered=0)
        await skill.prepare()
        await until(lambda: reader.state() is not None)
        _burst(log, 3, minute=20)
        await asyncio.sleep(0.5)
        await skill.unload()
        await reader.stop()

    asyncio.run(run())
    assert wingman.said == []
