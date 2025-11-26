import json
from typing import Optional
from typing import TYPE_CHECKING
import requests
from api.enums import LogType, WingmanInitializationErrorType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill, tool

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class StarHead(Skill):
    """
    StarHead skill for Star Citizen trading and ship information.

    Uses lookup tools to handle voice input spelling errors:
    1. LLM calls get_available_ships/locations to get valid names
    2. LLM fuzzy-matches user's spoken input to valid names
    3. LLM calls action tools with correct names
    """

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

        self.starhead_url = ""
        self.headers = {"x-origin": "wingman-ai"}
        self.timeout = 5
        self.star_citizen_wiki_url = ""

        # Data loaded at startup - used for dynamic enums
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
        """Load reference data from StarHead API for dynamic enums."""
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
        self.shop_names = list(dict.fromkeys([shop["name"] for shop in self.shops]))
        self.shop_parent_names = list(
            dict.fromkeys(
                [shop["parent"]["name"] for shop in self.shops if shop["parent"]]
            )
        )

    async def _fetch_data(
        self, endpoint: str, params: Optional[dict[str, any]] = None
    ) -> list[dict[str, any]]:
        url = f"{self.starhead_url}/{endpoint}"

        if self.settings.debug_mode:
            await self.printr.print_async(
                f"Retrieving {url}",
                color=LogType.INFO,
            )

        response = requests.get(
            url, params=params, timeout=self.timeout, headers=self.headers
        )
        response.raise_for_status()
        return response.json()

    def _format_ship_name(self, vehicle: dict[str, any]) -> str:
        return vehicle["name"]

    async def is_waiting_response_needed(self, tool_name: str) -> bool:
        # Lookup tools are fast (cached data), don't need waiting response
        if tool_name in (
            "get_available_ships",
            "get_available_locations",
            "get_available_shops",
        ):
            return False
        return True

    # ============================================================
    # LOOKUP TOOLS - Call these first to get valid names for voice input
    # ============================================================

    @tool(
        description="""Get a list of all available Star Citizen ship names.

        IMPORTANT: Call this tool FIRST when the user mentions a ship name via voice input,
        as speech-to-text often misspells ship names (e.g., 'Catapiller' instead of 'Caterpillar').

        Use the returned list to find the closest match to what the user said, then use
        that corrected name with get_best_trading_route or get_ship_information.

        Returns a list of all valid ship names in the StarHead database.
        """
    )
    async def get_available_ships(self) -> str:
        """Returns all available ship names for fuzzy matching."""
        return json.dumps(self.ship_names)

    @tool(
        description="""Get a list of all available Star Citizen locations (planets, moons, stations).

        IMPORTANT: Call this tool FIRST when the user mentions a location via voice input,
        as speech-to-text often misspells location names (e.g., 'Houston' instead of 'Hurston',
        'Yella' instead of 'Yela', 'Micro Tech' instead of 'microTech').

        Use the returned list to find the closest match to what the user said, then use
        that corrected name with get_best_trading_route or get_trading_shop_information_for_celestial_objects.

        Returns a list of all valid celestial object names (planets, moons, space stations).
        """
    )
    async def get_available_locations(self) -> str:
        """Returns all available celestial object names for fuzzy matching."""
        return json.dumps(self.celestial_object_names)

    @tool(
        description="""Get a list of all available Star Citizen shop names.

        IMPORTANT: Call this tool FIRST when the user mentions a shop name via voice input,
        as speech-to-text often misspells shop names.

        Use the returned list to find the closest match to what the user said, then use
        that corrected name with get_trading_information_of_specific_shop.

        Returns a list of all valid shop names in the StarHead database.
        """
    )
    async def get_available_shops(self) -> str:
        """Returns all available shop names for fuzzy matching."""
        return json.dumps(self.shop_names)

    # ============================================================
    # ACTION TOOLS - Use corrected names from lookup tools
    # ============================================================

    @tool(
        description="""Find the best trade route for a given spaceship and position in Star Citizen.

        PREREQUISITE: First call get_available_ships() and get_available_locations() to get valid names,
        especially if the user's input came from voice (speech-to-text often misspells names).

        Args:
            ship: Exact ship name from get_available_ships() list
            position: Exact celestial object name from get_available_locations() list
            money_to_spend: Available budget in aUEC (Alpha UEC)

        Returns trading route with buy/sell locations, commodity, profit margin, and travel time.
        """
    )
    async def get_best_trading_route(
        self, ship: str, position: str, money_to_spend: float
    ) -> str:
        """Calculates the best trading route for the specified ship and position."""
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

        try:
            response = requests.post(
                url=f"{self.starhead_url}/trading",
                json=data,
                timeout=self.timeout,
                headers=self.headers,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            return f"Failed to fetch trading route: {e}"

        parsed_response = response.json()
        if parsed_response:
            return json.dumps(parsed_response[0])
        return f"No route found for ship '{ship}' at '{position}' with '{money_to_spend}' aUEC."

    @tool(
        description="""Get detailed information about a Star Citizen spaceship.

        PREREQUISITE: First call get_available_ships() to get valid ship names,
        especially if the user's input came from voice (speech-to-text often misspells names).

        Args:
            ship: Exact ship name from get_available_ships() list

        Returns ship specifications, components, cargo capacity, weapons, and performance data from the Star Citizen wiki.
        """
    )
    async def get_ship_information(self, ship: str) -> str:
        """Gets information about a ship from the Star Citizen wiki."""
        try:
            response = requests.get(
                url=f"{self.star_citizen_wiki_url}/vehicles/{ship}",
                timeout=self.timeout,
                headers=self.headers,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            return f"Failed to fetch ship information: {e}"
        return json.dumps(response.json())

    @tool(
        description="""Get trading information for a specific shop in Star Citizen.

        PREREQUISITE: First call get_available_shops() to get valid shop names,
        especially if the user's input came from voice (speech-to-text often misspells names).

        Args:
            shop: Exact shop name from get_available_shops() list

        Returns commodities available for buying/selling with current prices. If multiple shops share the same name,
        you'll need to specify the celestial object using get_trading_shop_information_for_celestial_objects.
        """
    )
    async def get_trading_information_of_specific_shop(self, shop: str) -> str:
        """Gets trading information for a specific shop."""
        shops = [s for s in self.shops if s["name"].lower() == shop.lower()]

        if len(shops) > 1:
            return f"Multiple shops with the name '{shop}' found. Please specify the celestial object."

        if not shops:
            return f"Could not find shop '{shop}' in the StarHead database."

        items = await self._fetch_data(f"shop/{shops[0]['id']}/items")
        for item in items:
            item["pricePerItem"] = item["pricePerItem"] * 100

        return json.dumps(items)

    @tool(
        description="""Get all trading shop information for a celestial object in Star Citizen.

        PREREQUISITE: First call get_available_locations() to get valid location names,
        especially if the user's input came from voice (speech-to-text often misspells names).

        Args:
            celestial_object: Exact celestial object name from get_available_locations() list

        Returns all shops at that location with their commodities and prices.
        """
    )
    async def get_trading_shop_information_for_celestial_objects(
        self, celestial_object: str
    ) -> str:
        """Gets trading information for all shops on a celestial object."""
        object_id = self._get_celestial_object_id(celestial_object)

        if not object_id:
            return f"Could not find celestial object '{celestial_object}' in the StarHead database."

        shops = await self._fetch_data(f"shop?celestialObjectFilter={object_id}")

        shop_items = {}
        for shop in shops:
            items = await self._fetch_data(f"shop/{shop['id']}/items")
            for item in items:
                item["pricePerItem"] = item["pricePerItem"] * 100
                item["tradeType"] = (
                    "Sold by store" if item["tradeType"] == "buy" else "The shop buys"
                )
            shop_items[f"{shop['parent']['name']} - {shop['name']}"] = items

        return json.dumps(shop_items)

    # Helper methods

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
