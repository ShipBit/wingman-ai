"""Fakes and seeding helpers shared by the UEX skill tests.

Fixtures live in conftest.py. This module holds plain classes and functions, so
test modules import them explicitly.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import threading
from types import SimpleNamespace

from skills.uexcorp.uexcorp.api.llm import Llm
from skills.uexcorp.uexcorp.api.uex import RelayResponse, Uex, UexApiError, UexClientError
from skills.uexcorp.uexcorp.compression import LEGEND_KEY
from skills.uexcorp.uexcorp.tool.commodity_route import CommodityRoute

# ── Helper for the tools that read the database ─────────────────────


class NullHandler:
    def write(self, *args, **kwargs):
        return None


class FakeConfig:
    def __init__(self, wingman):
        self.use_estimated_availability = True
        self.ranking = "profit_per_stop"
        self.default_max_stops = 1
        self._wingman = wingman

    def get_wingman(self):
        return self._wingman

    def get_behavior_commodity_route_default_count(self) -> int:
        return 15

    def get_behavior_commodity_route_default_max_stops(self) -> int:
        return self.default_max_stops

    def get_behavior_commodity_route_use_estimated_availability(self) -> bool:
        return self.use_estimated_availability

    def get_behavior_commodity_route_ranking(self) -> str:
        return self.ranking

    def get_behavior_commodity_route_advanced_info(self) -> bool:
        return False


class FakeToolHandler:
    def __init__(self):
        self.notes: list[str] = []

    def add_note(self, note: str) -> None:
        self.notes.append(note)


class FakeHud:
    def __init__(self):
        self.panels: dict[str, str] = {}

    async def add_info(self, title: str, text: str = "", **kwargs) -> bool:
        self.panels[title] = text
        return True

    async def remove_info(self, title: str) -> bool:
        self.panels.pop(title, None)
        return True


class FakeAi:
    """Main model fallback of the name matcher: records the shortlist it was shown, matches nothing."""

    def __init__(self):
        self.prompts: list[str] = []

    async def generate(self, messages: list[dict]) -> str:
        self.prompts.append(messages[0]["content"])
        return "None"


class FakeHelper:
    """The parts of Helper the tools use, on a real sqlite database in a temp folder."""

    def __init__(self, data_path: str):
        self._database = None
        self._data_path = data_path
        self.wingman = SimpleNamespace(local_ai=None, ai=FakeAi(), system_one=None, hud=FakeHud())
        self._config = FakeConfig(self.wingman)
        self._tool = FakeToolHandler()
        self._debug = NullHandler()
        self._error = NullHandler()
        self._llm = Llm(self)

    @property
    def notes(self) -> list[str]:
        return self._tool.notes

    def set_database(self, database) -> None:
        self._database = database

    def get_database(self):
        return self._database

    def get_data_path(self) -> str:
        return self._data_path

    def get_state_path(self) -> str:
        return self._data_path

    def get_handler_config(self):
        return self._config

    def get_handler_tool(self):
        return self._tool

    def get_handler_debug(self):
        return self._debug

    def get_handler_error(self):
        return self._error

    def get_llm(self) -> Llm:
        return self._llm

    def add_context(self, context: str) -> None:
        pass


# ── Seeding and reading ─────────────────────────────────────────────


def add_terminal(db, terminal_id: int, name: str, **fields) -> None:
    row = {"id": terminal_id, "name": name, "type": "commodity", "is_available": 1, **fields}
    _insert(db, "terminal", row)


def add_route(db, route_id: int, **fields) -> None:
    """One derived trade leg. Margin and the names of the star systems are filled in when not given."""
    row = {
        "id": route_id, "commodity_name": "Laranite", "distance": 10,
        "origin_star_system_name": "Stanton", "destination_star_system_name": "Stanton",
        "origin_planet_name": "Hurston", "destination_planet_name": "Hurston", **fields,
    }
    if "price_margin" not in row and row.get("price_destination"):
        row["price_margin"] = (row["price_destination"] - row["price_origin"]) / row["price_destination"] * 100
    _insert(db, "commodity_route", row)


def _insert(db, table: str, row: dict) -> None:
    columns = ", ".join(row)
    db.execute(f"INSERT INTO {table} ({columns}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))


def parse_routes(payload: str) -> list[dict]:
    """Decode a tool payload, expanding keys shortened via the compression legend."""
    data = json.loads(payload)
    if isinstance(data, dict) and LEGEND_KEY in data:
        legend = data[LEGEND_KEY]

        def expand(value):
            if isinstance(value, dict):
                return {legend.get(key, key): expand(val) for key, val in value.items()}
            if isinstance(value, list):
                return [expand(item) for item in value]
            return value

        data = expand(data.get("data") or [])
    return data


def search(helper: FakeHelper, **kwargs) -> list[dict]:
    """uex_get_trade_routes as the AI calls it. The notes it gave are in helper.notes afterwards."""
    helper.notes.clear()
    payload, _instant = CommodityRoute().execute(**{"limit": 15, **kwargs})
    return parse_routes(payload)


def route_pairs(routes: list[dict]) -> set[tuple[str, str]]:
    """(first stop, last stop) terminal names of each route, also the other last stops of the same sale."""
    return {
        (route["stops"][0]["terminal"], end)
        for route in routes
        for end in [route["stops"][-1]["terminal"]] + route.get("last_sale_also_at", [])
    }


def stop_names(route: dict) -> list[str]:
    return [stop["terminal"] for stop in route["stops"]]


def bought(route: dict) -> set[str]:
    return {buy["commodity"] for stop in route["stops"] for buy in stop.get("buy", [])}


def first_buys(route: dict) -> list[dict]:
    return route["stops"][0].get("buy", [])


def buy_volume(route: dict) -> int:
    """SCU bought at the first stop (all commodities)."""
    return sum(buy["scu"] for buy in first_buys(route))


def volume_note(route: dict) -> str | None:
    return next((buy["volume_note"] for buy in first_buys(route) if "volume_note" in buy), None)


# ── Fakes for the relay and the import ──────────────────────────────


class Recorder:
    def __init__(self):
        self.messages = []

    def write(self, *args, **kwargs):
        self.messages.append(" ".join(str(a) for a in args))


class RelayConfig:
    def get_api_url(self):
        return "https://relay.example.test/uex/v3"

    def get_api_timeout(self):
        return 1

    def get_cache_lifetime_short(self):
        return 7200

    def get_cache_lifetime_long(self):
        return 14 * 24 * 3600


class ImportHelper:
    def __init__(self):
        self.debug = Recorder()
        self.error = Recorder()
        self.config = RelayConfig()
        self.db = None
        self.importer = None
        self.wingman = SimpleNamespace(settings=SimpleNamespace(debug_mode=False))

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
        pass

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


class FastStop(threading.Event):
    """The client's stop flag, but waiting for a retry costs no time. on_wait runs inside the wait."""

    def __init__(self):
        super().__init__()
        self.waited: list[float] = []
        self.on_wait = None

    def wait(self, timeout=None):
        self.waited.append(timeout)
        if self.on_wait:
            self.on_wait()
        return self.is_set()


