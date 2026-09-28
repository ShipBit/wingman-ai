"""
SC_Accountant — Market Data Module

Lightweight UEX API client with SQLite cache for commodity prices,
terminals, and trade routes. Independent of the UEXCorp skill.

API: https://api.uexcorp.space/2.0 (public, no auth required)

Author: Mallachi
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

UEX_BASE_URL = "https://api.uexcorp.space/2.0"

# Cache lifetimes in seconds
CACHE_STATIC = 14 * 24 * 3600  # 14 days — commodities, terminals
CACHE_PRICES = 24 * 3600  # 24 hours — prices, routes, status codes

# Status codes that indicate unavailable stock (excluded from trade results)
# These are commodity_status.code values from UEX
UNAVAILABLE_BUY_STATUSES: set[int] = set()  # Populated from commodity_status table
UNAVAILABLE_SELL_STATUSES: set[int] = set()  # Populated from commodity_status table

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_meta (
    table_name TEXT PRIMARY KEY,
    last_refreshed REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS commodity (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    code TEXT,
    slug TEXT,
    kind TEXT,
    price_buy REAL,
    price_sell REAL,
    is_buyable INTEGER DEFAULT 0,
    is_sellable INTEGER DEFAULT 0,
    is_illegal INTEGER DEFAULT 0,
    is_raw INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS terminal (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    nickname TEXT,
    code TEXT,
    type TEXT,
    star_system_name TEXT,
    planet_name TEXT,
    orbit_name TEXT,
    moon_name TEXT,
    space_station_name TEXT,
    outpost_name TEXT,
    city_name TEXT,
    has_loading_dock INTEGER DEFAULT 0,
    has_docking_port INTEGER DEFAULT 0,
    has_freight_elevator INTEGER DEFAULT 0,
    is_refuel INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS commodity_price (
    id INTEGER PRIMARY KEY,
    id_commodity INTEGER NOT NULL,
    id_terminal INTEGER NOT NULL,
    price_buy REAL,
    price_sell REAL,
    scu_buy REAL,
    scu_sell_stock REAL,
    status_buy INTEGER,
    status_sell INTEGER,
    commodity_name TEXT,
    commodity_code TEXT,
    terminal_name TEXT,
    terminal_code TEXT,
    FOREIGN KEY (id_commodity) REFERENCES commodity(id),
    FOREIGN KEY (id_terminal) REFERENCES terminal(id)
);

CREATE TABLE IF NOT EXISTS commodity_route (
    id INTEGER PRIMARY KEY,
    id_commodity INTEGER NOT NULL,
    commodity_name TEXT,
    commodity_code TEXT,
    price_origin REAL,
    price_destination REAL,
    price_margin REAL,
    scu_origin REAL,
    scu_destination REAL,
    profit REAL,
    investment REAL,
    distance REAL,
    score INTEGER,
    status_origin INTEGER,
    status_destination INTEGER,
    id_terminal_origin INTEGER,
    id_terminal_destination INTEGER,
    origin_terminal_name TEXT,
    origin_star_system_name TEXT,
    origin_planet_name TEXT,
    destination_terminal_name TEXT,
    destination_star_system_name TEXT,
    destination_planet_name TEXT,
    has_loading_dock_origin INTEGER DEFAULT 0,
    has_loading_dock_destination INTEGER DEFAULT 0,
    FOREIGN KEY (id_commodity) REFERENCES commodity(id)
);

CREATE TABLE IF NOT EXISTS commodity_status (
    code INTEGER NOT NULL,
    is_buy INTEGER NOT NULL,
    name TEXT,
    name_short TEXT,
    PRIMARY KEY (code, is_buy)
);

CREATE TABLE IF NOT EXISTS vehicle_price (
    id INTEGER PRIMARY KEY,
    id_vehicle INTEGER NOT NULL,
    id_terminal INTEGER NOT NULL,
    price_buy REAL,
    vehicle_name TEXT,
    terminal_name TEXT
);

CREATE INDEX IF NOT EXISTS idx_price_commodity ON commodity_price(id_commodity);
CREATE INDEX IF NOT EXISTS idx_price_terminal ON commodity_price(id_terminal);
CREATE INDEX IF NOT EXISTS idx_route_commodity ON commodity_route(id_commodity);
CREATE INDEX IF NOT EXISTS idx_route_score ON commodity_route(score DESC);
CREATE INDEX IF NOT EXISTS idx_route_profit ON commodity_route(profit DESC);
CREATE INDEX IF NOT EXISTS idx_vehicle_price_name ON vehicle_price(vehicle_name);
"""


