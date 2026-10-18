import importlib
import threading
import time
from typing import TYPE_CHECKING, NamedTuple

from skills.uexcorp.uexcorp.api.uex import Uex, UexApiError, UexClientError
if TYPE_CHECKING:
    from skills.uexcorp.uexcorp.helper import Helper
    from skills.uexcorp.uexcorp.model.data_model import DataModel


class _Dataset(NamedTuple):
    table: str
    bundle: str
    name: str  # key inside the relay bundle


class ImportHandler:
    # Max wait on unload for a stopped import to finish its current request/DB writes
    STOP_TIMEOUT = 30
    # Bundles: fetched again once the relay has newer data (its Cache-Control max-age), plus a
    # margin for the relay's own refresh, but never more often than every MIN_REFRESH seconds
    RELAY_MARGIN = 60
    MIN_REFRESH = 5 * 60
    # A failed version check is not repeated by the import that follows it
    VERSION_RETRY_PAUSE = 60
    UNREACHABLE = "the UEX data source is unreachable"

    # Every imported table and where the relay delivers it. Order inside a bundle = import order.
    DATASETS = (
        _Dataset("category", Uex.BUNDLE_LONG, Uex.CATEGORIES),
        _Dataset("category_attribute", Uex.BUNDLE_LONG, Uex.CATEGORIES_ATTRIBUTES),
        _Dataset("city", Uex.BUNDLE_LONG, Uex.CITIES),
        _Dataset("commodity", Uex.BUNDLE_LONG, Uex.COMMODITIES),
        _Dataset("commodity_status", Uex.BUNDLE_LONG, Uex.COMMODITIES_STATUS),
        _Dataset("company", Uex.BUNDLE_LONG, Uex.COMPANIES),
        _Dataset("faction", Uex.BUNDLE_LONG, Uex.FACTIONS),
        _Dataset("item", Uex.BUNDLE_LONG, Uex.ITEMS),
        _Dataset("item_attribute", Uex.BUNDLE_LONG, Uex.ITEMS_ATTRIBUTES),
        _Dataset("jurisdiction", Uex.BUNDLE_LONG, Uex.JURISDICTIONS),
        _Dataset("star_system", Uex.BUNDLE_LONG, Uex.STAR_SYSTEMS),
        _Dataset("moon", Uex.BUNDLE_LONG, Uex.MOONS),
        _Dataset("orbit", Uex.BUNDLE_LONG, Uex.ORBITS),
        _Dataset("orbit_distance", Uex.BUNDLE_LONG, Uex.ORBITS_DISTANCES),
        _Dataset("outpost", Uex.BUNDLE_LONG, Uex.OUTPOSTS),
        _Dataset("planet", Uex.BUNDLE_LONG, Uex.PLANETS),
        _Dataset("poi", Uex.BUNDLE_LONG, Uex.POI),
        _Dataset("refinery_audit", Uex.BUNDLE_LONG, Uex.REFINERIES_AUDITS),
        _Dataset("refinery_method", Uex.BUNDLE_LONG, Uex.REFINERIES_METHODS),
        _Dataset("space_station", Uex.BUNDLE_LONG, Uex.SPACE_STATIONS),
        _Dataset("terminal", Uex.BUNDLE_LONG, Uex.TERMINALS),
        _Dataset("vehicle", Uex.BUNDLE_LONG, Uex.VEHICLES),
        _Dataset("vehicle_purchase_price", Uex.BUNDLE_LONG, Uex.VEHICLES_PURCHASES_PRICES),
        _Dataset("vehicle_rental_price", Uex.BUNDLE_LONG, Uex.VEHICLES_RENTALS_PRICES),
        _Dataset("commodity_alert", Uex.BUNDLE_SHORT, Uex.COMMODITIES_ALERTS),
        _Dataset("commodity_price", Uex.BUNDLE_SHORT, Uex.COMMODITIES_PRICES),
        _Dataset("commodity_raw_price", Uex.BUNDLE_SHORT, Uex.COMMODITIES_RAW_PRICES),
        _Dataset("fuel_price", Uex.BUNDLE_SHORT, Uex.FUEL_PRICES),
        _Dataset("item_price", Uex.BUNDLE_SHORT, Uex.ITEMS_PRICES),
    )
    BUNDLES = (Uex.BUNDLE_LONG, Uex.BUNDLE_SHORT)

    def __init__(self, helper: "Helper"):
        self.__helper = helper
        self.__api = Uex(helper)
        self.active = True
        # Only one import at a time. The lock makes "check active + mark running" atomic
        # against destroy(); __idle is set while no import runs, destroy() waits on it
        # before the database gets closed.
        self.__state_lock = threading.Lock()
        self.__prepare_lock = threading.Lock()
        self.__running = False
        self.__completion_requested = False
        self.__idle = threading.Event()
        self.__idle.set()
        self.__common_data = {
            "last_import_run_id": 0,
        }
        self.__imported_percent: int = 0
        # Progress steps: game version, every dataset, trade route derivation
        self.__progress_steps = len(self.DATASETS) + 2
        self.__progress_done = 0
        self.__imported_tables: set[str] = set()  # tables replaced in the running import
        # Why the last import brought no fresh data (None: it did), for tool answers and the user
        self.__last_error: str | None = None
        self.__relay_down_reported = False
        self.__no_data_reported = False
        self.__version_failed_at = 0.0
        self.__round_errors: list[str] = []  # problems of the running import round

        self.generate_import_session()
        self.is_preload = False

    def prepare(self, preload: bool = False) -> None:
        # Exclusive: the version check may recreate the database, never next to a running import
        if self.is_running() or not self.__prepare_lock.acquire(blocking=False):
            if not preload:
                # The running (pre)load import counts as the real one and completes the skill setup
                self.request_completion()
            self.__helper.get_handler_debug().write("Import already running, skipped prepare.")
            return
        try:
            if not self.active:
                return
            self.is_preload = preload
            self.__helper.ensure_version_parity(True)
            if not self.active:
                return  # unloaded during the version check: the database is about to close
            self.import_data(True)
            self.is_preload = False
        finally:
            self.__prepare_lock.release()

    def request_completion(self) -> None:
        """The running (pre)load import should finish the skill setup (on_import_completed).
        A separate flag, so the preload thread setting is_preload can never overwrite it."""
        with self.__state_lock:
            self.__completion_requested = True

    def is_running(self) -> bool:
        return self.__running

    def generate_import_session(self) -> int:
        self.__common_data["last_import_run_id"] = self.__helper.get_timestamp()
        self.__helper.get_handler_debug().write(
            f"Generated new import session: {self.__common_data['last_import_run_id']}"
        )
        return self.__common_data["last_import_run_id"]

    def import_data(self, force: bool = False) -> None:
        if not force and self.get_imported_percent() < 100:
            self.__helper.get_handler_debug().write(
                "Blocked new import as previous import wasn't finished"
            )
            return

        with self.__state_lock:
            if not self.active:
                return
            if self.__running:
                self.__helper.get_handler_debug().write("Import already running, skipped new import.")
                return
            self.__running = True
            self.__idle.clear()

        try:
            self.__common_data["last_import_run_id"] = self.__helper.get_timestamp()

            self.__helper.get_handler_debug().write("Importing UEX data from the data relay ...")
            self.__helper.start_timer("import_total")
            total_count = self.__import_data()
        finally:
            with self.__state_lock:
                self.__running = False
                self.__idle.set()
        if not self.active:
            # Stopped by unload: the interrupted bundle is fetched again with the next start
            self.__helper.get_handler_debug().write("Import stopped by unload, it continues with the next start.")
            return
        if self.__helper.get_wingmen().settings.debug_mode:
            self.__helper.get_handler_debug().write(
                f"UEX data imported: {total_count} record(s) in {self.__helper.end_timer('import_total')}s",
                total_count > 0,
            )
        with self.__state_lock:
            completion_requested, self.__completion_requested = self.__completion_requested, False
        # An import that brought no data (relay unreachable on a fresh install) completes nothing:
        # the blacklists would be rewritten empty; the master loop retries it every minute
        if (not self.is_preload or completion_requested) and self.has_data():
            self.__helper.on_import_completed(total_count)

    def get_common_data(self) -> dict[str, any]:
        return self.__common_data

    def get_version_uex(self, force_check: bool = False) -> str:
        from skills.uexcorp.uexcorp.model.game_version import GameVersion

        try:
            self.__import_data_game_version(force_check)
        except UexApiError as e:
            # Keep working with the last known version, the next check fetches it again
            self.__helper.get_handler_debug().write(f"Game version check failed: {e}")
        return GameVersion(load=True).get_live()

    def get_imported_percent(self) -> int:
        return self.__imported_percent

    def has_data(self) -> bool:
        """Locations and prices are there: the tools can answer. False on a fresh install
        (or a rebuilt database) until the first import got them."""
        database = self.__helper.get_database()
        try:
            return all(
                database.table_exists(table)
                and database.execute_fetchall(f"SELECT EXISTS(SELECT 1 FROM {table})")[0][0]
                for table in ("terminal", "commodity_price")
            )
        except Exception:
            return False

    def get_last_error(self) -> str | None:
        return self.__last_error

    def __advance(self, steps: int = 1) -> None:
        self.__progress_done += steps
        self.__imported_percent = min(int(self.__progress_done * 100 / self.__progress_steps), 99)

    def __import_data(self) -> int:
        total_count = 0
        self.__imported_percent = 0
        self.__progress_done = 0
        self.__imported_tables = set()
        errors = self.__round_errors = []
        unreachable = False
        try:
            # First: an interrupted first import can only be continued if the game version is
            # already stored, otherwise the next start's version parity check recreates the DB.
            steps = [("game_version", self.__import_data_game_version, 1)]
            steps += [
                (f"{bundle} bundle", lambda bundle=bundle: self.__import_bundle(bundle), 0)
                for bundle in self.BUNDLES
            ]
            steps.append(("commodity_route", self.__import_data_commodity_route, 1))
            for name, importer, progress in steps:
                if not self.active:
                    break
                # The relay is down: its other requests would only fail too (the trade legs are local)
                if unreachable and name != "commodity_route":
                    continue
                try:
                    total_count += int(importer() or 0)
                except UexApiError as e:
                    if not self.active:
                        break  # cancelled by unload, not a failure
                    # Not marked as imported, so the next import run (master loop) retries it
                    errors.append(self.UNREACHABLE)
                    # A rejected request (4xx) concerns that request only; anything else, the relay
                    unreachable = unreachable or not isinstance(e, UexClientError)
                    self.__helper.get_handler_debug().write(
                        f"Import of {name} failed and will be retried with the next import run: {e}"
                    )
                except Exception as e:
                    # Unexpected data or database errors must not stop the other steps either
                    errors.append(str(e))
                    self.__helper.get_handler_error().write(f"ImportHandler.{name}", [], e)
                    self.__helper.get_handler_debug().write(
                        f"Import of {name} failed unexpectedly and will be retried with the next import run: {e}"
                    )
                self.__advance(progress)
        finally:
            # Always done: the master loop only refreshes at 100 %
            self.__imported_percent = 100
        if self.active:
            self.__report_outcome(errors)
        return total_count

    def __report_outcome(self, errors: list[str]) -> None:
        """One message per outage for the user (not one per request), and one when it is over."""
        if not errors:
            self.__last_error = None
            if self.__no_data_reported or self.__relay_down_reported:
                self.__helper.get_handler_debug().write("UEX data source reachable again, data is up to date.", True)
            self.__no_data_reported = self.__relay_down_reported = False
            return
        self.__last_error = self.UNREACHABLE if self.UNREACHABLE in errors else errors[0]
        if not self.has_data():
            if not self.__no_data_reported:
                self.__no_data_reported = True
                self.__helper.get_handler_debug().write(
                    f"UEX data could not be loaded ({self.__last_error}). Trading and location answers are "
                    f"unavailable until it works, retrying every minute.", True
                )
        elif not self.__relay_down_reported:
            self.__relay_down_reported = True
            self.__helper.get_handler_debug().write(
                f"UEX data could not be refreshed ({self.__last_error}). Working with the stored data, retrying in the background.",
                True,
            )

    def __import_bundle(self, bundle: str) -> int:
        """Fetches one relay bundle (if the stored one is outdated) and replaces its tables."""
        from skills.uexcorp.uexcorp.model.import_data import ImportData

        database = self.__helper.get_database()
        datasets = [dataset for dataset in self.DATASETS if dataset.bundle == bundle and database.table_exists(dataset.table)]
        state = ImportData(f"relay_{bundle}", load=True)
        complete = all(ImportData(dataset.table, load=True).get_date_imported() for dataset in datasets)
        if complete and not state.is_expired():
            self.__advance(len(datasets))
            return 0

        self.__helper.start_timer(f"bundle_{bundle}")
        try:
            response = self.__api.fetch_bundle(bundle, state.get_etag() if complete else None)
        except UexApiError:
            # The relay is the only source: the stored tables stay as they are
            self.__advance(len(datasets))
            raise
        now = self.__helper.get_timestamp()
        lifetime = self.__get_bundle_lifetime(bundle)

        unchanged = complete and (response.data is None or (response.etag and response.etag == state.get_etag()))
        count = 0
        failed = []
        if unchanged:
            self.__advance(len(datasets))
            self.__helper.get_handler_debug().write(f"Relay {bundle} bundle unchanged, nothing to import.")
        else:
            for dataset in datasets:
                if not self.active:
                    return count  # bundle stays outdated: fetched again with the next start
                try:
                    count += self.__import_dataset(dataset, response.data)
                except Exception as e:
                    # The other tables still import; the whole bundle is fetched again next run.
                    # The user hears of it once, with the round's other problems (__report_outcome)
                    failed.append(dataset.table)
                    self.__round_errors.append(f"{dataset.table}: {e}")
                    if not isinstance(e, UexApiError):
                        self.__helper.get_handler_error().write(f"ImportHandler.{dataset.table}", [], e)
                    self.__helper.get_handler_debug().write(
                        f"Import of {dataset.table} failed and will be retried with the next import run: {e}"
                    )
                self.__advance()

        if failed:
            state.set_date_expires(None)
        else:
            state.set_etag(response.etag)
            state.set_date_expires(now + self.__get_refresh_in(response.max_age, lifetime))
            if not unchanged:
                state.set_date_imported(now)
                state.set_dataset_count(count)
                state.set_time_taken(self.__helper.end_timer(f"bundle_{bundle}"))
        state.persist()
        if not unchanged:
            self.__helper.get_handler_debug().write(
                f"Relay {bundle} bundle imported: {count} record(s), next refresh in {self.__get_refresh_in(response.max_age, lifetime)}s"
                + (f", failed: {', '.join(failed)}" if failed else "")
            )
        return count

    def __get_bundle_lifetime(self, bundle: str) -> int:
        config = self.__helper.get_handler_config()
        return config.get_cache_lifetime_long() if bundle == Uex.BUNDLE_LONG else config.get_cache_lifetime_short()

    def __get_refresh_in(self, max_age: int | None, lifetime: int) -> int:
        """Seconds until the bundle is fetched again: when the relay has newer data, capped by the lifetime."""
        if max_age is None:
            return lifetime
        return min(lifetime, max(self.MIN_REFRESH, max_age + self.RELAY_MARGIN))

    def __import_dataset(self, dataset: _Dataset, bundle_data: dict) -> int:
        """Replaces one table with the dataset's rows in a single transaction."""
        from skills.uexcorp.uexcorp.model.import_data import ImportData

        if dataset.name not in bundle_data:
            raise UexApiError(f"{dataset.name} missing in the relay {dataset.bundle} bundle")
        self.__helper.start_timer("import")

        models = self.__build_models(dataset, bundle_data[dataset.name])
        columns = None
        values = []
        for model in models:
            data = model.get_persist_data()
            if columns is None:
                columns = list(data)
            values.append(tuple(data[column] for column in columns))
        # Every table has this column; with no rows only the old ones are removed
        self.__helper.get_database().replace_table(dataset.table, columns or ["last_import_run_id"], values)

        table_import = ImportData(dataset.table, load=True)
        table_import.set_date_imported(self.__helper.get_timestamp())
        table_import.set_dataset_count(len(values))
        table_import.set_time_taken(self.__helper.end_timer("import"))
        table_import.persist()
        self.__imported_tables.add(dataset.table)
        self.__helper.get_handler_debug().write(
            f"{dataset.table} data imported: {len(values)} record(s) in {table_import.get_time_taken()}s"
        )
        return len(values)

    def __build_models(self, dataset: _Dataset, rows: any) -> list["DataModel"]:
        from skills.uexcorp.uexcorp.model.commodity_alert import CommodityAlert
        from skills.uexcorp.uexcorp.model.commodity_status import CommodityStatus

        if dataset.table == "commodity_status":
            if not isinstance(rows, dict):
                raise UexApiError(f"Unexpected {dataset.name} format: {type(rows).__name__}")
            models = []
            for is_buy, key in ((True, "buy"), (False, "sell")):
                for row in rows.get(key) or []:
                    model = CommodityStatus(row["code"], is_buy)
                    model.set_data(row)
                    models.append(model)
            return models

        if not isinstance(rows, list):
            raise UexApiError(f"Unexpected {dataset.name} format: {type(rows).__name__}")

        if dataset.table == "commodity_alert":
            models = []
            for row in rows:
                model = CommodityAlert()
                model.set_data(row)
                models.append(model)
            return models

        model_class = self.__get_model_class(dataset.table)
        models = []
        skipped = 0
        for row in rows:
            if not isinstance(row, dict) or row.get("id") is None:
                # e.g. the relay lists empty API answers ({"status": "ok", "data": null}) as rows
                skipped += 1
                continue
            model = model_class(row["id"])
            if dataset.table == "item_attribute":
                model_class.normalize_unit(row)
            model.set_data(row)
            if dataset.table == "category":
                self.__prepare_category(model, row)
            models.append(model)
        if skipped:
            self.__helper.get_handler_debug().write(f"Skipped {skipped} {dataset.name} entries without an id.")
        return models

    @staticmethod
    def __get_model_class(table: str) -> type:
        module = importlib.import_module(f"skills.uexcorp.uexcorp.model.{table}")
        return getattr(module, "".join(part.capitalize() for part in table.split("_")))

    @staticmethod
    def __prepare_category(category, row: dict) -> None:
        # workaround for missing sqlite CONCAT function
        if "name" in row and "section" in row:
            category.data["combined_name"] = f"{row['section']} {row['name']}"
        if category.get_section() == "Armor" and category.get_name() == "Set":
            category.data["is_game_related"] = 0

    def __import_data_game_version(self, force_check: bool = False) -> bool | int:
        from skills.uexcorp.uexcorp.model.import_data import ImportData
        from skills.uexcorp.uexcorp.model.game_version import GameVersion

        if not self.__helper.get_database().table_exists("game_version"):
            return False

        game_version_import = ImportData("game_version", load=True)
        if not force_check and not game_version_import.needs_import(
            self.__helper.get_handler_config().get_cache_lifetime_short()
        ):
            return False
        # The version check right before an import failed: no second round of failing requests
        if not force_check and time.monotonic() - self.__version_failed_at < self.VERSION_RETRY_PAUSE:
            return False

        self.__helper.start_timer("import")

        try:
            game_version_data = self.__api.fetch_version()
        except UexApiError:
            self.__version_failed_at = time.monotonic()
            raise
        game_version = GameVersion()
        game_version.set_data(game_version_data)
        game_version.persist()

        game_version_import.set_date_imported(self.__helper.get_timestamp())
        game_version_import.set_dataset_count(1)
        game_version_import.set_time_taken(self.__helper.end_timer("import"))
        game_version_import.persist()
        self.__helper.get_handler_debug().write(
            f"Game Version data imported: {game_version.get_live()} in {game_version_import.get_time_taken()}s"
        )
        return 1

    # Ship-independent trade legs (buy at one terminal, sell at another), derived from our own
    # price, terminal and orbit distance data instead of the UEX routes endpoint (~70 requests).
    # Parent location flags come from the station/city/outpost/poi the terminal belongs to.
    COMMODITY_ROUTE_SQL = """
        SELECT
            b.id_commodity, c.name AS commodity_name, c.code AS commodity_code, c.slug AS commodity_slug,
            b.id_terminal AS id_terminal_origin, s.id_terminal AS id_terminal_destination,
            b.price_buy AS price_origin, s.price_sell AS price_destination,
            -- scu_sell 0 means "not reported" (most sell offers), not "no demand": UEX's own
            -- routes treated it the same way (checked on 7,079 of 7,079 routes)
            b.scu_buy AS scu_origin, NULLIF(s.scu_sell, 0) AS scu_destination,
            b.status_buy AS status_origin, s.status_sell AS status_destination,
            b.container_sizes AS container_sizes_origin, s.container_sizes AS container_sizes_destination,
            MAX(b.date_modified, s.date_modified) AS date_added,
            {terminal_columns_origin},
            {terminal_columns_destination},
            CASE WHEN o.id_orbit = d.id_orbit THEN 0 ELSE COALESCE(
                (SELECT od.distance FROM orbit_distance od
                 WHERE od.id_orbit_origin = o.id_orbit AND od.id_orbit_destination = d.id_orbit LIMIT 1),
                (SELECT od.distance FROM orbit_distance od
                 WHERE od.id_orbit_origin = d.id_orbit AND od.id_orbit_destination = o.id_orbit LIMIT 1)
            ) END AS distance
        FROM commodity_price b
        JOIN commodity_price s ON s.id_commodity = b.id_commodity AND s.id_terminal != b.id_terminal
        JOIN terminal o ON o.id = b.id_terminal
        JOIN terminal d ON d.id = s.id_terminal
        LEFT JOIN commodity c ON c.id = b.id_commodity
        {parent_joins}
        WHERE b.price_buy > 0 AND s.price_sell > b.price_buy
          -- Terminals not available in the game are no stops (the tool's location filters agree)
          AND o.is_available AND d.is_available
    """

    # Tables the trade legs are built from (prices, terminals, distances, parent locations)
    COMMODITY_ROUTE_SOURCES = (
        "commodity_price", "terminal", "orbit_distance", "space_station", "city", "outpost", "poi",
    )

    @staticmethod
    def __commodity_route_sql() -> str:
        def terminal_columns(alias: str, side: str) -> str:
            def parent(field: str) -> str:
                return (
                    f"CASE WHEN {alias}.id_space_station THEN {alias}_ss.{field} WHEN {alias}.id_city THEN {alias}_ci.{field} "
                    f"WHEN {alias}.id_outpost THEN {alias}_ou.{field} WHEN {alias}.id_poi THEN {alias}_po.{field} END"
                )
            return ", ".join([
                f"{alias}.id_star_system AS id_star_system_{side}",
                f"{alias}.id_planet AS id_planet_{side}",
                f"{alias}.id_orbit AS id_orbit_{side}",
                f"{alias}.id_faction AS id_faction_{side}",
                f"{alias}.star_system_name AS {side}_star_system_name",
                f"{alias}.planet_name AS {side}_planet_name",
                f"{alias}.orbit_name AS {side}_orbit_name",
                f"{alias}.faction_name AS {side}_faction_name",
                f"{alias}.name AS {side}_terminal_name",
                f"{alias}.code AS {side}_terminal_code",
                f"{alias}.is_player_owned AS {side}_terminal_is_player_owned",
                f"{alias}.game_version AS game_version_{side}",
                # Facilities count if the terminal or its parent location has them (matches UEX 100%)
                *(
                    f"CASE WHEN {alias}.{field} OR {parent(field)} THEN 1 ELSE 0 END AS {field}_{side}"
                    for field in ("has_loading_dock", "has_docking_port", "has_freight_elevator")
                ),
                f"{parent('is_monitored')} AS is_monitored_{side}",
                f"{parent('has_refuel')} AS has_refuel_{side}",
                f"{parent('has_cargo_center')} AS has_cargo_center_{side}",
                f"{parent('has_quantum_marker')} AS has_quantum_marker_{side}",
                f"CASE WHEN {alias}.id_space_station THEN 1 ELSE 0 END AS is_space_station_{side}",
                f"CASE WHEN {alias}.id_city OR {alias}.id_outpost THEN 1 ELSE 0 END AS is_on_ground_{side}",
            ])

        parent_joins = "\n".join(
            f"LEFT JOIN {table} {alias}_{short} ON {alias}_{short}.id = {alias}.{key}"
            for alias in ("o", "d")
            for table, short, key in (
                ("space_station", "ss", "id_space_station"),
                ("city", "ci", "id_city"),
                ("outpost", "ou", "id_outpost"),
                ("poi", "po", "id_poi"),
            )
        )
        return ImportHandler.COMMODITY_ROUTE_SQL.format(
            terminal_columns_origin=terminal_columns("o", "origin"),
            terminal_columns_destination=terminal_columns("d", "destination"),
            parent_joins=parent_joins,
        )

    def __import_data_commodity_route(self) -> bool | int:
        from skills.uexcorp.uexcorp.model.import_data import ImportData
        from skills.uexcorp.uexcorp.model.commodity_route import CommodityRoute

        database = self.__helper.get_database()
        if not database.table_exists("commodity_route"):
            return False

        # Derived only once every source table is there (not marked otherwise, so the next import
        # run derives them): a failed distance or location import would otherwise leave routes
        # without distances or facilities. Derived again whenever any source table is newer.
        sources = [ImportData(table, load=True) for table in self.COMMODITY_ROUTE_SOURCES]
        if not all(source.get_date_imported() for source in sources):
            return False
        commodity_route_import = ImportData("commodity_route", load=True)
        # Replaced in this run, or newer (a run whose derivation failed): timestamps are in
        # seconds, so the first check catches a refresh within the second of the last derivation
        sources_newer = bool(self.__imported_tables.intersection(self.COMMODITY_ROUTE_SOURCES)) or (
            commodity_route_import.get_date_imported() or 0
        ) < max(source.get_date_imported() for source in sources)
        if not sources_newer and not commodity_route_import.needs_import(
            self.__helper.get_handler_config().get_cache_lifetime_short()
        ):
            return False

        self.__helper.start_timer("import")

        rows = [dict(row) for row in database.execute_fetchall(self.__commodity_route_sql())]
        columns = None
        values = []
        for index, row in enumerate(rows):
            price_origin, price_destination = row["price_origin"], row["price_destination"]
            stock = row["scu_origin"] or 0
            demand = row["scu_destination"]
            tradeable = min(stock, demand) if demand else stock
            row.update({
                "code": f"{row['commodity_code']}-{row['origin_terminal_code']}-{row['destination_terminal_code']}",
                "price_margin": (price_destination - price_origin) / price_destination * 100,
                "price_roi": (price_destination - price_origin) / price_origin * 100,
                "investment": price_origin * stock,
                "profit": (price_destination - price_origin) * tradeable,
            })
            commodity_route = CommodityRoute(index + 1)
            commodity_route.set_data(row)
            data = commodity_route.get_persist_data()
            if columns is None:
                columns = list(data)
            values.append(tuple(data[column] for column in columns))
        # One transaction under the DB lock: route tool calls never see a half-built table
        database.replace_table("commodity_route", columns or ["id"], values)

        commodity_route_import.set_date_imported(self.__helper.get_timestamp())
        commodity_route_import.set_dataset_count(len(rows))
        commodity_route_import.set_time_taken(self.__helper.end_timer("import"))
        commodity_route_import.persist()
        self.__helper.get_handler_debug().write(
            f"Commodity Route data derived: {commodity_route_import.get_dataset_count()} trade leg(s) in {commodity_route_import.get_time_taken()}s"
        )
        return len(rows)

    def destroy(self) -> None:
        """Stops a running import right away instead of waiting for it.

        The interrupted bundle stays outdated, so the next start fetches it again."""
        with self.__state_lock:
            self.active = False  # no new import can start from here on
        # Aborts retry waits and running downloads (checked per chunk)
        self.__api.cancel()

        # A prepare's version check uses the database too (before any import runs): wait for it
        if self.__prepare_lock.acquire(timeout=self.STOP_TIMEOUT):
            self.__prepare_lock.release()

        if self.__idle.is_set():
            return
        self.__helper.get_handler_debug().write(
            f"Stopping running import at {self.__imported_percent}% for unload, it continues with the next start ..."
        )
        # Wait for the import thread to stop before the database gets closed
        if self.__idle.wait(self.STOP_TIMEOUT):
            self.__helper.get_handler_debug().write("Import stopped.")
        else:
            self.__helper.get_handler_debug().write(
                f"Import did not stop within {self.STOP_TIMEOUT}s, unloading anyway.", True
            )
