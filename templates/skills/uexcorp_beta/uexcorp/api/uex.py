import requests
import concurrent.futures
from itertools import product
from typing import Optional
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    try:
        from skills.uexcorp_beta.uexcorp.helper import Helper
    except ModuleNotFoundError:
        from uexcorp_beta.uexcorp.helper import Helper


class Uex:

    CATEGORIES = 'categories'
    CATEGORIES_ATTRIBUTES = 'categories_attributes'
    CITIES = 'cities'
    COMMODITIES = 'commodities'
    COMMODITIES_ALERTS = 'commodities_alerts'
    COMMODITIES_PRICES = 'commodities_prices_all'
    COMMODITIES_RAW_PRICES = 'commodities_raw_prices_all'
    COMMODITIES_STATUS = 'commodities_status'
    COMMODITIES_ROUTES = 'commodities_routes'
    COMPANIES = 'companies'
    FACTIONS = 'factions'
    FUEL_PRICES = 'fuel_prices_all'
    GAME_VERSIONS = 'game_versions'
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
    GAME_VERSION = 'game_versions'
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

    def _get_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (X11; CrOS x86_64 12871.102.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.141 Safari/537.36",
            "Connection": "keep-alive",
        }
        return headers

    def fetch(
        self,
        endpoint: str,
        get: Optional[dict[str, any]] = None,
        params: Optional[dict[str, any]] = None,
    ) -> list[dict[str, any]]|dict[str, any]:
        results = []
        if get and any(isinstance(value, list) for value in get.values()):
            keys, values = zip(*((k, v if isinstance(v, list) else [v]) for k, v in get.items()))
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                future_to_combination = {executor.submit(self.__actual_fetch, endpoint, dict(zip(keys, combination)), params): combination for combination in product(*values)}
                for future in concurrent.futures.as_completed(future_to_combination):
                    result = future.result()
                    if isinstance(result, list):
                        results.extend(result)
                    elif isinstance(result, dict):
                        results.append(result)
        else:
            results = self.__actual_fetch(endpoint, get, params)
        return results

    def __actual_fetch(
        self,
        endpoint: str,
        get: Optional[dict[str, any]] = None,
        params: Optional[dict[str, any]] = None,
    ) -> list[dict[str, any]]|dict[str, any]:
        url = f"{self.helper.get_handler_config().get_api_url()}/{endpoint}"
        if get:
            url += "?"
            for key, value in get.items():
                url += f"{key}={value}&"
            url = url[:-1]

        if not self.helper.get_handler_config().get_api_url() or not endpoint:
            self.helper.get_handler_debug().write(f"No API URL or endpoint provided -> {url}", True)
            self.helper.get_handler_error().write("Api.fetch", [endpoint, params], f"No API URL or endpoint provided -> {url}", False)
            return []

        if self.session is None:
            self.helper.get_handler_debug().write(f"Init session for {self.helper.get_handler_config().get_api_url()} for future requests ...")
            self.session = requests.Session()

        request_count = 1
        max_retries = 4
        timeout_error = False
        requests_error = False
        response_json = {}

        while request_count == 1 or (
            request_count <= (max_retries + 1) and (timeout_error or requests_error)
        ):
            self.helper.get_handler_debug().write(f"Fetching data (request {request_count}/{max_retries+1}) from {url} ...")
            requests_error = False
            timeout_error = False
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.helper.get_handler_config().get_api_timeout(),
                    headers=self._get_headers(),
                    stream = True
                )
                response.raise_for_status()
                # response.raw.chunked = True
                response.encoding = "utf-8"
                response_json = response.json()
                if "status" not in response_json or response_json["status"] != "ok":
                    self.helper.get_handler_debug().write(
                        f"Error while retrieving data from {url}. Status is not \"ok\".",
                        request_count > max_retries
                    )
                    requests_error = True
            except (requests.exceptions.RequestException, requests.exceptions.JSONDecodeError) as e:
                self.helper.get_handler_debug().write(f"Error while retrieving data from {url}: {e}", request_count > max_retries)
                self.helper.get_handler_error().write("Api.fetch", [endpoint, params], e)
                requests_error = True
                if isinstance(e, requests.exceptions.Timeout):
                    timeout_error = True
            request_count += 1

        if requests_error:
            return []

        return response_json.get("data", [])