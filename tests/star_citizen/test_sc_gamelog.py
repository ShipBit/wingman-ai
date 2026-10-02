"""Core's Star Citizen Game.log reader (services/sc_gamelog).

What must hold: history builds the state but is never announced, a restart
does not write the same log into the history twice, one failing subscriber
does not stop the others, and the rules fall back instead of breaking when
GitHub is down or publishes something broken.
"""

import asyncio
import json
import sqlite3

import pytest

from api.enums import ScGameLogRulesProblem
from services.sc_gamelog import rules as rules_module
from services.sc_gamelog.reader import Instructions, bundled_bytes
from services.sc_gamelog.rules import RulesSource
from tests.star_citizen.gamelog import ARMISTICE, CONTRACT, FIRST, LOGIN, until, write_game_log


def _rules_bytes(revision: int, **changes) -> bytes:
    data = json.loads(bundled_bytes())
    data["revision"] = revision
    data["version"] = f"test-{revision}"
    data.update(changes)
    return json.dumps(data).encode()


def test_history_builds_state_but_is_not_announced(reader, tmp_path):
    log = write_game_log(tmp_path, FIRST, LOGIN, ARMISTICE)

    async def run():
        heard = []
        reader.subscribe("*", heard.append)
        await reader.start(str(tmp_path / "game"))
        await until(lambda: reader.recent(10, {"armistice_zone"}))
        assert heard == []
        assert reader.state()["player_name"] == "TestPilot"

        with log.open("a") as stream:
            stream.write(CONTRACT)
        await until(lambda: heard)
        await reader.stop()
        return heard

    heard = asyncio.run(run())
    assert [event.type for event in heard] == ["mission_accepted"]
    assert heard[0].catching_up is False
    assert heard[0].data["mission_id"] == "abc-123"


def test_a_failing_subscriber_does_not_stop_the_others(reader, tmp_path):
    log = write_game_log(tmp_path, FIRST, LOGIN)

    async def run():
        heard = []

        async def broken(event):
            raise RuntimeError("skill bug")

        reader.subscribe("*", broken)
        reader.subscribe("armistice_zone", heard.append)
        await reader.start(str(tmp_path / "game"))
        await until(lambda: reader.state() is not None)
        with log.open("a") as stream:
            stream.write(ARMISTICE)
            stream.write(ARMISTICE.replace("10:00:02", "10:00:05"))
        await until(lambda: len(heard) == 2)
        await reader.stop()

    asyncio.run(run())


def test_a_restart_does_not_duplicate_the_history(reader, tmp_path):
    write_game_log(tmp_path, FIRST, LOGIN, ARMISTICE, CONTRACT)

    async def read_once():
        await reader.start(str(tmp_path / "game"))
        await until(lambda: reader.recent(10, {"mission_accepted"}))
        database = reader.database_path
        await reader.stop()
        return database

    database = asyncio.run(read_once())
    count = sqlite3.connect(database).execute("SELECT COUNT(*) FROM events").fetchone()[0]
    asyncio.run(read_once())
    again = sqlite3.connect(database).execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert count > 0 and again == count

    # SC Accountant reads these two keys to recognize the feed.
    keys = dict(sqlite3.connect(database).execute("SELECT key, value FROM metadata"))
    assert keys["erp_feed_contract_version"] == "1"
    assert keys["erp_feed_source_id"]


def test_a_new_game_launch_is_live_not_history(reader, tmp_path):
    log = write_game_log(tmp_path, FIRST, LOGIN)

    async def run():
        heard = []
        reader.subscribe("armistice_zone", heard.append)
        await reader.start(str(tmp_path / "game"))
        await until(lambda: reader.state() is not None)
        # The game starts again: a new Game.log with a new first line.
        log.write_text(FIRST.replace("10:00:00", "11:00:00") + LOGIN + ARMISTICE)
        await until(lambda: heard)
        await reader.stop()

    asyncio.run(run())


# --- rules -----------------------------------------------------------------


def _source(tmp_path, monkeypatch, status, raw=b"", etag=None) -> RulesSource:
    async def fetch(self):
        return status, raw, etag

    monkeypatch.setattr(RulesSource, "_fetch", fetch)
    return RulesSource(str(tmp_path))


