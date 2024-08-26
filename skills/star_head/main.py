import json
from typing import Optional
from typing import TYPE_CHECKING
import requests
from api.enums import LogType, WingmanInitializationErrorType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class StarHead(Skill):

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

        # config entry existence not validated yet. Assign later when checked!
        self.starhead_url = ""
        """The base URL of the StarHead API"""

        self.headers = {"x-origin": "wingman-ai"}
        """Requireds header for the StarHead API"""

        self.timeout = 5
        """Global timeout for calls to the the StarHead API (in seconds)"""

        self.star_citizen_wiki_url = ""

        self.vehicles = []
        self.ship_names = []
        self.celestial_objects = []
        self.celestial_object_names = []
        self.quantum_drives = []
        self.shops = []
        self.shop_names = []
        self.shop_parent_names = []

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        self.starhead_url = self.retrieve_custom_property_value(
            "starhead_api_url", errors
        )
        self.star_citizen_wiki_url = self.retrieve_custom_property_value(
            "star_citizen_wiki_api_url", errors
        )

        try:
            await self._prepare_data()
        except Exception as e:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.name,
                    message=f"Failed to load data from StarHead API: {e}",
                    error_type=WingmanInitializationErrorType.UNKNOWN,
                )
            )

        return errors

    async def _prepare_data(self):
        self.vehicles = await self._fetch_data("vehicle")
        self.ship_names = [
            self._format_ship_name(vehicle)
            for vehicle in self.vehicles
            if vehicle["type"] == "Ship"
        ]

        self.celestial_objects = await self._fetch_data("celestialobject")
        self.celestial_object_names = [
            celestial_object["name"] for celestial_object in self.celestial_objects
        ]

        self.quantum_drives = await self._fetch_data(
            "vehiclecomponent", {"typeFilter": 8}
        )

        self.shops = await self._fetch_data("shop")
        self.shop_names = [shop["name"] for shop in self.shops]

        # Remove duplicate shop names
        self.shop_names = list(dict.fromkeys(self.shop_names))

        self.shop_parent_names = [
            shop["parent"]["name"] for shop in self.shops if shop["parent"]
        ]

        # Remove duplicate parent names
        self.shop_parent_names = list(dict.fromkeys(self.shop_parent_names))

    async def _fetch_data(
        self, endpoint: str, params: Optional[dict[str, any]] = None
    ) -> list[dict[str, any]]:
        url = f"{self.starhead_url}/{endpoint}"

        if self.settings.debug_mode:
            self.start_execution_benchmark()
            await self.printr.print_async(
                f"Retrieving {url}",
                color=LogType.INFO,
            )

        response = requests.get(
            url, params=params, timeout=self.timeout, headers=self.headers
        )
        response.raise_for_status()
        if self.settings.debug_mode:
            await self.print_execution_time()

        return response.json()

    def _format_ship_name(self, vehicle: dict[str, any]) -> str:
        """Formats name by combining model and name, avoiding repetition"""
        return vehicle["name"]

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        instant_response = ""
        function_response = ""

        if tool_name == "get_best_trading_route":
            function_response = await self._get_best_trading_route(**parameters)
        if tool_name == "get_ship_information":
            function_response = await self._get_ship_information(**parameters)
        if tool_name == "get_trading_information_of_specific_shop":
            function_response = await self._get_trading_information_of_specific_shop(
                **parameters
            )
        if tool_name == "get_trading_shop_information_for_celestial_objects":
            function_response = await self._get_trading_shop_information_for_celestial_objects(
                **parameters
            )
        return function_response, instant_response

    async def is_waiting_response_needed(self, tool_name: str) -> bool:
        return True

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = [
            (
                "get_best_trading_route",
                {
                    "type": "function",
                    "function": {
                        "name": "get_best_trading_route",
                        "description": "Finds the best trade route for a given spaceship and position.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "ship": {"type": "string", "enum": self.ship_names},
                                "position": {
                                    "type": "string",
                                    "enum": self.celestial_object_names,
                                },
                                "money_to_spend": {"type": "number"},
                            },
                            "required": ["ship", "position", "money_to_spend"],
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
                        "description": "Gives information about the given ship.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "ship": {"type": "string", "enum": self.ship_names},
                            },
                            "required": ["ship"],
                        },
                    },
                },
            ),
            (
                "get_trading_information_of_specific_shop",
                {
                    "type": "function",
                    "function": {
                        "name": "get_trading_information_of_specific_shop",
                        "description": "Gives trading information about the given shop, like which commodities you can sell or buy and for which price. If the name of the shop is not unique, you have to specify the celestial object.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "shop": {"type": "string", "enum": self.shop_names},
                            },
                            "required": ["shop"],
                        },
                    },
                },
            ),
            (
                "get_trading_shop_information_for_celestial_objects",
                {
                    "type": "function",
                    "function": {
                        "name": "get_trading_shop_information_for_celestial_objects",
                        "description": "Gives trading information about the given celestial object, like which commodities you can sell or buy at which shop and for which price. All shops with shop items on that celestial object will be returned.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "celestial_object": {
                                    "type": "string",
                                    "enum": self.celestial_object_names,
                                },
                            },
                            "required": ["celestial_object"],
                        },
                    },
                },
            ),
        ]

        return tools

    async def _get_trading_shop_information_for_celestial_objects(
        self, celestial_object: str
    ) -> str:
        object_id = self._get_celestial_object_id(celestial_object)

        if not object_id:
            return f"Could not find celestial object '{celestial_object}' in the StarHead database."

        shops = await self._fetch_data(f"shop?celestialObjectFilter={object_id}")

        shop_items = {}
        for shop in shops:
            items = await self._fetch_data(f"shop/{shop['id']}/items")
            for item in items:
                item["pricePerItem"] = item["pricePerItem"] * 100
                item["tradeType"] = "Sold by store" if item["tradeType"] == "buy" else "The shop buys"
            shop_items[f"{shop['parent']['name']} - {shop['name']}"] = items

        shop_details = json.dumps(shop_items)
        return shop_details

    async def _get_trading_information_of_specific_shop(
        self, shop: str = None
    ) -> str:
        # Get all shops with the given name
        shops = [
            shop
            for shop in self.shops
            if shop["name"].lower() == shop["name"].lower()
        ]

        # Check if there are multiple shops with the same name
        if len(shops) > 1:
            return f"Multiple shops with the name '{shop}' found. Please specify the celestial object."

        if not shops:
            return f"Could not find shop '{shop}' in the StarHead database."

        shop_items = {}

        for shop in shops:
            items = await self._fetch_data(f"shop/{shop['id']}/items")
            for item in items:
                item["pricePerItem"] = item["pricePerItem"] * 100
            shop_items[shop["name"]] = items

        shop_details = json.dumps(items)
        return shop_details

    async def _get_ship_information(self, ship: str) -> str:
        try:
            response = requests.get(
                url=f"{self.star_citizen_wiki_url}/vehicles/{ship}",
                timeout=self.timeout,
                headers=self.headers,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            return f"Failed to fetch ship information: {e}"
        ship_details = json.dumps(response.json())
        return ship_details

    async def _get_best_trading_route(
        self, ship: str, position: str, money_to_spend: float
    ) -> str:
        """Calculates the best trading route for the specified ship and position.
        Note that the function arguments have to match the funtion_args from OpenAI, hence the camelCase!
        """

        cargo, qd = await self._get_ship_details(ship)
        if not cargo or not qd:
            return f"Could not find ship '{ship}' in the StarHead database."

        celestial_object_id = self._get_celestial_object_id(position)
        if not celestial_object_id:
            return f"Could not find celestial object '{position}' in the StarHead database."

        data = {
            "startCelestialObjectId": celestial_object_id,
            "quantumDriveId": qd["id"] if qd else None,
            "maxAvailablScu": cargo,
            "maxAvailableMoney": money_to_spend,
            "useOnlyWeaponFreeZones": False,
            "onlySingleSections": True,
        }
        url = f"{self.starhead_url}/trading"
        try:
            response = requests.post(
                url=url,
                json=data,
                timeout=self.timeout,
                headers=self.headers,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            return f"Failed to fetch trading route: {e}"

        parsed_response = response.json()
        if parsed_response:
            section = parsed_response[0]
            return json.dumps(section)
        return f"No route found for ship '{ship}' at '{position}' with '{money_to_spend}' aUEC."

    def _get_celestial_object_id(self, name: str) -> Optional[int]:
        """Finds the ID of the celestial object with the specified name."""
        return next(
            (
                obj["id"]
                for obj in self.celestial_objects
                if obj["name"].lower() == name.lower()
            ),
            None,
        )

    async def _get_ship_details(
        self, ship_name: str
    ) -> tuple[Optional[int], Optional[dict[str, any]]]:
        """Gets ship details including cargo capacity and quantum drive information."""
        vehicle = next(
            (
                v
                for v in self.vehicles
                if self._format_ship_name(v).lower() == ship_name.lower()
            ),
            None,
        )
        if vehicle:
            cargo = vehicle.get("scuCargo")
            loadouts = await self._get_ship_loadout(vehicle.get("id"))
            if loadouts:
                loadout = next(
                    (l for l in loadouts.get("loadouts") if l["isDefaultLayout"]), None
                )
                qd = next(
                    (
                        qd
                        for qd in self.quantum_drives
                        for item in loadout.get("data")
                        if item.get("componentId") == qd.get("id")
                    ),
                    None,
                )
                return cargo, qd
        return None, None

    async def _get_ship_loadout(
        self, ship_id: Optional[int]
    ) -> Optional[dict[str, any]]:
        """Retrieves loadout data for a given ship ID."""
        if ship_id:
            try:
                loadout = await self._fetch_data(f"vehicle/{ship_id}/loadout")
                return loadout or None
            except requests.HTTPError:
                await self.printr.print_async(
                    f"Failed to fetch loadout data for ship with ID: {ship_id}",
                    color=LogType.ERROR,
                )
        return None
