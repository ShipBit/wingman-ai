"""Wingman AI Skill to utalize uexcorp api for trade recommendations"""

import asyncio
import threading
import difflib
import heapq
import itertools
import json
import math
import traceback
from os import path
import collections
import re
from typing import Optional
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

class UEXCorp(Skill):

    # enable for verbose logging
    DEV_MODE = False

    def __init__(
        self,
        config: SkillConfig,
        wingman_config: WingmanConfig,
        settings: SettingsConfig,
    ) -> None:
        super().__init__(
            config=config, wingman_config=wingman_config, settings=settings
        )

        self.data_path = get_writable_dir(path.join("skills", "uexcorp", "data"))
        self.logfileerror = path.join(self.data_path, "error.log")
        self.logfiledebug = path.join(self.data_path, "debug.log")
        self.cachefile = path.join(self.data_path, "cache.json")

        self.skill_version = "v12"
        self.skill_loaded = False
        self.skill_loaded_asked = False

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

        # init of data lists
        # self.status_codes = []

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

        self.tradeports = []
        self.tradeport_names = []
        self.tradeport_dict = {}
        self.tradeport_code_dict = {}
        self.tradeports_by_system = collections.defaultdict(list)
        self.tradeports_by_planet = collections.defaultdict(list)
        self.tradeports_by_satellite = collections.defaultdict(list)
        self.tradeports_by_city = collections.defaultdict(list)

        self.planets = []
        self.planet_names = []
        self.planet_dict = {}
        self.planet_code_dict = {}
        self.planets_by_system = collections.defaultdict(list)

        self.satellites = []
        self.satellite_names = []
        self.satellite_dict = {}
        self.satellite_code_dict = {}
        self.satellites_by_planet = collections.defaultdict(list)

        self.cities = []
        self.city_names = []
        self.city_dict = {}
        self.city_code_dict = {}
        self.cities_by_planet = collections.defaultdict(list)

        self.location_names_set = set()

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
            await self._save_to_cachefile()
            return

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
            ):
                if data.get("ships"):
                    self.ships = data["ships"]
                if data.get("commodities"):
                    self.commodities = data["commodities"]
                if data.get("systems"):
                    self.systems = data["systems"]
                if data.get("tradeports"):
                    self.tradeports = data["tradeports"]
                    # fix prices keys (from string to integer due to unintentional json conversion)
                    for tradeport in self.tradeports:
                        if "prices" in tradeport:
                            tradeport["prices"] = {
                                int(key): value
                                for key, value in tradeport["prices"].items()
                            }
                if data.get("planets"):
                    self.planets = data["planets"]
                if data.get("satellites"):
                    self.satellites = data["satellites"]
                if data.get("cities"):
                    self.cities = data["cities"]

        async def _load_missing_data():
            if not self.ships:
                self.ships = await self._fetch_uex_data("vehicles")
                self.ships = [ship for ship in self.ships if ship["game_version"]]

            if not self.commodities:
                self.commodities = await self._fetch_uex_data("commodities")
                self.commodities = [commodity for commodity in self.commodities if commodity["is_available"] == 1]

            if not self.systems:
                self.systems = await self._fetch_uex_data("star_systems")
                self.systems = [
                    system for system in self.systems if system["is_available"] == 1
                ]
                for system in self.systems:
                    self.tradeports += await self._fetch_uex_data(
                        f"terminals/id_star_system/{system['id']}/type/commodity/is_available/1/is_visible/1"
                    )
                    self.cities += await self._fetch_uex_data(
                        f"cities/id_star_system/{system['id']}"
                    )
                    self.satellites += await self._fetch_uex_data(
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

                for tradeport in self.tradeports:
                    if (
                        tradeport["id_space_station"]
                        and len(tradeport["nickname"].split("-")) == 2
                        and tradeport["nickname"].split("-")[0] in planet_codes
                        and re.match(r"^L\d+$", tradeport["nickname"].split("-")[1])
                    ):
                        tradeport["id_planet"] = ""

        def _load_data(callback=None):
            async def _actual_loading(callback=None):
                await _load_from_cache()
                await _load_missing_data()
                await self._save_to_cachefile()

                if callback:
                    await callback()

            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            new_loop.run_until_complete(_actual_loading(callback))
            new_loop.close()

        threading.Thread(target=_load_data, args=(callback,)).start()

    async def _save_to_cachefile(self) -> None:
        if (
            self.uexcorp_cache
            and self.uexcorp_cache_duration > 0
            and self.ships
            and self.commodities
            and self.systems
            and self.tradeports
            and self.planets
            and self.satellites
            and self.cities
        ):
            data = {
                "timestamp": self._get_timestamp(),
                "skill_version": self.skill_version,
                "ships": self.ships,
                "commodities": self.commodities,
                "systems": self.systems,
                "tradeports": self.tradeports,
                "planets": self.planets,
                "satellites": self.satellites,
                "cities": self.cities,
            }
            with open(self.cachefile, "w", encoding="UTF-8") as f:
                json.dump(data, f, indent=4)

    async def _load_commodity_prices(self) -> None:
        """
        Load commodity prices from UEX corp API.

        Returns:
            None
        """

        self.cache["readable_objects"] = {}

        # currently the prices are saved in api v1 style to minimize rework time for now
        for i in range(0, len(self.tradeports), 10):
            tradeports_batch = self.tradeports[i : i + 10]
            tradeport_ids = [tradeport["id"] for tradeport in tradeports_batch]

            commodity_prices = await self._fetch_uex_data(
                "commodities_prices/id_terminal/" + ",".join(map(str, tradeport_ids))
            )

            for tradeport in tradeports_batch:
                tradeport["prices"] = {}

                for commodity_price in commodity_prices:
                    if commodity_price["id_terminal"] == tradeport["id"]:
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

                            tradeport["prices"][commodity["id"]] = price

    async def _start_loading_data(self) -> None:
        """
        Prepares the wingman for execution by initializing necessary variables and loading data.

        This method retrieves configuration values, sets up API URL and timeout, and loads data
        such as ship names, commodity names, system names, tradeport names, city names,
        satellite names and planet names.
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

        self.satellites = [
            satellite
            for satellite in self.satellites
            if satellite["is_available"] == 1
        ]

        # remove urls from ships
        for ship in self.ships:
            ship.pop("url_store", None)
            ship.pop("url_brochure", None)
            ship.pop("url_hotsite", None)
            ship.pop("url_video", None)
            ship.pop("url_photos", None)

        # remove screenshot from tradeports
        for tradeport in self.tradeports:
            tradeport.pop("screenshot", None)
            tradeport.pop("screenshot_thumbnail", None)
            tradeport.pop("screenshot_author", None)

        # add hull trading option to trade ports
        for tradeport in self.tradeports:
            tradeport["hull_trading"] = bool(tradeport["has_loading_dock"])

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

        self.tradeport_names = [
            self._format_tradeport_name(tradeport) for tradeport in self.tradeports
        ]
        self.tradeport_dict = {
            self._format_tradeport_name(tradeport).lower(): tradeport
            for tradeport in self.tradeports
        }
        self.tradeport_code_dict = {
            tradeport["id"]: tradeport for tradeport in self.tradeports
        }
        for tradeport in self.tradeports:
            if tradeport["id_star_system"]:
                self.tradeports_by_system[tradeport["id_star_system"]].append(tradeport)
            if tradeport["id_planet"]:
                self.tradeports_by_planet[tradeport["id_planet"]].append(tradeport)
            if tradeport["id_moon"]:
                self.tradeports_by_satellite[tradeport["id_moon"]].append(
                    tradeport
                )
            if tradeport["id_city"]:
                self.tradeports_by_city[tradeport["id_city"]].append(tradeport)

        self.city_names = [self._format_city_name(city) for city in self.cities]
        self.city_dict = {
            self._format_city_name(city).lower(): city for city in self.cities
        }
        self.city_code_dict = {city["id"]: city for city in self.cities}
        for city in self.cities:
            self.cities_by_planet[city["id_planet"]].append(city)

        self.satellite_names = [
            self._format_satellite_name(satellite) for satellite in self.satellites
        ]
        self.satellite_dict = {
            self._format_satellite_name(satellite).lower(): satellite
            for satellite in self.satellites
        }
        self.satellite_code_dict = {
            satellite["id"]: satellite for satellite in self.satellites
        }
        for satellite in self.satellites:
            self.satellites_by_planet[satellite["id_planet"]].append(satellite)

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
            + self.tradeport_names
            + self.city_names
            + self.satellite_names
            + self.planet_names
        )

        self.skill_loaded = True
        if self.skill_loaded_asked:
            self.skill_loaded_asked = False
            await self._print("UEXcorp skill data loading complete.", False, False)

    def _add_context(self, content: str):
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

        while request_count == 1 or (request_count <= (self.uexcorp_api_timeout + 1) and timeout_error):
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

    def _format_ship_name(self, ship: dict[str, any]) -> str:
        """
        Formats the name of a ship.
        This represents a list of names that can be used by the player.
        So if you like to use manufacturer names + ship names, do it here.

        Args:
            ship (dict[str, any]): The ship dictionary containing the ship details.

        Returns:
            str: The formatted ship name.
        """
        return ship["name_full"]

    def _format_tradeport_name(self, tradeport: dict[str, any]) -> str:
        """
        Formats the name of a tradeport.

        Args:
            tradeport (dict[str, any]): The tradeport dictionary containing the name.

        Returns:
            str: The formatted tradeport name.
        """
        return tradeport["nickname"]

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

    def _format_satellite_name(self, satellite: dict[str, any]) -> str:
        """
        Formats the name of a satellite.

        Args:
            satellite (dict[str, any]): The satellite dictionary.

        Returns:
            str: The formatted satellite name.
        """
        return satellite["name"]

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
                            "required": [],
                            "optional": (
                                [
                                    "ship_name",
                                    "position_start_name",
                                    "money_to_spend",
                                    "free_cargo_space",
                                    "position_end_name",
                                    "commodity_name",
                                    "illegal_commodities_allowed",
                                    "maximal_number_of_routes",
                                ]
                            ),
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
                "get_commodity_prices_and_tradeports",
                {
                    "type": "function",
                    "function": {
                        "name": "get_commodity_prices_and_tradeports",
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
            "get_commodity_prices_and_tradeports": "get_commodity_information",
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
        completion = await self.gpt_call(messages)
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
        self._add_context(f"\n\nInstead of '{search}', you should use '{answer}'.")
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
            output_commodity = self._get_converted_commodity_for_output(commodity)
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
            output_ship = self._get_converted_ship_for_output(ship)
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
            output[self._format_ship_name(ship)] = self._get_converted_ship_for_output(
                ship
            )

        output = (
            "Point out differences between these ships but keep it short, like 4-5 sentences, and dont mention something both cant do:\n"
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

        # get a clone of the data
        tradeport = self._get_tradeport_by_name(location_name)
        if tradeport is not None:
            output = self._get_converted_tradeport_for_output(tradeport)
            self._log(output, True)
            return json.dumps(output)
        city = self._get_city_by_name(location_name)
        if city is not None:
            output = self._get_converted_city_for_output(city)
            self._log(output, True)
            return json.dumps(output)
        satellite = self._get_satellite_by_name(location_name)
        if satellite is not None:
            output = self._get_converted_satellite_for_output(satellite)
            self._log(output, True)
            return json.dumps(output)
        planet = self._get_planet_by_name(location_name)
        if planet is not None:
            output = self._get_converted_planet_for_output(planet)
            self._log(output, True)
            return json.dumps(output)
        system = self._get_system_by_name(location_name)
        if system is not None:
            output = self._get_converted_system_for_output(system)
            self._log(output, True)
            return json.dumps(output)

    def _get_converted_tradeport_for_output(
        self, tradeport: dict[str, any]
    ) -> dict[str, any]:
        """
        Converts a tradeport dictionary to a dictionary that can be used as output.

        Args:
            tradeport (dict[str, any]): The tradeport dictionary to be converted.

        Returns:
            dict[str, any]: The converted tradeport dictionary.
        """
        checksum = f"tradeport--{tradeport['id']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        output = {
            "type": "Tradeport",
            "name": self._format_tradeport_name(tradeport),
            "star_system": self._get_system_name_by_code(tradeport["id_star_system"]),
            "planet": self._get_planet_name_by_code(tradeport["id_planet"]),
            "city": self._get_city_name_by_code(tradeport["id_city"]),
            "satellite": self._get_satellite_name_by_code(tradeport["id_moon"]),
        }
        output["hull_trading"] = (
            "Trading with large ships, that need a loading area, is possible."
            if tradeport["hull_trading"]
            else "Trading with large ships, that need a loading area, is not possible."
        )

        buyable_commodities = [
            f"{data['name']} for {data['price_buy']} aUEC per SCU"
            for commodity_code, data in tradeport["prices"].items()
            if data["operation"] == "buy"
        ]
        sellable_commodities = [
            f"{data['name']} for {data['price_sell']} aUEC per SCU"
            for commodity_code, data in tradeport["prices"].items()
            if data["operation"] == "sell"
        ]

        if len(buyable_commodities):
            output["buyable_commodities"] = ", ".join(buyable_commodities)
        if len(sellable_commodities):
            output["sellable_commodities"] = ", ".join(sellable_commodities)

        for key in ["system", "planet", "city", "satellite"]:
            if output.get(key) is None:
                output.pop(key, None)

        self.cache["readable_objects"][checksum] = output
        return output

    def _get_converted_city_for_output(self, city: dict[str, any]) -> dict[str, any]:
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
            "moon": self._get_satellite_name_by_code(city["id_moon"]),
            "is_armistice": "Yes" if city["is_armistice"] else "No",
            "has_freight_elevator": "Yes" if city["has_freight_elevator"] else "No",
            "has_docking_ports": "Yes" if city["has_docking_port"] else "No",
            "has_clinic": "Yes" if city["has_clinic"] else "No",
            "has_food": "Yes" if city["has_food"] else "No",
            "has_refuel_option": "Yes" if city["has_refuel"] else "No",
            "has_repair_option": "Yes" if city["has_repair"] else "No",
            "has_refinery": "Yes" if city["has_refinery"] else "No",
        }

        tradeports = self._get_tradeports_by_position_name(city["name"])
        if tradeports:
            output["options_to_trade"] = ", ".join(
                [self._format_tradeport_name(tradeport) for tradeport in tradeports]
            )

        for key in ["star_system", "planet", "moon"]:
            if output.get(key) is None:
                output.pop(key, None)

        self.cache["readable_objects"][checksum] = output
        return output

    def _get_converted_satellite_for_output(
        self, satellite: dict[str, any]
    ) -> dict[str, any]:
        """
        Converts a satellite dictionary to a dictionary that can be used as output.

        Args:
            satellite (dict[str, any]): The satellite dictionary to be converted.

        Returns:
            dict[str, any]: The converted satellite dictionary.
        """
        checksum = f"satellite--{satellite['id']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        output = {
            "type": "Moon",
            "name": self._format_satellite_name(satellite),
            "star_system": self._get_system_name_by_code(satellite["id_star_system"]),
            "orbits_planet": self._get_planet_name_by_code(satellite["id_planet"]),
        }

        tradeports = self._get_tradeports_by_position_name(self._format_satellite_name(satellite))
        if tradeports:
            output["options_to_trade"] = ", ".join(
                [self._format_tradeport_name(tradeport) for tradeport in tradeports]
            )

        for key in ["star_system", "orbits_planet"]:
            if output.get(key) is None:
                output.pop(key, None)

        self.cache["readable_objects"][checksum] = output
        return output

    def _get_converted_planet_for_output(
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

        tradeports = self._get_tradeports_by_position_name(planet["name"])
        if tradeports:
            output["options_to_trade"] = ", ".join(
                [self._format_tradeport_name(tradeport) for tradeport in tradeports]
            )

        satellites = self._get_satellites_by_planetcode(planet["code"])
        if satellites:
            output["satellites"] = ", ".join(
                [self._format_satellite_name(satellite) for satellite in satellites]
            )

        cities = self._get_cities_by_planetcode(planet["code"])
        if cities:
            output["cities"] = ", ".join(
                [self._format_city_name(city) for city in cities]
            )

        for key in ["star_system"]:
            if output.get(key) is None:
                output.pop(key, None)

        self.cache["readable_objects"][checksum] = output
        return output

    def _get_converted_system_for_output(
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

        tradeports = self._get_tradeports_by_position_name(system["name"])
        if tradeports:
            output["options_to_trade"] = f"{len(tradeports)} different options to trade."
            tradeport_without_planets = []
            gateways = []
            for tradeport in tradeports:
                if not tradeport["id_planet"]:
                    if tradeport["name"].find("Gateway") != -1:
                        gateways.append(tradeport)
                    else:
                        tradeport_without_planets.append(tradeport)
            if tradeport_without_planets:
                output["space_stations"] = ", ".join(
                    [self._format_tradeport_name(tradeport) for tradeport in tradeport_without_planets]
                )
            if gateways:
                output["gateways"] = ", ".join(
                    [self._format_tradeport_name(tradeport) for tradeport in gateways]
                )

        planets = self._get_planets_by_systemcode(system["code"])
        if planets:
            output["planets"] = ", ".join(
                [self._format_planet_name(planet) for planet in planets]
            )

        self.cache["readable_objects"][checksum] = output
        return output

    def _get_converted_ship_for_output(self, ship: dict[str, any]) -> dict[str, any]:
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
            "added_on_version": "Unknown" if ship["is_concept"] else ship["game_version"],
            "field_of_activity": self._get_ship_field_of_activity(ship),
        }

        buy_rent_options = self._get_converted_rent_and_buy_option_for_output(ship)
        if "buy_at" in buy_rent_options:
            output["buy_at"] = buy_rent_options["buy_at"]

        if "rent_at" in buy_rent_options:
            output["rent_at"] = buy_rent_options["rent_at"]

        if ship["hull_trading"] is True:
            output["trading_info"] = (
                "This ship can only trade on suitable space stations with cargo loading option."
            )

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

    def _get_converted_rent_and_buy_option_for_output(
        self, ship: dict[str, any]
    ) -> dict[str, any]:
        """
        Converts the rent and buy options of a ship to a dictionary that can be used as output.

        Args:
            ship (dict[str, any]): The ship dictionary to get the rent and buy options for.

        Returns:
            dict[str, any]: The converted rent and buy options dictionary.
        """

        # TODO: implement this with API v2
        return {}

    def _get_converted_commodity_for_output(
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

        for tradeport in self.tradeports:
            if "prices" not in tradeport:
                continue
            if commodity["id"] in tradeport["prices"]:
                if tradeport["prices"][commodity["id"]]["operation"] == "buy":
                    price_buy = tradeport["prices"][commodity["id"]]["price_buy"]
                    if price_buy_best is None or price_buy < price_buy_best:
                        price_buy_best = price_buy
                    output["buy_at"][
                        self._format_tradeport_name(tradeport)
                    ] = f"{price_buy} aUEC"
                else:
                    price_sell = tradeport["prices"][commodity["id"]]["price_sell"]
                    if price_sell_best is None or price_sell > price_sell_best:
                        price_sell_best = price_sell
                    output["sell_at"][
                        self._format_tradeport_name(tradeport)
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
            "position_name": (position_name, self.location_names_set),
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

        tradeports = (
            self.tradeports
            if position_name is None
            else self._get_tradeports_by_position_name(position_name)
        )
        commodity = self._get_commodity_by_name(commodity_name)
        ship = self._get_ship_by_name(ship_name)
        amount = max(1, int(commodity_amount or 1))
        maximal_number_of_locations = max(1, int(maximal_number_of_locations or 3))

        selloptions = collections.defaultdict(list)
        for tradeport in tradeports:
            sellprice = self._get_data_location_sellprice(
                tradeport, commodity, ship, amount
            )
            if sellprice is not None:
                selloptions[sellprice].append(tradeport)

        selloptions = dict(sorted(selloptions.items(), reverse=True))
        selloptions = dict(
            itertools.islice(selloptions.items(), maximal_number_of_locations)
        )

        messages = [
            f"Here are the best {len(selloptions)} locations to sell {amount} SCU {commodity_name}:"
        ]

        for sellprice, tradeports in selloptions.items():
            messages.append(f"{sellprice} aUEC:")
            messages.extend(
                self._get_tradeport_route_description(tradeport)
                for tradeport in tradeports
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
            "location_name": (position_name, self.location_names_set),
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

        tradeports = (
            self.tradeports
            if position_name is None
            else self._get_tradeports_by_position_name(position_name)
        )
        commodity = self._get_commodity_by_name(commodity_name)
        ship = self._get_ship_by_name(ship_name)
        amount = max(1, int(commodity_amount or 1))
        maximal_number_of_locations = max(1, int(maximal_number_of_locations or 3))

        buyoptions = collections.defaultdict(list)
        for tradeport in tradeports:
            buyprice = self._get_data_location_buyprice(
                tradeport, commodity, ship, amount
            )
            if buyprice is not None:
                buyoptions[buyprice].append(tradeport)

        buyoptions = dict(sorted(buyoptions.items(), reverse=False))
        buyoptions = dict(
            itertools.islice(buyoptions.items(), maximal_number_of_locations)
        )

        messages = [
            f"Here are the best {len(buyoptions)} locations to buy {amount} SCU {commodity_name}:"
        ]
        for buyprice, tradeports in buyoptions.items():
            messages.append(f"{buyprice} aUEC:")
            messages.extend(
                self._get_tradeport_route_description(tradeport)
                for tradeport in tradeports
            )
            messages.append("\n")

        self._log("\n".join(messages), True)
        return "\n".join(messages)

    def _get_data_location_sellprice(self, tradeport, commodity, ship=None, amount=1):
        if (
            ship is not None
            and ship["hull_trading"] is True
            and tradeport["hull_trading"] is False
        ):
            return None

        if "prices" not in tradeport:
            return None

        commodity_code = commodity["id"]
        for code, price in tradeport["prices"].items():
            if code == commodity_code and price["operation"] == "sell":
                return price["price_sell"] * amount
        return None

    def _get_data_location_buyprice(self, tradeport, commodity, ship=None, amount=1):
        if (
            ship is not None
            and ship["hull_trading"] is True
            and tradeport["hull_trading"] is False
        ):
            return None

        if "prices" not in tradeport:
            return None

        commodity_code = commodity["id"]
        for code, price in tradeport["prices"].items():
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
            "position_start_name": (position_start_name, self.location_names_set),
            "position_end_name": (position_end_name, self.location_names_set),
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
        start_tradeports = (
            self._get_tradeports_by_position_name(position_start_name)
            if position_start_name
            else self.tradeports
        )
        end_tradeports = (
            self._get_tradeports_by_position_name(position_end_name)
            if position_end_name
            else self.tradeports
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
            for start_tradeport in start_tradeports:
                if (
                    "prices" not in start_tradeport
                    or commodity["id"] not in start_tradeport["prices"]
                    or start_tradeport["prices"][commodity["id"]]["operation"]
                    != "buy"
                ):
                    continue
                for end_tradeport in end_tradeports:
                    if (
                        "prices" not in end_tradeport
                        or commodity["id"] not in end_tradeport["prices"]
                        or end_tradeport["prices"][commodity["id"]]["operation"]
                        != "sell"
                    ):
                        continue

                    if (
                        ship
                        and ship["hull_trading"] is True
                        and (
                            "hull_trading" not in start_tradeport
                            or start_tradeport["hull_trading"] is not True
                            or "hull_trading" not in end_tradeport
                            or end_tradeport["hull_trading"] is not True
                        )
                    ):
                        continue

                    trading_route_new = self._get_trading_route(
                        ship,
                        start_tradeport,
                        end_tradeport,
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
                for tradeport in trading_route["end"]:
                    destinationselection.append(
                        f"{self._get_tradeport_route_description(tradeport)}"
                    )
                trading_route["end"] = " OR ".join(destinationselection)
                startselection = []
                for tradeport in trading_route["start"]:
                    startselection.append(
                        f"{self._get_tradeport_route_description(tradeport)}"
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
        start_tradeports = [position_start]
        if ship["hull_trading"] is True:
            start_tradeports = [
                tradeport
                for tradeport in start_tradeports
                if "hull_trading" in tradeport and tradeport["hull_trading"] is True
            ]
        if len(start_tradeports) < 1:
            if ship["hull_trading"] is True:
                return "No valid start position given. Make sure to provide a start point compatible with your ship."
            return "No valid start position given. Try a different position or just name a planet or star system."

        end_tradeports = [position_end]
        if ship["hull_trading"] is True:
            end_tradeports = [
                tradeport
                for tradeport in end_tradeports
                if "hull_trading" in tradeport and tradeport["hull_trading"] is True
            ]
        if len(end_tradeports) < 1:
            return "No valid end position given."

        if (
            len(end_tradeports) == 1
            and len(start_tradeports) == 1
            and end_tradeports[0]["id"] == start_tradeports[0]["id"]
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
                    for tradeport in start_tradeports:
                        if self._format_tradeport_name(tradeport) == blacklist_item["tradeport"]:
                            if (
                                "commodity" not in blacklist_item
                                or not blacklist_item["commodity"]
                            ):
                                # remove tradeport, if no commodity given
                                start_tradeports.remove(tradeport)
                                break
                            else:
                                commodity = self._get_commodity_by_name(
                                    blacklist_item["commodity"]
                                )
                                for commodity_code, data in tradeport["prices"].items():
                                    if commodity["id"] == commodity_code:
                                        # remove commodity code from tradeport
                                        tradeport["prices"].pop(commodity_code)
                                        break
                    for tradeport in end_tradeports:
                        if self._format_tradeport_name(tradeport) == blacklist_item["tradeport"]:
                            if (
                                "commodity" not in blacklist_item
                                or not blacklist_item["commodity"]
                            ):
                                # remove tradeport, if no commodity given
                                end_tradeports.remove(tradeport)
                                break
                            else:
                                commodity = self._get_commodity_by_name(
                                    blacklist_item["commodity"]
                                )
                                for commodity_code, data in tradeport["prices"].items():
                                    if commodity["id"] == commodity_code:
                                        # remove commodity code from tradeport
                                        tradeport["prices"].pop(commodity_code)
                                        break

        if len(start_tradeports) < 1 or len(end_tradeports) < 1:
            return "Exluded by blacklist."

        for tradeport_start in start_tradeports:
            commodities = []
            if "prices" not in tradeport_start:
                continue

            for commodity_code, price in tradeport_start["prices"].items():
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
                                        # remove commodity code from tradeport
                                        in_blacklist = True
                                        break

                        if not in_blacklist:
                            commodities.append(price)

            if len(commodities) < 1:
                continue

            for tradeport_end in end_tradeports:
                if "prices" not in tradeport_end:
                    continue

                for commodity_code, price in tradeport_end["prices"].items():
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
                                    # remove commodity code from tradeport
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
                                    best_route["start"] = [tradeport_start]
                                    best_route["end"] = [tradeport_end]
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
                                        if tradeport_start not in best_route["start"]:
                                            best_route["start"].append(tradeport_start)
                                        if tradeport_end not in best_route["end"]:
                                            best_route["end"].append(tradeport_end)

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

    def _get_tradeport_by_name(self, name: str) -> dict[str, any] | None:
        """Finds the tradeport with the specified name and returns the tradeport or None.

        Args:
            name (str): The name of the tradeport to search for.

        Returns:
            Optional[object]: The tradeport object if found, otherwise None.
        """
        return self.tradeport_dict.get(name.lower()) if name else None

    def _get_tradeport_by_code(self, code: str) -> dict[str, any] | None:
        """Finds the tradeport with the specified code and returns the tradeport or None.

        Args:
            code (str): The code of the tradeport to search for.

        Returns:
            Optional[object]: The tradeport object if found, otherwise None.
        """
        return self.tradeport_code_dict.get(code) if code else None

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

    def _get_satellite_by_name(self, name: str) -> dict[str, any] | None:
        """Finds the satellite with the specified name and returns the satellite or None.

        Args:
            name (str): The name of the satellite to search for.

        Returns:
            Optional[object]: The satellite object if found, otherwise None.
        """
        return self.satellite_dict.get(name.lower()) if name else None

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

    def _get_tradeport_route_description(self, tradeport: dict[str, any]) -> str:
        """Returns the breadcrums of a tradeport.

        Args:
            tradeport (dict[str, any]): The tradeport information.

        Returns:
            str: The description of the tradeport route.
        """
        tradeport = self._get_converted_tradeport_for_output(tradeport)
        keys = [
            ("star_system", "Star-System"),
            ("planet", "Planet"),
            ("satellite", "Satellite"),
            ("city", "City"),
            ("name", "Trade Point"),
        ]
        route = [f"{name}: {tradeport[key]}" for key, name in keys if key in tradeport]
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

    def _get_satellite_name_by_code(self, code: str) -> str:
        """Returns the name of the satellite with the specified code.

        Args:
            code (str): The code of the satellite.

        Returns:
            str: The name of the satellite with the specified code.
        """
        return (
            self._format_satellite_name(self.satellite_code_dict.get(code))
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

    def _get_tradeports_by_position_name(
        self, name: str
    ) -> list[dict[str, any]]:
        """Returns all tradeports with the specified position name.

        Args:
            name (str): The position name to search for.

        Returns:
            list[dict[str, any]]: A list of tradeports matching the position name.
        """
        if not name:
            return []

        tradeports = []

        tradeport_temp = self._get_tradeport_by_name(name)
        if tradeport_temp:
            tradeports.append(tradeport_temp)

        tradeports.extend(self._get_tradeports_by_systemname(name))
        tradeports.extend(self._get_tradeports_by_planetname(name))
        tradeports.extend(self._get_tradeports_by_satellitename(name))
        tradeports.extend(self._get_tradeports_by_cityname(name))
        return tradeports

    def _get_satellites_by_planetcode(self, code: str) -> list[dict[str, any]]:
        """Returns the satellite with the specified planet code.

        Args:
            code (str): The code of the planet.

        Returns:
            Optional[object]: The satellite object if found, otherwise None.
        """
        return self.satellites_by_planet.get(code, []) if code else []

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

    def _get_tradeports_by_systemcode(self, code: str) -> list[dict[str, any]]:
        """Returns all tradeports with the specified system code.

        Args:
            code (str): The code of the system.

        Returns:
            list[dict[str, any]]: A list of tradeports matching the system code.
        """
        return self.tradeports_by_system.get(code, []) if code else []

    def _get_tradeports_by_planetcode(self, code: str) -> list[dict[str, any]]:
        """Returns all tradeports with the specified planet code.

        Args:
            code (str): The code of the planet.

        Returns:
            list[dict[str, any]]: A list of tradeports matching the planet code.
        """
        return self.tradeports_by_planet.get(code, []) if code else []

    def _get_tradeports_by_satellitecode(self, code: str) -> list[dict[str, any]]:
        """Returns all tradeports with the specified satellite code.

        Args:
            code (str): The code of the satellite.

        Returns:
            list[dict[str, any]]: A list of tradeports matching the satellite code.
        """
        return self.tradeports_by_satellite.get(code, []) if code else []

    def _get_tradeports_by_citycode(self, code: str) -> list[dict[str, any]]:
        """Returns all tradeports with the specified city code.

        Args:
            code (str): The code of the city.

        Returns:
            list[dict[str, any]]: A list of tradeports matching the city code.
        """
        return self.tradeports_by_city.get(code, []) if code else []

    def _get_tradeports_by_planetname(self, name: str) -> list[dict[str, any]]:
        """Returns all tradeports with the specified planet name.

        Args:
            name (str): The name of the planet.

        Returns:
            list[dict[str, any]]: A list of tradeports matching the planet name.
        """
        planet = self._get_planet_by_name(name)
        return self._get_tradeports_by_planetcode(planet["id"]) if planet else []

    def _get_tradeports_by_satellitename(self, name: str) -> list[dict[str, any]]:
        """Returns all tradeports with the specified satellite name.

        Args:
            name (str): The name of the satellite.

        Returns:
            list[dict[str, any]]: A list of tradeports matching the satellite name.
        """
        satellite = self._get_satellite_by_name(name)
        return (
            self._get_tradeports_by_satellitecode(satellite["id"])
            if satellite
            else []
        )

    def _get_tradeports_by_cityname(self, name: str) -> list[dict[str, any]]:
        """Returns all tradeports with the specified city name.

        Args:
            name (str): The name of the city.

        Returns:
            list[dict[str, any]]: A list of tradeports matching the city name.
        """
        city = self._get_city_by_name(name)
        return self._get_tradeports_by_citycode(city["id"]) if city else []

    def _get_tradeports_by_systemname(self, name: str) -> list[dict[str, any]]:
        """Returns all tradeports with the specified system name.

        Args:
            name (str): The name of the system.

        Returns:
            list[dict[str, any]]: A list of tradeports matching the system name.
        """
        system = self._get_system_by_name(name)
        return self._get_tradeports_by_systemcode(system["id"]) if system else []
    