def test_newer_valid_rules_are_taken_and_cached(tmp_path, monkeypatch):
    bundled = Instructions.load(bundled_bytes()).revision
    source = _source(tmp_path, monkeypatch, 200, _rules_bytes(bundled + 1), '"e1"')
    newer = asyncio.run(source.check())
    assert newer is not None and newer.revision == bundled + 1
    assert source.status.problem is None

    # The next start begins with the cached download.
    assert RulesSource(str(tmp_path)).status.source == "downloaded"


def test_an_older_revision_is_ignored(tmp_path, monkeypatch):
    source = _source(tmp_path, monkeypatch, 200, _rules_bytes(1))
    assert asyncio.run(source.check()) is None
    assert source.status.source == "bundled"


def test_unreachable_github_keeps_the_rules_and_says_so(tmp_path, monkeypatch):
    source = _source(tmp_path, monkeypatch, 404)
    before = source.instructions
    assert asyncio.run(source.check()) is None
    assert source.instructions is before
    assert source.status.problem == ScGameLogRulesProblem.UNREACHABLE


def test_broken_rules_are_rejected(tmp_path, monkeypatch):
    bundled = Instructions.load(bundled_bytes()).revision
    source = _source(tmp_path, monkeypatch, 200, _rules_bytes(bundled + 1, rules=[]))
    assert asyncio.run(source.check()) is None
    assert source.status.problem == ScGameLogRulesProblem.INVALID


def test_rules_that_need_a_newer_reader(tmp_path, monkeypatch):
    bundled = Instructions.load(bundled_bytes()).revision
    raw = _rules_bytes(bundled + 1, minimum_reader_version="99.0.0")
    source = _source(tmp_path, monkeypatch, 200, raw)
    assert asyncio.run(source.check()) is None
    assert source.status.problem == ScGameLogRulesProblem.NEEDS_UPDATE


def test_the_maintainer_comes_from_the_rules(tmp_path, monkeypatch):
    bundled = Instructions.load(bundled_bytes()).revision
    maintainer = {"name": "Mallachi", "discord": "mallachi"}
    source = _source(
        tmp_path, monkeypatch, 200, _rules_bytes(bundled + 1, maintainer=maintainer)
    )
    asyncio.run(source.check())
    assert source.status.maintainer == maintainer


def test_the_default_maintainer_without_one_in_the_rules(tmp_path, monkeypatch):
    source = _source(tmp_path, monkeypatch, 304)
    assert source.status.maintainer == rules_module.DEFAULT_MAINTAINER


def test_a_maintainer_link_must_be_https():
    with pytest.raises(Exception):
        Instructions.load(_rules_bytes(9, maintainer={"name": "X", "url": "javascript:alert(1)"}))
    ok = Instructions.load(_rules_bytes(9, maintainer={"name": "X", "url": "https://example.org"}))
    assert ok.data["maintainer"]["url"] == "https://example.org"


def test_rules_arriving_in_pieces_are_read_whole(tmp_path, monkeypatch):
    """aiohttp's read(n) returns what has arrived, not n bytes."""
    body = _rules_bytes(9)

    class Content:
        def __init__(self):
            self.parts = [body[i : i + 1000] for i in range(0, len(body), 1000)]

        async def readany(self):
            return self.parts.pop(0) if self.parts else b""

    class Response:
        status = 200
        headers = {"ETag": "abc"}
        content = Content()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class Session:
        def __init__(self, **kw):
            pass

        def get(self, *a, **kw):
            return Response()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(rules_module.aiohttp, "ClientSession", Session)
    source = RulesSource(str(tmp_path))
    status, raw, etag = asyncio.run(source._fetch())
    assert status == 200 and raw == body and etag == "abc"


def test_quick_saves_leave_one_reader(reader, tmp_path):
    """Without the switch lock this left two threads and crashed on a closed database."""
    import threading

    write_game_log(tmp_path, FIRST, LOGIN)
    game = str(tmp_path / "game")

    async def run():
        await reader.start(game)
        await asyncio.gather(
            reader.apply_settings(False, game),
            reader.apply_settings(True, game),
            reader.apply_settings(True, game + "x"),
            reader.apply_settings(True, game),
        )
        await asyncio.sleep(0.3)
        readers = [t for t in threading.enumerate() if t.name == "sc-gamelog"]
        assert len(readers) == 1 and reader._history is not None
        await reader.stop()

    asyncio.run(run())
