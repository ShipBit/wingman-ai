"""The import from the relay: a failed, broken or interrupted bundle is retried with the next run
without crashing the skill or losing stored data, an outage is reported once, and an unload
or a second import never breaks a running one."""

import asyncio
import threading

from skills.uexcorp.uexcorp.api.uex import Uex
from skills.uexcorp.uexcorp.handler.import_handler import ImportHandler
from skills.uexcorp.uexcorp.handler.tool_handler import ToolHandler
from tests.skills.uexcorp.support import GateRelay, relay

ALL_REQUESTS = {Uex.VERSION, Uex.BUNDLE_LONG, Uex.BUNDLE_SHORT}

# ── Full import and refresh timing ──────────────────────────────────


def test_a_full_import_is_three_requests_and_marks_everything_imported(import_env):
    api = relay()

    import_env.run_import(api)

    assert api.fetched == [Uex.VERSION, Uex.BUNDLE_LONG, Uex.BUNDLE_SHORT]  # the version first, see the parity check
    imports = import_env.imports()
    assert {dataset.table for dataset in ImportHandler.DATASETS} <= set(imports)
    assert {"game_version", "commodity_route", "relay_long", "relay_short"} <= set(imports)
    assert import_env.count("terminal") == 1
    assert import_env.importer.get_imported_percent() == 100
    assert import_env.helper.completed_imports == 1
    assert import_env.helper.error.messages == []
    assert not import_env.debug_messages("failed")


def test_nothing_is_fetched_before_the_relay_has_new_data(import_env):
    import_env.run_import(relay())
    api = relay()

    import_env.run_import(api)

    assert api.fetched == []


def test_the_next_refresh_follows_the_relays_max_age(import_env):
    api = relay()
    api.max_age = 3000

    import_env.run_import(api)

    short = import_env.imports()["relay_short"]
    assert abs((short["date_expires"] - short["date_imported"]) - (3000 + ImportHandler.RELAY_MARGIN)) <= 2
    refresh_in = import_env.importer._ImportHandler__get_refresh_in
    assert refresh_in(10 ** 9, 7200) == 7200  # never longer than the configured lifetime
    assert refresh_in(0, 7200) == ImportHandler.MIN_REFRESH  # a stale relay is not hammered


def test_an_unchanged_bundle_is_not_written_again(import_env):
    import_env.run_import(relay())
    before = import_env.imports()
    import_env.db.execute("UPDATE imports SET date_imported = 1 WHERE `table` = 'terminal'")
    import_env.db.commit()
    import_env.expire(Uex.BUNDLE_LONG)
    api = relay()

    import_env.run_import(api)

    assert api.fetched == [Uex.BUNDLE_LONG]
    imports = import_env.imports()
    assert imports["terminal"]["date_imported"] == 1  # same ETag: tables untouched
    assert imports["relay_long"]["date_expires"] >= before["relay_long"]["date_expires"]


def test_a_changed_bundle_replaces_its_tables_without_duplicating_rows(import_env):
    import_env.run_import(relay(**{Uex.TERMINALS: [
        {"id": 1, "name": "Old", "type": "commodity"}, {"id": 2, "name": "Removed", "type": "commodity"},
    ]}))
    assert import_env.count("terminal") == 2
    import_env.expire(Uex.BUNDLE_LONG)

    import_env.run_import(relay(**{Uex.TERMINALS: [{"id": 1, "name": "Renamed", "type": "commodity"}]}))

    rows = import_env.db.execute_fetchall("SELECT id, name FROM terminal")
    assert [(r["id"], r["name"]) for r in rows] == [(1, "Renamed")]  # removed rows are gone
    buy = import_env.db.execute_fetchall("SELECT is_buy, COUNT(*) AS c FROM commodity_status GROUP BY is_buy")
    assert {r["is_buy"]: r["c"] for r in buy} == {0: 2, 1: 1}  # the status rows are not added a second time


# ── Failures ────────────────────────────────────────────────────────


def test_a_failed_bundle_is_not_marked_and_retried_with_the_next_run(import_env):
    api = relay()
    api.rejected = {Uex.BUNDLE_LONG}

    import_env.run_import(api)

    imports = import_env.imports()
    assert "terminal" not in imports
    assert "commodity_price" in imports  # the other bundle still imports
    assert import_env.importer.get_imported_percent() == 100
    assert any("retried" in m for m in import_env.debug_messages("long bundle"))
    retry = relay()
    import_env.run_import(retry)
    assert retry.fetched == [Uex.BUNDLE_LONG]  # only the failed bundle again
    assert import_env.count("terminal") == 1


