import copy
import difflib
import heapq
import itertools
import json
import logging
import math
from os import path
import collections
import re
import time
from typing import Optional
from datetime import datetime
import requests
from api.enums import LogType, WingmanInitializationErrorType
from api.interface import WingmanConfig, WingmanInitializationError
from services.file import get_writable_dir
from skills.skill_base import Skill


class UEXCorp(Skill):

    # TODO: retrieve this from an API
    MANUFACTURERS = {
        "AEGS": "Aegis Dynamics",
        "ANVL": "Anvil Aerospace",
        "AOPO": "Aopoa",
        "ARGO": "ARGO Astronautics",
        "BANU": "Banu",
        "CNOU": "Consolidated Outland",
        "CRUS": "Crusader Industries",
        "DRAK": "Drake Interplanetary",
        "ESPR": "Esperia",
        "GATA": "Gatac",
        "GRIN": "Greycat Industrial",
        "KRIG": "Kruger Intergalactic",
        "MIRA": "Mirai",
        "MISC": "Musashi Industrial & Starflight Concern",
        "ORIG": "Origin Jumpworks",
        "RSIN": "Roberts Space Industries",
        "TMBL": "Tumbril Land Systems",
        "VNDL": "Vanduul",
    }

    CUSTOMCONFIG = {
        "uexcorp_api_url": {"type": "str", "values": []},
        "uexcorp_api_timeout": {"type": "int", "values": []},
        "uexcorp_debug": {"type": "auto", "values": ["true", "false", "Extensive"]},
        "uexcorp_cache": {"type": "bool", "values": []},
        "uexcorp_cache_duration": {"type": "int", "values": []},
        "uexcorp_additional_context": {"type": "bool", "values": []},
        "uexcorp_summarize_routes_by_commodity": {"type": "bool", "values": []},
        "uexcorp_tradestart_mandatory": {"type": "bool", "values": []},
        "uexcorp_trade_blacklist": {"type": "json", "values": []},
        "uexcorp_default_trade_route_count": {"type": "int", "values": []},
    }

    def __init__(self, config: WingmanConfig) -> None:
        super().__init__(config=config)

        self.data_path = get_writable_dir(path.join("wingmen_data", self.name))
        self.logfile = path.join(self.data_path, "error.log")
        self.cachefile = path.join(self.data_path, "cache.json")
        logging.basicConfig(filename=self.logfile, level=logging.ERROR)

        self.uexcorp_version = "v10"

        # init of config options
        self.uexcorp_api_url = None
        self.uexcorp_api_key = None
        self.uexcorp_api_timeout = None
        self.uexcorp_debug = None
        self.uexcorp_cache = None
        self.uexcorp_cache_duration = None
        self.uexcorp_additional_context = None
        self.uexcorp_summarize_routes_by_commodity = None
        self.uexcorp_tradestart_mandatory = None
        self.uexcorp_trade_blacklist = []
        self.uexcorp_default_trade_route_count = None

        # init of data lists
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

    def _print_debug(self, message: str | dict, is_extensive: bool = False) -> None:
        """
        Prints a debug message if debug mode is enabled.

        Args:
            message (str | dict): The message to be printed.
            is_extensive (bool, optional): Whether the message is extensive. Defaults to False.

        Returns:
            None
        """
        if not self.uexcorp_debug or (
            not self.cache_enabled and self.uexcorp_debug != "Extensive"
        ):
            return

        if self.uexcorp_debug == "Extensive" or not is_extensive:
            tag = LogType.INFO if not is_extensive else LogType.WARNING
            self.printr.print(message, color=tag)

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
                self._print_debug(
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
            self._print_debug(
                f"Set function arg '{arg_name}' to cache. Previous value: {old_value} >> New value: {arg_value}",
                True,
            )
            function_args[arg_name] = arg_value
        elif arg_name in function_args:
            self._print_debug(
                f"Removing function arg '{arg_name}' from cache. Previous value: {old_value}",
                True,
            )
            function_args.pop(arg_name, None)

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        self.uexcorp_api_key = await self.retrieve_secret(
            "uexcorp", errors, "You can get one here: https://uexcorp.space/api.html"
        )

        for key, settings in self.CUSTOMCONFIG.items():
            typesettings = settings["type"]
            valueoptions = settings["values"]

            value = self.retrieve_custom_property_value(key, errors)
            if valueoptions and not value in valueoptions:
                errors.append(
                    WingmanInitializationError(
                        wingman_name=self.name,
                        message=f"Invalid custom property '{key}' in config. Possible values: {', '.join(valueoptions)}",
                        error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                    )
                )
            elif typesettings == "int":
                try:
                    int(value)
                except ValueError:
                    errors.append(
                        WingmanInitializationError(
                            wingman_name=self.name,
                            message=f"Invalid custom property '{key}' in config. Value must be convertable to a number.",
                            error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                        )
                    )
            elif typesettings == "bool":
                if value not in ["true", "false"]:
                    errors.append(
                        WingmanInitializationError(
                            wingman_name=self.name,
                            message=f"Invalid custom property '{key}' in config. Value must be 'true' or 'false'.",
                            error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                        )
                    )
            elif typesettings == "json":
                try:
                    json.loads(value)
                except json.decoder.JSONDecodeError:
                    errors.append(
                        WingmanInitializationError(
                            wingman_name=self.name,
                            message=f"Invalid custom property '{key}' in config. Value must be a valid JSON string.",
                            error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                        )
                    )

        try:
            self._prepare_data()
        except Exception as e:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.name,
                    message=f"Failed to load data: {e}",
                    error_type=WingmanInitializationErrorType.UNKNOWN,
                )
            )

        return errors

    def _load_data(self, reload: bool = False) -> None:
        """
        Load data for UEX corp wingman.

        Args:
            reload (bool, optional): Whether to reload the data from the source. Defaults to False.
        """

        boo_tradeports_reloaded = False

        save_cache = False
        # if cache is enabled and file is not too old, load from cache
        if self.uexcorp_cache and not reload:
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
                and data.get("wingman_version") == self.uexcorp_version
            ):
                if data.get("ships"):
                    self.ships = data["ships"]
                if data.get("commodities"):
                    self.commodities = data["commodities"]
                if data.get("systems"):
                    self.systems = data["systems"]
                if data.get("tradeports"):
                    self.tradeports = data["tradeports"]
                    boo_tradeports_reloaded = True
                if data.get("planets"):
                    self.planets = data["planets"]
                if data.get("satellites"):
                    self.satellites = data["satellites"]
                if data.get("cities"):
                    self.cities = data["cities"]
            else:
                save_cache = True

        if not self.ships:
            self.ships = self._fetch_uex_data("ships")
            self.ships = [ship for ship in self.ships if ship["implemented"] == "1"]

        if not self.commodities:
            self.commodities = self._fetch_uex_data("commodities")

        if not self.systems:
            self.systems = self._fetch_uex_data("star_systems")
            self.systems = [
                system for system in self.systems if system["available"] == 1
            ]
            for system in self.systems:
                self.tradeports += self._fetch_uex_data(
                    f"tradeports/system/{system['code']}"
                )
                self.cities += self._fetch_uex_data(f"cities/system/{system['code']}")
                self.satellites += self._fetch_uex_data(
                    f"satellites/system/{system['code']}"
                )
                self.planets += self._fetch_uex_data(f"planets/system/{system['code']}")

            self.tradeports = [
                tradeport
                for tradeport in self.tradeports
                if tradeport["visible"] == "1"
            ]
            boo_tradeports_reloaded = True

            self.planets = [
                planet for planet in self.planets if planet["available"] == 1
            ]

            self.satellites = [
                satellite
                for satellite in self.satellites
                if satellite["available"] == 1
            ]
        else:
            if reload:
                self.tradeports = []
                for system in self.systems:
                    self.tradeports += self._fetch_uex_data(
                        f"tradeports/system/{system['code']}"
                    )

                self.tradeports = [
                    tradeport
                    for tradeport in self.tradeports
                    if tradeport["visible"] == "1"
                ]
                boo_tradeports_reloaded = True
                save_cache = True

        if (
            save_cache
            and self.uexcorp_cache
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
                "wingman_version": self.uexcorp_version,
                "ships": self.ships,
                "commodities": self.commodities,
                "systems": self.systems,
                "tradeports": self.tradeports,
                "planets": self.planets,
                "satellites": self.satellites,
                "cities": self.cities,
            }
            with open(self.cachefile, "w", encoding="UTF-8") as f:
                json.dump(data, f)

        # data manipulation
        # remove planet information from space tradeports
        if boo_tradeports_reloaded is True:
            planet_codes = []
            for planet in self.planets:
                if planet["code"] not in planet_codes:
                    planet_codes.append(planet["code"])

            for tradeport in self.tradeports:
                shorted_name = tradeport["name"].split(" ")[0]
                if (
                    tradeport["space"] == "1"
                    and len(shorted_name.split("-")) == 2
                    and shorted_name.split("-")[0] in planet_codes
                    and re.match(r"^L\d+$", shorted_name.split("-")[1])
                ):
                    tradeport["planet"] = ""
        # remove urls from ships and resolve manufacturer code
        for ship in self.ships:
            ship.pop("store_url", None)
            ship.pop("photos", None)
            ship.pop("brochure_url", None)
            ship.pop("hotsite_url", None)
            ship.pop("video_url", None)
        # remove unavailable cities
        self.cities = [city for city in self.cities if city["available"] == 1]
        # add hull trading option to trade ports
        tradeports_for_hull_trading = [
            "Baijini Point",
            "Everus Harbor",
            "Magnus Gateway",
            "Pyro Gateway",
            "Seraphim Station",
            "Terra Gateway",
            "Port Tressler",
        ]
        for tradeport in self.tradeports:
            tradeport["hull_trading"] = tradeport["name"] in tradeports_for_hull_trading
        # add hull trading option to ships
        ships_for_hull_trading = ["Hull C"]
        for ship in self.ships:
            ship["hull_trading"] = ship["name"] in ships_for_hull_trading

    def _prepare_data(self) -> None:
        """
        Prepares the wingman for execution by initializing necessary variables and loading data.

        This method retrieves configuration values, sets up API URL and timeout, and loads data
        such as ship names, commodity names, system names, tradeport names, city names,
        satellite names and planet names.
        It also adds additional context information for function parameters.

        Returns:
            None
        """

        for key, settings in self.CUSTOMCONFIG.items():
            typesettings = settings["type"]
            # valueoptions = settings["values"]
            value = next(
                (
                    prop.value
                    for prop in self.config.custom_properties
                    if prop.id == key
                ),
                None,
            )

            if typesettings == "auto":
                try:
                    int(value)
                    typesettings = "int"
                except ValueError:
                    if value == "true" or value == "false":
                        typesettings = "bool"
                    else:
                        typesettings = "str"

            if typesettings == "bool":
                value = value == "true"
            elif typesettings == "int":
                value = int(value)
            elif typesettings == "json":
                value = json.loads(value)

            setattr(self, key, value)

        if not self.uexcorp_debug and self.config.debug_mode:
            self.uexcorp_debug = True

        # self.start_execution_benchmark()
        self._load_data()

        self.ship_names = [
            self._format_ship_name(ship)
            for ship in self.ships
            if ship["implemented"] == "1"
        ]
        self.ship_dict = {
            self._format_ship_name(ship).lower(): ship for ship in self.ships
        }
        self.ship_code_dict = {ship["code"].lower(): ship for ship in self.ships}

        self.commodity_names = [
            self._format_commodity_name(commodity) for commodity in self.commodities
        ]
        self.commodity_dict = {
            self._format_commodity_name(commodity).lower(): commodity
            for commodity in self.commodities
        }
        self.commodity_code_dict = {
            commodity["code"].lower(): commodity for commodity in self.commodities
        }

        self.system_names = [
            self._format_system_name(system) for system in self.systems
        ]
        self.system_dict = {
            self._format_system_name(system).lower(): system for system in self.systems
        }
        self.system_code_dict = {
            system["code"].lower(): system for system in self.systems
        }

        self.tradeport_names = [
            self._format_tradeport_name(tradeport) for tradeport in self.tradeports
        ]
        self.tradeport_dict = {
            self._format_tradeport_name(tradeport).lower(): tradeport
            for tradeport in self.tradeports
        }
        self.tradeport_code_dict = {
            tradeport["code"].lower(): tradeport for tradeport in self.tradeports
        }
        for tradeport in self.tradeports:
            if tradeport["system"]:
                self.tradeports_by_system[tradeport["system"].lower()].append(tradeport)
            if tradeport["planet"]:
                self.tradeports_by_planet[tradeport["planet"].lower()].append(tradeport)
            if tradeport["satellite"]:
                self.tradeports_by_satellite[tradeport["satellite"].lower()].append(
                    tradeport
                )
            if tradeport["city"]:
                self.tradeports_by_city[tradeport["city"].lower()].append(tradeport)

        self.city_names = [self._format_city_name(city) for city in self.cities]
        self.city_dict = {
            self._format_city_name(city).lower(): city for city in self.cities
        }
        self.city_code_dict = {city["code"].lower(): city for city in self.cities}
        for city in self.cities:
            self.cities_by_planet[city["planet"].lower()].append(city)

        self.satellite_names = [
            self._format_satellite_name(satellite) for satellite in self.satellites
        ]
        self.satellite_dict = {
            self._format_satellite_name(satellite).lower(): satellite
            for satellite in self.satellites
        }
        self.satellite_code_dict = {
            satellite["code"].lower(): satellite for satellite in self.satellites
        }
        for satellite in self.satellites:
            self.satellites_by_planet[satellite["planet"].lower()].append(satellite)

        self.planet_names = [
            self._format_planet_name(planet) for planet in self.planets
        ]
        self.planet_dict = {
            self._format_planet_name(planet).lower(): planet for planet in self.planets
        }
        self.planet_code_dict = {
            planet["code"].lower(): planet for planet in self.planets
        }
        for planet in self.planets:
            self.planets_by_system[planet["system"].lower()].append(planet)

        self.location_names_set = set(
            self.system_names
            + self.tradeport_names
            + self.city_names
            + self.satellite_names
            + self.planet_names
        )

        if self.uexcorp_additional_context:
            self._add_context(
                'Possible values for function parameter "ship_name". If none is explicitly given by player, use "None": '
                + ", ".join(self.ship_names)
                + "\n\n"
                + 'Possible values for function parameter "commodity_name": '
                + ", ".join(self.commodity_names)
                + "\n\n"
                + 'Possible values for function parameters "position_start_name", "position_end_name", "currentposition_name" and "location_name": '
                + ", ".join(self.location_names_set)
            )

        self._add_context(
            "\nDo not (never) translate any properties when giving them to the player. They must stay in english or untouched."
            + "\nOnly give functions parameters that were previously clearly provided by a request. Never assume any values, not the current ship, not the location, not the available money, nothing! Always send a None-value instead."
            + "\nIf you are not using one of the definied functions, dont give any trading recommendations."
            + "\nIf you execute a function that requires a commodity name, make sure to always provide the name in english, not in german or any other language."
            + "\nNever mention optional function (tool) parameters to the user. Only mention the required parameters, if some are missing."
        )

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
        return {"api_key": key}

    def _fetch_uex_data(
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

        try:
            response = requests.get(
                url,
                params=params,
                timeout=self.uexcorp_api_timeout,
                headers=self._get_header(),
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            self._print_debug(f"Error while retrieving data from {url}: {e}")
            return []

        # if self.config.debug_mode:
        #     self.print_execution_time(reset_timer=True)

        response_json = response.json()
        if "status" not in response_json or response_json["status"] != "ok":
            self._print_debug(f"Error while retrieving data from {url}")
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
        return ship["name"]

    def _format_tradeport_name(self, tradeport: dict[str, any]) -> str:
        """
        Formats the name of a tradeport.

        Args:
            tradeport (dict[str, any]): The tradeport dictionary containing the name.

        Returns:
            str: The formatted tradeport name.
        """
        return tradeport["name"]

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
                                if self.uexcorp_tradestart_mandatory
                                else [
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
        ]

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
                if self.uexcorp_debug:
                    start = time.perf_counter()
                self._print_debug(f"Executing function: {tool_name}")
                function = getattr(self, "_gpt_call_" + functions[tool_name])
                function_response = await function(**parameters)
                if self.uexcorp_debug:
                    self._print_debug(
                        f"...took {(time.perf_counter() - start):.2f}s", True
                    )
        except Exception as e:
            logging.error(e, exc_info=True)
            file_object = open(self.logfile, "a", encoding="UTF-8")
            file_object.write(
                "========================================================================================\n"
            )
            file_object.write(
                f"Above error while executing custom function: _gpt_call_{tool_name}\n"
            )
            file_object.write(f"With parameters: {parameters}\n")
            file_object.write(f"On date: {datetime.now()}\n")
            file_object.write(f"Version: {self.uexcorp_version}\n")
            file_object.write(
                "========================================================================================\n"
            )
            file_object.close()
            self._print_debug(
                f"Error while executing custom function: {tool_name}\nCheck log file for more details."
            )
            function_response = f"Error while executing custom function: {tool_name}"
            function_response += "\nTell user there seems to be an error. And you must say that it should be report to the 'uexcorp wingman developers'."

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

        self._print_debug(f"Searching for closest match to '{search}' in list.", True)

        checksum = f"{hash(frozenset(lst))}-{hash(search)}"
        if checksum in self.cache["search_matches"]:
            match = self.cache["search_matches"][checksum]
            self._print_debug(
                f"Found closest match to '{search}' in cache: '{match}'", True
            )
            return match

        if search in lst:
            self._print_debug(f"Found exact match to '{search}' in list.", True)
            return search

        # make a list of possible matches
        closest_matches = difflib.get_close_matches(search, lst, n=10, cutoff=0.4)
        closest_matches.extend(item for item in lst if search.lower() in item.lower())
        self._print_debug(
            f"Making a list for closest matches for search term '{search}': {', '.join(closest_matches)}",
            True,
        )

        if not closest_matches:
            self._print_debug(
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
                self._print_debug(
                    f"OpenAI did not answer for '{search}'. Returning dumb match '{dumb_match}'",
                    True,
                )
                return dumb_match[0]
            else:
                self._print_debug(
                    f"OpenAI did not answer for '{search}' and dumb match not possible. Returning None.",
                    True,
                )
                return None

        self._print_debug(f"OpenAI answered: '{answer}'", True)

        if answer == "None" or answer not in closest_matches:
            self._print_debug(
                f"No closest match found for '{search}' in list. Returning None.", True
            )
            return None

        self._print_debug(
            f"Found closest match to '{search}' in list: '{answer}'", True
        )
        self._add_context(f"\n\nInstead of '{search}', you should use '{answer}'.")
        self.cache["search_matches"][checksum] = answer
        return answer

    async def get_additional_context(self) -> str | None:
        """Return additional context."""
        additional_context = self.config.additional_context or ""
        additional_context += "\n" + self.dynamic_context
        return additional_context

    async def _gpt_call_show_cached_function_values(self) -> str:
        """
        Prints the cached function's argument values to the console.

        Returns:
            str: A message indicating that the cached function's argument values have been printed to the console.
        """
        if self.uexcorp_debug:
            self._print_debug(self.cache["function_args"])
            return "Please check the console for the cached function's argument values."
        return ""

    async def _gpt_call_reload_current_commodity_prices(self) -> str:
        """
        Reloads the current commodity prices from UEX corp.

        Returns:
            str: A message indicating that the current commodity prices have been reloaded.
        """
        self._load_data(reload=True)
        # clear cached data
        for key in self.cache:
            self.cache[key] = {}

        self._print_debug("Reloaded current commodity prices from UEX corp.", True)
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
        self._print_debug(f"Parameters: Commodity: {commodity_name}", True)

        commodity_name = self._get_function_arg_from_cache(
            "commodity_name", commodity_name
        )

        if commodity_name is None:
            self._print_debug("No commodity given. Ask for a commodity.", True)
            return "No commodity given. Ask for a commodity."

        misunderstood = []
        closest_match = await self._find_closest_match(
            commodity_name, self.commodity_names
        )
        if closest_match is None:
            misunderstood.append(f"Commodity: {commodity_name}")
        else:
            commodity_name = closest_match

        self._print_debug(f"Interpreted Parameters: Commodity: {commodity_name}", True)

        if misunderstood:
            misunderstood_str = ", ".join(misunderstood)
            self._print_debug(
                f"These given parameters do not exist in game. Exactly ask for clarification of these values: {misunderstood_str}",
                True,
            )
            return f"These given parameters do not exist in game. Exactly ask for clarification of these values: {misunderstood_str}"

        commodity = self._get_commodity_by_name(commodity_name)
        if commodity is not None:
            output_commodity = self._get_converted_commodity_for_output(commodity)
            self._print_debug(output_commodity, True)
            return json.dumps(output_commodity)

    async def _gpt_call_get_ship_information(self, ship_name: str = None) -> str:
        """
        Retrieves information about a specific ship.

        Args:
            ship_name (str, optional): The name of the ship. Defaults to None.

        Returns:
            str: The ship information or an error message.

        """
        self._print_debug(f"Parameters: Ship: {ship_name}", True)

        ship_name = self._get_function_arg_from_cache("ship_name", ship_name)

        if ship_name is None:
            self._print_debug("No ship given. Ask for a ship. Dont say sorry.", True)
            return "No ship given. Ask for a ship. Dont say sorry."

        misunderstood = []
        closest_match = await self._find_closest_match(ship_name, self.ship_names)
        if closest_match is None:
            misunderstood.append(f"Ship: {ship_name}")
        else:
            ship_name = closest_match

        self._print_debug(f"Interpreted Parameters: Ship: {ship_name}", True)

        if misunderstood:
            misunderstood_str = ", ".join(misunderstood)
            self._print_debug(
                f"These given parameters do not exist in game. Exactly ask for clarification of these values: {misunderstood_str}",
                True,
            )
            return f"These given parameters do not exist in game. Exactly ask for clarification of these values: {misunderstood_str}"

        ship = self._get_ship_by_name(ship_name)
        if ship is not None:
            output_ship = self._get_converted_ship_for_output(ship)
            self._print_debug(output_ship, True)
            return json.dumps(output_ship)

    async def _gpt_call_get_ship_comparison(self, ship_names: list[str] = None) -> str:
        """
        Retrieves information about multiple ships.

        Args:
            ship_names (list[str], optional): The names of the ships. Defaults to None.

        Returns:
            str: The ship information or an error message.
        """
        self._print_debug(f"Parameters: Ships: {', '.join(ship_names)}", True)

        if ship_names is None or not ship_names:
            self._print_debug("No ship given. Ask for a ship. Dont say sorry.", True)
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

        self._print_debug(
            f"Interpreted Parameters: Ships: {', '.join(ship_names)}", True
        )

        if misunderstood:
            self._print_debug(
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
            "Point out differences between these ships but keep it short, like 4-5 sentences, and dont mention something both cant do, like getting rented:\n"
            + json.dumps(output)
        )
        self._print_debug(output, True)
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
        self._print_debug(f"Parameters: Location: {location_name}", True)

        location_name = self._get_function_arg_from_cache(
            "location_name", location_name
        )

        if location_name is None:
            self._print_debug("No location given. Ask for a location.", True)
            return "No location given. Ask for a location."

        misunderstood = []
        closest_match = await self._find_closest_match(
            location_name, self.location_names_set
        )
        if closest_match is None:
            misunderstood.append(f"Location: {location_name}")
        else:
            location_name = closest_match

        self._print_debug(f"Interpreted Parameters: Location: {location_name}", True)

        if misunderstood:
            misunderstood_str = ", ".join(misunderstood)
            self._print_debug(
                f"These given parameters do not exist in game. Exactly ask for clarification of these values: {misunderstood_str}",
                True,
            )
            return f"These given parameters do not exist in game. Exactly ask for clarification of these values: {misunderstood_str}"

        # get a clone of the data
        tradeport = self._get_tradeport_by_name(location_name)
        if tradeport is not None:
            output = self._get_converted_tradeport_for_output(tradeport)
            self._print_debug(output, True)
            return json.dumps(output)
        city = self._get_city_by_name(location_name)
        if city is not None:
            output = self._get_converted_city_for_output(city)
            self._print_debug(output, True)
            return json.dumps(output)
        satellite = self._get_satellite_by_name(location_name)
        if satellite is not None:
            output = self._get_converted_satellite_for_output(satellite)
            self._print_debug(output, True)
            return json.dumps(output)
        planet = self._get_planet_by_name(location_name)
        if planet is not None:
            output = self._get_converted_planet_for_output(planet)
            self._print_debug(output, True)
            return json.dumps(output)
        system = self._get_system_by_name(location_name)
        if system is not None:
            output = self._get_converted_system_for_output(system)
            self._print_debug(output, True)
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
        checksum = f"tradeport--{tradeport['code']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        tradeport = copy.deepcopy(tradeport)
        deletable_keys = [
            "code",
            "name_short",
            "space",
            "visible",
            "prices",
            "date_modified",
            "date_added",
        ]
        tradeport["type"] = "Tradeport"
        tradeport["system"] = self._get_system_name_by_code(tradeport["system"])
        tradeport["planet"] = self._get_planet_name_by_code(tradeport["planet"])
        tradeport["city"] = self._get_city_name_by_code(tradeport["city"])
        tradeport["satellite"] = self._get_satellite_name_by_code(
            tradeport["satellite"]
        )
        tradeport["hull_trading"] = (
            "Trading with MISC Hull C is possible."
            if tradeport["hull_trading"]
            else "Trading with MISC Hull C is not possible."
        )

        if "prices" in tradeport:
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
        else:
            buyable_commodities = []
            sellable_commodities = []

        if len(buyable_commodities):
            tradeport["buyable_commodities"] = ", ".join(buyable_commodities)
        if len(sellable_commodities):
            tradeport["sellable_commodities"] = ", ".join(sellable_commodities)

        for key in ["system", "planet", "city", "satellite"]:
            if tradeport.get(key) is None:
                deletable_keys.append(key)

        for key in deletable_keys:
            tradeport.pop(key, None)

        self.cache["readable_objects"][checksum] = tradeport
        return tradeport

    def _get_converted_city_for_output(self, city: dict[str, any]) -> dict[str, any]:
        """
        Converts a city dictionary to a dictionary that can be used as output.

        Args:
            city (dict[str, any]): The city dictionary to be converted.

        Returns:
            dict[str, any]: The converted city dictionary.
        """
        checksum = f"city--{city['code']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        city = copy.deepcopy(city)
        deletable_keys = [
            "code",
            "available",
            "date_added",
            "date_modified",
        ]
        city["type"] = "City"
        city["system"] = self._get_system_name_by_code(city["system"])
        city["planet"] = self._get_planet_name_by_code(city["planet"])
        tradeports = self._get_tradeports_by_position_name(city["name"], True)

        if tradeports:
            city["options_to_trade"] = ", ".join(
                [self._format_tradeport_name(tradeport) for tradeport in tradeports]
            )

        for key in deletable_keys:
            city.pop(key, None)

        self.cache["readable_objects"][checksum] = city
        return city

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
        checksum = f"satellite--{satellite['code']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        satellite = copy.deepcopy(satellite)
        deletable_keys = [
            "code",
            "available",
            "date_added",
            "date_modified",
        ]
        satellite["type"] = "Satellite"
        satellite["system"] = self._get_system_name_by_code(satellite["system"])
        satellite["planet"] = self._get_planet_name_by_code(satellite["planet"])
        tradeports = self._get_tradeports_by_position_name(satellite["name"], True)

        if tradeports:
            satellite["options_to_trade"] = ", ".join(
                [self._format_tradeport_name(tradeport) for tradeport in tradeports]
            )

        for key in deletable_keys:
            satellite.pop(key, None)

        self.cache["readable_objects"][checksum] = satellite
        return satellite

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
        checksum = f"planet--{planet['code']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        planet = copy.deepcopy(planet)
        deletable_keys = [
            "code",
            "available",
            "date_added",
            "date_modified",
        ]
        planet["type"] = "Planet"
        planet["system"] = self._get_system_name_by_code(planet["system"])
        tradeports = self._get_tradeports_by_position_name(planet["name"], True)

        if tradeports:
            planet["options_to_trade"] = ", ".join(
                [self._format_tradeport_name(tradeport) for tradeport in tradeports]
            )

        satellites = self._get_satellites_by_planetcode(planet["code"])
        if satellites:
            planet["satellites"] = ", ".join(
                [self._format_satellite_name(satellite) for satellite in satellites]
            )

        cities = self._get_cities_by_planetcode(planet["code"])
        if cities:
            planet["cities"] = ", ".join(
                [self._format_city_name(city) for city in cities]
            )

        for key in deletable_keys:
            planet.pop(key, None)

        self.cache["readable_objects"][checksum] = planet
        return planet

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
        checksum = f"system--{system['code']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        system = copy.deepcopy(system)
        deletable_keys = [
            "code",
            "available",
            "default",
            "date_added",
            "date_modified",
        ]
        system["type"] = "System"
        tradeports = self._get_tradeports_by_position_name(system["name"], True)

        if tradeports:
            system["options_to_trade"] = ", ".join(
                [self._format_tradeport_name(tradeport) for tradeport in tradeports]
            )

        planets = self._get_planets_by_systemcode(system["code"])
        if planets:
            system["planets"] = ", ".join(
                [self._format_planet_name(planet) for planet in planets]
            )

        for key in deletable_keys:
            system.pop(key, None)

        self.cache["readable_objects"][checksum] = system
        return system

    def _get_converted_ship_for_output(self, ship: dict[str, any]) -> dict[str, any]:
        """
        Converts a ship dictionary to a dictionary that can be used as output.

        Args:
            ship (dict[str, any]): The ship dictionary to be converted.

        Returns:
            dict[str, any]: The converted ship dictionary.
        """
        checksum = f"ship--{ship['code']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        ship = copy.deepcopy(ship)
        deletable_keys = [
            "code",
            "loaner",
            "scu",
            "implemented",
            "mining",
            "stealth",
            "price",
            "price_warbond",
            "price_pkg",
            "sell_active",
            "sell_active_warbond",
            "sell_active_pkg",
            "stock_qt_speed",
            "showdown_winner",
            "date_added",
            "date_modified",
            "hull_trading",
        ]
        ship["type"] = "Ship"
        ship["manufacturer"] = (
            self.MANUFACTURERS[ship["manufacturer"]]
            if ship["manufacturer"] in self.MANUFACTURERS
            else ship["manufacturer"]
        )
        ship["cargo"] = f"{ship['scu']} SCU"
        ship["price_USD"] = f"{ship['price']}"

        ship["buy_at"] = (
            "This ship cannot be bought."
            if not ship["buy_at"]
            else [
                self._get_converted_rent_and_buy_option_for_output(position)
                for position in ship["buy_at"]
            ]
        )

        ship["rent_at"] = (
            "This ship cannot be rented."
            if not ship["rent_at"]
            else [
                self._get_converted_rent_and_buy_option_for_output(position)
                for position in ship["rent_at"]
            ]
        )

        if ship["hull_trading"] is True:
            ship["trading_info"] = (
                "This ship can only trade on suitable space stations with a cargo deck."
            )

        for key in deletable_keys:
            ship.pop(key, None)

        self.cache["readable_objects"][checksum] = ship
        return ship

    def _get_converted_rent_and_buy_option_for_output(
        self, position: dict[str, any]
    ) -> dict[str, any]:
        """
        Converts a rent/buy option dictionary to a dictionary that can be used as output.

        Args:
            position (dict[str, any]): The rent/buy option dictionary to be converted.

        Returns:
            dict[str, any]: The converted rent/buy option dictionary.
        """
        position = copy.deepcopy(position)
        keys = ["system", "planet", "satellite", "city", "store"]
        if not position["tradeport"]:
            for key in keys:
                if not position[key]:
                    position.pop(key, None)
                else:
                    position[key] = position[f"{key}_name"]
            position.pop("tradeport", None)
        else:
            tradeport = self._get_tradeport_by_code(position["tradeport"])
            position["tradeport"] = self._format_tradeport_name(tradeport)
            for key in keys:
                function_name = f"_get_{key}_name_by_code"
                if function_name in dir(self):
                    name = getattr(self, function_name)(tradeport[key])
                    if name:
                        position[key] = name
                    else:
                        position.pop(key, None)
            position["store"] = (
                "Refinery"  # TODO: remove this when refinery is implemented
            )
        position["price"] = f"{position['price']} aUEC"

        keys_to_remove = [
            "tradeport_name",
            "system_name",
            "planet_name",
            "satellite_name",
            "tradeport_name",
            "city_name",
            "store_name",
            "date_added",
            "date_modified",
        ]
        for key in keys_to_remove:
            position.pop(key, None)

        return position

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
        checksum = f"commodity--{commodity['code']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        commodity = copy.deepcopy(commodity)
        commodity["notes"] = ""
        deletable_keys = [
            "code",
            "tradable",
            "temporary",
            "restricted",
            "raw",
            "available",
            "date_added",
            "date_modified",
            "trade_price_buy",
            "trade_price_sell",
        ]

        price_buy_best = None
        price_sell_best = None
        commodity["buy_options"] = {}
        commodity["sell_options"] = {}

        for tradeport in self.tradeports:
            if "prices" not in tradeport:
                continue
            if commodity["code"] in tradeport["prices"]:
                if tradeport["prices"][commodity["code"]]["operation"] == "buy":
                    price_buy = tradeport["prices"][commodity["code"]]["price_buy"]
                    if price_buy_best is None or price_buy < price_buy_best:
                        price_buy_best = price_buy
                    commodity["buy_options"][
                        self._format_tradeport_name(tradeport)
                    ] = f"{price_buy} aUEC"
                else:
                    price_sell = tradeport["prices"][commodity["code"]]["price_sell"]
                    if price_sell_best is None or price_sell > price_sell_best:
                        price_sell_best = price_sell
                    commodity["sell_options"][
                        self._format_tradeport_name(tradeport)
                    ] = f"{price_sell} aUEC"

        commodity["best_buy_price"] = (
            f"{price_buy_best} aUEC" if price_buy_best else "Not buyable."
        )
        commodity["best_sell_price"] = (
            f"{price_sell_best} aUEC" if price_sell_best else "Not sellable."
        )

        boolean_keys = ["minable", "harvestable", "illegal"]
        for key in boolean_keys:
            commodity[key] = "Yes" if commodity[key] != "0" else "No"
        if commodity["illegal"] == "Yes":
            commodity[
                "notes"
            ] += "Stay away from ship scanns to avoid fines and crimestat, as this commodity is illegal."

        for key in deletable_keys:
            commodity.pop(key, None)

        self.cache["readable_objects"][checksum] = commodity
        return commodity

    async def _gpt_call_get_locations_to_sell_to(
        self,
        commodity_name: str = None,
        ship_name: str = None,
        position_name: str = None,
        commodity_amount: int = 1,
        maximal_number_of_locations: int = 5,
    ) -> str:
        self._print_debug(
            f"Given Parameters: Commodity: {commodity_name}, Ship Name: {ship_name}, Current Position: {position_name}, Amount: {commodity_amount}, Maximal Number of Locations: {maximal_number_of_locations}",
            True,
        )

        commodity_name = self._get_function_arg_from_cache(
            "commodity_name", commodity_name
        )
        ship_name = self._get_function_arg_from_cache("ship_name", ship_name)

        if commodity_name is None:
            self._print_debug("No commodity given. Ask for a commodity.", True)
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

        self._print_debug(
            f"Interpreted Parameters: Commodity: {commodity_name}, Ship Name: {ship_name}, Position: {position_name}, Amount: {commodity_amount}, Maximal Number of Locations: {maximal_number_of_locations}",
            True,
        )

        if misunderstood:
            self._print_debug(
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

        self._print_debug("\n".join(messages), True)
        return "\n".join(messages)

    async def _gpt_call_get_locations_to_buy_from(
        self,
        commodity_name: str = None,
        ship_name: str = None,
        position_name: str = None,
        commodity_amount: int = 1,
        maximal_number_of_locations: int = 5,
    ) -> str:
        self._print_debug(
            f"Given Parameters: Commodity: {commodity_name}, Ship Name: {ship_name}, Current Position: {position_name}, Amount: {commodity_amount}, Maximal Number of Locations: {maximal_number_of_locations}",
            True,
        )

        commodity_name = self._get_function_arg_from_cache(
            "commodity_name", commodity_name
        )
        ship_name = self._get_function_arg_from_cache("ship_name", ship_name)

        if commodity_name is None:
            self._print_debug("No commodity given. Ask for a commodity.", True)
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

        self._print_debug(
            f"Interpreted Parameters: Commodity: {commodity_name}, Ship Name: {ship_name}, Position: {position_name}, Amount: {commodity_amount}, Maximal Number of Locations: {maximal_number_of_locations}",
            True,
        )

        if misunderstood:
            self._print_debug(
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

        self._print_debug("\n".join(messages), True)
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

        commodity_code = commodity["code"]
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

        commodity_code = commodity["code"]
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

        self._print_debug(
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

        self._print_debug(
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

            self._print_debug(answer, True)
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
            if not illegal_commodities_allowed and commodity["illegal"] == "1":
                continue
            for start_tradeport in start_tradeports:
                if (
                    "prices" not in start_tradeport
                    or commodity["code"] not in start_tradeport["prices"]
                    or start_tradeport["prices"][commodity["code"]]["operation"]
                    != "buy"
                ):
                    continue
                for end_tradeport in end_tradeports:
                    if (
                        "prices" not in end_tradeport
                        or commodity["code"] not in end_tradeport["prices"]
                        or end_tradeport["prices"][commodity["code"]]["operation"]
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

                    # self._print_debug(f"Searching traderoute..(Ship: {ship['name']}, Start: {start_tradeport['name']}, End: {end_tradeport['name']})", True)

                    trading_route_new = self._get_trading_route(
                        ship,
                        start_tradeport,
                        money,
                        free_cargo_space,
                        end_tradeport,
                        commodity,
                        illegal_commodities_allowed,
                    )
                    # self._print_debug(trading_route_new, True)

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
                "Possible commodities with their profit. Just give basic overview at first."
                + additional_answer
                + " JSON: "
                + json.dumps(trading_routes)
            )

            self._print_debug(message, True)
            return message
        else:
            return_string = "No trading routes found."
            if len(errors) > 0:
                return_string += "\nPossible errors are:\n- " + "\n- ".join(errors)
            self._print_debug(return_string, True)
            return return_string

    def _get_trading_route(
        self,
        ship: dict[str, any],
        position_start: dict[str, any],
        money: int = None,
        free_cargo_space: int = None,
        position_end: dict[str, any] = None,
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
        start_tradeports = self._get_tradeports_by_position_name(position_start["name"])
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

        end_tradeports = []
        if position_end is None:
            for tradeport in self.tradeports:
                if tradeport["system"] == start_tradeports[0]["system"]:
                    end_tradeports.append(tradeport)
        else:
            end_tradeports = self._get_tradeports_by_position_name(position_end["name"])
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
            and end_tradeports[0]["code"] == start_tradeports[0]["code"]
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
                        if tradeport["name"] == blacklist_item["tradeport"]:
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
                                    if commodity["code"] == commodity_code:
                                        # remove commodity code from tradeport
                                        tradeport["prices"].pop(commodity_code)
                                        break
                    for tradeport in end_tradeports:
                        if tradeport["name"] == blacklist_item["tradeport"]:
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
                                    if commodity["code"] == commodity_code:
                                        # remove commodity code from tradeport
                                        tradeport["prices"].pop(commodity_code)
                                        break

        for tradeport_start in start_tradeports:
            commodities = []
            if "prices" not in tradeport_start:
                continue

            for attr, price in tradeport_start["prices"].items():
                if price["operation"] == "buy" and (
                    commodity_filter is None or commodity_filter["code"] == attr
                ):
                    commodity = self._get_commodity_by_code(attr)
                    if (
                        illegal_commodities_allowed is True
                        or commodity["illegal"] != "1"
                    ):
                        price["short_name"] = attr

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
                if "prices" not in tradeport_end or (
                    commodity_filter is not None
                    and commodity_filter["code"] not in tradeport_end["prices"]
                ):
                    continue
                for attr, price in tradeport_end["prices"].items():
                    price["short_name"] = attr

                    sell_commodity = self._get_commodity_by_code(attr)
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

                    for commodity in commodities:
                        if (
                            commodity["short_name"] == price["short_name"]
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
                            cargo = min(cargo_by_money, cargo_by_space)
                            if cargo >= 1:
                                profit = round(
                                    cargo
                                    * (price["price_sell"] - commodity["price_buy"])
                                )
                                if profit > best_route["profit"]:
                                    best_route["start"] = [tradeport_start]
                                    best_route["end"] = [tradeport_end]
                                    best_route["commodity"] = price
                                    best_route["profit"] = profit
                                    best_route["cargo"] = cargo
                                    best_route["buy"] = commodity["price_buy"] * cargo
                                    best_route["sell"] = price["price_sell"] * cargo
                                else:
                                    if (
                                        profit == best_route["profit"]
                                        and best_route["commodity"]["short_name"]
                                        == price["short_name"]
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
        return self.tradeport_code_dict.get(code.lower()) if code else None

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
            ("system", "Star-System"),
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
            self._format_system_name(self.system_code_dict.get(code.lower()))
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
            self._format_planet_name(self.planet_code_dict.get(code.lower()))
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
            self._format_satellite_name(self.satellite_code_dict.get(code.lower()))
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
            self._format_city_name(self.city_code_dict.get(code.lower()))
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
            self._format_commodity_name(self.commodity_code_dict.get(code.lower()))
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
        return self.commodity_code_dict.get(code.lower()) if code else None

    def _get_tradeports_by_position_name(
        self, name: str, direct: bool = False
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
        return self.satellites_by_planet.get(code.lower(), []) if code else []

    def _get_cities_by_planetcode(self, code: str) -> list[dict[str, any]]:
        """Returns all cities with the specified planet code.

        Args:
            code (str): The code of the planet.

        Returns:
            list[dict[str, any]]: A list of cities matching the planet code.
        """
        return self.cities_by_planet.get(code.lower(), []) if code else []

    def _get_planets_by_systemcode(self, code: str) -> list[dict[str, any]]:
        """Returns all planets with the specified system code.

        Args:
            code (str): The code of the system.

        Returns:
            list[dict[str, any]]: A list of planets matching the system code.
        """
        return self.planets_by_system.get(code.lower(), []) if code else []

    def _get_tradeports_by_systemcode(self, code: str) -> list[dict[str, any]]:
        """Returns all tradeports with the specified system code.

        Args:
            code (str): The code of the system.

        Returns:
            list[dict[str, any]]: A list of tradeports matching the system code.
        """
        return self.tradeports_by_system.get(code.lower(), []) if code else []

    def _get_tradeports_by_planetcode(self, code: str) -> list[dict[str, any]]:
        """Returns all tradeports with the specified planet code.

        Args:
            code (str): The code of the planet.

        Returns:
            list[dict[str, any]]: A list of tradeports matching the planet code.
        """
        return self.tradeports_by_planet.get(code.lower(), []) if code else []

    def _get_tradeports_by_satellitecode(self, code: str) -> list[dict[str, any]]:
        """Returns all tradeports with the specified satellite code.

        Args:
            code (str): The code of the satellite.

        Returns:
            list[dict[str, any]]: A list of tradeports matching the satellite code.
        """
        return self.tradeports_by_satellite.get(code.lower(), []) if code else []

    def _get_tradeports_by_citycode(self, code: str) -> list[dict[str, any]]:
        """Returns all tradeports with the specified city code.

        Args:
            code (str): The code of the city.

        Returns:
            list[dict[str, any]]: A list of tradeports matching the city code.
        """
        return self.tradeports_by_city.get(code.lower(), []) if code else []

    def _get_tradeports_by_planetname(self, name: str) -> list[dict[str, any]]:
        """Returns all tradeports with the specified planet name.

        Args:
            name (str): The name of the planet.

        Returns:
            list[dict[str, any]]: A list of tradeports matching the planet name.
        """
        planet = self._get_planet_by_name(name)
        return self._get_tradeports_by_planetcode(planet["code"]) if planet else []

    def _get_tradeports_by_satellitename(self, name: str) -> list[dict[str, any]]:
        """Returns all tradeports with the specified satellite name.

        Args:
            name (str): The name of the satellite.

        Returns:
            list[dict[str, any]]: A list of tradeports matching the satellite name.
        """
        satellite = self._get_satellite_by_name(name)
        return (
            self._get_tradeports_by_satellitecode(satellite["code"])
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
        return self._get_tradeports_by_citycode(city["code"]) if city else []

    def _get_tradeports_by_cityname(self, name: str) -> list[dict[str, any]]:
        """Returns all tradeports with the specified city name.

        Args:
            name (str): The name of the city.

        Returns:
            list[dict[str, any]]: A list of tradeports matching the city name.
        """
        city = self._get_city_by_name(name)
        return self._get_tradeports_by_citycode(city["code"]) if city else []

    def _get_tradeports_by_systemname(self, name: str) -> list[dict[str, any]]:
        """Returns all tradeports with the specified system name.

        Args:
            name (str): The name of the system.

        Returns:
            list[dict[str, any]]: A list of tradeports matching the system name.
        """
        system = self._get_system_by_name(name)
        return self._get_tradeports_by_systemcode(system["code"]) if system else []