class MarketData:
    """Lightweight UEX market data cache.

    Fetches commodity prices, terminals, and trade routes from the public
    UEX API and caches them in a local SQLite database.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._session = requests.Session()
        self._session.headers["Accept"] = "application/json"
        self._session.timeout = 15
        self._unavailable_buy: set[int] = set()
        self._unavailable_sell: set[int] = set()

    def open(self) -> None:
        """Open the database connection and ensure schema exists."""
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            timeout=10,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._load_unavailable_statuses()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # API fetching
    # ------------------------------------------------------------------

    def _fetch(self, endpoint: str, params: dict | None = None) -> list[dict]:
        """Fetch data from the UEX API.

        Args:
            endpoint: API endpoint path (appended to base URL).
            params: Optional query parameters.

        Returns:
            List of data records, or empty list on failure.
        """
        url = f"{UEX_BASE_URL}/{endpoint}"
        try:
            resp = self._session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            body = resp.json()
            if body.get("status") == "ok" and "data" in body:
                return body["data"]
            logger.warning(
                "UEX API unexpected response for %s: %s", endpoint, body.get("status")
            )
            return []
        except requests.RequestException:
            logger.exception("UEX API request failed for %s", endpoint)
            return []
        except (json.JSONDecodeError, KeyError):
            logger.exception("UEX API response parse error for %s", endpoint)
            return []

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def _get_cache_age(self, table_name: str) -> float:
        """Return seconds since last refresh for a table. Inf if never refreshed."""
        if not self._conn:
            return float("inf")
        row = self._conn.execute(
            "SELECT last_refreshed FROM cache_meta WHERE table_name = ?",
            (table_name,),
        ).fetchone()
        if not row:
            return float("inf")
        return time.time() - row["last_refreshed"]

    def _set_cache_timestamp(self, table_name: str) -> None:
        """Mark a table as freshly refreshed."""
        if not self._conn:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO cache_meta (table_name, last_refreshed) VALUES (?, ?)",
            (table_name, time.time()),
        )
        self._conn.commit()

    def needs_refresh(self, table_name: str, max_age: float) -> bool:
        """Check if a table's cache has expired."""
        return self._get_cache_age(table_name) > max_age

    # ------------------------------------------------------------------
    # Import: Commodities (static, 14-day cache)
    # ------------------------------------------------------------------

    def refresh_commodities(self, force: bool = False) -> int:
        """Refresh the commodity list from UEX.

        Returns number of commodities imported.
        """
        if not force and not self.needs_refresh("commodity", CACHE_STATIC):
            return 0

        data = self._fetch("commodities")
        if not data:
            return 0

        if not self._conn:
            return 0

        self._conn.execute("DELETE FROM commodity")
        count = 0
        for row in data:
            try:
                self._conn.execute(
                    """INSERT OR REPLACE INTO commodity
                    (id, name, code, slug, kind, price_buy, price_sell,
                     is_buyable, is_sellable, is_illegal, is_raw)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row.get("id"),
                        row.get("name", ""),
                        row.get("code", ""),
                        row.get("slug", ""),
                        row.get("kind", ""),
                        row.get("price_buy", 0),
                        row.get("price_sell", 0),
                        row.get("is_buyable", 0),
                        row.get("is_sellable", 0),
                        row.get("is_illegal", 0),
                        row.get("is_raw", 0),
                    ),
                )
                count += 1
            except sqlite3.Error:
                logger.warning("Failed to insert commodity: %s", row.get("name"))

        self._conn.commit()
        self._set_cache_timestamp("commodity")
        logger.info("Imported %d commodities from UEX", count)
        return count

    # ------------------------------------------------------------------
    # Import: Terminals (static, 14-day cache)
    # ------------------------------------------------------------------

    def refresh_terminals(self, force: bool = False) -> int:
        """Refresh the terminal list from UEX."""
        if not force and not self.needs_refresh("terminal", CACHE_STATIC):
            return 0

        data = self._fetch("terminals")
        if not data:
            return 0

        if not self._conn:
            return 0

        self._conn.execute("DELETE FROM terminal")
        count = 0
        for row in data:
            try:
                self._conn.execute(
                    """INSERT OR REPLACE INTO terminal
                    (id, name, nickname, code, type,
                     star_system_name, planet_name, orbit_name, moon_name,
                     space_station_name, outpost_name, city_name,
                     has_loading_dock, has_docking_port, has_freight_elevator,
                     is_refuel)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row.get("id"),
                        row.get("name", ""),
                        row.get("nickname", ""),
                        row.get("code", ""),
                        row.get("type", ""),
                        row.get("star_system_name", ""),
                        row.get("planet_name", ""),
                        row.get("orbit_name", ""),
                        row.get("moon_name", ""),
                        row.get("space_station_name", ""),
                        row.get("outpost_name", ""),
                        row.get("city_name", ""),
                        row.get("has_loading_dock", 0),
                        row.get("has_docking_port", 0),
                        row.get("has_freight_elevator", 0),
                        row.get("is_refuel", 0),
                    ),
                )
                count += 1
            except sqlite3.Error:
                logger.warning("Failed to insert terminal: %s", row.get("name"))

        self._conn.commit()
        self._set_cache_timestamp("terminal")
        logger.info("Imported %d terminals from UEX", count)
        return count

    # ------------------------------------------------------------------
    # Import: Commodity Status Codes (24h cache)
    # ------------------------------------------------------------------

    def refresh_statuses(self, force: bool = False) -> int:
        """Refresh commodity status codes from UEX."""
        if not force and not self.needs_refresh("commodity_status", CACHE_PRICES):
            return 0

        raw = self._fetch("commodities_status")
        if not raw:
            return 0

        if not self._conn:
            return 0

        # API returns {"buy": [...], "sell": [...]} instead of a flat list.
        # Flatten into rows with an is_buy flag.
        data: list[dict] = []
        if isinstance(raw, dict):
            for row in raw.get("buy", []):
                data.append({**row, "is_buy": 1})
            for row in raw.get("sell", []):
                data.append({**row, "is_buy": 0})
        elif isinstance(raw, list):
            data = raw

        self._conn.execute("DELETE FROM commodity_status")
        count = 0
        for row in data:
            try:
                self._conn.execute(
                    """INSERT OR REPLACE INTO commodity_status
                    (code, is_buy, name, name_short)
                    VALUES (?, ?, ?, ?)""",
                    (
                        row.get("code"),
                        row.get("is_buy", 0),
                        row.get("name", ""),
                        row.get("name_short", ""),
                    ),
                )
                count += 1
            except sqlite3.Error:
                logger.warning("Failed to insert commodity_status: %s", row.get("code"))

        self._conn.commit()
        self._set_cache_timestamp("commodity_status")
        self._load_unavailable_statuses()
        logger.info("Imported %d commodity status codes from UEX", count)
        return count

    def _load_unavailable_statuses(self) -> None:
        """Load status codes that mean 'out of stock' / 'inventory full'."""
        if not self._conn:
            return

        self._unavailable_buy = set()
        self._unavailable_sell = set()

        rows = self._conn.execute(
            "SELECT code, is_buy, name FROM commodity_status"
        ).fetchall()
        for row in rows:
            name_lower = (row["name"] or "").lower()
            # "out of stock" on the buy side = terminal has nothing to sell
            if row["is_buy"] and (
                "out of stock" in name_lower or "no stock" in name_lower
            ):
                self._unavailable_buy.add(row["code"])
            # "inventory full" on the sell side = terminal won't buy any more
            if not row["is_buy"] and (
                "inventory full" in name_lower or "no demand" in name_lower
            ):
                self._unavailable_sell.add(row["code"])

    # ------------------------------------------------------------------
    # Import: Commodity Prices (24h full, per-commodity on trade)
    # ------------------------------------------------------------------

    def refresh_prices(self, force: bool = False) -> int:
        """Refresh all commodity prices from UEX."""
        if not force and not self.needs_refresh("commodity_price", CACHE_PRICES):
            return 0

        data = self._fetch("commodities_prices_all")
        if not data:
            return 0

        if not self._conn:
            return 0

        self._conn.execute("DELETE FROM commodity_price")
        count = self._insert_prices(data)
        self._set_cache_timestamp("commodity_price")
        logger.info("Imported %d commodity prices from UEX", count)
        return count

    def refresh_commodity_prices(self, commodity_id: int) -> int:
        """Refresh prices for a single commodity (targeted, on trade events).

        Args:
            commodity_id: The UEX commodity ID to refresh.

        Returns:
            Number of price records updated.
        """
        data = self._fetch(
            "commodities_prices_all", params={"id_commodity": commodity_id}
        )
        if not data:
            return 0

        if not self._conn:
            return 0

        # Delete only this commodity's prices, then re-insert
        self._conn.execute(
            "DELETE FROM commodity_price WHERE id_commodity = ?",
            (commodity_id,),
        )
        count = self._insert_prices(data)
        self._conn.commit()
        logger.info("Refreshed %d prices for commodity %d", count, commodity_id)
        return count

    def _insert_prices(self, data: list[dict]) -> int:
        """Insert commodity price records into the database."""
        if not self._conn:
            return 0

        count = 0
        for row in data:
            try:
                self._conn.execute(
                    """INSERT OR REPLACE INTO commodity_price
                    (id, id_commodity, id_terminal,
                     price_buy, price_sell,
                     scu_buy, scu_sell_stock,
                     status_buy, status_sell,
                     commodity_name, commodity_code,
                     terminal_name, terminal_code)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row.get("id"),
                        row.get("id_commodity"),
                        row.get("id_terminal"),
                        row.get("price_buy", 0),
                        row.get("price_sell", 0),
                        row.get("scu_buy", 0),
                        row.get("scu_sell_stock", 0),
                        row.get("status_buy"),
                        row.get("status_sell"),
                        row.get("commodity_name", ""),
                        row.get("commodity_code", ""),
                        row.get("terminal_name", ""),
                        row.get("terminal_code", ""),
                    ),
                )
                count += 1
            except sqlite3.Error:
                logger.warning(
                    "Failed to insert price for commodity %s", row.get("commodity_name")
                )

        self._conn.commit()
        return count

    # ------------------------------------------------------------------
    # Import: Trade Routes (24h cache)
    # ------------------------------------------------------------------

    def refresh_routes(self, force: bool = False) -> int:
        """Refresh all trade routes from UEX.

        Routes are fetched per-commodity via /commodities_routes?id_commodity=X.
        Only fetches for commodities that are both buyable and sellable.
        """
        if not force and not self.needs_refresh("commodity_route", CACHE_PRICES):
            return 0

        if not self._conn:
            return 0

        # Get all tradeable commodity IDs
        commodity_ids = [
            row["id"]
            for row in self._conn.execute(
                "SELECT id FROM commodity WHERE is_buyable = 1 AND is_sellable = 1"
            ).fetchall()
        ]

        if not commodity_ids:
            # Ensure commodities are loaded first
            self.refresh_commodities(force=True)
            commodity_ids = [
                row["id"]
                for row in self._conn.execute(
                    "SELECT id FROM commodity WHERE is_buyable = 1 AND is_sellable = 1"
                ).fetchall()
            ]

        self._conn.execute("DELETE FROM commodity_route")
        total = 0

        for cid in commodity_ids:
            data = self._fetch("commodities_routes", params={"id_commodity": cid})
            if data:
                total += self._insert_routes(data)

        self._set_cache_timestamp("commodity_route")
        logger.info("Imported %d trade routes from UEX", total)
        return total

    def refresh_commodity_routes(self, commodity_id: int) -> int:
        """Refresh routes for a single commodity."""
        data = self._fetch("commodities_routes", params={"id_commodity": commodity_id})
        if not data:
            return 0

        if not self._conn:
            return 0

        self._conn.execute(
            "DELETE FROM commodity_route WHERE id_commodity = ?",
            (commodity_id,),
        )
        count = self._insert_routes(data)
        logger.info("Refreshed %d routes for commodity %d", count, commodity_id)
        return count

    def _insert_routes(self, data: list[dict]) -> int:
        """Insert trade route records."""
        if not self._conn:
            return 0

        count = 0
        for row in data:
            try:
                self._conn.execute(
                    """INSERT OR REPLACE INTO commodity_route
                    (id, id_commodity, commodity_name, commodity_code,
                     price_origin, price_destination, price_margin,
                     scu_origin, scu_destination,
                     profit, investment, distance, score,
                     status_origin, status_destination,
                     id_terminal_origin, id_terminal_destination,
                     origin_terminal_name, origin_star_system_name, origin_planet_name,
                     destination_terminal_name, destination_star_system_name, destination_planet_name,
                     has_loading_dock_origin, has_loading_dock_destination)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row.get("id"),
                        row.get("id_commodity"),
                        row.get("commodity_name", ""),
                        row.get("commodity_code", ""),
                        row.get("price_origin", 0),
                        row.get("price_destination", 0),
                        row.get("price_margin", 0),
                        row.get("scu_origin", 0),
                        row.get("scu_destination", 0),
                        row.get("profit", 0),
                        row.get("investment", 0),
                        row.get("distance", 0),
                        row.get("score", 0),
                        row.get("status_origin"),
                        row.get("status_destination"),
                        row.get("id_terminal_origin"),
                        row.get("id_terminal_destination"),
                        row.get("origin_terminal_name", ""),
                        row.get("origin_star_system_name", ""),
                        row.get("origin_planet_name", ""),
                        row.get("destination_terminal_name", ""),
                        row.get("destination_star_system_name", ""),
                        row.get("destination_planet_name", ""),
                        row.get("has_loading_dock_origin", 0),
                        row.get("has_loading_dock_destination", 0),
                    ),
                )
                count += 1
            except sqlite3.Error:
                logger.warning(
                    "Failed to insert route for commodity %s",
                    row.get("commodity_name"),
                )

        self._conn.commit()
        return count

    # ------------------------------------------------------------------
    # Import: Vehicle Prices (24h cache)
    # ------------------------------------------------------------------

    def refresh_vehicle_prices(self, force: bool = False) -> int:
        """Refresh in-game ship/vehicle purchase prices from UEX.

        Fetches per-terminal prices from vehicles_purchases_prices_all.
        Used to set estimated market value on fleet assets.

        Returns:
            Number of price records imported.
        """
        if not force and not self.needs_refresh("vehicle_price", CACHE_PRICES):
            return 0

        data = self._fetch("vehicles_purchases_prices_all")
        if not data or not self._conn:
            return 0

        self._conn.execute("DELETE FROM vehicle_price")
        count = 0
        for row in data:
            try:
                self._conn.execute(
                    """INSERT OR REPLACE INTO vehicle_price
                    (id, id_vehicle, id_terminal, price_buy, vehicle_name, terminal_name)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        row.get("id"),
                        row.get("id_vehicle"),
                        row.get("id_terminal"),
                        row.get("price_buy", 0),
                        row.get("vehicle_name", ""),
                        row.get("terminal_name", ""),
                    ),
                )
                count += 1
            except sqlite3.Error:
                logger.warning(
                    "Failed to insert price for vehicle %s", row.get("vehicle_name")
                )

        self._conn.commit()
        self._set_cache_timestamp("vehicle_price")
        logger.info("Imported %d vehicle prices from UEX", count)
        return count

    def get_vehicle_price(self, name: str) -> float | None:
        """Get average in-game purchase price for a vehicle across all terminals.

        Args:
            name: Vehicle name (exact match first, then partial).

        Returns:
            Average price_buy in aUEC, or None if not found.
        """
        if not self._conn:
            return None

        # 1. Exact match
        rows = self._conn.execute(
            "SELECT price_buy FROM vehicle_price WHERE LOWER(vehicle_name) = LOWER(?) AND price_buy > 0",
            (name,),
        ).fetchall()

        # 2. Asset name contains the UEX vehicle name (e.g. "MISC Hull B" → "Hull B")
        if not rows:
            rows = self._conn.execute(
                "SELECT price_buy FROM vehicle_price WHERE LOWER(?) LIKE '%' || LOWER(vehicle_name) || '%' AND price_buy > 0",
                (name,),
            ).fetchall()

        # 3. UEX vehicle name contains the asset name (e.g. partial model name)
        if not rows:
            rows = self._conn.execute(
                "SELECT price_buy FROM vehicle_price WHERE LOWER(vehicle_name) LIKE LOWER(?) AND price_buy > 0",
                (f"%{name}%",),
            ).fetchall()

        if not rows:
            return None

        prices = [r["price_buy"] for r in rows]
        return sum(prices) / len(prices)

    # ------------------------------------------------------------------
    # Full refresh (respects cache tiers)
    # ------------------------------------------------------------------

    def refresh_all(self, force: bool = False) -> dict[str, int]:
        """Refresh all data, respecting cache lifetimes.

        Args:
            force: If True, ignore cache timestamps and refresh everything.

        Returns:
            Dict of table_name -> records_imported.
        """
        results = {}
        results["commodity_status"] = self.refresh_statuses(force=force)
        results["commodity"] = self.refresh_commodities(force=force)
        results["terminal"] = self.refresh_terminals(force=force)
        results["commodity_price"] = self.refresh_prices(force=force)
        results["commodity_route"] = self.refresh_routes(force=force)
        results["vehicle_price"] = self.refresh_vehicle_prices(force=force)
        return results

    # ------------------------------------------------------------------
    # Targeted refresh (on trade events)
    # ------------------------------------------------------------------

    def refresh_for_commodity_name(self, commodity_name: str) -> bool:
        """Refresh prices and routes for a commodity identified by name.

        Args:
            commodity_name: The commodity name (fuzzy matched).

        Returns:
            True if commodity was found and refreshed.
        """
        commodity = self.find_commodity(commodity_name)
        if not commodity:
            return False

        cid = commodity["id"]
        self.refresh_commodity_prices(cid)
        self.refresh_commodity_routes(cid)
        return True

    # ------------------------------------------------------------------
    # Queries: Commodities
    # ------------------------------------------------------------------

    def find_commodity(self, name: str) -> dict | None:
        """Find a commodity by name (case-insensitive, partial match).

        Args:
            name: Commodity name or code to search for.

        Returns:
            Commodity dict or None.
        """
        if not self._conn:
            return None

        # Try exact match first (case-insensitive)
        row = self._conn.execute(
            "SELECT * FROM commodity WHERE LOWER(name) = LOWER(?) OR LOWER(code) = LOWER(?)",
            (name, name),
        ).fetchone()
        if row:
            return dict(row)

        # Partial match
        row = self._conn.execute(
            "SELECT * FROM commodity WHERE LOWER(name) LIKE LOWER(?)",
            (f"%{name}%",),
        ).fetchone()
        if row:
            return dict(row)

        return None

    def get_all_commodity_names(self) -> list[dict[str, str]]:
        """Get all commodity names and codes for reference/GUID mapping."""
        if not self._conn:
            return []
        rows = self._conn.execute(
            "SELECT id, name, code, slug FROM commodity ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Queries: Prices
    # ------------------------------------------------------------------

    def get_commodity_prices(
        self,
        commodity_name: str,
        exclude_unavailable: bool = True,
    ) -> list[dict]:
        """Get all terminal prices for a commodity.

        Args:
            commodity_name: Commodity name or code.
            exclude_unavailable: Filter out terminals with no stock / full inventory.

        Returns:
            List of price records sorted by best sell price descending.
        """
        commodity = self.find_commodity(commodity_name)
        if not commodity or not self._conn:
            return []

        rows = self._conn.execute(
            """SELECT cp.*, t.star_system_name, t.planet_name, t.city_name
            FROM commodity_price cp
            LEFT JOIN terminal t ON cp.id_terminal = t.id
            WHERE cp.id_commodity = ?
            ORDER BY cp.price_sell DESC""",
            (commodity["id"],),
        ).fetchall()

        results = []
        for row in rows:
            r = dict(row)
            if exclude_unavailable:
                # Skip if buy stock is out
                if (
                    r.get("status_buy") in self._unavailable_buy
                    and r.get("price_buy", 0) > 0
                ):
                    continue
                # Skip if sell demand is full
                if (
                    r.get("status_sell") in self._unavailable_sell
                    and r.get("price_sell", 0) > 0
                ):
                    continue
            results.append(r)

        return results

    # ------------------------------------------------------------------
    # Queries: Best Trades
    # ------------------------------------------------------------------

    def get_best_trades(
        self,
        limit: int = 10,
        cargo_scu: float | None = None,
        budget_auec: float | None = None,
        star_system: str | None = None,
        location: str = "",
        exclude_unavailable: bool = True,
    ) -> list[dict]:
        """Get the top N most profitable trade routes.

        Args:
            limit: Maximum results.
            cargo_scu: Player's available cargo capacity in SCU (caps profit calc).
            budget_auec: Player's available budget in aUEC (caps profit calc).
            star_system: Filter to routes within this star system.
            location: Filter to routes where origin terminal name contains this
                string (case-insensitive). Empty = no filter.
            exclude_unavailable: Skip routes where origin/destination has no stock.

        Returns:
            List of trade route dicts, most profitable first.
        """
        if not self._conn:
            return []

        query = "SELECT * FROM commodity_route WHERE profit > 0"
        params: list = []

        if star_system:
            query += " AND LOWER(origin_star_system_name) = LOWER(?)"
            params.append(star_system)

        if location:
            query += " AND LOWER(origin_terminal_name) LIKE LOWER(?)"
            params.append(f"%{location}%")

        query += " ORDER BY score DESC, profit DESC LIMIT ?"
        params.append(limit * 3)  # Over-fetch to account for filtering

        rows = self._conn.execute(query, params).fetchall()
        results = []

        for row in rows:
            r = dict(row)

            if exclude_unavailable:
                if r.get("status_origin") in self._unavailable_buy:
                    continue
                if r.get("status_destination") in self._unavailable_sell:
                    continue

            # Cap profit by player constraints
            actual_scu = r.get("scu_origin", 0)
            if cargo_scu is not None:
                actual_scu = min(actual_scu, cargo_scu)
            if budget_auec is not None and r.get("price_origin", 0) > 0:
                affordable_scu = budget_auec / r["price_origin"]
                actual_scu = min(actual_scu, affordable_scu)

            # Recalculate profit with capped SCU
            if r.get("price_origin", 0) > 0 and r.get("price_destination", 0) > 0:
                margin_per_scu = r["price_destination"] - r["price_origin"]
                r["adjusted_profit"] = round(margin_per_scu * actual_scu, 2)
                r["adjusted_scu"] = round(actual_scu, 2)
                r["adjusted_investment"] = round(r["price_origin"] * actual_scu, 2)
            else:
                r["adjusted_profit"] = r.get("profit", 0)
                r["adjusted_scu"] = actual_scu
                r["adjusted_investment"] = r.get("investment", 0)

            results.append(r)

            if len(results) >= limit:
                break

        # Re-sort by adjusted profit if constraints were applied
        if cargo_scu is not None or budget_auec is not None:
            results.sort(key=lambda x: x.get("adjusted_profit", 0), reverse=True)

        return results

    # ------------------------------------------------------------------
    # Utility: commodity name resolution for GUID mapping
    # ------------------------------------------------------------------

    def build_name_index(self) -> dict[str, str]:
        """Build a name lookup index from commodity data.

        Returns dict mapping lowercase name/code/slug to canonical name.
        Useful for fuzzy GUID resolution.
        """
        if not self._conn:
            return {}

        rows = self._conn.execute("SELECT name, code, slug FROM commodity").fetchall()
        index: dict[str, str] = {}
        for row in rows:
            name = row["name"]
            if name:
                index[name.lower()] = name
            code = row["code"]
            if code:
                index[code.lower()] = name
            slug = row["slug"]
            if slug:
                index[slug.lower()] = name

        return index

    def get_terminal_locations(self) -> list[dict]:
        """Get distinct locations grouped by star system.

        Returns:
            List of dicts with 'star_system' and 'planet' keys, sorted
            alphabetically by system then planet.
        """
        if not self._conn:
            return []

        rows = self._conn.execute(
            """SELECT DISTINCT star_system_name, planet_name
            FROM terminal
            WHERE star_system_name != '' AND planet_name != ''
            ORDER BY star_system_name, planet_name"""
        ).fetchall()

        return [
            {"star_system": row["star_system_name"], "planet": row["planet_name"]}
            for row in rows
        ]

    def get_terminals(self) -> list[dict]:
        """Get all trade terminals that appear in route data.

        Uses route terminal names (not the terminal table) because these
        are the exact names stored in Opportunity objects.

        Returns:
            List of dicts with 'name', 'star_system', and 'planet' keys,
            sorted alphabetically by name.
        """
        if not self._conn:
            return []

        # Collect distinct terminal names from both sides of routes
        rows = self._conn.execute(
            """SELECT DISTINCT name, star_system, planet FROM (
                SELECT origin_terminal_name AS name,
                       origin_star_system_name AS star_system,
                       origin_planet_name AS planet
                FROM commodity_route
                WHERE origin_terminal_name != ''
                UNION
                SELECT destination_terminal_name AS name,
                       destination_star_system_name AS star_system,
                       destination_planet_name AS planet
                FROM commodity_route
                WHERE destination_terminal_name != ''
            ) ORDER BY name"""
        ).fetchall()

        return [
            {
                "name": row["name"],
                "star_system": row["star_system"],
                "planet": row["planet"],
            }
            for row in rows
        ]

    def is_data_available(self) -> bool:
        """Check if market data has been loaded at least once."""
        if not self._conn:
            return False
        row = self._conn.execute("SELECT COUNT(*) as cnt FROM commodity").fetchone()
        return row["cnt"] > 0 if row else False