def test_a_dataset_missing_from_the_bundle_fails_only_its_table_and_retries_the_bundle(import_env):
    api = relay()
    api.missing = {Uex.TERMINALS}

    import_env.run_import(api)

    imports = import_env.imports()
    assert "terminal" not in imports
    assert "vehicle" in imports  # later tables of the bundle still import
    assert imports["relay_long"]["date_expires"] is None
    retry = relay()
    import_env.run_import(retry)
    assert retry.fetched == [Uex.BUNDLE_LONG]
    assert "terminal" in import_env.imports()


def test_a_malformed_dataset_does_not_stop_the_import(import_env):
    import_env.run_import(relay(**{Uex.COMMODITIES_STATUS: [1, 2, 3], Uex.TERMINALS: [{"name": "no id"}, 5]}))

    assert import_env.importer.get_imported_percent() == 100  # not stuck below
    imports = import_env.imports()
    assert "commodity_status" not in imports
    assert "vehicle" in imports


def test_entries_without_an_id_are_skipped(import_env):
    # The relay lists empty API answers of categories without items as entries
    placeholder = {"data": None, "http_code": 200, "message": "", "status": "ok"}

    import_env.run_import(relay(**{Uex.ITEMS: [{"id": 5, "name": "P4-AR", "id_category": 2}, placeholder, placeholder]}))

    assert import_env.count("item") == 1
    assert "item" in import_env.imports()


def test_a_failed_version_check_keeps_the_known_version_and_is_not_repeated_by_the_import(import_env):
    import_env.run_import(relay())
    api = relay()
    api.failing = {Uex.VERSION}
    import_env.importer._ImportHandler__api = api

    assert import_env.importer.get_version_uex(force_check=True) == "4.10.2"  # does not raise
    import_env.importer.import_data(force=True)

    assert api.fetched.count(Uex.VERSION) == 1


# ── Relay outage ────────────────────────────────────────────────────


def test_a_relay_that_is_down_on_an_empty_database_completes_nothing_and_says_so_once(import_env):
    api = relay()
    api.failing = ALL_REQUESTS

    import_env.run_import(api)

    import_env.run_import(api)
    assert not import_env.importer.has_data()
    assert import_env.importer.get_last_error() == import_env.importer.UNREACHABLE
    assert not hasattr(import_env.helper, "completed_imports")  # no blacklist sync, the skill is not ready
    assert len(import_env.debug_messages("could not be loaded")) == 1  # not one per run or request

    import_env.run_import(relay())  # the relay is back
    assert import_env.importer.has_data()
    assert import_env.importer.get_last_error() is None
    assert import_env.helper.completed_imports == 1
    assert import_env.debug_messages("reachable again")


def test_a_relay_that_is_down_gets_no_more_requests_in_that_round(import_env):
    api = relay()
    api.failing = {Uex.BUNDLE_LONG}

    import_env.run_import(api)

    assert api.fetched == [Uex.VERSION, Uex.BUNDLE_LONG]  # not the short bundle as well


def test_a_relay_that_is_down_leaves_the_stored_data_in_use(import_env):
    import_env.run_import(relay())
    import_env.expire(Uex.BUNDLE_LONG)
    import_env.expire(Uex.BUNDLE_SHORT)
    api = relay()
    api.failing = {Uex.BUNDLE_LONG, Uex.BUNDLE_SHORT}

    import_env.run_import(api)

    assert import_env.importer.has_data()
    assert import_env.count("terminal") == 1
    assert len(import_env.debug_messages("could not be refreshed")) == 1


def test_a_dataset_missing_from_the_relay_is_reported_once(import_env):
    import_env.run_import(relay())
    for _ in range(3):
        import_env.expire(Uex.BUNDLE_LONG)
        api = relay()
        api.missing = {Uex.TERMINALS}
        import_env.run_import(api)

    notices = import_env.debug_messages("could not be refreshed")
    assert len(notices) == 1
    assert "terminal" in notices[0]
    assert "terminal" in import_env.importer.get_last_error()