class Response:
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


class Session:
    """Answers each URL from a per-URL list of responses (the last one repeats)."""

    def __init__(self, responses_by_url: dict[str, list[Response]]):
        self.responses_by_url = responses_by_url
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        responses = self.responses_by_url[url]
        return responses.pop(0) if len(responses) > 1 else responses[0]


RELAY_URL = "https://relay.example.test/uex/v3"


class DataApi:
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


class GateRelay(DataApi):
    """Holds the given bundle until the gate opens, or until cancel() when cancellable, like an unload."""

    def __init__(self, block_on: str, cancellable: bool = False):
        super().__init__(relay().data)
        self.block_on = block_on
        self.cancellable = cancellable
        self.reached = threading.Event()
        self.gate = threading.Event()

    def fetch_bundle(self, bundle, etag=None):
        if bundle == self.block_on:
            self.fetched.append(bundle)
            self.reached.set()
            self.gate.wait(10)
            if self.cancellable:
                raise UexApiError(f"Cancelled request to {bundle}")
        return super().fetch_bundle(bundle, etag)

    def cancel(self):
        if self.cancellable:
            self.gate.set()


def relay(**data) -> DataApi:
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
    return DataApi(base)


class ImportEnv:
    """An ImportHandler on a real database in a temp folder, fed by a fake relay."""

    def __init__(self, helper: ImportHelper, importer):
        self.helper = helper
        self.importer = importer
        self.db = helper.db

    def imports(self) -> dict[str, dict]:
        return {row["table"]: dict(row) for row in self.db.execute_fetchall("SELECT * FROM imports")}

    def count(self, table: str) -> int:
        return self.db.execute_fetchall(f"SELECT COUNT(*) AS c FROM {table}")[0]["c"]

    def run_import(self, api) -> None:
        self.importer._ImportHandler__api = api
        self.importer.import_data(force=True)

    def expire(self, bundle: str) -> None:
        """The relay has new data for this bundle: it is due again."""
        self.db.execute("UPDATE imports SET date_expires = 0 WHERE `table` = ?", (f"relay_{bundle}",))
        self.db.commit()

    def debug_messages(self, containing: str) -> list[str]:
        return [m for m in self.helper.debug.messages if containing in m]
