"""The UEX skill as a whole: its tool lock across turns, the blacklists after a fresh import,
which Wingman owns it, and the log files."""

import asyncio
import os
import threading
import time
from os import path
from types import SimpleNamespace

import pytest
import yaml

import skills.uexcorp.main as skill_module
from api.interface import SkillConfig
from skills.uexcorp.uexcorp.handler.debug_handler import DebugHandler
from skills.uexcorp.uexcorp.handler.error_handler import ErrorHandler
from skills.uexcorp.uexcorp.handler.tool_handler import ToolHandler


# ── Tool lock ───────────────────────────────────────────────────────


def _run_turn(coroutine, results: dict, name: str) -> None:
    """A turn as Core runs it: a thread with an event loop of its own."""
    loop = asyncio.new_event_loop()
    try:
        results[name] = loop.run_until_complete(coroutine)
    except Exception as e:
        results[name] = e
    finally:
        loop.close()


def test_a_second_turn_gets_the_tool_after_the_first_one():
    """An asyncio.Lock shared by two turns never woke the second one, and refused every later call."""
    handler = ToolHandler(SimpleNamespace())

    async def slow_tool(tool_name, parameters):
        await asyncio.sleep(0.3)
        return tool_name, ""

    handler._ToolHandler__execute_tool = slow_tool
    results = {}
    first = threading.Thread(target=_run_turn, args=(handler.execute_tool("first", {}), results, "first"), daemon=True)
    first.start()
    time.sleep(0.1)
    second = threading.Thread(target=_run_turn, args=(handler.execute_tool("second", {}), results, "second"), daemon=True)
    second.start()
    first.join(3)
    second.join(3)

    assert results == {"first": ("first", ""), "second": ("second", "")}
    _run_turn(handler.execute_tool("later", {}), results, "later")
    assert results["later"] == ("later", "")


def test_a_turn_cancelled_while_waiting_leaves_the_tool_free():
    handler = ToolHandler(SimpleNamespace())
    lock = handler._ToolHandler__lock

    async def tool(tool_name, parameters):
        return tool_name, ""

    handler._ToolHandler__execute_tool = tool

    async def cancelled_while_waiting():
        lock.acquire()  # another turn runs a tool
        waiting = asyncio.ensure_future(handler.execute_tool("waiting", {}))
        await asyncio.sleep(0.1)
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)
        lock.release()

    asyncio.run(cancelled_while_waiting())
    assert not lock.locked()


# ── Blacklists after an import ──────────────────────────────────────


def test_blacklists_apply_before_the_skill_is_ready(tmp_path, monkeypatch):
    """A fresh import replaces the tables: the user's blacklists must be back before the
    tools run, not only on the next refresh ten minutes later."""
    from skills.uexcorp.uexcorp.database.database import Database
    from skills.uexcorp.uexcorp.handler import config_handler
    from skills.uexcorp.uexcorp.helper import Helper

    monkeypatch.setattr(config_handler, "get_writable_dir", lambda folder: os.makedirs(folder, exist_ok=True) or folder)
    null = SimpleNamespace(write=lambda *a, **k: None)
    helper = SimpleNamespace(
        get_data_path=lambda: str(tmp_path),
        get_handler_debug=lambda: null,
        get_handler_error=lambda: null,
        get_handler_import=lambda: SimpleNamespace(has_data=lambda: True, get_common_data=lambda: {}),
        is_ready=lambda: False,
    )
    database = Database(str(tmp_path), version="test-blacklists", helper=helper)
    helper.get_database = lambda: database
    monkeypatch.setattr(Helper, "_instance", helper)
    try:
        database.execute("INSERT INTO commodity (id, name, is_illegal, is_blacklisted) VALUES (11, 'Tin', 0, 0)")
        database.execute("INSERT INTO terminal (id, name, type, is_available, is_blacklisted) VALUES (5, 'Levski', 'commodity', 1, 0)")
        database.commit()
        handler = config_handler.ConfigHandler(helper)
        config = tmp_path / "config"
        (config / "commodity_blacklist.yaml").write_text(yaml.dump([{"id": 11, "is_blacklisted": True}]))
        (config / "terminal_blacklist.yaml").write_text(yaml.dump([{"id": 5, "is_blacklisted": True}]))

        handler.sync_blacklists()

        assert database.execute_fetchall("SELECT is_blacklisted FROM commodity WHERE id = 11")[0][0] == 1
        assert database.execute_fetchall("SELECT is_blacklisted FROM terminal WHERE id = 5")[0][0] == 1
    finally:
        database.destroy()


# ── Which Wingman owns the skill ────────────────────────────────────
#
# Data, trade run and HUD panel are shared by every Wingman with the skill, so only one may use it.
# Every Wingman with the skill in its config gets a skill object at start, in parallel. The owner
# used to be whichever was created first, even one that never activated UEX: another Wingman was
# then told "already initialized with <a Wingman that is gone>" until Core restarted.


