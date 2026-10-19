"""The UEX skill: its tool lock across turns, the blacklists after a fresh import,
and a trade run's recorded purchase that the plan split in two."""

import asyncio
import os
import threading
import time
from types import SimpleNamespace

import yaml

from skills.uexcorp.uexcorp.active_trade_route import ActiveTradeRoute
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


# ── Trade run ───────────────────────────────────────────────────────


def _gold_split_in_two(tmp_path) -> ActiveTradeRoute:
    """Stop 1 buys 1000 Gold in two parts: 300 for stop 2 (short on demand), 700 for stop 3."""
    store = ActiveTradeRoute(SimpleNamespace(get_data_path=lambda: str(tmp_path)))
    stops = [
        {"terminal": "A", "buy": [
            {"commodity": "Gold", "scu": 300, "total_aUEC": 3000, "price_per_scu": 10, "sell_at": None},
            {"commodity": "Gold", "scu": 700, "total_aUEC": 7000, "price_per_scu": 10, "sell_at": "C"},
        ]},
        {"terminal": "B", "sell": [{"commodity": "Gold", "scu": 300, "total_aUEC": 6000, "price_per_scu": 20}]},
        {"terminal": "C", "sell": [{"commodity": "Gold", "scu": 700, "total_aUEC": 14000, "price_per_scu": 20}]},
    ]
    store.remember_search([{"stops": stops, "estimated_profit": 10000, "hold_scu": 1000}])
    assert store.set(1)
    return store


def _sales(active: dict) -> list[int]:
    return [stop["sell"][0]["scu"] for stop in active["route"]["stops"][1:]]


def test_a_purchase_the_plan_split_in_two_is_recorded_as_planned(tmp_path):
    store = _gold_split_in_two(tmp_path)

    active, problem, warnings = store.record("buy", "Gold", 1000, 10000)

    assert problem is None
    assert warnings == []
    assert [e["scu"] for e in active["route"]["stops"][0]["buy"]] == [300, 700]
    assert _sales(active) == [300, 700]
    assert active["route"]["estimated_profit"] == 10000


def test_a_smaller_purchase_takes_the_missing_cargo_from_the_last_part(tmp_path):
    store = _gold_split_in_two(tmp_path)

    active, _, warnings = store.record("buy", "Gold", 900, 9900)

    assert [e["scu"] for e in active["route"]["stops"][0]["buy"]] == [300, 600]
    assert _sales(active) == [300, 600]
    assert active["route"]["estimated_profit"] == 300 * 20 + 600 * 20 - 9900
    assert warnings == []
