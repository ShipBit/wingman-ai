"""Public EDSM lookups with persistent caching for Wingman's per-call MCP process.

No accounts, journal uploads, arbitrary URLs, or logging on protocol stdout.
"""

from datetime import datetime, timezone
from contextlib import contextmanager
import csv
import io
import json
from pathlib import Path
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote, urlsplit
from urllib.request import Request, urlopen


BASE = "https://www.edsm.net"
SPANSH = "https://spansh.co.uk"
GITHUB = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"
MAX_BYTES = 2 * 1024 * 1024


def now_iso():
    return datetime.now(timezone.utc).isoformat()


class PublicData:
    def __init__(self, cache_dir: Path, opener=urlopen):
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.database = cache_dir / "public-data.sqlite3"
        self.opener = opener
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS cache (url TEXT PRIMARY KEY, fetched REAL, payload TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS throttle (host TEXT PRIMARY KEY, next_request REAL)")

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _reserve_request(self, host=BASE):
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT next_request FROM throttle WHERE host=?", (host,)).fetchone()
            delay = max(0, row[0] - time.time()) if row else 0
            if delay > 5:
                return delay
            conn.execute("INSERT OR REPLACE INTO throttle VALUES (?, ?)", (host, time.time() + delay + 2))
        if delay:
            time.sleep(delay)
        return 0

    def _fetch(self, url, deadline=None, cache_seconds=300):
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in (BASE, SPANSH, GITHUB, GITHUB_RAW):
            raise ValueError("Unsupported data provider")
        with self._connect() as conn:
            row = conn.execute("SELECT fetched, payload FROM cache WHERE url=?", (url,)).fetchone()
        cached = json.loads(row[1]) if row else None
        if row and 0 <= time.time() - row[0] < cache_seconds:
            return cached, row[0], True, None
        if deadline is not None and time.monotonic() >= deadline:
            return cached, row[0] if row else None, bool(row), "Search time budget exhausted."
        hold = self._reserve_request(host)
        if hold:
            return cached, row[0] if row else None, bool(row), f"Provider cooldown; retry after {int(hold) + 1} seconds."
        try:
            timeout = 12 if deadline is None else min(12, deadline - time.monotonic())
            if timeout <= 0:
                return cached, row[0] if row else None, bool(row), "Search time budget exhausted."
            request = Request(url, headers={"User-Agent": "WingmanElitePrivate/0.1", "Accept": "application/json"})
            with self.opener(request, timeout=timeout) as response:
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("Provider response exceeds size limit")
            payload = (list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
                       if host == GITHUB_RAW and parts.path.endswith("/material.csv") else json.loads(raw))
            if not isinstance(payload, (dict, list)):
                raise ValueError("Unexpected provider response")
            fetched = time.time()
            with self._connect() as conn:
                conn.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)", (url, fetched, json.dumps(payload)))
                conn.execute("DELETE FROM cache WHERE url NOT IN (SELECT url FROM cache ORDER BY fetched DESC LIMIT 32)")
            return payload, fetched, False, None
        except HTTPError as exc:
            if exc.code == 429 or (host == GITHUB and exc.code == 403 and exc.headers.get("X-RateLimit-Remaining") == "0"):
                try:
                    reset = int(exc.headers.get("X-RateLimit-Reset", "0")) - time.time() if host == GITHUB else 0
                    delay = min(3600, max(60, reset, int(exc.headers.get("Retry-After", "60"))))
                except (TypeError, ValueError):
                    delay = 60
                with self._connect() as conn:
                    conn.execute("INSERT OR REPLACE INTO throttle VALUES (?, ?)", (host, time.time() + delay))
            error = f"Provider returned HTTP {exc.code}; no automatic retry."
        except (OSError, URLError, ValueError):
            error = "Provider unavailable or response invalid; no automatic retry."
        return cached, row[0] if row else None, bool(row), error

    def lookup(self, system: str, kind="system", query="", galaxy="live"):
        if galaxy != "live":
            return {"error": "This provider is configured for Live only. Legacy/unknown galaxy queries are unsupported."}
        if kind not in ("system", "stations"):
            return {"error": "Choose system or stations."}
        if not isinstance(system, str) or not system.strip() or len(system) > 128:
            return {"error": "Supply a system name between 1 and 128 characters."}
        if not isinstance(query, str) or len(query) > 128:
            return {"error": "Use a station/service filter of at most 128 characters."}
        system = system.strip()
        parameters = {"systemName": system}
        endpoint = "/api-system-v1/stations"
        if kind == "system":
            endpoint = "/api-v1/system"
            parameters.update(showCoordinates=1, showInformation=1, showPermit=1, showId=1)
        url = BASE + endpoint + "?" + urlencode(parameters)
        try:
            payload, fetched, cached, error = self._fetch(url)
        except (OSError, sqlite3.Error, ValueError):
            return {"source": url, "error": "Local provider cache unavailable; query not completed."}
        result = {
            "provider": "EDSM", "source": url, "retrieved_at": now_iso(),
            "fetched_at": datetime.fromtimestamp(fetched, timezone.utc).isoformat() if fetched else None,
            "cache_hit": cached, "stale_fallback": bool(error and payload is not None),
            "galaxy_policy": "Live queries only; response does not independently identify galaxy.",
            "warning": "Community observations can be incomplete or old. Retrieval time is not observation time. Unknown access, permits, stock and prices are not guarantees.",
            "inara_link": "https://inara.cz/elite/starsystem/?search=" + quote(system, safe=""),
        }
        if error:
            result["error"] = error
        if not payload:
            result["found"] = False
            return result
        if not isinstance(payload, dict):
            result["error"] = "Unexpected provider response shape."
            return result
        if kind == "system":
            result["found"] = bool(payload.get("name"))
            result["system"] = {k: payload[k] for k in (
                "name", "id64", "coords", "requirePermit", "permitName", "information") if k in payload}
            result["observed_at"] = None
        else:
            stations = payload.get("stations")
            if not isinstance(stations, list) or not all(isinstance(s, dict) for s in stations):
                result["error"] = "Unexpected station response shape."
                return result
            stations = [s for s in stations if query.casefold() in json.dumps({
                k: s.get(k) for k in ("name", "type", "otherServices")}).casefold()]
            stations.sort(key=lambda s: s.get("distanceToArrival") if isinstance(s.get("distanceToArrival"), (float, int)) else float("inf"))
            result.update(found=bool(stations), matched=len(stations), omitted=max(0, len(stations) - 5))
            result["stations"] = [{k: station[k] for k in (
                "name", "marketId", "type", "distanceToArrival", "haveMarket", "haveShipyard",
                "haveOutfitting", "otherServices", "updateTime") if k in station} for station in stations[:5]]
            result["ordering"] = "Distance from arrival in light seconds, within the named system only."
        # Normalized known fields still receive a final size cap.
        encoded = json.dumps(result, ensure_ascii=False)
        if len(encoded) > 7000:
            result.pop("system", None)
            result["stations"] = result.get("stations", [])[:1]
            result["truncated"] = "Result too large; narrow the station/service filter."
            if len(json.dumps(result, ensure_ascii=False)) > 7000:
                result.pop("stations", None)
        return result
