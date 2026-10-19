"""Focused tests for the data relay client and failed or interrupted imports.

No pytest. Run from the project root:

    python3 -m skills.uexcorp.tests.test_uex_api_failures

Exits non-zero on the first failed assertion or crash; prints "ALL OK" on success.

Why this exists
---------------
The skill imports everything from a relay that caches the UEX API in two bundles
(long: 2 weeks, short: 2 hours) plus a version lookup. A request that fails must raise
UexApiError instead of returning empty data - otherwise a table would be recorded as
imported with 0 rows and not fetched again for up to 14 days. A bundle is fetched
again once the relay has newer data (Cache-Control max-age), an unchanged bundle
(same ETag) is not written again, and a failed or interrupted bundle is retried with
the next import run.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import os
import tempfile
import threading
import time
import types
import unittest

from skills.uexcorp.uexcorp.api.uex import RelayResponse, Uex, UexApiError, UexClientError
from skills.uexcorp.uexcorp.helper import Helper


class _Recorder:
    def __init__(self):
        self.messages = []

    def write(self, *args, **kwargs):
        self.messages.append(" ".join(str(a) for a in args))


class _Config:
    def get_api_url(self):
        return "https://relay.example.test/uex/v3"

    def get_api_timeout(self):
        return 1

    def get_cache_lifetime_short(self):
        return 7200

    def get_cache_lifetime_long(self):
        return 14 * 24 * 3600


class _Helper:
    def __init__(self):
        self.debug = _Recorder()
        self.error = _Recorder()
        self.config = _Config()
        self.db = None
        self.importer = None
        self.timers = {}
        self.wingman = types.SimpleNamespace(settings=types.SimpleNamespace(debug_mode=False))

    def get_handler_debug(self):
        return self.debug

    def get_handler_error(self):
        return self.error

    def get_handler_config(self):
        return self.config

    def get_database(self):
        return self.db

    def get_handler_import(self):
        return self.importer

    def get_wingmen(self):
        return self.wingman

    def get_timestamp(self):
        return int(datetime.datetime.now().timestamp())

    def start_timer(self, id="default"):
        self.timers[id] = self.get_timestamp()

    def end_timer(self, id="default"):
        return 0

    def ensure_version_parity(self, *args, **kwargs):
        pass

    def on_import_completed(self, count):
        self.completed_imports = getattr(self, "completed_imports", 0) + 1

    def toast(self, *args, **kwargs):
        pass

    def set_request_while_not_loaded(self, request: bool):
        self.request_while_not_loaded = request

    async def wait_async(self, seconds: float):
        pass


class _Response:
    def __init__(self, status_code=200, payload=None, headers=None, body: bytes | None = None, chunks: int = 1):
        self.status_code = status_code
        if body is None:
            body = json.dumps(payload if payload is not None else {}).encode()
        size = max(1, len(body) // chunks)
        self._chunks = [body[i:i + size] for i in range(0, len(body), size)] or [b""]
        self.headers = headers or {}
        self.closed = False
        self.on_chunk = None

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.exceptions.HTTPError(f"{self.status_code} error")

    def iter_content(self, chunk_size=None):
        for chunk in self._chunks:
            if self.on_chunk:
                self.on_chunk()
            yield chunk

    def close(self):
        self.closed = True


class _Session:
    """Answers each URL from a per-URL list of responses (last one repeats)."""

    def __init__(self, responses_by_url: dict[str, list[_Response]]):
        self.responses_by_url = responses_by_url
        self.calls = []
        self.lock = threading.Lock()

    def get(self, url, **kwargs):
        with self.lock:
            self.calls.append((url, kwargs))
            responses = self.responses_by_url[url]
            return responses.pop(0) if len(responses) > 1 else responses[0]


BASE = "https://relay.example.test/uex/v3"


class RelayClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self._helper = _Helper()
        self._api = Uex(self._helper)

    def _session(self, responses_by_url):
        self._api.session = _Session(responses_by_url)
        return self._api.session

    def test_bundle_with_etag_and_max_age(self) -> None:
        self._session({f"{BASE}/short": [_Response(
            payload={"commodities_prices_all": [{"id": 1}]},
            headers={"ETag": '"abc"', "Cache-Control": "public, max-age=5559"},
        )]})
        response = self._api.fetch_bundle(Uex.BUNDLE_SHORT)
        self.assertEqual(response, RelayResponse({"commodities_prices_all": [{"id": 1}]}, '"abc"', 5559))

    def test_stored_etag_is_sent_and_304_means_unchanged(self) -> None:
        session = self._session({f"{BASE}/long": [_Response(304, headers={"Cache-Control": "max-age=60"})]})
        response = self._api.fetch_bundle(Uex.BUNDLE_LONG, etag='"abc"')
        self.assertEqual(response, RelayResponse(None, '"abc"', 60))
        self.assertEqual(session.calls[0][1]["headers"]["If-None-Match"], '"abc"')

    def test_compressed_transfer_is_requested(self) -> None:
        session = self._session({f"{BASE}/long": [_Response(payload={})]})
        self._api.fetch_bundle(Uex.BUNDLE_LONG)
        self.assertIn("gzip", session.calls[0][1]["headers"]["Accept-Encoding"])

    def test_server_error_is_retried_then_raises(self) -> None:
        self._api.MAX_RETRIES = 1
        session = self._session({f"{BASE}/long": [_Response(500)]})
        with self.assertRaises(UexApiError):
            self._api.fetch_bundle(Uex.BUNDLE_LONG)
        self.assertEqual(len(session.calls), 2)

    def test_server_error_then_success(self) -> None:
        self._session({f"{BASE}/long": [_Response(503), _Response(payload={"terminals": []})]})
        self.assertEqual(self._api.fetch_bundle(Uex.BUNDLE_LONG).data, {"terminals": []})

    def test_rejected_request_is_not_retried(self) -> None:
        session = self._session({f"{BASE}/long": [_Response(404)]})
        with self.assertRaises(UexClientError):
            self._api.fetch_bundle(Uex.BUNDLE_LONG)
        self.assertEqual(len(session.calls), 1)  # asking again gives the same answer

    def test_429_pauses_and_retries(self) -> None:
        session = self._session({f"{BASE}/short": [_Response(429, headers={"Retry-After": "1"}), _Response(payload={})]})
        start = time.monotonic()
        self.assertEqual(self._api.fetch_bundle(Uex.BUNDLE_SHORT).data, {})
        self.assertGreaterEqual(time.monotonic() - start, 0.95)
        self.assertEqual(len(session.calls), 2)

    def test_invalid_json_raises(self) -> None:
        self._api.MAX_RETRIES = 0
        self._session({f"{BASE}/long": [_Response(body=b'{"terminals": [')]})
        with self.assertRaises(UexApiError):
            self._api.fetch_bundle(Uex.BUNDLE_LONG)

    def test_bundle_must_be_an_object(self) -> None:
        self._session({f"{BASE}/long": [_Response(payload=[1, 2])]})
        with self.assertRaises(UexApiError):
            self._api.fetch_bundle(Uex.BUNDLE_LONG)

    def test_version(self) -> None:
        self._session({f"{BASE}/version": [_Response(payload={"live": "4.10.2"})]})
        self.assertEqual(self._api.fetch_version(), {"live": "4.10.2"})

    def test_version_without_live_raises(self) -> None:
        self._session({f"{BASE}/version": [_Response(payload={"status": "error"})]})
        with self.assertRaises(UexApiError):
            self._api.fetch_version()

    def test_every_response_is_closed(self) -> None:
        self._api.MAX_RETRIES = 0
        responses = {
            "ok": _Response(payload={}),
            "unchanged": _Response(304),
            "error": _Response(500),
            "rejected": _Response(404),
            "bad_json": _Response(body=b"nope"),
        }
        self._session({f"{BASE}/{name}": [response] for name, response in responses.items()})
        for name in responses:
            try:
                self._api.fetch_bundle(name)
            except UexApiError:
                pass
        self.assertEqual({name: r.closed for name, r in responses.items()}, dict.fromkeys(responses, True))

    def test_cancel_aborts_a_running_download(self) -> None:
        response = _Response(payload={"items": list(range(1000))}, chunks=10)
        response.on_chunk = self._api.cancel  # unload while the bundle is downloading
        self._session({f"{BASE}/long": [response]})
        with self.assertRaises(UexApiError):
            self._api.fetch_bundle(Uex.BUNDLE_LONG)
        self.assertTrue(response.closed)

    def test_cancel_aborts_a_retry_wait(self) -> None:
        self._session({f"{BASE}/long": [_Response(429, headers={"Retry-After": "30"})]})
        threading.Timer(0.2, self._api.cancel).start()
        start = time.monotonic()
        with self.assertRaises(UexApiError):
            self._api.fetch_bundle(Uex.BUNDLE_LONG)
        self.assertLess(time.monotonic() - start, 5)


class _DataApi:
    """Stands in for ImportHandler's relay client: serves canned datasets as relay bundles.

    data maps dataset names (Uex constants) to rows; datasets in `missing` are left out of
    their bundle, bundles/"version" in `failing` raise UexApiError (the relay is down), those
    in `rejected` raise UexClientError (the relay refused that one request)."""

    def __init__(self, data: dict[str, list], version: str = "4.10.2"):
        self.data = data
        self.version = version
        self.fetched = []  # bundle names and "version", in request order
        self.failing: set[str] = set()
        self.rejected: set[str] = set()
        self.missing: set[str] = set()
        self.max_age: int | None = None

    def __getattr__(self, name):
        return getattr(Uex, name)  # dataset constants

    def bundle(self, bundle: str) -> dict:
        from skills.uexcorp.uexcorp.handler.import_handler import ImportHandler

        empty = {Uex.COMMODITIES_STATUS: {"buy": [], "sell": []}}
        return {
            dataset.name: copy.deepcopy(self.data.get(dataset.name, empty.get(dataset.name, [])))
            for dataset in ImportHandler.DATASETS
            if dataset.bundle == bundle and dataset.name not in self.missing
        }

    def fetch_bundle(self, bundle: str, etag: str | None = None) -> RelayResponse:
        self.fetched.append(bundle)
        if bundle in self.failing:
            raise UexApiError(f"{bundle} bundle failed")
        if bundle in self.rejected:
            raise UexClientError(f"HTTP 404 for {bundle}")
        data = self.bundle(bundle)
        new_etag = hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
        return RelayResponse(data, new_etag, self.max_age)

    def fetch_version(self) -> dict:
        self.fetched.append(Uex.VERSION)
        if Uex.VERSION in self.failing:
            raise UexApiError("version failed")
        return {"live": self.version}

    def cancel(self):
        pass


def _relay(**data):
    base = {
        Uex.TERMINALS: [{"id": 1, "name": "Test Terminal", "type": "commodity", "is_available": 1}],
        Uex.VEHICLES: [{"id": 7, "name": "Cutlass", "name_full": "Drake Cutlass Black", "scu": 46}],
        Uex.CATEGORIES: [
            {"id": 1, "type": "item", "section": "Armor", "name": "Set", "is_game_related": 1},
            {"id": 2, "type": "item", "section": "Systems", "name": "Quantum Drives", "is_game_related": 1},
        ],
        Uex.COMMODITIES_STATUS: {
            "buy": [{"code": 1, "name": "Out of Stock"}],
            "sell": [{"code": 1, "name": "Out of Stock"}, {"code": 2, "name": "Very Low"}],
        },
        Uex.COMMODITIES_PRICES: [{"id": 1, "id_commodity": 5, "id_terminal": 1, "price_buy": 10}],
    }
    base.update(data)
    return _DataApi(base)


class ImportTest(unittest.TestCase):
    def setUp(self) -> None:
        from skills.uexcorp.uexcorp.database.database import Database
        from skills.uexcorp.uexcorp.handler.import_handler import ImportHandler

        self._original_helper = Helper._instance
        self._tmp_dir = tempfile.mkdtemp(prefix="uexcorp_import_test_")
        self._helper = _Helper()
        Helper._instance = self._helper
        self._helper.db = Database(self._tmp_dir, version="test-import", helper=self._helper)
        self._importer = ImportHandler(self._helper)
        self._helper.importer = self._importer

    def tearDown(self) -> None:
        try:
            self._helper.db.destroy()
        except Exception:
            pass
        Helper._instance = self._original_helper
        try:
            for name in os.listdir(self._tmp_dir):
                os.remove(os.path.join(self._tmp_dir, name))
            os.rmdir(self._tmp_dir)
        except OSError:
            pass

    def _imports(self) -> dict[str, dict]:
        return {row["table"]: dict(row) for row in self._helper.db.execute_fetchall("SELECT * FROM imports")}

    def _count(self, table: str) -> int:
        return self._helper.db.execute_fetchall(f"SELECT COUNT(*) AS c FROM {table}")[0]["c"]

    def _run_import(self, api) -> None:
        self._importer._ImportHandler__api = api
        self._importer.import_data(force=True)

    def _expire(self, bundle: str) -> None:
        self._helper.db.execute("UPDATE imports SET date_expires = 0 WHERE `table` = ?", (f"relay_{bundle}",))
        self._helper.db.commit()

    # ---- full import and refresh timing

    def test_full_import_is_three_requests(self) -> None:
        from skills.uexcorp.uexcorp.handler.import_handler import ImportHandler

        api = _relay()
        self._run_import(api)
        self.assertEqual(api.fetched, [Uex.VERSION, Uex.BUNDLE_LONG, Uex.BUNDLE_SHORT])
        imports = self._imports()
        self.assertTrue({dataset.table for dataset in ImportHandler.DATASETS} <= set(imports))
        self.assertTrue({"game_version", "commodity_route", "relay_long", "relay_short"} <= set(imports))
        self.assertEqual(self._count("terminal"), 1)
        self.assertEqual(self._importer.get_imported_percent(), 100)
        self.assertEqual(self._helper.completed_imports, 1)
        self.assertEqual(self._helper.error.messages, [])
        self.assertFalse(any("failed" in m for m in self._helper.debug.messages))

    def test_nothing_is_fetched_before_the_relay_has_new_data(self) -> None:
        self._run_import(_relay())
        api = _relay()
        self._run_import(api)
        self.assertEqual(api.fetched, [])

    def test_refresh_follows_the_relay_max_age(self) -> None:
        from skills.uexcorp.uexcorp.handler.import_handler import ImportHandler

        api = _relay()
        api.max_age = 3000
        self._run_import(api)
        imports = self._imports()
        short = imports["relay_short"]["date_expires"] - imports["relay_short"]["date_imported"]
        self.assertAlmostEqual(short, 3000 + ImportHandler.RELAY_MARGIN, delta=2)

    def test_refresh_bounds(self) -> None:
        from skills.uexcorp.uexcorp.handler.import_handler import ImportHandler

        refresh_in = self._importer._ImportHandler__get_refresh_in
        self.assertEqual(refresh_in(None, 7200), 7200)  # no header: the configured lifetime
        self.assertEqual(refresh_in(10 ** 9, 7200), 7200)  # never longer than the lifetime
        self.assertEqual(refresh_in(0, 7200), ImportHandler.MIN_REFRESH)  # stale relay: no hammering

    def test_unchanged_bundle_is_not_written_again(self) -> None:
        self._run_import(_relay())
        before = self._imports()
        self._helper.db.execute("UPDATE imports SET date_imported = 1 WHERE `table` = 'terminal'")
        self._helper.db.commit()
        self._expire(Uex.BUNDLE_LONG)
        api = _relay()
        self._run_import(api)
        self.assertEqual(api.fetched, [Uex.BUNDLE_LONG])
        imports = self._imports()
        self.assertEqual(imports["terminal"]["date_imported"], 1)  # same ETag: tables untouched
        self.assertGreaterEqual(imports["relay_long"]["date_expires"], before["relay_long"]["date_expires"])

    def test_changed_bundle_replaces_its_tables(self) -> None:
        self._run_import(_relay(**{Uex.TERMINALS: [
            {"id": 1, "name": "Old", "type": "commodity"}, {"id": 2, "name": "Removed", "type": "commodity"},
        ]}))
        self.assertEqual(self._count("terminal"), 2)
        self._expire(Uex.BUNDLE_LONG)
        self._run_import(_relay(**{Uex.TERMINALS: [{"id": 1, "name": "Renamed", "type": "commodity"}]}))
        rows = self._helper.db.execute_fetchall("SELECT id, name FROM terminal")
        self.assertEqual([(r["id"], r["name"]) for r in rows], [(1, "Renamed")])  # removed rows are gone

    def test_reimport_does_not_duplicate_status_rows(self) -> None:
        self._run_import(_relay())
        self._expire(Uex.BUNDLE_LONG)
        self._run_import(_relay(**{Uex.FACTIONS: [{"id": 3, "name": "changed"}]}))
        self.assertEqual(self._count("commodity_status"), 3)
        buy = self._helper.db.execute_fetchall("SELECT is_buy, COUNT(*) AS c FROM commodity_status GROUP BY is_buy")
        self.assertEqual({r["is_buy"]: r["c"] for r in buy}, {0: 2, 1: 1})

    def test_category_names_and_armor_sets(self) -> None:
        self._run_import(_relay())
        rows = {r["id"]: dict(r) for r in self._helper.db.execute_fetchall("SELECT * FROM category")}
        self.assertEqual(rows[2]["combined_name"], "Systems Quantum Drives")
        self.assertEqual(rows[1]["is_game_related"], 0)  # armor sets are no items of their own

    def test_entries_without_id_are_skipped(self) -> None:
        # The relay lists empty API answers of categories without items as entries
        placeholder = {"data": None, "http_code": 200, "message": "", "status": "ok"}
        self._run_import(_relay(**{Uex.ITEMS: [{"id": 5, "name": "P4-AR", "id_category": 2}, placeholder, placeholder]}))
        self.assertEqual(self._count("item"), 1)
        self.assertIn("item", self._imports())

    # ---- failures

    def test_failed_bundle_is_not_marked_and_retried_next_run(self) -> None:
        api = _relay()
        api.rejected = {Uex.BUNDLE_LONG}
        self._run_import(api)
        imports = self._imports()
        self.assertNotIn("terminal", imports)
        self.assertIn("commodity_price", imports)  # the other bundle still imports
        self.assertEqual(self._importer.get_imported_percent(), 100)
        self.assertTrue(any("long bundle" in m and "retried" in m for m in self._helper.debug.messages))

        retry = _relay()
        self._run_import(retry)
        self.assertEqual(retry.fetched, [Uex.BUNDLE_LONG])  # only the failed bundle again
        self.assertEqual(self._count("terminal"), 1)

    def test_missing_dataset_fails_only_its_table_and_retries_the_bundle(self) -> None:
        api = _relay()
        api.missing = {Uex.TERMINALS}
        self._run_import(api)
        imports = self._imports()
        self.assertNotIn("terminal", imports)
        self.assertIn("vehicle", imports)  # later tables of the bundle still import
        self.assertIsNone(imports["relay_long"]["date_expires"])

        retry = _relay()
        self._run_import(retry)
        self.assertEqual(retry.fetched, [Uex.BUNDLE_LONG])
        self.assertIn("terminal", self._imports())

    def test_unexpected_dataset_error_does_not_stop_the_import(self) -> None:
        # e.g. a malformed dataset: must not leave the import stuck below 100 %
        self._run_import(_relay(**{Uex.COMMODITIES_STATUS: [1, 2, 3], Uex.TERMINALS: [{"name": "no id"}, 5]}))
        self.assertEqual(self._importer.get_imported_percent(), 100)
        imports = self._imports()
        self.assertNotIn("commodity_status", imports)
        self.assertIn("vehicle", imports)

    def test_failed_prices_leave_routes_to_be_derived_next_run(self) -> None:
        api = _relay()
        api.failing = {Uex.BUNDLE_SHORT}
        self._run_import(api)
        imports = self._imports()
        self.assertNotIn("commodity_price", imports)
        self.assertNotIn("commodity_route", imports)

        retry = _relay()
        self._run_import(retry)
        self.assertEqual(retry.fetched, [Uex.BUNDLE_SHORT])
        self.assertTrue({"commodity_price", "commodity_route"} <= set(self._imports()))

    def test_failed_game_version_check_keeps_last_known_version(self) -> None:
        self._run_import(_relay())
        api = _relay()
        api.failing = {Uex.VERSION}
        self._importer._ImportHandler__api = api
        self.assertEqual(self._importer.get_version_uex(force_check=True), "4.10.2")  # must not raise

    def test_game_version_is_imported_first(self) -> None:
        # An interrupted first import can only continue if the game version is already stored,
        # otherwise the next start's version parity check recreates the database.
        api = _relay()
        self._run_import(api)
        self.assertEqual(api.fetched[0], Uex.VERSION)

    # ---- relay outage: no data, stored data, one notice

    def test_relay_down_on_an_empty_database_completes_nothing_and_says_so_once(self) -> None:
        api = _relay()
        api.failing = {Uex.VERSION, Uex.BUNDLE_LONG, Uex.BUNDLE_SHORT}
        self._run_import(api)
        self._run_import(api)
        self.assertFalse(self._importer.has_data())
        self.assertEqual(self._importer.get_last_error(), self._importer.UNREACHABLE)
        self.assertFalse(hasattr(self._helper, "completed_imports"))  # no blacklist sync, not ready
        notices = [m for m in self._helper.debug.messages if "could not be loaded" in m]
        self.assertEqual(len(notices), 1)  # not one per run or request

        self._run_import(_relay())  # the relay is back
        self.assertTrue(self._importer.has_data())
        self.assertIsNone(self._importer.get_last_error())
        self.assertEqual(self._helper.completed_imports, 1)
        self.assertTrue(any("reachable again" in m for m in self._helper.debug.messages))

    def test_relay_down_with_stored_data_keeps_working_on_it(self) -> None:
        self._run_import(_relay())
        self._expire(Uex.BUNDLE_LONG)
        self._expire(Uex.BUNDLE_SHORT)
        api = _relay()
        api.failing = {Uex.BUNDLE_LONG, Uex.BUNDLE_SHORT}
        self._run_import(api)
        self.assertTrue(self._importer.has_data())
        self.assertEqual(self._count("terminal"), 1)
        self.assertEqual(len([m for m in self._helper.debug.messages if "could not be refreshed" in m]), 1)

    def test_a_relay_that_is_down_gets_no_more_requests_in_that_round(self) -> None:
        api = _relay()
        api.failing = {Uex.BUNDLE_LONG}
        self._run_import(api)
        self.assertEqual(api.fetched, [Uex.VERSION, Uex.BUNDLE_LONG])  # not the short bundle as well

    def test_a_dataset_missing_from_the_relay_is_reported_once(self) -> None:
        self._run_import(_relay())
        for _ in range(3):
            self._expire(Uex.BUNDLE_LONG)
            api = _relay()
            api.missing = {Uex.TERMINALS}
            self._run_import(api)
        notices = [m for m in self._helper.debug.messages if "could not be refreshed" in m]
        self.assertEqual(len(notices), 1)
        self.assertIn("terminal", notices[0])
        self.assertIn("terminal", self._importer.get_last_error())

    def test_a_failed_version_check_is_not_repeated_by_the_import_after_it(self) -> None:
        api = _relay()
        api.failing = {Uex.VERSION}
        self._importer._ImportHandler__api = api
        self._importer.get_version_uex(force_check=True)  # the start's parity check
        self._importer.import_data(force=True)
        self.assertEqual(api.fetched.count(Uex.VERSION), 1)

    def test_a_tool_without_data_says_so_instead_of_rejecting_the_names(self) -> None:
        import asyncio

        from skills.uexcorp.uexcorp.handler.tool_handler import ToolHandler

        api = _relay()
        api.failing = {Uex.VERSION, Uex.BUNDLE_LONG, Uex.BUNDLE_SHORT}
        self._run_import(api)
        response, _ = asyncio.run(ToolHandler(self._helper).execute_tool(
            "uex_get_trade_routes", {"used_ship": "Drake Caterpillar", "filter_start_location": "Area18"}
        ))
        self.assertIn("UEX data is not available right now (the UEX data source is unreachable)", response)
        self.assertNotIn("Invalid", response)
        self.assertTrue(self._helper.request_while_not_loaded)

    # ---- unload, concurrency, skill setup

    def test_unload_during_the_version_check_waits_for_it_and_starts_no_import(self) -> None:
        # The start's version check uses the database before any import runs: an unload must not
        # close it underneath (the thread died and created a stray Helper)
        api = _relay()
        self._importer._ImportHandler__api = api
        reached, release, unloaded = threading.Event(), threading.Event(), threading.Event()

        def slow_parity_check(force_check: bool = False):
            reached.set()
            release.wait(10)

        self._helper.ensure_version_parity = slow_parity_check
        prepare = threading.Thread(target=self._importer.prepare)
        prepare.start()
        self.assertTrue(reached.wait(10))
        unload = threading.Thread(target=lambda: (self._importer.destroy(), unloaded.set()))
        unload.start()
        self.assertFalse(unloaded.wait(0.5))  # waits for the version check
        release.set()
        self.assertTrue(unloaded.wait(5))
        prepare.join(5)
        self.assertEqual(api.fetched, [])  # no import after the unload

    def test_unload_stops_import_and_next_start_continues(self) -> None:
        from skills.uexcorp.uexcorp.handler.import_handler import ImportHandler

        api = _BlockingRelay(block_on=Uex.BUNDLE_LONG)
        self._importer._ImportHandler__api = api
        import_thread = threading.Thread(target=self._importer.import_data, kwargs={"force": True})
        import_thread.start()
        self.assertTrue(api.reached.wait(10), "import never reached the long bundle")

        start = time.monotonic()
        self._importer.destroy()  # unload while the long bundle downloads
        self.assertLess(time.monotonic() - start, 3)
        import_thread.join(5)
        self.assertFalse(import_thread.is_alive())

        imports = self._imports()
        self.assertIn("game_version", imports)
        self.assertNotIn("terminal", imports)
        self.assertNotIn("commodity_price", imports)  # the short bundle never started
        self.assertEqual(getattr(self._helper, "completed_imports", 0), 0)
        self.assertFalse(any("failed" in m for m in self._helper.debug.messages))

        # Next start: the bundles are fetched, the stored game version is not
        restarted = ImportHandler(self._helper)
        self._helper.importer = restarted
        retry = _relay()
        restarted._ImportHandler__api = retry
        restarted.import_data(force=True)
        self.assertEqual(retry.fetched, [Uex.BUNDLE_LONG, Uex.BUNDLE_SHORT])
        self.assertIn("terminal", self._imports())
        self.assertEqual(self._helper.completed_imports, 1)

    def test_only_one_import_runs_at_a_time(self) -> None:
        # main.py starts a preload import and prepare() could start a second one while the first
        # was still at 0 %; two imports broke the unload wait and could recreate the DB mid-import
        api = _BlockingRelay(block_on=Uex.BUNDLE_LONG)
        self._importer._ImportHandler__api = api
        import_thread = threading.Thread(target=self._importer.import_data, kwargs={"force": True})
        import_thread.start()
        self.assertTrue(api.reached.wait(10))
        self.assertTrue(self._importer.is_running())

        fetched_before = list(api.fetched)
        self._importer.import_data(force=True)  # returns at once instead of importing again
        self._importer.prepare()  # skipped as well (no version check next to a running import)
        self.assertEqual(api.fetched, fetched_before)
        self.assertTrue(any("already running" in m for m in self._helper.debug.messages))

        self._importer.destroy()
        import_thread.join(5)
        self.assertFalse(import_thread.is_alive())
        self.assertFalse(self._importer.is_running())

    def test_skipped_prepare_hands_completion_to_the_running_preload(self) -> None:
        # Skill activation while the preload import runs: the skipped prepare must make the
        # preload finish the skill setup (on_import_completed), whatever order the threads take
        api = _GateRelay(block_on=Uex.BUNDLE_LONG)
        self._importer._ImportHandler__api = api
        preload = threading.Thread(target=self._importer.prepare, kwargs={"preload": True})
        preload.start()
        self.assertTrue(api.reached.wait(10))
        self._importer.prepare()  # the regular prepare on skill activation: skipped
        api.gate.set()
        preload.join(10)
        self.assertFalse(preload.is_alive())
        self.assertEqual(getattr(self._helper, "completed_imports", 0), 1)

    def test_preload_alone_does_not_complete_the_setup(self) -> None:
        self._importer._ImportHandler__api = _relay()
        self._importer.prepare(preload=True)
        self.assertEqual(getattr(self._helper, "completed_imports", 0), 0)

    def test_destroy_without_running_import_returns_immediately(self) -> None:
        start = time.monotonic()
        self._importer.destroy()
        self.assertLess(time.monotonic() - start, 0.5)
        self.assertFalse(self._importer.active)


class _GateRelay(_DataApi):
    """Holds the given bundle until gate is set, then answers normally."""

    def __init__(self, block_on: str):
        super().__init__(_relay().data)
        self.block_on = block_on
        self.reached = threading.Event()
        self.gate = threading.Event()

    def fetch_bundle(self, bundle, etag=None):
        if bundle == self.block_on:
            self.reached.set()
            self.gate.wait(10)
        return super().fetch_bundle(bundle, etag)


class _BlockingRelay(_DataApi):
    """Blocks the given bundle until cancel(), like a download stopped by unload."""

    def __init__(self, block_on: str):
        super().__init__(_relay().data)
        self.block_on = block_on
        self.reached = threading.Event()
        self.cancelled = threading.Event()

    def fetch_bundle(self, bundle, etag=None):
        if bundle == self.block_on:
            self.fetched.append(bundle)
            self.reached.set()
            self.cancelled.wait(10)
            raise UexApiError(f"Cancelled request to {bundle}")
        return super().fetch_bundle(bundle, etag)

    def cancel(self):
        self.cancelled.set()


class LogFileTest(unittest.TestCase):
    """The skill's own log files: game names outside cp1252 (Windows' default) must not crash a tool."""

    def setUp(self) -> None:
        import threading

        self._tmp_dir = tempfile.mkdtemp(prefix="uexcorp_log_test_")
        self._helper = types.SimpleNamespace(
            get_data_path=lambda: self._tmp_dir, is_debug=lambda: True,
            get_default_thread_ident=threading.get_ident,
            get_version_skill_short=lambda: "v3", get_version_skill=lambda: "v3.0.0",
        )

    def tearDown(self) -> None:
        for name in os.listdir(self._tmp_dir):
            os.remove(os.path.join(self._tmp_dir, name))
        os.rmdir(self._tmp_dir)

    def test_names_outside_cp1252_are_written(self) -> None:
        from skills.uexcorp.uexcorp.handler.debug_handler import DebugHandler
        from skills.uexcorp.uexcorp.handler.error_handler import ErrorHandler

        debug, error = DebugHandler(self._helper), ErrorHandler(self._helper)
        debug.write("Aopoa San tok.Yāi")
        error.write("tool", ["Katsu Karē Kacho"], ValueError("Karē"))
        self.assertIn("Yāi", debug.read())
        self.assertIn("Karē", error.read())

    def test_the_debug_log_keeps_one_old_file(self) -> None:
        from skills.uexcorp.uexcorp.handler.debug_handler import DebugHandler

        debug = DebugHandler(self._helper)
        debug.MAX_SIZE = 100
        for i in range(20):
            debug.write(f"line {i} " + "x" * 20)
        self.assertLessEqual(os.path.getsize(debug.get_debug_file_path()), 200)
        self.assertTrue(os.path.exists(debug.get_debug_file_path() + ".1"))

    def test_the_error_log_keeps_one_old_file_and_network_errors_have_no_traceback(self) -> None:
        from skills.uexcorp.uexcorp.handler.error_handler import ErrorHandler

        error = ErrorHandler(self._helper)
        error.MAX_SIZE = 300
        try:
            raise ValueError("inside")
        except ValueError:
            error.write("Api.fetch", ["long"], "521 Server Error", write_traceback=False)
        self.assertNotIn("Traceback", error.read())
        for _ in range(10):
            error.write("Api.fetch", ["long"], "521 Server Error", write_traceback=False)
        self.assertLessEqual(os.path.getsize(error.get_error_file_path()), 600)
        self.assertTrue(os.path.exists(error.get_error_file_path() + ".1"))


def main() -> None:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(RelayClientTest),
        loader.loadTestsFromTestCase(ImportTest),
        loader.loadTestsFromTestCase(LogFileTest),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
