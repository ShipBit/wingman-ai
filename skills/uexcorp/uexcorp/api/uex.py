import json
import re
import threading
from dataclasses import dataclass
from typing import Optional
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from skills.uexcorp.uexcorp.helper import Helper


class UexApiError(Exception):
    """A request failed after all retries (or was cancelled). Raised instead of
    returning empty data, so an import is never recorded as done when it failed."""


class UexClientError(UexApiError):
    """The relay rejected the request itself (HTTP 4xx except 429): retrying won't help."""


@dataclass
class RelayResponse:
    data: Optional[dict]  # None: unchanged since the given ETag (HTTP 304)
    etag: Optional[str]
    max_age: Optional[int]  # seconds until the relay has newer data (Cache-Control), if sent


class Uex:
    """Client for the data relay, which caches the UEX API in two bundles.

    One request per bundle replaces ~130 rate limited UEX API requests:
    - long: locations, terminals, commodities, items, vehicles, ... (relay refresh every 2 weeks)
    - short: commodity, fuel and item prices, commodity alerts (relay refresh every 2 hours)
    - version: the current game version

    The relay is the only data source: when it is down, the stored data stays in use.
    """

    MAX_RETRIES = 2
    RATE_LIMIT_PAUSE = 60  # seconds, if a 429 response has no Retry-After header
    MAX_RATE_LIMIT_PAUSE = 120
    CHUNK_SIZE = 1024 * 1024

    BUNDLE_LONG = 'long'
    BUNDLE_SHORT = 'short'
    VERSION = 'version'

    # Datasets inside the bundles (named like the UEX API endpoints)
    CATEGORIES = 'categories'
    CATEGORIES_ATTRIBUTES = 'categories_attributes'
    CITIES = 'cities'
    COMMODITIES = 'commodities'
    COMMODITIES_ALERTS = 'commodities_alerts'
    COMMODITIES_PRICES = 'commodities_prices_all'
    COMMODITIES_RAW_PRICES = 'commodities_raw_prices_all'
    COMMODITIES_STATUS = 'commodities_status'
    COMPANIES = 'companies'
    FACTIONS = 'factions'
    FUEL_PRICES = 'fuel_prices_all'
    ITEMS = 'items'
    ITEMS_ATTRIBUTES = 'items_attributes'
    ITEMS_PRICES = 'items_prices_all'
    JURISDICTIONS = 'jurisdictions'
    MOONS = 'moons'
    ORBITS = 'orbits'
    ORBITS_DISTANCES = 'orbits_distances'
    OUTPOSTS = 'outposts'
    PLANETS = 'planets'
    POI = 'poi'
    REFINERIES_AUDITS = 'refineries_audits'
    REFINERIES_METHODS = 'refineries_methods'
    SPACE_STATIONS = 'space_stations'
    VEHICLES = 'vehicles'
    VEHICLES_PURCHASES_PRICES = 'vehicles_purchases_prices_all'
    VEHICLES_RENTALS_PRICES = 'vehicles_rentals_prices_all'
    STAR_SYSTEMS = 'star_systems'
    TERMINALS = 'terminals'

    def __init__(
        self,
        helper: "Helper"
    ):
        self.helper = helper
        self.session = None
        self.__stop = threading.Event()

    def cancel(self):
        """Aborts waiting, retrying and downloading requests (skill unload)."""
        self.__stop.set()

    def _get_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": "WingmanAI-UEXCorp-Skill",
        }

    def fetch_bundle(self, bundle: str, etag: Optional[str] = None) -> RelayResponse:
        """One bundle as {dataset name: rows}. With the ETag of the stored data, an unchanged
        bundle is not downloaded again (data None)."""
        response = self.__get(bundle, etag)
        if response.data is not None and not isinstance(response.data, dict):
            raise UexApiError(f"Unexpected {bundle} bundle format: {type(response.data).__name__}")
        return response

    def fetch_version(self) -> dict:
        """The current game version, e.g. {"live": "4.10.2"}."""
        data = self.__get(self.VERSION).data
        if not isinstance(data, dict) or not data.get("live"):
            raise UexApiError(f"Unexpected version response: {data!r}")
        return data

    def __get(self, path: str, etag: Optional[str] = None) -> RelayResponse:
        base_url = self.helper.get_handler_config().get_api_url()
        if not base_url or not path:
            raise UexApiError(f"No relay URL or path provided -> {base_url}/{path}")
        url = f"{base_url.rstrip('/')}/{path}"

        if self.session is None:
            self.helper.get_handler_debug().write(f"Init session for {base_url} for future requests ...")
            self.session = requests.Session()

        headers = self._get_headers()
        if etag:
            headers["If-None-Match"] = etag

        failed_attempts = 0
        rate_limited_attempts = 0
        while True:
            if self.__stop.is_set():
                raise UexApiError(f"Cancelled request to {url}")

            self.helper.get_handler_debug().write(f"Fetching data (attempt {failed_attempts + rate_limited_attempts + 1}) from {url} ...")
            response = None
            try:
                response = self.session.get(
                    url,
                    timeout=self.helper.get_handler_config().get_api_timeout(),
                    headers=headers,
                    stream=True,
                )
                if response.status_code == 304:
                    return RelayResponse(None, response.headers.get("ETag") or etag, self.__get_max_age(response))
                if response.status_code == 429:
                    rate_limited_attempts += 1
                    if rate_limited_attempts > self.MAX_RETRIES:
                        raise self.__error(path, UexApiError(f"Rate limited by relay after {self.MAX_RETRIES} pauses: {url}"))
                    pause = self.__get_retry_after(response)
                    self.helper.get_handler_debug().write(
                        f"Relay rate limit hit at {url}, pausing for {pause}s ({rate_limited_attempts}/{self.MAX_RETRIES}).", True
                    )
                    if self.__stop.wait(pause):
                        raise UexApiError(f"Cancelled request to {url}")
                    continue
                if 400 <= response.status_code < 500:
                    # Rejected by the relay itself (e.g. 404): asking again gives the same answer
                    raise self.__error(path, UexClientError(f"HTTP {response.status_code} for {url}"))
                response.raise_for_status()
                data = json.loads(self.__read(response, url))
                return RelayResponse(data, response.headers.get("ETag"), self.__get_max_age(response))
            except (requests.exceptions.RequestException, ValueError) as e:
                # ValueError: invalid JSON (json.JSONDecodeError) or a broken download
                error = e
            finally:
                # Streamed responses hold a pooled connection until closed, whatever the outcome
                if response is not None:
                    response.close()

            failed_attempts += 1
            # Log file only: the import tells the user once per outage (ImportHandler)
            self.helper.get_handler_debug().write(
                f"Error while retrieving data from {url} ({failed_attempts}/{self.MAX_RETRIES + 1}): {error}"
            )
            if failed_attempts > self.MAX_RETRIES:
                # One short entry per failed request: during an outage this runs every minute
                self.helper.get_handler_error().write("Api.fetch", [path], error, write_traceback=False)
                raise UexApiError(f"Request to {url} failed: {error}")
            # Short backoff before the retry (1s, 2s), aborted on unload
            if self.__stop.wait(failed_attempts):
                raise UexApiError(f"Cancelled request to {url}")

    def __read(self, response: requests.Response, url: str) -> bytes:
        """Downloads the body in chunks, so an unload can stop a large bundle mid-way."""
        chunks = []
        for chunk in response.iter_content(self.CHUNK_SIZE):
            if self.__stop.is_set():
                raise UexApiError(f"Cancelled request to {url}")
            chunks.append(chunk)
        return b"".join(chunks)

    def __error(self, path: str, error: UexApiError) -> UexApiError:
        self.helper.get_handler_error().write("Api.fetch", [path], error, write_traceback=False)
        self.helper.get_handler_debug().write(f"Error while retrieving data: {error}")
        return error

    def __get_retry_after(self, response: requests.Response) -> int:
        try:
            return min(self.MAX_RATE_LIMIT_PAUSE, max(1, int(response.headers.get("Retry-After", ""))))
        except ValueError:
            return self.RATE_LIMIT_PAUSE

    @staticmethod
    def __get_max_age(response: requests.Response) -> Optional[int]:
        match = re.search(r"max-age=(\d+)", response.headers.get("Cache-Control", ""))
        return int(match.group(1)) if match else None
