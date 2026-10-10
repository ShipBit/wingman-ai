"""SC Accountant as a bundled skill on top of Core's Star Citizen log reader.

Two Wingmen with the skill share one set of books, a reward in the log is
booked without any tool call, the dashboard dialog appears once, and books
that read the old SC Log Reader skill move over without booking twice.
"""

import asyncio
import json
import sqlite3
from os import path
from types import SimpleNamespace

import pytest
import yaml

from api.interface import SkillConfig
from services import skill_dialogs
from tests.star_citizen.gamelog import FIRST, LOGIN, until, write_game_log
from tests.support import REPO_ROOT
from wingmen.facade import SkillScGameLog

CONFIG = path.join(REPO_ROOT, "skills", "sc_accountant", "default_config.yaml")
REWARD = (
    '<2026-09-28T10:10:00.000Z> [Notice] <SHUDEvent> Added notification '
    '"Awarded 500 aUEC:" [14] to queue.\n'
)


@pytest.fixture
def reader(reader, tmp_path, monkeypatch):
    """The shared reader, plus a fresh set of books and no real browser tab."""
    monkeypatch.setattr(skill_dialogs, "get_users_dir", lambda: str(tmp_path))
    import skills.sc_accountant.main as accountant

    monkeypatch.setattr(accountant, "CAPTURE_DELAY_SECONDS", 0.05)
    monkeypatch.setattr(accountant.webbrowser, "open", lambda url: True)
    accountant._Books._instance = None
    accountant._Books._lock = None
    return reader


class FakeWingman:
    def __init__(self, name, dialogs):
        self.name = name
        self.sc_gamelog = SkillScGameLog()

        async def show_dialog(title, text, *, image=None, once=None):
            if once and skill_dialogs.was_shown(once):
                return False
            dialogs.append((name, title, text, image))
            if once:
                skill_dialogs.mark_shown(once)
            return True

        self.ui = SimpleNamespace(show_dialog=show_dialog)


def _skill(wingman, data_dir):
    from skills.sc_accountant.main import SC_Accountant

    raw = yaml.safe_load(open(CONFIG, encoding="utf-8"))
    for prop in raw["custom_properties"]:
        if prop["id"] == "dashboard_port":
            prop["value"] = 17863
    skill = SC_Accountant(SkillConfig(**raw), SimpleNamespace(), wingman)
    skill.get_generated_files_dir = lambda: str(data_dir)
    return skill


def test_two_wingmen_share_the_books_and_a_reward_is_booked(reader, tmp_path):
    log = write_game_log(tmp_path, FIRST, LOGIN)
    dialogs = []

    async def run():
        await reader.start(str(tmp_path / "game"))
        one = _skill(FakeWingman("Computer", dialogs), tmp_path / "books")
        two = _skill(FakeWingman("ATC", dialogs), tmp_path / "books")
        await one.prepare()
        await two.prepare()
        assert one._books is two._books and one._books.users == 2

        with log.open("a") as stream:
            stream.write(REWARD)

        async def booked():
            report = json.loads(await one.erp_report("overview"))
            return report["data"]["balance"] == "500.00"

        for _ in range(100):
            if await booked():
                break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError(await one.erp_report("overview"))

        books = one._books
        await one.unload()
        assert books.engine is not None  # ATC still uses them.
        answer = await two.erp_dashboard()
        await two.unload()
        assert books.engine is None and books.server is None
        await reader.stop()
        return answer

    answer = asyncio.run(run())
    assert "127.0.0.1:17863" in answer
    # Once at the first start, then only because the dashboard was asked for.
    assert [name for name, *_ in dialogs] == ["Computer", "ATC"]
    assert all(title == "Accountant dashboard" for _, title, _, _ in dialogs)


def test_books_from_the_old_reader_move_over_without_booking_twice(reader, tmp_path):
    from skills.sc_accountant.erp import ERP
    from skills.sc_accountant.erp_feed import capture_once

    write_game_log(tmp_path, FIRST, LOGIN, REWARD)

    async def fill_core_database():
        await reader.start(str(tmp_path / "game"))
        await until(lambda: reader.recent(5, {"reward_earned"}))
        database = reader.database_path
        await reader.stop()
        return database

    database = asyncio.run(fill_core_database())
    engine = ERP(tmp_path / "books" / "erp.sqlite3")
    # Books that the old skill's database fed: a different source, a cursor.
    engine.bind_core_reader("old-reader-source", 42)
    with engine.lock, engine.db:
        feed = engine._setting("feed")
        feed["core_reader"] = False
        engine._set("feed", feed)

    capture_once(engine, database)
    feed = engine.view("feed")["data"]
    high_water = sqlite3.connect(database).execute("SELECT MAX(id) FROM events").fetchone()[0]
    assert feed["core_reader"] is True
    assert feed["previous_source_id"] == "old-reader-source"
    assert feed["cursor"] == high_water  # What Core read before is not booked again.
    overview = engine.view("overview")["data"]
    assert (overview["balance"], overview["cash_flow"]) == ("0.00", "0.00")
    engine.close()