class FakeSkillHelper:
    """The parts of Helper the skill class uses, without a database in the user's folders."""

    _instance = None
    destroyed = 0
    settings_read_by: list[str] = []  # whose skill settings were read, in order

    @classmethod
    def get_instance(cls) -> "FakeSkillHelper":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def destroy_instance(cls) -> None:
        cls.destroyed += 1
        cls._instance = None

    def __init__(self):
        self.prepared_by = None
        self.owner = None
        self.wingman = None
        self.debug = SimpleNamespace(write=lambda *a, **k: None)
        self.import_handler = SimpleNamespace(
            is_running=lambda: False, request_completion=lambda: None, prepare=lambda preload=False: None
        )

    def is_prepared(self) -> bool:
        return self.prepared_by is not None

    def prepare(self, run_in_thread, wingman) -> None:
        self.prepared_by = wingman.name
        self.wingman = wingman

    def get_owner(self):
        return self.owner

    def claim(self, wingman) -> None:
        self.owner, self.wingman = wingman.name, wingman

    def get_wingmen(self):
        return self.wingman

    def get_handler_debug(self):
        return self.debug

    def get_handler_import(self):
        return self.import_handler

    def get_handler_config(self):
        async def validate(errors, retrieve):
            FakeSkillHelper.settings_read_by.append(retrieve.__self__.wingman.name)
            return errors
        return SimpleNamespace(validate=validate)

    def get_handler_tool(self):
        async def execute_tool(name, parameters):
            return f"{name} ran", ""
        return SimpleNamespace(execute_tool=execute_tool, get_tools=lambda: [])

    def set_loaded(self, loaded: bool = True) -> None:
        pass


class Benchmark:
    def start_snapshot(self, *args):
        pass

    def finish_snapshot(self):
        pass


@pytest.fixture
def make_skill(monkeypatch):
    """Skill objects for Wingmen of a given name, all on one fake shared helper."""
    FakeSkillHelper._instance = None
    FakeSkillHelper.destroyed = 0
    FakeSkillHelper.settings_read_by = []
    monkeypatch.setattr(skill_module, "Helper", FakeSkillHelper)

    async def start(skill):  # the skill's own trade run HUD refresh needs the real store: not part of this test
        pass

    monkeypatch.setattr(skill_module.UEXCorp, "_UEXCorp__start", start)
    with open(path.join(path.dirname(skill_module.__file__), "default_config.yaml"), encoding="utf-8") as file:
        config = yaml.safe_load(file)

    def make(name: str) -> skill_module.UEXCorp:
        async def remove_info(title):
            return True

        wingman = SimpleNamespace(name=name, run_in_thread=lambda *a, **k: None, hud=SimpleNamespace(remove_info=remove_info))
        return skill_module.UEXCorp(SkillConfig(**config), SimpleNamespace(), wingman)
    return make


def activate(skill) -> None:
    asyncio.run(skill.validate())
    asyncio.run(skill.prepare())


def call(skill) -> str:
    return asyncio.run(skill.execute_tool("uex_get_trade_routes", {}, Benchmark()))[0]


def test_the_wingman_that_activates_the_skill_owns_it_not_the_first_one_created(make_skill):
    first, second = make_skill("Orionis"), make_skill("Computer")
    assert FakeSkillHelper.get_instance().prepared_by == "Orionis"  # the download starts early

    activate(second)
    activate(first)

    assert FakeSkillHelper.get_instance().get_owner() == "Computer"
    assert call(second) == "uex_get_trade_routes ran"
    assert "already initialized with 'Computer'" in call(first)


def test_only_the_owner_ends_the_shared_helper(make_skill):
    owner, other = make_skill("Computer"), make_skill("Orionis")
    activate(owner)
    activate(other)

    asyncio.run(other.unload())
    assert FakeSkillHelper.destroyed == 0

    asyncio.run(owner.unload())
    assert FakeSkillHelper.destroyed == 1


def test_another_wingman_takes_over_once_the_owner_is_gone(make_skill):
    owner, other = make_skill("Computer"), make_skill("Orionis")
    activate(owner)
    activate(other)

    asyncio.run(owner.unload())  # e.g. the Wingman was switched off

    assert call(other) == "uex_get_trade_routes ran"
    assert FakeSkillHelper.get_instance().get_owner() == "Orionis"
    assert FakeSkillHelper.settings_read_by == ["Computer", "Orionis"]  # the new owner's own settings, not the defaults


def test_a_reloaded_wingman_keeps_the_helper_its_new_skill_claimed(make_skill):
    old = make_skill("Orionis")
    activate(old)
    new = make_skill("Orionis")  # config saved: a new skill object, the old one unloads after
    activate(new)

    asyncio.run(old.unload())

    assert FakeSkillHelper.destroyed == 0
    assert call(new) == "uex_get_trade_routes ran"


# ── Log files ───────────────────────────────────────────────────────


@pytest.fixture
def log_helper(tmp_path):
    return SimpleNamespace(
        get_data_path=lambda: str(tmp_path), is_debug=lambda: True, get_default_thread_ident=threading.get_ident,
        get_version_skill_short=lambda: "v3", get_version_skill=lambda: "v3.0.0",
    )


def test_game_names_outside_cp1252_are_written_to_the_logs(log_helper):
    """Windows' default encoding must not crash a tool over a name like 'Yāi'."""
    debug, error = DebugHandler(log_helper), ErrorHandler(log_helper)

    debug.write("Aopoa San tok.Yāi")
    error.write("tool", ["Katsu Karē Kacho"], ValueError("Karē"))

    assert "Yāi" in debug.read()
    assert "Karē" in error.read()


def test_the_debug_log_keeps_one_old_file(log_helper):
    debug = DebugHandler(log_helper)
    debug.MAX_SIZE = 100

    for i in range(20):
        debug.write(f"line {i} " + "x" * 20)

    assert os.path.getsize(debug.get_debug_file_path()) <= 200
    assert os.path.exists(debug.get_debug_file_path() + ".1")
