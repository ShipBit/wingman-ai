"""Wingman AI Skill to utalize uexcorp api for trade recommendations"""

import asyncio
import difflib
import heapq
import itertools
import json
import math
import traceback
from os import path
import collections
import re
from typing import Optional, TYPE_CHECKING
from datetime import datetime
import requests
from api.enums import LogType, WingmanInitializationErrorType
from api.interface import (
    SettingsConfig,
    SkillConfig,
    WingmanConfig,
    WingmanInitializationError,
)
from services.file import get_writable_dir
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.wingman import Wingman

class UEXCorp(Skill):

    # enable for verbose logging
    DEV_MODE = False

    def __init__(
        self,
        config: SkillConfig,
        wingman_config: WingmanConfig,
        settings: SettingsConfig,
        wingman: "Wingman",
    ) -> None:
        super().__init__(
            config=config, wingman_config=wingman_config, settings=settings, wingman=wingman
        )

        self.data_path = get_writable_dir(path.join("skills", "uexcorp", "data"))
        self.logfileerror = path.join(self.data_path, "error.log")
        self.logfiledebug = path.join(self.data_path, "debug.log")
        self.cachefile = path.join(self.data_path, "cache.json")

        self.skill_version = "v13"
        self.skill_loaded = False
        self.skill_loaded_asked = False
        self.game_version = "unknown"

        # init of config options
        self.uexcorp_api_url: str = None
        self.uexcorp_api_key: str = None
        self.uexcorp_api_timeout: int = None
        self.uexcorp_api_timeout_retries: int = None
        self.uexcorp_cache: bool = None
        self.uexcorp_cache_duration: int = None
        self.uexcorp_summarize_routes_by_commodity: bool = None
        self.uexcorp_tradestart_mandatory: bool = None
        self.uexcorp_trade_blacklist = []
        self.uexcorp_default_trade_route_count: int = None
        self.uexcorp_use_estimated_availability: bool = None
        self.uexcorp_add_lore: bool = None

        self.ships = []
        self.ship_names = []
        self.ship_dict = {}
        self.ship_code_dict = {}

        self.commodities = []
        self.commodity_names = []
        self.commodity_dict = {}
        self.commodity_code_dict = {}

        self.systems = []
        self.system_names = []
        self.system_dict = {}
        self.system_code_dict = {}

        self.terminals = []
        self.terminal_names = []
        self.terminal_names_trading = []
        self.terminal_dict = {}
        self.terminal_code_dict = {}
        self.terminals_by_system = collections.defaultdict(list)
        self.terminals_by_planet = collections.defaultdict(list)
        self.terminals_by_moon = collections.defaultdict(list)
        self.terminals_by_city = collections.defaultdict(list)

        self.planets = []
        self.planet_names = []
        self.planet_dict = {}
        self.planet_code_dict = {}
        self.planets_by_system = collections.defaultdict(list)

        self.moons = []
        self.moon_names = []
        self.moon_dict = {}
        self.moon_code_dict = {}
        self.moons_by_planet = collections.defaultdict(list)

        self.cities = []
        self.city_names = []
        self.city_dict = {}
        self.city_code_dict = {}
        self.cities_by_planet = collections.defaultdict(list)

        self.location_names_set = set()
        self.location_names_set_trading = set()

        self.cache_enabled = True
        self.cache = {
            "function_args": {},
            "search_matches": {},
            "readable_objects": {},
        }

        self.dynamic_context = ""

    async def _print(self, message: str | dict, is_extensive: bool = False, is_debug: bool = True) -> None:
        """
        Prints a message if debug mode is enabled. Will be sent to the server terminal, log file and client.

        Args:
            message (str | dict): The message to be printed.
            is_extensive (bool, optional): Whether the message is extensive. Defaults to False.

        Returns:
            None
        """
        if (not is_extensive and self.settings.debug_mode) or not is_debug:
            await self.printr.print_async(
                message,
                color=LogType.INFO,
            )
        elif self.DEV_MODE:
            with open(self.logfiledebug, "a", encoding="UTF-8") as f:
                f.write(f"#### Time: {datetime.now()} ####\n")
                f.write(f"{message}\n\n")


    def _log(self, message: str | dict, is_extensive: bool = False) -> None:
        """
        Prints a debug message (synchronously) only on the server (and in the log file).

        Args:
            message (str | dict): The message to be printed.
            is_extensive (bool, optional): Whether the message is extensive. Defaults to False.

        Returns:
            None
        """
        if not is_extensive and self.settings.debug_mode:
            self.printr.print(
                message,
                color=LogType.INFO,
                server_only=True,
            )
        elif self.DEV_MODE:
            with open(self.logfiledebug, "a", encoding="UTF-8") as f:
                f.write(f"#### Time: {datetime.now()} ####\n")
                f.write(f"{message}\n\n")

    def _get_function_arg_from_cache(
        self, arg_name: str, arg_value: str | int = None
    ) -> str | int | None:
        """
        Retrieves a function argument from the cache if available, otherwise returns the provided argument value.

        Args:
            arg_name (str): The name of the function argument.
            arg_value (str | int, optional): The default value for the argument. Defaults to None.

        Returns:
            dict[str, any]: The cached value of the argument if available, otherwise the provided argument value.
        """
        if not self.cache_enabled:
            return arg_value

        if arg_value is None or (
            isinstance(arg_value, str) and arg_value.lower() == "current"
        ):
            cached_arg = self.cache["function_args"].get(arg_name)
            if cached_arg is not None:
                self._log(
                    f"'{arg_name}' was not given and got overwritten by cache: {cached_arg}"
                )
                return cached_arg

        return arg_value

    def _set_function_arg_to_cache(
        self, arg_name: str, arg_value: str | int | float = None
    ) -> None:
        """
        Sets the value of a function argument to the cache.

        Args:
            arg_name (str): The name of the argument.
            arg_value (str | int, optional): The value of the argument. Defaults to None.
        """
        if not self.cache_enabled:
            return

        function_args = self.cache["function_args"]
        old_value = function_args.get(arg_name, "None")

        if arg_value is not None:
            self._log(
                f"Set function arg '{arg_name}' to cache. Previous value: {old_value} >> New value: {arg_value}",
                True,
            )
            function_args[arg_name] = arg_value
        elif arg_name in function_args:
            self._log(
                f"Removing function arg '{arg_name}' from cache. Previous value: {old_value}",
                True,
            )
            function_args.pop(arg_name, None)

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        self.uexcorp_api_key = await self.retrieve_secret(
            "uexcorp", errors, "You can create your own API key here: https://uexcorp.space/api/apps/"
        )
        self.uexcorp_api_url = self.retrieve_custom_property_value(
            "uexcorp_api_url", errors
        )
        self.uexcorp_api_timeout = self.retrieve_custom_property_value(
            "uexcorp_api_timeout", errors
        )
        self.uexcorp_api_timeout_retries = self.retrieve_custom_property_value(
            "uexcorp_api_timeout_retries", errors
        )
        self.uexcorp_cache = self.retrieve_custom_property_value(
            "uexcorp_cache", errors
        )
        self.uexcorp_cache_duration = self.retrieve_custom_property_value(
            "uexcorp_cache_duration", errors
        )
        self.uexcorp_summarize_routes_by_commodity = (
            self.retrieve_custom_property_value(
                "uexcorp_summarize_routes_by_commodity", errors
            )
        )
        self.uexcorp_tradestart_mandatory = self.retrieve_custom_property_value(
            "uexcorp_tradestart_mandatory", errors
        )
        self.uexcorp_default_trade_route_count = self.retrieve_custom_property_value(
            "uexcorp_default_trade_route_count", errors
        )
        self.uexcorp_use_estimated_availability = self.retrieve_custom_property_value(
            "uexcorp_use_estimated_availability", errors
        )
        self.uexcorp_add_lore = self.retrieve_custom_property_value(
            "uexcorp_add_lore", errors
        )

        trade_backlist_str: str = self.retrieve_custom_property_value(
            "uexcorp_trade_blacklist", errors
        )
        if trade_backlist_str:
            try:
                self.uexcorp_trade_blacklist = json.loads(trade_backlist_str)
            except json.decoder.JSONDecodeError:
                errors.append(
                    WingmanInitializationError(
                        wingman_name=self.name,
                        message="Invalid custom property 'uexcorp_trade_blacklist' in config. Value must be a valid JSON string.",
                        error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                    )
                )

        try:
            await self._start_loading_data()
        except Exception as e:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.name,
                    message=f"Failed to load data: {e}",
                    error_type=WingmanInitializationErrorType.UNKNOWN,
                )
            )

        return errors

    async def _load_data(self, reload_prices: bool = False, callback = None) -> None:
        """
        Load data for UEX corp wingman.

        Args:
            reload (bool, optional): Whether to reload the data from the source. Defaults to False.
        """

        if reload_prices:
            await self._load_commodity_prices()
            self.threaded_execution(self._save_to_cachefile)
            return
        
        self.game_version = (await self._fetch_uex_data("game_versions"))['live']

        async def _load_from_cache():
            if not self.uexcorp_cache:
                return

            # check file age
            data = {}
            try:
                with open(self.cachefile, "r", encoding="UTF-8") as f:
                    data = json.load(f)
            except (FileNotFoundError, json.decoder.JSONDecodeError):
                pass

            # check file age
            if (
                data.get("timestamp")
                and data.get("timestamp") + self.uexcorp_cache_duration
                > self._get_timestamp()
                and data.get("skill_version") == self.skill_version
                and data.get("game_version") == self.game_version
            ):
                if data.get("ships"):
                    self.ships = data["ships"]
                if data.get("commodities"):
                    self.commodities = data["commodities"]
                if data.get("systems"):
                    self.systems = data["systems"]
                if data.get("terminals"):
                    self.terminals = data["terminals"]
                    # fix prices keys (from string to integer due to unintentional json conversion)
                    for terminal in self.terminals:
                        if "prices" in terminal:
                            terminal["prices"] = {
                                int(key): value
                                for key, value in terminal["prices"].items()
                            }
                if data.get("planets"):
                    self.planets = data["planets"]
                if data.get("moons"):
                    self.moons = data["moons"]
                if data.get("cities"):
                    self.cities = data["cities"]

        async def _load_missing_data():
            load_purchase_and_rental = False

            if not self.ships:
                load_purchase_and_rental = True
                self.ships = await self._fetch_uex_data("vehicles")
                self.ships = [ship for ship in self.ships if ship["game_version"]]

            if not self.commodities:
                self.commodities = await self._fetch_uex_data("commodities")
                self.commodities = [commodity for commodity in self.commodities if commodity["is_available"] == 1]

            if not self.systems:
                load_purchase_and_rental = True
                self.systems = await self._fetch_uex_data("star_systems")
                self.systems = [
                    system for system in self.systems if system["is_available"] == 1
                ]
                for system in self.systems:
                    self.terminals += await self._fetch_uex_data(
                        f"terminals/id_star_system/{system['id']}/is_available/1/is_visible/1"
                    )
                    self.cities += await self._fetch_uex_data(
                        f"cities/id_star_system/{system['id']}"
                    )
                    self.moons += await self._fetch_uex_data(
                        f"moons/id_star_system/{system['id']}"
                    )
                    self.planets += await self._fetch_uex_data(
                        f"planets/id_star_system/{system['id']}"
                )
                await self._load_commodity_prices()

                # data manipulation
                planet_codes = []
                for planet in self.planets:
                    if planet["code"] not in planet_codes:
                        planet_codes.append(planet["code"])

                for terminal in self.terminals:
                    if (
                        terminal["id_space_station"]
                        and len(terminal["nickname"].split("-")) == 2
                        and terminal["nickname"].split("-")[0] in planet_codes
                        and re.match(r"^L\d+$", terminal["nickname"].split("-")[1])
                    ):
                        terminal["id_planet"] = ""

            if load_purchase_and_rental:
                await self._load_purchase_and_rental()

        async def _load_data(callback=None):
            await _load_from_cache()
            await _load_missing_data()
            self.threaded_execution(self._save_to_cachefile)

            if callback:
                await callback()

        self.threaded_execution(_load_data, callback)

    async def _save_to_cachefile(self) -> None:
        if (
            self.uexcorp_cache
            and self.uexcorp_cache_duration > 0
            and self.ships
            and self.commodities
            and self.systems
            and self.terminals
            and self.planets
            and self.moons
            and self.cities
        ):
            data = {
                "timestamp": self._get_timestamp(),
                "skill_version": self.skill_version,
                "game_version": self.game_version,
                "ships": self.ships,
                "commodities": self.commodities,
                "systems": self.systems,
                "terminals": self.terminals,
                "planets": self.planets,
                "moons": self.moons,
                "cities": self.cities,
            }
            with open(self.cachefile, "w", encoding="UTF-8") as f:
                json.dump(data, f, indent=4)

    async def _load_purchase_and_rental(self) -> None:
        """
        Load purchase and rental information for ships and vehicles.

        Returns:
            None
        """
        ships_purchase = await self._fetch_uex_data("vehicles_purchases_prices_all")
        ships_rental = await self._fetch_uex_data("vehicles_rentals_prices_all")

        for ship in self.ships:
            ship["purchase"] = [
                purchase for purchase in ships_purchase if purchase["id_vehicle"] == ship["id"]
            ]
            ship["rental"] = [
                rental for rental in ships_rental if rental["id_vehicle"] == ship["id"]
            ]

        for terminal in self.terminals:
            terminal["vehicle_rental"] = [
                rental for rental in ships_rental if rental["id_terminal"] == terminal["id"]
            ]
            terminal["vehicle_purchase"] = [
                purchase for purchase in ships_purchase if purchase["id_terminal"] == terminal["id"]
            ]

    async def _load_commodity_prices(self) -> None:
        """
        Load commodity prices from UEX corp API.

        Returns:
            None
        """

        self.cache["readable_objects"] = {}

        # currently the prices are saved in api v1 style to minimize rework time for now
        for i in range(0, len(self.terminals), 10):
            terminals_batch = self.terminals[i : i + 10]
            terminal_ids = [terminal["id"] for terminal in terminals_batch if terminal["type"] in ["commodity", "commodity_raw"]]
            if not terminal_ids:
                continue

            commodity_prices = await self._fetch_uex_data(
                "commodities_prices/id_terminal/" + ",".join(map(str, terminal_ids))
            )

            for terminal in terminals_batch:
                terminal["prices"] = {}

                for commodity_price in commodity_prices:
                    if commodity_price["id_terminal"] == terminal["id"]:
                        commodity = next(
                            (
                                commodity
                                for commodity in self.commodities
                                if commodity["id"] == commodity_price["id_commodity"]
                            ),
                            None,
                        )
                        if commodity:
                            transaction_type = "buy" if commodity_price["price_buy"] > 0 else "sell"
                            price = {
                                "name": self._format_commodity_name(commodity),
                                "kind": commodity["kind"],
                                "operation": transaction_type,
                                "price_buy": commodity_price["price_buy"],
                                "price_sell": commodity_price["price_sell"],
                                "date_update": commodity_price["date_modified"],
                                "is_updated": bool(commodity_price["date_modified"]),
                                "scu": commodity_price[f"scu_{transaction_type}"] or None,
                                "scu_average": commodity_price[f"scu_{transaction_type}_avg"] or None,
                                "scu_average_week": commodity_price[f"scu_{transaction_type}_avg_week"] or None,
                            }
                            # calculate expected scu
                            count = 0
                            total = 0
                            if price["scu"]:
                                count += 2
                                total += (price["scu"] * 2)
                            if price["scu_average"]:
                                count += 1
                                total += price["scu_average"]
                            if price["scu_average_week"]:
                                count += 1
                                total += price["scu_average_week"]
                            price["scu_expected"] = int(total / count) if count > 0 else None

                            terminal["prices"][commodity["id"]] = price

    async def _start_loading_data(self) -> None:
        """
        Prepares the wingman for execution by initializing necessary variables and loading data.

        This method retrieves configuration values, sets up API URL and timeout, and loads data
        such as ship names, commodity names, system names, terminal names, city names,
        moon names and planet names.
        It also adds additional context information for function parameters.

        Returns:
            None
        """

        # fix api url
        if self.uexcorp_api_url and self.uexcorp_api_url.endswith("/"):
            self.uexcorp_api_url = self.uexcorp_api_url[:-1]

        # fix timeout
        self.uexcorp_api_timeout = max(3, self.uexcorp_api_timeout)
        self.uexcorp_api_timeout_retries = max(0, self.uexcorp_api_timeout_retries)

        await self._load_data(False, self._prepare_data)

    async def _prepare_data(self) -> None:
        """
        Prepares the wingman for execution by initializing necessary variables.
        """

        self.planets = [
            planet for planet in self.planets if planet["is_available"] == 1
        ]

        self.moons = [
            moon
            for moon in self.moons
            if moon["is_available"] == 1
        ]

        # remove urls from ships
        for ship in self.ships:
            ship.pop("url_store", None)
            ship.pop("url_brochure", None)
            ship.pop("url_hotsite", None)
            ship.pop("url_video", None)
            ship.pop("url_photos", None)

        # remove screenshot from terminals
        for terminal in self.terminals:
            terminal.pop("screenshot", None)
            terminal.pop("screenshot_thumbnail", None)
            terminal.pop("screenshot_author", None)

        # add hull trading option to trade ports
        for terminal in self.terminals:
            terminal["hull_trading"] = bool(terminal["has_loading_dock"])

        # add hull trading option to ships
        ships_for_hull_trading = [
            "Hull C",
            "Hull D",
            "Hull E",
        ]
        for ship in self.ships:
            ship["hull_trading"] = ship["name"] in ships_for_hull_trading

        self.ship_names = [
            self._format_ship_name(ship)
            for ship in self.ships
        ]
        self.ship_dict = {
            self._format_ship_name(ship).lower(): ship for ship in self.ships
        }
        self.ship_code_dict = {ship["id"]: ship for ship in self.ships}

        self.commodity_names = [
            self._format_commodity_name(commodity) for commodity in self.commodities
        ]
        self.commodity_dict = {
            self._format_commodity_name(commodity).lower(): commodity
            for commodity in self.commodities
        }
        self.commodity_code_dict = {
            commodity["id"]: commodity for commodity in self.commodities
        }

        self.system_names = [
            self._format_system_name(system) for system in self.systems
        ]
        self.system_dict = {
            self._format_system_name(system).lower(): system for system in self.systems
        }
        self.system_code_dict = {
            system["id"]: system for system in self.systems
        }

        self.terminal_names = [
            self._format_terminal_name(terminal) for terminal in self.terminals
        ]
        self.terminal_names_trading = [
            self._format_terminal_name(terminal) for terminal in self.terminals if terminal["type"] in ["commodity", "commodity_raw"]
        ]
        self.terminal_dict = {
            self._format_terminal_name(terminal).lower(): terminal
            for terminal in self.terminals
        }
        self.terminal_code_dict = {
            terminal["id"]: terminal for terminal in self.terminals
        }
        for terminal in self.terminals:
            if terminal["id_star_system"]:
                self.terminals_by_system[terminal["id_star_system"]].append(terminal)
            if terminal["id_planet"]:
                self.terminals_by_planet[terminal["id_planet"]].append(terminal)
            if terminal["id_moon"]:
                self.terminals_by_moon[terminal["id_moon"]].append(
                    terminal
                )
            if terminal["id_city"]:
                self.terminals_by_city[terminal["id_city"]].append(terminal)

        self.city_names = [self._format_city_name(city) for city in self.cities]
        self.city_dict = {
            self._format_city_name(city).lower(): city for city in self.cities
        }
        self.city_code_dict = {city["id"]: city for city in self.cities}
        for city in self.cities:
            self.cities_by_planet[city["id_planet"]].append(city)

        self.moon_names = [
            self._format_moon_name(moon) for moon in self.moons
        ]
        self.moon_dict = {
            self._format_moon_name(moon).lower(): moon
            for moon in self.moons
        }
        self.moon_code_dict = {
            moon["id"]: moon for moon in self.moons
        }
        for moon in self.moons:
            self.moons_by_planet[moon["id_planet"]].append(moon)

        self.planet_names = [
            self._format_planet_name(planet) for planet in self.planets
        ]
        self.planet_dict = {
            self._format_planet_name(planet).lower(): planet for planet in self.planets
        }
        self.planet_code_dict = {
            planet["id"]: planet for planet in self.planets
        }
        for planet in self.planets:
            self.planets_by_system[planet["id_star_system"]].append(planet)

        self.location_names_set = set(
            self.system_names
            + self.terminal_names
            + self.city_names
            + self.moon_names
            + self.planet_names
        )
        self.location_names_set_trading = set(
            self.system_names
            + self.terminal_names_trading
            + self.city_names
            + self.moon_names
            + self.planet_names
        )

        self.skill_loaded = True
        if self.skill_loaded_asked:
            self.skill_loaded_asked = False
            await self._print("UEXcorp skill data loading complete.", False, False)

    def add_context(self, content: str):
        """
        Adds additional context to the first message content,
        that represents the context given to open ai.

        Args:
            content (str): The additional context to be added.

        Returns:
            None
        """
        self.dynamic_context += "\n" + content

    def _get_timestamp(self) -> int:
        """
        Get the current timestamp as an integer.

        Returns:
            int: The current timestamp.
        """
        return int(datetime.now().timestamp())

    def _get_header(self):
        """
        Returns the header dictionary containing the API key.
        Used for API requests.

        Returns:
            dict: The header dictionary with the API key.
        """
        key = self.uexcorp_api_key
        return {"Authorization": f"Bearer {key}"}

    async def _fetch_uex_data(
        self, endpoint: str, params: Optional[dict[str, any]] = None
    ) -> list[dict[str, any]]:
        """
        Fetches data from the specified endpoint.

        Args:
            endpoint (str): The API endpoint to fetch data from.
            params (Optional[dict[str, any]]): Optional parameters to include in the request.

        Returns:
            list[dict[str, any]]: The fetched data as a list of dictionaries.
        """
        url = f"{self.uexcorp_api_url}/{endpoint}"
        await self._print(f"Fetching data from {url} ...", True)

        request_count = 1
        timeout_error = False
        requests_error = False

        while request_count == 1 or (request_count <= (self.uexcorp_api_timeout_retries + 1) and timeout_error):
            if requests_error:
                await self._print(f"Retrying request #{request_count}...", True)
                requests_error = False

            timeout_error = False
            try:
                response = requests.get(
                    url,
                    params=params,
                    timeout=(self.uexcorp_api_timeout * request_count),
                    headers=self._get_header(),
                )
                response.raise_for_status()
            except requests.exceptions.RequestException as e:
                await self._print(f"Error while retrieving data from {url}: {e}")
                requests_error = True
                if isinstance(e, requests.exceptions.Timeout):
                    timeout_error = True
            request_count += 1

        if requests_error:
            return []

        response_json = response.json()
        if "status" not in response_json or response_json["status"] != "ok":
            await self._print(f"Error while retrieving data from {url}")
            return []

        return response_json.get("data", [])
    
    async def _fetch_lore(self, search: str) -> dict[str, any]:
        """
        Fetches data for a search query.

        Args:
            search (str): The search query to fetch data for.

        Returns:
            dict[str, any]: The fetched data as a dictionary.
        """
        url = "https://api.star-citizen.wiki/api/v2/galactapedia/search"
        await self._print(f"Fetching data from SC wiki ({url}) for search query '{search}' ...", True)

        request_count = 1
        max_retries = 2
        timeout_error = False
        requests_error = False

        while request_count == 1 or (request_count <= (max_retries + 1) and timeout_error):
            if requests_error:
                await self._print(f"Retrying request #{request_count}...", True)
                requests_error = False

            timeout_error = False
            try:
                response = requests.post(
                    url,
                    headers={"accept": "application/json", "Content-Type": "application/json"},
                    json={"query": search},
                    timeout=self.uexcorp_api_timeout,
                )
                response.raise_for_status()
            except requests.exceptions.RequestException as e:
                await self._print(f"Error while retrieving data from {url}: {e}")
                requests_error = True
                if isinstance(e, requests.exceptions.Timeout):
                    timeout_error = True
            request_count += 1

        if requests_error:
            return {}

        try :
            response_json = response.json()
        except json.decoder.JSONDecodeError as e:
            await self._print(f"Error while retrieving data from {url}: {e}")
            return None

        max_articles = 5
        min_articles = 3
        max_length = 2000
        max_time = self.uexcorp_api_timeout
        loaded_articles = []
        articles = response_json.get("data", [])[:max_articles]

        async def _load_article(article_id: str):
            article_url = f"https://api.star-citizen.wiki/api/v2/galactapedia/{article_id}"
            try:
                article_response = requests.get(article_url, timeout=self.uexcorp_api_timeout)
                article_response.raise_for_status()
            except requests.exceptions.RequestException as e:
                await self._print(f"Error while retrieving data from {article_url}: {e}")
                return None

            try:
                article_response_json = article_response.json()
            except json.decoder.JSONDecodeError as e:
                await self._print(f"Error while retrieving data from {article_url}: {e}")
                return None

            response = article_response_json.get("data", {}).get("translations", {}).get("en_EN", "")
            # scrap links and only keep link name for example [link name](link)
            response = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", response)
            response = re.sub(r"\n", " ", response)
            response = re.sub(r"\s+", " ", response)
            response = response[:max_length]
            loaded_articles.append(response)

        start_time = datetime.now()
        for article in articles:
            self.threaded_execution(_load_article, article["id"])

        while len(loaded_articles) < min_articles and (datetime.now() - start_time).seconds < max_time:
            await asyncio.sleep(0.1)

        return loaded_articles

    def _format_ship_name(self, ship: dict[str, any], full_name: bool = True) -> str:
        """
        Formats the name of a ship.
        This represents a list of names that can be used by the player.
        So if you like to use manufacturer names + ship names, do it here.

        Args:
            ship (dict[str, any]): The ship dictionary containing the ship details.

        Returns:
            str: The formatted ship name.
        """
        if full_name:
            return ship["name_full"]
        
        return ship["name"]

    def _format_terminal_name(self, terminal: dict[str, any], full_name: bool = False) -> str:
        """
        Formats the name of a terminal.

        Args:
            terminal (dict[str, any]): The terminal dictionary containing the name.

        Returns:
            str: The formatted terminal name.
        """
        if full_name:
            return terminal["name"]
        
        return terminal["nickname"]

    def _format_city_name(self, city: dict[str, any]) -> str:
        """
        Formats the name of a city.

        Args:
            city (dict[str, any]): A dictionary representing a city.

        Returns:
            str: The formatted name of the city.
        """
        return city["name"]

    def _format_planet_name(self, planet: dict[str, any]) -> str:
        """
        Formats the name of a planet.

        Args:
            planet (dict[str, any]): A dictionary representing a planet.

        Returns:
            str: The formatted name of the planet.
        """
        return planet["name"]

    def _format_moon_name(self, moon: dict[str, any]) -> str:
        """
        Formats the name of a moon.

        Args:
            moon (dict[str, any]): The moon dictionary.

        Returns:
            str: The formatted moon name.
        """
        return moon["name"]

    def _format_system_name(self, system: dict[str, any]) -> str:
        """
        Formats the name of a system.

        Args:
            system (dict[str, any]): The system dictionary containing the name.

        Returns:
            str: The formatted system name.
        """
        return system["name"]

    def _format_commodity_name(self, commodity: dict[str, any]) -> str:
        """
        Formats the name of a commodity.

        Args:
            commodity (dict[str, any]): The commodity dictionary.

        Returns:
            str: The formatted commodity name.
        """
        return commodity["name"]

    def get_tools(self) -> list[tuple[str, dict]]:
        trading_routes_optional = [
            "money_to_spend",
            "free_cargo_space",
            "position_end_name",
            "commodity_name",
            "illegal_commodities_allowed",
            "maximal_number_of_routes",
        ]
        trading_routes_required = [
            "ship_name"
        ]

        if self.uexcorp_tradestart_mandatory:
            trading_routes_required.append("position_start_name")
        else:
            trading_routes_optional.append("position_start_name")

        tools = [
            (
                "get_trading_routes",
                {
                    "type": "function",
                    "function": {
                        "name": "get_trading_routes",
                        "description": "Finds all possible commodity trade options and gives back a selection of the best trade routes. Needs ship name and start position.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "ship_name": {"type": "string"},
                                "position_start_name": {"type": "string"},
                                "money_to_spend": {"type": "number"},
                                "position_end_name": {"type": "string"},
                                "free_cargo_space": {"type": "number"},
                                "commodity_name": {"type": "string"},
                                "illegal_commodities_allowed": {"type": "boolean"},
                                "maximal_number_of_routes": {"type": "number"},
                            },
                            "required": trading_routes_required,
                            "optional": trading_routes_optional,
                        },
                    },
                },
            ),
            (
                "get_locations_to_sell_to",
                {
                    "type": "function",
                    "function": {
                        "name": "get_locations_to_sell_to",
                        "description": "Finds the best locations at what the player can sell cargo at. Only give position_name if the player specifically wanted to filter for it. Needs commodity name.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "commodity_name": {"type": "string"},
                                "ship_name": {"type": "string"},
                                "position_name": {"type": "string"},
                                "commodity_amount": {"type": "number"},
                                "maximal_number_of_locations": {"type": "number"},
                            },
                            "required": ["commodity_name"],
                            "optional": [
                                "ship_name",
                                "position_name",
                                "commodity_amount",
                                "maximal_number_of_locations",
                            ],
                        },
                    },
                },
            ),
            (
                "get_locations_to_buy_from",
                {
                    "type": "function",
                    "function": {
                        "name": "get_locations_to_buy_from",
                        "description": "Finds the best locations at what the player can buy cargo at. Only give position_name if the player specifically wanted to filter for it. Needs commodity name.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "commodity_name": {"type": "string"},
                                "ship_name": {"type": "string"},
                                "position_name": {"type": "string"},
                                "commodity_amount": {"type": "number"},
                                "maximal_number_of_locations": {"type": "number"},
                            },
                            "required": ["commodity_name"],
                            "optional": [
                                "ship_name",
                                "position_name",
                                "commodity_amount",
                                "maximal_number_of_locations",
                            ],
                        },
                    },
                },
            ),
            (
                "get_location_information",
                {
                    "type": "function",
                    "function": {
                        "name": "get_location_information",
                        "description": "Gives information and commodity prices of this location. Execute this if the player asks for all buy or sell options for a specific location.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "location_name": {"type": "string"},
                            },
                            "required": ["location_name"],
                        },
                    },
                },
            ),
            (
                "get_ship_information",
                {
                    "type": "function",
                    "function": {
                        "name": "get_ship_information",
                        "description": "Gives information about the given ship. If a player asks to rent something or buy a ship, this function needs to be executed.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "ship_name": {"type": "string"},
                            },
                            "required": ["ship_name"],
                        },
                    },
                },
            ),
            (
                "get_ship_comparison",
                {
                    "type": "function",
                    "function": {
                        "name": "get_ship_comparison",
                        "description": "Gives information about given ships. Also execute this function if the player asks for a ship information on multiple ships or a model series.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "ship_names": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["ship_names"],
                        },
                    },
                },
            ),
            (
                "get_commodity_information",
                {
                    "type": "function",
                    "function": {
                        "name": "get_commodity_information",
                        "description": "Gives information about the given commodity. If a player asks for information about a commodity, this function needs to be executed.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "commodity_name": {"type": "string"},
                            },
                            "required": ["commodity_name"],
                        },
                    },
                },
            ),
            (
                "get_commodity_prices_and_terminals",
                {
                    "type": "function",
                    "function": {
                        "name": "get_commodity_prices_and_terminals",
                        "description": "Gives information about the given commodity and its buy and sell offers. If a player asks for buy and sell information or locations on a commodity, this function needs to be executed.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "commodity_name": {"type": "string"},
                            },
                            "required": ["commodity_name"],
                        },
                    },
                },
            ),
            (
                "reload_current_commodity_prices",
                {
                    "type": "function",
                    "function": {
                        "name": "reload_current_commodity_prices",
                        "description": "Reloads the current commodity prices from UEX corp.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                },
            ),
        ]

        if self.DEV_MODE:
            tools.append(
                (
                    "show_cached_function_values",
                    {
                        "type": "function",
                        "function": {
                            "name": "show_cached_function_values",
                            "description": "Prints the cached function's argument values to the console.",
                            "parameters": {
                                "type": "object",
                                "properties": {},
                                "required": [],
                            },
                        },
                    },
                ),
            )

        return tools

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        function_response = ""
        instant_response = ""

        functions = {
            "get_trading_routes": "get_trading_routes",
            "get_locations_to_sell_to": "get_locations_to_sell_to",
            "get_locations_to_buy_from": "get_locations_to_buy_from",
            "get_location_information": "get_location_information",
            "get_ship_information": "get_ship_information",
            "get_ship_comparison": "get_ship_comparison",
            "get_commodity_information": "get_commodity_information",
            "get_commodity_prices_and_terminals": "get_commodity_information",
            "reload_current_commodity_prices": "reload_current_commodity_prices",
            "show_cached_function_values": "show_cached_function_values",
        }

        try:
            if tool_name in functions:
                if(not self.skill_loaded):
                    self.skill_loaded_asked = True
                    await self._print("UEXcorp skill is not loaded yet. Please wait a moment.", False, False)
                    function_response = "Data is still beeing loaded. Please wait a moment."
                    return function_response, instant_response

                self.start_execution_benchmark()
                await self._print(f"Executing function: {tool_name}")
                function = getattr(self, "_gpt_call_" + functions[tool_name])
                function_response = await function(**parameters)
                if self.settings.debug_mode:
                    await self.print_execution_time()
                if self.DEV_MODE:
                    await self._print(f"_gpt_call_{functions[tool_name]} response: {function_response}", True)
        except Exception:
            file_object = open(self.logfileerror, "a", encoding="UTF-8")
            file_object.write(traceback.format_exc())
            file_object.write(
                "========================================================================================\n"
            )
            file_object.write(
                f"Above error while executing custom function: _gpt_call_{tool_name}\n"
            )
            file_object.write(f"With parameters: {parameters}\n")
            file_object.write(f"On date: {datetime.now()}\n")
            file_object.write(f"Version: {self.skill_version}\n")
            file_object.write(
                "========================================================================================\n"
            )
            file_object.close()
            await self._print(
                f"Error while executing custom function: {tool_name}\nCheck log file for more details."
            )
            function_response = f"Error while executing custom function: {tool_name}"
            function_response += "\nTell user there seems to be an error. And you must say that it should be report to the 'uexcorp skill developer (JayMatthew on Discord)'."

        return function_response, instant_response

    async def _find_closest_match(
        self, search: str | None, lst: list[str] | set[str]
    ) -> str | None:
        """
        Finds the closest match to a given string in a list.
        Or returns an exact match if found.
        If it is not an exact match, OpenAI is used to find the closest match.

        Args:
            search (str): The search to find a match for.
            lst (list): The list of strings to search for a match.

        Returns:
            str or None: The closest match found in the list, or None if no match is found.
        """
        if search is None or search == "None":
            return None

        self._log(f"Searching for closest match to '{search}' in list.", True)

        checksum = f"{hash(frozenset(lst))}-{hash(search)}"
        if checksum in self.cache["search_matches"]:
            match = self.cache["search_matches"][checksum]
            self._log(f"Found closest match to '{search}' in cache: '{match}'", True)
            return match

        if search in lst:
            self._log(f"Found exact match to '{search}' in list.", True)
            return search

        # make a list of possible matches
        closest_matches = difflib.get_close_matches(search, lst, n=10, cutoff=0.4)
        closest_matches.extend(item for item in lst if search.lower() in item.lower())
        self._log(
            f"Making a list for closest matches for search term '{search}': {', '.join(closest_matches)}",
            True,
        )

        if not closest_matches:
            self._log(
                f"No closest match found for '{search}' in list. Returning None.", True
            )
            return None

        messages = [
            {
                "role": "system",
                "content": f"""
                    I'll give you just a string value.
                    You will figure out, what value in this list represents this value best: {', '.join(closest_matches)}
                    Keep in mind that the given string value can be misspelled or has missing words as it has its origin in a speech to text process.
                    You must only return the value of the closest match to the given value from the defined list, nothing else.
                    For example if "Hercules A2" is given and the list contains of "A2, C2, M2", you will return "A2" as string.
                    Or if "C2" is given and the list contains of "A2 Hercules Star Lifter, C2 Monster Truck, M2 Extreme cool ship", you will return "C2 Monster Truck" as string.
                    On longer search terms, prefer the exact match, if it is in the list.
                    The response must not contain anything else, than the exact value of the closest match from the list.
                    If you can't find a match, return 'None'. Do never return the given search value.
                """,
            },
            {
                "role": "user",
                "content": search,
            },
        ]
        completion = await self.llm_call(messages)
        answer = (
            completion.choices[0].message.content
            if completion and completion.choices
            else ""
        )

        if not answer:
            dumb_match = difflib.get_close_matches(
                search, closest_matches, n=1, cutoff=0.9
            )
            if dumb_match:
                self._log(
                    f"OpenAI did not answer for '{search}'. Returning dumb match '{dumb_match}'",
                    True,
                )
                return dumb_match[0]
            else:
                self._log(
                    f"OpenAI did not answer for '{search}' and dumb match not possible. Returning None.",
                    True,
                )
                return None

        self._log(f"OpenAI answered: '{answer}'", True)

        if answer == "None" or answer not in closest_matches:
            self._log(
                f"No closest match found for '{search}' in list. Returning None.", True
            )
            return None

        self._log(f"Found closest match to '{search}' in list: '{answer}'", True)
        self.add_context(f"\n\nInstead of '{search}', you should use '{answer}'.")
        self.cache["search_matches"][checksum] = answer
        return answer

    async def get_prompt(self) -> str | None:
        """Return additional context."""
        additional_context = self.config.prompt or ""
        additional_context += "\n" + self.dynamic_context
        return additional_context

    async def _gpt_call_show_cached_function_values(self) -> str:
        """
        Prints the cached function's argument values to the console.

        Returns:
            str: A message indicating that the cached function's argument values have been printed to the console.
        """
        self._log(self.cache["function_args"], True)
        return "The cached function values are: \n" + json.dumps(self.cache["function_args"])

    async def _gpt_call_reload_current_commodity_prices(self) -> str:
        """
        Reloads the current commodity prices from UEX corp.

        Returns:
            str: A message indicating that the current commodity prices have been reloaded.
        """
        await self._load_data(True)
        # clear cached data
        for key in self.cache:
            self.cache[key] = {}

        self._log("Reloaded current commodity prices from UEX corp.", True)
        return "Reloaded current commodity prices from UEX corp."

    async def _gpt_call_get_commodity_information(
        self, commodity_name: str = None
    ) -> str:
        """
        Retrieves information about a given commodity.

        Args:
            commodity_name (str, optional): The name of the commodity. Defaults to None.

        Returns:
            str: The information about the commodity in JSON format, or an error message if the commodity is not found.
        """
        self._log(f"Parameters: Commodity: {commodity_name}", True)

        commodity_name = self._get_function_arg_from_cache(
            "commodity_name", commodity_name
        )

        if commodity_name is None:
            self._log("No commodity given. Ask for a commodity.", True)
            return "No commodity given. Ask for a commodity."

        misunderstood = []
        closest_match = await self._find_closest_match(
            commodity_name, self.commodity_names
        )
        if closest_match is None:
            misunderstood.append(f"Commodity: {commodity_name}")
        else:
            commodity_name = closest_match

        self._log(f"Interpreted Parameters: Commodity: {commodity_name}", True)

        if misunderstood:
            misunderstood_str = ", ".join(misunderstood)
            self._log(
                f"These given parameters do not exist in game. Exactly ask for clarification of these values: {misunderstood_str}",
                True,
            )
            return f"These given parameters do not exist in game. Exactly ask for clarification of these values: {misunderstood_str}"

        commodity = self._get_commodity_by_name(commodity_name)
        if commodity is not None:
            output_commodity = await self._get_converted_commodity_for_output(commodity)
            self._log(output_commodity, True)
            return json.dumps(output_commodity)

    async def _gpt_call_get_ship_information(self, ship_name: str = None) -> str:
        """
        Retrieves information about a specific ship.

        Args:
            ship_name (str, optional): The name of the ship. Defaults to None.

        Returns:
            str: The ship information or an error message.

        """
        self._log(f"Parameters: Ship: {ship_name}", True)

        ship_name = self._get_function_arg_from_cache("ship_name", ship_name)

        if ship_name is None:
            self._log("No ship given. Ask for a ship. Dont say sorry.", True)
            return "No ship given. Ask for a ship. Dont say sorry."

        misunderstood = []
        closest_match = await self._find_closest_match(ship_name, self.ship_names)
        if closest_match is None:
            misunderstood.append(f"Ship: {ship_name}")
        else:
            ship_name = closest_match

        self._log(f"Interpreted Parameters: Ship: {ship_name}", True)

        if misunderstood:
            misunderstood_str = ", ".join(misunderstood)
            self._log(
                f"These given parameters do not exist in game. Exactly ask for clarification of these values: {misunderstood_str}",
                True,
            )
            return f"These given parameters do not exist in game. Exactly ask for clarification of these values: {misunderstood_str}"

        ship = self._get_ship_by_name(ship_name)
        if ship is not None:
            output_ship = f"Summarize in natural language: {(await self._get_converted_ship_for_output(ship))}"
            self._log(output_ship, True)
            return json.dumps(output_ship)

    async def _gpt_call_get_ship_comparison(self, ship_names: list[str] = None) -> str:
        """
        Retrieves information about multiple ships.

        Args:
            ship_names (list[str], optional): The names of the ships. Defaults to None.

        Returns:
            str: The ship information or an error message.
        """
        self._log(f"Parameters: Ships: {', '.join(ship_names)}", True)

        if ship_names is None or not ship_names:
            self._log("No ship given. Ask for a ship. Dont say sorry.", True)
            return "No ship given. Ask for a ship. Dont say sorry."

        misunderstood = []
        ships = []
        for ship_name in ship_names:
            closest_match = await self._find_closest_match(ship_name, self.ship_names)
            if closest_match is None:
                misunderstood.append(ship_name)
            else:
                ship_name = closest_match
                ships.append(self._get_ship_by_name(ship_name))

        self._log(f"Interpreted Parameters: Ships: {', '.join(ship_names)}", True)

        if misunderstood:
            self._log(
                f"These ship names do not exist in game. Exactly ask for clarification of these ships: {', '.join(misunderstood)}",
                True,
            )
            return f"These ship names do not exist in game. Exactly ask for clarification of these ships: {', '.join(misunderstood)}"

        output = {}
        for ship in ships:
            async def get_ship_info(ship):
                output[self._format_ship_name(ship)] = await self._get_converted_ship_for_output(ship)
            self.threaded_execution(get_ship_info, ship)

        while len(output) < len(ships):
            await asyncio.sleep(0.1)

        output = (
            "Point out differences between these ships in natural language and sentences without just listing differences. Describe them! And dont mention something both cant do:\n"
            + json.dumps(output)
        )
        self._log(output, True)
        return output

    async def _gpt_call_get_location_information(
        self, location_name: str = None
    ) -> str:
        """
        Retrieves information about a given location.

        Args:
            location_name (str, optional): The name of the location. Defaults to None.

        Returns:
            str: The information about the location in JSON format, or an error message if the location is not found.
        """
        self._log(f"Parameters: Location: {location_name}", True)

        location_name = self._get_function_arg_from_cache(
            "location_name", location_name
        )

        if location_name is None:
            self._log("No location given. Ask for a location.", True)
            return "No location given. Ask for a location."

        misunderstood = []
        closest_match = await self._find_closest_match(
            location_name, self.location_names_set
        )
        if closest_match is None:
            misunderstood.append(f"Location: {location_name}")
        else:
            location_name = closest_match

        self._log(f"Interpreted Parameters: Location: {location_name}", True)

        if misunderstood:
            misunderstood_str = ", ".join(misunderstood)
            self._log(
                f"These given parameters do not exist in game. Exactly ask for clarification of these values: {misunderstood_str}",
                True,
            )
            return f"These given parameters do not exist in game. Exactly ask for clarification of these values: {misunderstood_str}"

        formating = "Summarize in natural language: "

        # get a clone of the data
        terminal = self._get_terminal_by_name(location_name)
        if terminal is not None:
            output = await self._get_converted_terminal_for_output(terminal)
            self._log(output, True)
            return formating + json.dumps(output)
        city = self._get_city_by_name(location_name)
        if city is not None:
            output = await self._get_converted_city_for_output(city)
            self._log(output, True)
            return formating + json.dumps(output)
        moon = self._get_moon_by_name(location_name)
        if moon is not None:
            output = await self._get_converted_moon_for_output(moon)
            self._log(output, True)
            return formating + json.dumps(output)
        planet = self._get_planet_by_name(location_name)
        if planet is not None:
            output = await self._get_converted_planet_for_output(planet)
            self._log(output, True)
            return formating + json.dumps(output)
        system = self._get_system_by_name(location_name)
        if system is not None:
            output = await self._get_converted_system_for_output(system)
            self._log(output, True)
            return formating + json.dumps(output)

    async def _get_converted_terminal_for_output(
        self, terminal: dict[str, any]
    ) -> dict[str, any]:
        """
        Converts a terminal dictionary to a dictionary that can be used as output.

        Args:
            terminal (dict[str, any]): The terminal dictionary to be converted.

        Returns:
            dict[str, any]: The converted terminal dictionary.
        """
        checksum = f"terminal--{terminal['id']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        output = {
            "type": "terminal",
            "subtype": terminal["type"],
            "name": self._format_terminal_name(terminal, True),
            "nickname": self._format_terminal_name(terminal),
            "star_system": self._get_system_name_by_code(terminal["id_star_system"]),
            "planet": self._get_planet_name_by_code(terminal["id_planet"]),
            "city": self._get_city_name_by_code(terminal["id_city"]),
            "moon": self._get_moon_name_by_code(terminal["id_moon"]),
        }
        if terminal["type"] == "commodity":
            output["hull_trading"] = (
                "Trading with large ships, that need a loading area, is possible."
                if "hull_trading" in terminal and terminal["hull_trading"]
                else "Trading with large ships, that need a loading area, is not possible."
            )

        if "vehicle_rental" in terminal:
            output["vehicles_for_rental"] = []
            for option in terminal["vehicle_rental"]:
                ship = self.ship_code_dict[option["id_vehicle"]]
                output["vehicles_for_rental"].append(
                    f"Rent {self._format_ship_name(ship)} for {option['price_rent']} aUEC."
                )

        if "vehicle_purchase" in terminal:
            output["vehicles_for_purchase"] = []
            for option in terminal["vehicle_purchase"]:
                ship = self.ship_code_dict[option["id_vehicle"]]
                output["vehicles_for_purchase"].append(
                    f"Buy {self._format_ship_name(ship)} for {option['price_buy']} aUEC."
                )

        if "prices" in terminal:
            buyable_commodities = [
                f"{data['name']} for {data['price_buy']} aUEC per SCU"
                for commodity_code, data in terminal["prices"].items()
                if data["operation"] == "buy"
            ]
            sellable_commodities = [
                f"{data['name']} for {data['price_sell']} aUEC per SCU"
                for commodity_code, data in terminal["prices"].items()
                if data["operation"] == "sell"
            ]

            if len(buyable_commodities):
                output["buyable_commodities"] = ", ".join(buyable_commodities)
            if len(sellable_commodities):
                output["sellable_commodities"] = ", ".join(sellable_commodities)

        for key in ["system", "planet", "city", "moon"]:
            if output.get(key) is None:
                output.pop(key, None)

        if self.uexcorp_add_lore:
            output["background_information"] = await self._fetch_lore(self._format_terminal_name(terminal))

        self.cache["readable_objects"][checksum] = output
        return output

    async def _get_converted_city_for_output(self, city: dict[str, any]) -> dict[str, any]:
        """
        Converts a city dictionary to a dictionary that can be used as output.

        Args:
            city (dict[str, any]): The city dictionary to be converted.

        Returns:
            dict[str, any]: The converted city dictionary.
        """
        checksum = f"city--{city['id']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        output = {
            "type": "City",
            "name": self._format_city_name(city),
            "star_system": self._get_system_name_by_code(city["id_star_system"]),
            "planet": self._get_planet_name_by_code(city["id_planet"]),
            "moon": self._get_moon_name_by_code(city["id_moon"]),
            "is_armistice": "Yes" if city["is_armistice"] else "No",
            "has_freight_elevator": "Yes" if city["has_freight_elevator"] else "No",
            "has_docking_ports": "Yes" if city["has_docking_port"] else "No",
            "has_clinic": "Yes" if city["has_clinic"] else "No",
            "has_food": "Yes" if city["has_food"] else "No",
            "has_refuel_option": "Yes" if city["has_refuel"] else "No",
            "has_repair_option": "Yes" if city["has_repair"] else "No",
            "has_refinery": "Yes" if city["has_refinery"] else "No",
        }

        terminals = self._get_terminals_by_position_name(city["name"])
        if terminals:
            output["options_to_trade"] = ", ".join(
                [self._format_terminal_name(terminal) for terminal in terminals]
            )

        for key in ["star_system", "planet", "moon"]:
            if output.get(key) is None:
                output.pop(key, None)

        if self.uexcorp_add_lore:
            output["background_information"] = await self._fetch_lore(self._format_city_name(city))

        self.cache["readable_objects"][checksum] = output
        return output

    async def _get_converted_moon_for_output(
        self, moon: dict[str, any]
    ) -> dict[str, any]:
        """
        Converts a moon dictionary to a dictionary that can be used as output.

        Args:
            moon (dict[str, any]): The moon dictionary to be converted.

        Returns:
            dict[str, any]: The converted moon dictionary.
        """
        checksum = f"moon--{moon['id']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        output = {
            "type": "Moon",
            "name": self._format_moon_name(moon),
            "star_system": self._get_system_name_by_code(moon["id_star_system"]),
            "orbits_planet": self._get_planet_name_by_code(moon["id_planet"]),
        }

        terminals = self._get_terminals_by_position_name(self._format_moon_name(moon))
        if terminals:
            output["options_to_trade"] = ", ".join(
                [self._format_terminal_name(terminal) for terminal in terminals]
            )

        for key in ["star_system", "orbits_planet"]:
            if output.get(key) is None:
                output.pop(key, None)

        if self.uexcorp_add_lore:
            output["background_information"] = await self._fetch_lore(self._format_moon_name(moon))

        self.cache["readable_objects"][checksum] = output
        return output

    async def _get_converted_planet_for_output(
        self, planet: dict[str, any]
    ) -> dict[str, any]:
        """
        Converts a planet dictionary to a dictionary that can be used as output.

        Args:
            planet (dict[str, any]): The planet dictionary to be converted.

        Returns:
            dict[str, any]: The converted planet dictionary.
        """
        checksum = f"planet--{planet['id']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        output = {
            "type": "Planet",
            "name": self._format_planet_name(planet),
            "star_system": self._get_system_name_by_code(planet["id_star_system"]),
        }

        terminals = self._get_terminals_by_position_name(planet["name"])
        if terminals:
            output["options_to_trade"] = ", ".join(
                [self._format_terminal_name(terminal) for terminal in terminals]
            )

        moons = self._get_moons_by_planetcode(planet["code"])
        if moons:
            output["moons"] = ", ".join(
                [self._format_moon_name(moon) for moon in moons]
            )

        cities = self._get_cities_by_planetcode(planet["code"])
        if cities:
            output["cities"] = ", ".join(
                [self._format_city_name(city) for city in cities]
            )

        for key in ["star_system"]:
            if output.get(key) is None:
                output.pop(key, None)

        if self.uexcorp_add_lore:
            output["background_information"] = await self._fetch_lore(self._format_planet_name(planet))

        self.cache["readable_objects"][checksum] = output
        return output

    async def _get_converted_system_for_output(
        self, system: dict[str, any]
    ) -> dict[str, any]:
        """
        Converts a system dictionary to a dictionary that can be used as output.

        Args:
            system (dict[str, any]): The system dictionary to be converted.

        Returns:
            dict[str, any]: The converted system dictionary.
        """
        checksum = f"system--{system['id']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        output = {
            "type": "Star System",
            "name": self._format_system_name(system),
        }

        terminals = self._get_terminals_by_position_name(system["name"])
        if terminals:
            output["options_to_trade"] = f"{len(terminals)} different options to trade."
            terminal_without_planets = []
            gateways = []
            for terminal in terminals:
                if not terminal["id_planet"]:
                    if terminal["name"].find("Gateway") != -1:
                        gateways.append(terminal)
                    else:
                        terminal_without_planets.append(terminal)
            if terminal_without_planets:
                output["space_stations"] = ", ".join(
                    [self._format_terminal_name(terminal) for terminal in terminal_without_planets]
                )
            if gateways:
                output["gateways"] = ", ".join(
                    [self._format_terminal_name(terminal) for terminal in gateways]
                )

        planets = self._get_planets_by_systemcode(system["code"])
        if planets:
            output["planets"] = ", ".join(
                [self._format_planet_name(planet) for planet in planets]
            )

        if self.uexcorp_add_lore:
            output["background_information"] = await self._fetch_lore(self._format_system_name(system))

        self.cache["readable_objects"][checksum] = output
        return output

    async def _get_converted_ship_for_output(self, ship: dict[str, any]) -> dict[str, any]:
        """
        Converts a ship dictionary to a dictionary that can be used as output.

        Args:
            ship (dict[str, any]): The ship dictionary to be converted.

        Returns:
            dict[str, any]: The converted ship dictionary.
        """
        checksum = f"ship--{ship['id']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        output = {
            "type": "Ship" if ship["is_spaceship"] else "Groud Vehicle",
            "name": self._format_ship_name(ship),
            "manufacturer": ship["company_name"],
            "cargo_capacity": f"{ship['scu']} SCU",
            # "added_on_version": "Unknown" if ship["is_concept"] else ship["game_version"],
            "field_of_activity": self._get_ship_field_of_activity(ship),
        }

        if not ship["is_concept"]:
            if ship['purchase']:
                output["purchase_at"] = []
                for option in ship['purchase']:
                    terminal = self.terminal_code_dict[option['id_terminal']]
                    output["purchase_at"].append(
                        f"Buy at {self._format_terminal_name(terminal)} for {option['price_buy']} aUEC"
                    )
            else:
                output["purchase_at"] = 'Not available for purchase.'
            if ship['rental']:
                output["rent_at"] = []
                for option in ship['rental']:
                    terminal = self.terminal_code_dict[option['id_terminal']]
                    output["rent_at"].append(
                        f"Rent at {self._format_terminal_name(terminal)} for {option['price_rent']} aUEC per day."
                    )
            else:
                output["rent_at"] = 'Not available as rental.'

        if ship["hull_trading"] is True:
            output["trading_info"] = (
                "This ship can only trade on suitable space stations with cargo loading option."
            )

        if self.uexcorp_add_lore:
            output["additional_info"] = await self._fetch_lore(self._format_ship_name(ship, False))

        self.cache["readable_objects"][checksum] = output
        return output
    
    def _get_ship_field_of_activity(self, ship: dict[str, any]) -> str:
        """
        Returns the field of activity of a ship.

        Args:
            ship (dict[str, any]): The ship dictionary to get the field of activity for.

        Returns:
            str: The field of activity of the ship.
        """

        field = []
        if ship["is_exploration"]:
            field.append("Exploration")
        if ship["is_mining"]:
            field.append("Mining")
        if ship["is_salvage"]:
            field.append("Salvage")
        if ship["is_refinery"]:
            field.append("Refinery")
        if ship["is_scanning"]:
            field.append("Scanning")
        if ship["is_cargo"]:
            field.append("Cargo")
        if ship["is_medical"]:
            field.append("Medical")
        if ship["is_racing"]:
            field.append("Racing")
        if ship["is_repair"]:
            field.append("Repair")
        if ship["is_refuel"]:
            field.append("Refuel")
        if ship["is_interdiction"]:
            field.append("Interdiction")
        if ship["is_tractor_beam"]:
            field.append("Tractor Beam")
        if ship["is_qed"]:
            field.append("Quantum Interdiction")
        if ship["is_emp"]:
            field.append("EMP")
        if ship["is_construction"]:
            field.append("Construction")
        if ship["is_datarunner"]:
            field.append("Datarunner")
        if ship["is_science"]:
            field.append("Science")
        if ship["is_boarding"]:
            field.append("Boarding")
        if ship["is_stealth"]:
            field.append("Stealth")
        if ship["is_research"]:
            field.append("Research")
        if ship["is_carrier"]:
            field.append("Carrier")

        addition = []
        if ship["is_civilian"]:
            addition.append("Civilian")
        if ship["is_military"]:
            addition.append("Military")

        return f"{', '.join(field)} ({' & '.join(addition)})"

    async def _get_converted_commodity_for_output(
        self, commodity: dict[str, any]
    ) -> dict[str, any]:
        """
        Converts a commodity dictionary to a dictionary that can be used as output.

        Args:
            commodity (dict[str, any]): The commodity dictionary to be converted.

        Returns:
            dict[str, any]: The converted commodity dictionary.
        """
        checksum = f"commodity--{commodity['id']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        output = {
            "type": "Commodity",
            "subtype": commodity["kind"],
            "name": commodity["name"],
        }

        price_buy_best = None
        price_sell_best = None
        output["buy_at"] = {}
        output["sell_at"] = {}

        for terminal in self.terminals:
            if "prices" not in terminal:
                continue
            if commodity["id"] in terminal["prices"]:
                if terminal["prices"][commodity["id"]]["operation"] == "buy":
                    price_buy = terminal["prices"][commodity["id"]]["price_buy"]
                    if price_buy_best is None or price_buy < price_buy_best:
                        price_buy_best = price_buy
                    output["buy_at"][
                        self._format_terminal_name(terminal)
                    ] = f"{price_buy} aUEC"
                else:
                    price_sell = terminal["prices"][commodity["id"]]["price_sell"]
                    if price_sell_best is None or price_sell > price_sell_best:
                        price_sell_best = price_sell
                    output["sell_at"][
                        self._format_terminal_name(terminal)
                    ] = f"{price_sell} aUEC"

        output["best_buy_price"] = (
            f"{price_buy_best} aUEC" if price_buy_best else "Not buyable."
        )
        output["best_sell_price"] = (
            f"{price_sell_best} aUEC" if price_sell_best else "Not sellable."
        )

        boolean_keys = ["is_harvestable", "is_mineral", "is_illegal"]
        for key in boolean_keys:
            output[key] = "Yes" if commodity[key] else "No"

        if commodity["is_illegal"]:
            output["notes"] = "Stay away from ship scanns to avoid fines and crimestat, as this commodity is illegal."

        if self.uexcorp_add_lore:
            output["additional_info"] = await self._fetch_lore(commodity["name"])
        
        self.cache["readable_objects"][checksum] = output
        return output

    async def _gpt_call_get_locations_to_sell_to(
        self,
        commodity_name: str = None,
        ship_name: str = None,
        position_name: str = None,
        commodity_amount: int = 1,
        maximal_number_of_locations: int = 5,
    ) -> str:
        await self._print(
            f"Given Parameters: Commodity: {commodity_name}, Ship Name: {ship_name}, Current Position: {position_name}, Amount: {commodity_amount}, Maximal Number of Locations: {maximal_number_of_locations}",
            True,
        )

        commodity_name = self._get_function_arg_from_cache(
            "commodity_name", commodity_name
        )
        ship_name = self._get_function_arg_from_cache("ship_name", ship_name)

        if commodity_name is None:
            self._log("No commodity given. Ask for a commodity.", True)
            return "No commodity given. Ask for a commodity."

        misunderstood = []
        parameters = {
            "commodity_name": (commodity_name, self.commodity_names),
            "ship_name": (ship_name, self.ship_names),
            "position_name": (position_name, self.location_names_set_trading),
        }
        for param, (value, names_set) in parameters.items():
            if value is not None:
                match = await self._find_closest_match(value, names_set)
                if match is None:
                    misunderstood.append(f"{param}: {value}")
                else:
                    self._set_function_arg_to_cache(param, match)
                    parameters[param] = (match, names_set)
        commodity_name = parameters["commodity_name"][0]
        ship_name = parameters["ship_name"][0]
        position_name = parameters["position_name"][0]

        await self._print(
            f"Interpreted Parameters: Commodity: {commodity_name}, Ship Name: {ship_name}, Position: {position_name}, Amount: {commodity_amount}, Maximal Number of Locations: {maximal_number_of_locations}",
            True,
        )

        if misunderstood:
            self._log(
                "These given parameters do not exist in game. Exactly ask for clarification of these values: "
                + ", ".join(misunderstood),
                True,
            )
            return (
                "These given parameters do not exist in game. Exactly ask for clarification of these values: "
                + ", ".join(misunderstood)
            )

        terminals = (
            self.terminals
            if position_name is None
            else self._get_terminals_by_position_name(position_name)
        )
        commodity = self._get_commodity_by_name(commodity_name)
        ship = self._get_ship_by_name(ship_name)
        amount = max(1, int(commodity_amount or 1))
        maximal_number_of_locations = max(1, int(maximal_number_of_locations or 3))

        selloptions = collections.defaultdict(list)
        for terminal in terminals:
            sellprice = self._get_data_location_sellprice(
                terminal, commodity, ship, amount
            )
            if sellprice is not None:
                selloptions[sellprice].append(terminal)

        selloptions = dict(sorted(selloptions.items(), reverse=True))
        selloptions = dict(
            itertools.islice(selloptions.items(), maximal_number_of_locations)
        )

        messages = [
            f"Here are the best {len(selloptions)} locations to sell {amount} SCU {commodity_name}:"
        ]

        for sellprice, terminals in selloptions.items():
            messages.append(f"{sellprice} aUEC:")
            messages.extend(
                (await self._get_terminal_route_description(terminal))
                for terminal in terminals
            )
            messages.append("\n")

        self._log("\n".join(messages), True)
        return "\n".join(messages)

    async def _gpt_call_get_locations_to_buy_from(
        self,
        commodity_name: str = None,
        ship_name: str = None,
        position_name: str = None,
        commodity_amount: int = 1,
        maximal_number_of_locations: int = 5,
    ) -> str:
        await self._print(
            f"Given Parameters: Commodity: {commodity_name}, Ship Name: {ship_name}, Current Position: {position_name}, Amount: {commodity_amount}, Maximal Number of Locations: {maximal_number_of_locations}",
            True,
        )

        commodity_name = self._get_function_arg_from_cache(
            "commodity_name", commodity_name
        )
        ship_name = self._get_function_arg_from_cache("ship_name", ship_name)

        if commodity_name is None:
            self._log("No commodity given. Ask for a commodity.", True)
            return "No commodity given. Ask for a commodity."

        misunderstood = []
        parameters = {
            "ship_name": (ship_name, self.ship_names),
            "location_name": (position_name, self.location_names_set_trading),
            "commodity_name": (commodity_name, self.commodity_names),
        }
        for param, (value, names_set) in parameters.items():
            if value is not None:
                match = await self._find_closest_match(value, names_set)
                if match is None:
                    misunderstood.append(f"{param}: {value}")
                else:
                    self._set_function_arg_to_cache(param, match)
                    parameters[param] = (match, names_set)
        ship_name = parameters["ship_name"][0]
        position_name = parameters["location_name"][0]
        commodity_name = parameters["commodity_name"][0]

        await self._print(
            f"Interpreted Parameters: Commodity: {commodity_name}, Ship Name: {ship_name}, Position: {position_name}, Amount: {commodity_amount}, Maximal Number of Locations: {maximal_number_of_locations}",
            True,
        )

        if misunderstood:
            self._log(
                "These given parameters do not exist in game. Exactly ask for clarification of these values: "
                + ", ".join(misunderstood),
                True,
            )
            return (
                "These given parameters do not exist in game. Exactly ask for clarification of these values: "
                + ", ".join(misunderstood)
            )

        terminals = (
            self.terminals
            if position_name is None
            else self._get_terminals_by_position_name(position_name)
        )
        commodity = self._get_commodity_by_name(commodity_name)
        ship = self._get_ship_by_name(ship_name)
        amount = max(1, int(commodity_amount or 1))
        maximal_number_of_locations = max(1, int(maximal_number_of_locations or 3))

        buyoptions = collections.defaultdict(list)
        for terminal in terminals:
            buyprice = self._get_data_location_buyprice(
                terminal, commodity, ship, amount
            )
            if buyprice is not None:
                buyoptions[buyprice].append(terminal)

        buyoptions = dict(sorted(buyoptions.items(), reverse=False))
        buyoptions = dict(
            itertools.islice(buyoptions.items(), maximal_number_of_locations)
        )

        messages = [
            f"Here are the best {len(buyoptions)} locations to buy {amount} SCU {commodity_name}:"
        ]
        for buyprice, terminals in buyoptions.items():
            messages.append(f"{buyprice} aUEC:")
            messages.extend(
                (await self._get_terminal_route_description(terminal))
                for terminal in terminals
            )
            messages.append("\n")

        self._log("\n".join(messages), True)
        return "\n".join(messages)

    def _get_data_location_sellprice(self, terminal, commodity, ship=None, amount=1):
        if (
            ship is not None
            and ship["hull_trading"] is True
            and terminal["hull_trading"] is False
        ):
            return None

        if "prices" not in terminal:
            return None

        commodity_code = commodity["id"]
        for code, price in terminal["prices"].items():
            if code == commodity_code and price["operation"] == "sell":
                return price["price_sell"] * amount
        return None

    def _get_data_location_buyprice(self, terminal, commodity, ship=None, amount=1):
        if (
            ship is not None
            and ship["hull_trading"] is True
            and terminal["hull_trading"] is False
        ):
            return None

        if "prices" not in terminal:
            return None

        commodity_code = commodity["id"]
        for code, price in terminal["prices"].items():
            if code == commodity_code and price["operation"] == "buy":
                return price["price_buy"] * amount
        return None

    async def _gpt_call_get_trading_routes(
        self,
        ship_name: str = None,
        money_to_spend: float = None,
        position_start_name: str = None,
        free_cargo_space: float = None,
        position_end_name: str = None,
        commodity_name: str = None,
        illegal_commodities_allowed: bool = None,
        maximal_number_of_routes: int = None,
    ) -> str:
        """
        Finds multiple best trading routes based on the given parameters.

        Args:
            ship_name (str, optional): The name of the ship. Defaults to None.
            money_to_spend (float, optional): The amount of money to spend. Defaults to None.
            position_start_name (str, optional): The name of the starting position. Defaults to None.
            free_cargo_space (float, optional): The amount of free cargo space. Defaults to None.
            position_end_name (str, optional): The name of the ending position. Defaults to None.
            commodity_name (str, optional): The name of the commodity. Defaults to None.
            illegal_commodities_allowed (bool, optional): Flag indicating whether illegal commodities are allowed. Defaults to True.
            maximal_number_of_routes (int, optional): The maximum number of routes to return. Defaults to 2.

        Returns:
            str: A string representation of the trading routes found.
        """

        # For later use in distance calculation:
        # https://starmap.tk/api/v2/oc/
        # https://starmap.tk/api/v2/pois/

        await self._print(
            f"Parameters: Ship: {ship_name}, Position Start: {position_start_name}, Position End: {position_end_name}, Commodity Name: {commodity_name}, Money: {money_to_spend} aUEC, free_cargo_space: {free_cargo_space} SCU, Maximal Number of Routes: {maximal_number_of_routes}, Illegal Allowed: {illegal_commodities_allowed}",
            True,
        )

        ship_name = self._get_function_arg_from_cache("ship_name", ship_name)
        illegal_commodities_allowed = self._get_function_arg_from_cache(
            "illegal_commodities_allowed", illegal_commodities_allowed
        )
        if illegal_commodities_allowed is None:
            illegal_commodities_allowed = True

        missing_args = []
        if ship_name is None:
            missing_args.append("ship_name")

        if self.uexcorp_tradestart_mandatory and position_start_name is None:
            missing_args.append("position_start_name")

        money_to_spend = (
            None
            if money_to_spend is not None and int(money_to_spend) < 1
            else money_to_spend
        )
        free_cargo_space = (
            None
            if free_cargo_space is not None and int(free_cargo_space) < 1
            else free_cargo_space
        )

        misunderstood = []
        parameters = {
            "ship_name": (ship_name, self.ship_names),
            "position_start_name": (position_start_name, self.location_names_set_trading),
            "position_end_name": (position_end_name, self.location_names_set_trading),
            "commodity_name": (commodity_name, self.commodity_names),
        }
        for param, (value, names_set) in parameters.items():
            if value is not None:
                match = await self._find_closest_match(value, names_set)
                if match is None:
                    misunderstood.append(f"{param}: {value}")
                else:
                    self._set_function_arg_to_cache(param, match)
                    parameters[param] = (match, names_set)
        ship_name = parameters["ship_name"][0]
        position_start_name = parameters["position_start_name"][0]
        position_end_name = parameters["position_end_name"][0]
        commodity_name = parameters["commodity_name"][0]

        if money_to_spend is not None:
            self._set_function_arg_to_cache("money", money_to_spend)

        await self._print(
            f"Interpreted Parameters: Ship: {ship_name}, Position Start: {position_start_name}, Position End: {position_end_name}, Commodity Name: {commodity_name}, Money: {money_to_spend} aUEC, free_cargo_space: {free_cargo_space} SCU, Maximal Number of Routes: {maximal_number_of_routes}, Illegal Allowed: {illegal_commodities_allowed}",
            True,
        )

        self._set_function_arg_to_cache("money", money_to_spend)

        if misunderstood or missing_args:
            misunderstood_str = ", ".join(misunderstood)
            missing_str = ", ".join(missing_args)
            answer = ""
            if missing_str:
                answer += f"Missing parameters: {missing_str}. "
            if misunderstood_str:
                answer += (
                    f"These given parameters were misunderstood: {misunderstood_str}"
                )
            return answer

        # set variables
        ship = self._get_ship_by_name(ship_name)
        if money_to_spend is not None:
            money = int(money_to_spend)
        else:
            money = None
        if free_cargo_space is not None:
            free_cargo_space = int(free_cargo_space)
        else:
            free_cargo_space = None
        commodity = (
            self._get_commodity_by_name(commodity_name) if commodity_name else None
        )
        maximal_number_of_routes = int(
            maximal_number_of_routes or self.uexcorp_default_trade_route_count
        )
        start_terminals = (
            self._get_terminals_by_position_name(position_start_name)
            if position_start_name
            else self.terminals
        )
        end_terminals = (
            self._get_terminals_by_position_name(position_end_name)
            if position_end_name
            else self.terminals
        )

        commodities = []
        if commodity is None:
            commodities = self.commodities
        else:
            commodities.append(commodity)

        trading_routes = []
        errors = []
        for commodity in commodities:
            commodity_routes = []
            if not illegal_commodities_allowed and commodity["is_illegal"]:
                continue
            for start_terminal in start_terminals:
                if (
                    "prices" not in start_terminal
                    or commodity["id"] not in start_terminal["prices"]
                    or start_terminal["prices"][commodity["id"]]["operation"]
                    != "buy"
                ):
                    continue
                for end_terminal in end_terminals:
                    if (
                        "prices" not in end_terminal
                        or commodity["id"] not in end_terminal["prices"]
                        or end_terminal["prices"][commodity["id"]]["operation"]
                        != "sell"
                    ):
                        continue

                    if (
                        ship
                        and ship["hull_trading"] is True
                        and (
                            "hull_trading" not in start_terminal
                            or start_terminal["hull_trading"] is not True
                            or "hull_trading" not in end_terminal
                            or end_terminal["hull_trading"] is not True
                        )
                    ):
                        continue

                    trading_route_new = self._get_trading_route(
                        ship,
                        start_terminal,
                        end_terminal,
                        money,
                        free_cargo_space,
                        commodity,
                        illegal_commodities_allowed,
                    )

                    if isinstance(trading_route_new, str):
                        if trading_route_new not in errors:
                            errors.append(trading_route_new)
                    else:
                        commodity_routes.append(trading_route_new)

            if len(commodity_routes) > 0:
                if self.uexcorp_summarize_routes_by_commodity:
                    best_commodity_routes = heapq.nlargest(
                        1, commodity_routes, key=lambda k: int(k["profit"])
                    )
                    trading_routes.extend(best_commodity_routes)
                else:
                    trading_routes.extend(commodity_routes)

        if len(trading_routes) > 0:
            additional_answer = ""
            if len(trading_routes) < maximal_number_of_routes:
                additional_answer += f" There are only {len(trading_routes)} with different commodities available. "
            else:
                additional_answer += f" There are {len(trading_routes)} routes available and these are the best {maximal_number_of_routes} ones."

            # sort trading routes by profit and limit to maximal_number_of_routes
            trading_routes = heapq.nlargest(
                maximal_number_of_routes, trading_routes, key=lambda k: int(k["profit"])
            )

            for trading_route in trading_routes:
                destinationselection = []
                for terminal in trading_route["end"]:
                    destinationselection.append(
                        f"{(await self._get_terminal_route_description(terminal))}"
                    )
                trading_route["end"] = " OR ".join(destinationselection)
                startselection = []
                for terminal in trading_route["start"]:
                    startselection.append(
                        f"{(await self._get_terminal_route_description(terminal))}"
                    )
                trading_route["start"] = " OR ".join(startselection)

            # format the trading routes
            for trading_route in trading_routes:
                trading_route["start"] = trading_route["start"]
                trading_route["end"] = trading_route["end"]
                trading_route["commodity"] = self._format_commodity_name(
                    trading_route["commodity"]
                )
                trading_route["profit"] = f"{trading_route['profit']} aUEC"
                trading_route["buy"] = f"{trading_route['buy']} aUEC"
                trading_route["sell"] = f"{trading_route['sell']} aUEC"
                trading_route["cargo"] = f"{trading_route['cargo']} SCU"

            message = (
                "Possible commodities with their profit. Just give basic overview at first.\n"
                + additional_answer
                + " JSON: \n "
                + json.dumps(trading_routes)
            )
            return message
        else:
            return_string = "No trading routes found."
            if len(errors) > 0:
                return_string += "\nPossible errors are:\n- " + "\n- ".join(errors)
            return return_string

    def _get_trading_route(
        self,
        ship: dict[str, any],
        position_start: dict[str, any],
        position_end: dict[str, any],
        money: int = None,
        free_cargo_space: int = None,
        commodity: dict[str, any] = None,
        illegal_commodities_allowed: bool = True,
    ) -> str:
        """
        Finds the best trading route based on the given parameters.

        Args:
            ship (dict[str, any]): The ship dictionary.
            position_start (dict[str, any]): The starting position dictionary.
            money (int, optional): The amount of money to spend. Defaults to None.
            free_cargo_space (int, optional): The amount of free cargo space. Defaults to None.
            position_end (dict[str, any], optional): The ending position dictionary. Defaults to None.
            commodity (dict[str, any], optional): The commodity dictionary. Defaults to None.
            illegal_commodities_allowed (bool, optional): Flag indicating whether illegal commodities are allowed. Defaults to True.

        Returns:
            str: A string representation of the trading route found. JSON if the route is found, otherwise an error message.
        """

        # set variables
        cargo_space = ship["scu"]
        if free_cargo_space:
            cargo_space = free_cargo_space
            if free_cargo_space > ship["scu"]:
                cargo_space = ship["scu"]

        if cargo_space < 1:
            return "Your ship has no cargo space to trade."

        commodity_filter = commodity
        start_terminals = [position_start]
        if ship["hull_trading"] is True:
            start_terminals = [
                terminal
                for terminal in start_terminals
                if "hull_trading" in terminal and terminal["hull_trading"] is True
            ]
        if len(start_terminals) < 1:
            if ship["hull_trading"] is True:
                return "No valid start position given. Make sure to provide a start point compatible with your ship."
            return "No valid start position given. Try a different position or just name a planet or star system."

        end_terminals = [position_end]
        if ship["hull_trading"] is True:
            end_terminals = [
                terminal
                for terminal in end_terminals
                if "hull_trading" in terminal and terminal["hull_trading"] is True
            ]
        if len(end_terminals) < 1:
            return "No valid end position given."

        if (
            len(end_terminals) == 1
            and len(start_terminals) == 1
            and end_terminals[0]["id"] == start_terminals[0]["id"]
        ):
            return "Start and end position are the same."

        if money is not None and money <= 0:
            return "You dont have enough money to trade."

        best_route = {
            "start": [],
            "end": [],
            "commodity": {},
            "profit": 0,
            "cargo": 0,
            "buy": 0,
            "sell": 0,
        }

        # apply trade port blacklist
        if self.uexcorp_trade_blacklist:
            for blacklist_item in self.uexcorp_trade_blacklist:
                if "tradeport" in blacklist_item and blacklist_item["tradeport"]:
                    for terminal in start_terminals:
                        if self._format_terminal_name(terminal) == blacklist_item["tradeport"]:
                            if (
                                "commodity" not in blacklist_item
                                or not blacklist_item["commodity"]
                            ):
                                # remove terminal, if no commodity given
                                start_terminals.remove(terminal)
                                break
                            else:
                                commodity = self._get_commodity_by_name(
                                    blacklist_item["commodity"]
                                )
                                for commodity_code, data in terminal["prices"].items():
                                    if commodity["id"] == commodity_code:
                                        # remove commodity code from terminal
                                        terminal["prices"].pop(commodity_code)
                                        break
                    for terminal in end_terminals:
                        if self._format_terminal_name(terminal) == blacklist_item["tradeport"]:
                            if (
                                "commodity" not in blacklist_item
                                or not blacklist_item["commodity"]
                            ):
                                # remove terminal, if no commodity given
                                end_terminals.remove(terminal)
                                break
                            else:
                                commodity = self._get_commodity_by_name(
                                    blacklist_item["commodity"]
                                )
                                for commodity_code, data in terminal["prices"].items():
                                    if commodity["id"] == commodity_code:
                                        # remove commodity code from terminal
                                        terminal["prices"].pop(commodity_code)
                                        break

        if len(start_terminals) < 1 or len(end_terminals) < 1:
            return "Exluded by blacklist."

        for terminal_start in start_terminals:
            commodities = []
            if "prices" not in terminal_start:
                continue

            for commodity_code, price in terminal_start["prices"].items():
                if price["operation"] == "buy" and (
                    commodity_filter is None or commodity_filter["id"] == commodity_code
                ):
                    commodity = self._get_commodity_by_code(commodity_code)
                    if (
                        illegal_commodities_allowed is True
                        or not commodity["is_illegal"]
                    ):
                        temp_price = price
                        temp_price["commodity_code"] = commodity_code

                        in_blacklist = False
                        # apply commodity blacklist
                        if self.uexcorp_trade_blacklist:
                            for blacklist_item in self.uexcorp_trade_blacklist:
                                if (
                                    "commodity" in blacklist_item
                                    and blacklist_item["commodity"]
                                    and not "tradeport" in blacklist_item
                                    or not blacklist_item["tradeport"]
                                ):
                                    if commodity["name"] == blacklist_item["commodity"]:
                                        # remove commodity code from terminal
                                        in_blacklist = True
                                        break

                        if not in_blacklist:
                            commodities.append(price)

            if len(commodities) < 1:
                continue

            for terminal_end in end_terminals:
                if "prices" not in terminal_end:
                    continue

                for commodity_code, price in terminal_end["prices"].items():
                    sell_commodity = self._get_commodity_by_code(commodity_code)

                    in_blacklist = False
                    # apply commodity blacklist
                    if sell_commodity and self.uexcorp_trade_blacklist:
                        for blacklist_item in self.uexcorp_trade_blacklist:
                            if (
                                "commodity" in blacklist_item
                                and blacklist_item["commodity"]
                                and not "tradeport" in blacklist_item
                                or not blacklist_item["tradeport"]
                            ):
                                if (
                                    sell_commodity["name"]
                                    == blacklist_item["commodity"]
                                ):
                                    # remove commodity code from terminal
                                    in_blacklist = True
                                    break

                    if in_blacklist:
                        continue

                    temp_price = price
                    temp_price["commodity_code"] = commodity_code

                    for commodity in commodities:
                        if (
                            commodity["commodity_code"] == temp_price["commodity_code"]
                            and price["operation"] == "sell"
                            and price["price_sell"] > commodity["price_buy"]
                        ):
                            if money is None:
                                cargo_by_money = cargo_space
                            else:
                                cargo_by_money = math.floor(
                                    money / commodity["price_buy"]
                                )
                            cargo_by_space = cargo_space
                            if self.uexcorp_use_estimated_availability:
                                cargo_by_availability = min(commodity["scu_expected"] or 0, temp_price["scu_expected"] or 0)
                            else:
                                cargo_by_availability = cargo_by_space

                            cargo = min(cargo_by_money, cargo_by_space, cargo_by_availability)
                            if cargo >= 1:
                                profit = round(
                                    cargo
                                    * (price["price_sell"] - commodity["price_buy"])
                                )
                                if profit > best_route["profit"]:
                                    best_route["start"] = [terminal_start]
                                    best_route["end"] = [terminal_end]
                                    best_route["commodity"] = temp_price
                                    best_route["profit"] = profit
                                    best_route["cargo"] = cargo
                                    best_route["buy"] = commodity["price_buy"] * cargo
                                    best_route["sell"] = price["price_sell"] * cargo
                                else:
                                    if (
                                        profit == best_route["profit"]
                                        and best_route["commodity"]["commodity_code"]
                                        == temp_price["commodity_code"]
                                    ):
                                        if terminal_start not in best_route["start"]:
                                            best_route["start"].append(terminal_start)
                                        if terminal_end not in best_route["end"]:
                                            best_route["end"].append(terminal_end)

        if len(best_route["start"]) == 0:
            return f"No route found for your {ship['name']}. Try a different route."

        best_route["commodity"] = best_route["commodity"]
        best_route["profit"] = f"{best_route['profit']}"
        best_route["cargo"] = f"{best_route['cargo']}"
        best_route["buy"] = f"{best_route['buy']}"
        best_route["sell"] = f"{best_route['sell']}"

        return best_route

    def _get_ship_by_name(self, name: str) -> dict[str, any] | None:
        """Finds the ship with the specified name and returns the ship or None.

        Args:
            name (str): The name of the ship to search for.

        Returns:
            Optional[object]: The ship object if found, or None if not found.
        """
        return self.ship_dict.get(name.lower()) if name else None

    def _get_terminal_by_name(self, name: str) -> dict[str, any] | None:
        """Finds the terminal with the specified name and returns the terminal or None.

        Args:
            name (str): The name of the terminal to search for.

        Returns:
            Optional[object]: The terminal object if found, otherwise None.
        """
        return self.terminal_dict.get(name.lower()) if name else None

    def _get_terminal_by_code(self, code: str) -> dict[str, any] | None:
        """Finds the terminal with the specified code and returns the terminal or None.

        Args:
            code (str): The code of the terminal to search for.

        Returns:
            Optional[object]: The terminal object if found, otherwise None.
        """
        return self.terminal_code_dict.get(code) if code else None

    def _get_planet_by_name(self, name: str) -> dict[str, any] | None:
        """Finds the planet with the specified name and returns the planet or None.

        Args:
            name (str): The name of the planet to search for.

        Returns:
            Optional[object]: The planet object if found, otherwise None.
        """
        return self.planet_dict.get(name.lower()) if name else None

    def _get_city_by_name(self, name: str) -> dict[str, any] | None:
        """Finds the city with the specified name and returns the city or None.

        Args:
            name (str): The name of the city to search for.

        Returns:
            Optional[object]: The city object if found, or None if not found.
        """
        return self.city_dict.get(name.lower()) if name else None

    def _get_moon_by_name(self, name: str) -> dict[str, any] | None:
        """Finds the moon with the specified name and returns the moon or None.

        Args:
            name (str): The name of the moon to search for.

        Returns:
            Optional[object]: The moon object if found, otherwise None.
        """
        return self.moon_dict.get(name.lower()) if name else None

    def _get_system_by_name(self, name: str) -> dict[str, any] | None:
        """Finds the system with the specified name and returns the system or None.

        Args:
            name (str): The name of the system to search for.

        Returns:
            Optional[object]: The system object if found, otherwise None.
        """
        return self.system_dict.get(name.lower()) if name else None

    def _get_commodity_by_name(self, name: str) -> dict[str, any] | None:
        """Finds the commodity with the specified name and returns the commodity or None.

        Args:
            name (str): The name of the commodity to search for.

        Returns:
            Optional[object]: The commodity object if found, otherwise None.
        """
        return self.commodity_dict.get(name.lower()) if name else None

    async def _get_terminal_route_description(self, terminal: dict[str, any]) -> str:
        """Returns the breadcrums of a terminal.

        Args:
            terminal (dict[str, any]): The terminal information.

        Returns:
            str: The description of the terminal route.
        """
        terminal = await self._get_converted_terminal_for_output(terminal)
        keys = [
            ("star_system", "Star-System"),
            ("planet", "Planet"),
            ("moon", "moon"),
            ("city", "City"),
            ("name", "Trade Point"),
        ]
        route = [f"{name}: {terminal[key]}" for key, name in keys if key in terminal]
        return f"({' >> '.join(route)})"

    def _get_system_name_by_code(self, code: str) -> str:
        """Returns the name of the system with the specified code.

        Args:
            code (str): The code of the system.

        Returns:
            str: The name of the system with the specified code.
        """
        return (
            self._format_system_name(self.system_code_dict.get(code))
            if code
            else None
        )

    def _get_planet_name_by_code(self, code: str) -> str:
        """Returns the name of the planet with the specified code.

        Args:
            code (str): The code of the planet.

        Returns:
            str: The name of the planet with the specified code.
        """
        return (
            self._format_planet_name(self.planet_code_dict.get(code))
            if code
            else None
        )

    def _get_moon_name_by_code(self, code: str) -> str:
        """Returns the name of the moon with the specified code.

        Args:
            code (str): The code of the moon.

        Returns:
            str: The name of the moon with the specified code.
        """
        return (
            self._format_moon_name(self.moon_code_dict.get(code))
            if code
            else None
        )

    def _get_city_name_by_code(self, code: str) -> str:
        """Returns the name of the city with the specified code.

        Args:
            code (str): The code of the city.

        Returns:
            str: The name of the city with the specified code.
        """
        return (
            self._format_city_name(self.city_code_dict.get(code))
            if code
            else None
        )

    def _get_commodity_name_by_code(self, code: str) -> str:
        """Returns the name of the commodity with the specified code.

        Args:
            code (str): The code of the commodity.

        Returns:
            str: The name of the commodity with the specified code.
        """
        return (
            self._format_commodity_name(self.commodity_code_dict.get(code))
            if code
            else None
        )

    def _get_commodity_by_code(self, code: str) -> dict[str, any] | None:
        """Finds the commodity with the specified code and returns the commodity or None.

        Args:
            code (str): The code of the commodity to search for.

        Returns:
            Optional[object]: The commodity object if found, otherwise None.
        """
        return self.commodity_code_dict.get(code) if code else None

    def _get_terminals_by_position_name(
        self, name: str
    ) -> list[dict[str, any]]:
        """Returns all terminals with the specified position name.

        Args:
            name (str): The position name to search for.

        Returns:
            list[dict[str, any]]: A list of terminals matching the position name.
        """
        if not name:
            return []

        terminals = []

        terminal_temp = self._get_terminal_by_name(name)
        if terminal_temp:
            terminals.append(terminal_temp)

        terminals.extend(self._get_terminals_by_systemname(name))
        terminals.extend(self._get_terminals_by_planetname(name))
        terminals.extend(self._get_terminals_by_moonname(name))
        terminals.extend(self._get_terminals_by_cityname(name))
        return terminals

    def _get_moons_by_planetcode(self, code: str) -> list[dict[str, any]]:
        """Returns the moon with the specified planet code.

        Args:
            code (str): The code of the planet.

        Returns:
            Optional[object]: The moon object if found, otherwise None.
        """
        return self.moons_by_planet.get(code, []) if code else []

    def _get_cities_by_planetcode(self, code: str) -> list[dict[str, any]]:
        """Returns all cities with the specified planet code.

        Args:
            code (str): The code of the planet.

        Returns:
            list[dict[str, any]]: A list of cities matching the planet code.
        """
        return self.cities_by_planet.get(code, []) if code else []

    def _get_planets_by_systemcode(self, code: str) -> list[dict[str, any]]:
        """Returns all planets with the specified system code.

        Args:
            code (str): The code of the system.

        Returns:
            list[dict[str, any]]: A list of planets matching the system code.
        """
        return self.planets_by_system.get(code, []) if code else []

    def _get_terminals_by_systemcode(self, code: str) -> list[dict[str, any]]:
        """Returns all terminals with the specified system code.

        Args:
            code (str): The code of the system.

        Returns:
            list[dict[str, any]]: A list of terminals matching the system code.
        """
        return self.terminals_by_system.get(code, []) if code else []

    def _get_terminals_by_planetcode(self, code: str) -> list[dict[str, any]]:
        """Returns all terminals with the specified planet code.

        Args:
            code (str): The code of the planet.

        Returns:
            list[dict[str, any]]: A list of terminals matching the planet code.
        """
        return self.terminals_by_planet.get(code, []) if code else []

    def _get_terminals_by_mooncode(self, code: str) -> list[dict[str, any]]:
        """Returns all terminals with the specified moon code.

        Args:
            code (str): The code of the moon.

        Returns:
            list[dict[str, any]]: A list of terminals matching the moon code.
        """
        return self.terminals_by_moon.get(code, []) if code else []

    def _get_terminals_by_citycode(self, code: str) -> list[dict[str, any]]:
        """Returns all terminals with the specified city code.

        Args:
            code (str): The code of the city.

        Returns:
            list[dict[str, any]]: A list of terminals matching the city code.
        """
        return self.terminals_by_city.get(code, []) if code else []

    def _get_terminals_by_planetname(self, name: str) -> list[dict[str, any]]:
        """Returns all terminals with the specified planet name.

        Args:
            name (str): The name of the planet.

        Returns:
            list[dict[str, any]]: A list of terminals matching the planet name.
        """
        planet = self._get_planet_by_name(name)
        return self._get_terminals_by_planetcode(planet["id"]) if planet else []

    def _get_terminals_by_moonname(self, name: str) -> list[dict[str, any]]:
        """Returns all terminals with the specified moon name.

        Args:
            name (str): The name of the moon.

        Returns:
            list[dict[str, any]]: A list of terminals matching the moon name.
        """
        moon = self._get_moon_by_name(name)
        return (
            self._get_terminals_by_mooncode(moon["id"])
            if moon
            else []
        )

    def _get_terminals_by_cityname(self, name: str) -> list[dict[str, any]]:
        """Returns all terminals with the specified city name.

        Args:
            name (str): The name of the city.

        Returns:
            list[dict[str, any]]: A list of terminals matching the city name.
        """
        city = self._get_city_by_name(name)
        return self._get_terminals_by_citycode(city["id"]) if city else []

    def _get_terminals_by_systemname(self, name: str) -> list[dict[str, any]]:
        """Returns all terminals with the specified system name.

        Args:
            name (str): The name of the system.

        Returns:
            list[dict[str, any]]: A list of terminals matching the system name.
        """
        system = self._get_system_by_name(name)
        return self._get_terminals_by_systemcode(system["id"]) if system else []
    