def test_a_tool_without_data_says_so_instead_of_rejecting_the_names(import_env):
    api = relay()
    api.failing = ALL_REQUESTS
    import_env.run_import(api)

    response, _ = asyncio.run(ToolHandler(import_env.helper).execute_tool(
        "uex_get_trade_routes", {"used_ship": "Drake Caterpillar", "filter_start_location": "Area18"}
    ))

    assert "UEX data is not available right now (the UEX data source is unreachable)" in response
    assert "Invalid" not in response
    assert import_env.helper.request_while_not_loaded


# ── Unload and parallel imports ─────────────────────────────────────


def test_an_unload_during_the_version_check_waits_for_it_and_starts_no_import(import_env):
    # The start's version check uses the database before any import runs: an unload must not
    # close it underneath (the thread died and created a stray Helper)
    api = relay()
    import_env.importer._ImportHandler__api = api
    reached, release, unloaded = threading.Event(), threading.Event(), threading.Event()

    def slow_parity_check(force_check: bool = False):
        reached.set()
        release.wait(10)

    import_env.helper.ensure_version_parity = slow_parity_check
    prepare = threading.Thread(target=import_env.importer.prepare)
    prepare.start()
    assert reached.wait(10)
    unload = threading.Thread(target=lambda: (import_env.importer.destroy(), unloaded.set()))
    unload.start()
    assert not unloaded.wait(0.3)  # waits for the version check

    release.set()

    assert unloaded.wait(5)
    prepare.join(5)
    assert api.fetched == []  # no import after the unload


def test_an_unload_stops_the_import_and_the_next_start_continues(import_env):
    api = GateRelay(block_on=Uex.BUNDLE_LONG, cancellable=True)
    import_env.importer._ImportHandler__api = api
    import_thread = threading.Thread(target=import_env.importer.import_data, kwargs={"force": True})
    import_thread.start()
    assert api.reached.wait(10), "import never reached the long bundle"

    import_env.importer.destroy()  # unload while the long bundle downloads

    import_thread.join(5)
    assert not import_thread.is_alive()
    imports = import_env.imports()
    assert "game_version" in imports
    assert "terminal" not in imports
    assert "commodity_price" not in imports  # the short bundle never started
    assert getattr(import_env.helper, "completed_imports", 0) == 0
    assert not import_env.debug_messages("failed")

    # Next start: the bundles are fetched, the stored game version is not
    restarted = ImportHandler(import_env.helper)
    import_env.helper.importer = restarted
    retry = relay()
    restarted._ImportHandler__api = retry
    restarted.import_data(force=True)
    assert retry.fetched == [Uex.BUNDLE_LONG, Uex.BUNDLE_SHORT]
    assert import_env.count("terminal") == 1
    assert import_env.helper.completed_imports == 1


def test_only_one_import_runs_at_a_time(import_env):
    # main.py starts a preload import and prepare() could start a second one while the first
    # was still at 0 %; two imports broke the unload wait and could recreate the DB mid-import
    api = GateRelay(block_on=Uex.BUNDLE_LONG, cancellable=True)
    import_env.importer._ImportHandler__api = api
    import_thread = threading.Thread(target=import_env.importer.import_data, kwargs={"force": True})
    import_thread.start()
    assert api.reached.wait(10)
    assert import_env.importer.is_running()
    fetched_before = list(api.fetched)

    import_env.importer.import_data(force=True)  # returns at once instead of importing again
    import_env.importer.prepare()  # skipped as well

    assert api.fetched == fetched_before
    assert import_env.debug_messages("already running")
    import_env.importer.destroy()
    import_thread.join(5)
    assert not import_thread.is_alive()
    assert not import_env.importer.is_running()


def test_a_skipped_prepare_hands_the_skill_setup_to_the_running_preload(import_env):
    # Skill activation while the preload import runs: the skipped prepare must make the
    # preload finish the skill setup (on_import_completed), whatever order the threads take
    api = GateRelay(block_on=Uex.BUNDLE_LONG)
    import_env.importer._ImportHandler__api = api
    preload = threading.Thread(target=import_env.importer.prepare, kwargs={"preload": True})
    preload.start()
    assert api.reached.wait(10)

    import_env.importer.prepare()  # the regular prepare on skill activation: skipped
    api.gate.set()

    preload.join(10)
    assert not preload.is_alive()
    assert getattr(import_env.helper, "completed_imports", 0) == 1
