from typing import Optional
import json
import requests
from services.printr import Printr
from services.secret_keeper import SecretKeeper
from wingmen.open_ai_wingman import OpenAiWingman

printr = Printr()


class StarHeadWingman(OpenAiWingman):
    """Our StarHead Wingman uses the StarHead API to find the best trading route for a given spaceship, position and the money to spend.
    If it's missing any of these parameters, it will ask the user for them.
    """

    def __init__(
        self,
        name: str,
        config: dict[str, any],
        secret_keeper: SecretKeeper,
        app_root_dir: str,
    ) -> None:
        super().__init__(
            name=name,
            config=config,
            secret_keeper=secret_keeper,
            app_root_dir=app_root_dir,
        )

        # config entry existence not validated yet. Assign later when checked!
        self.star_head_url = ""
        """The base URL of the StarHead API"""

        self.headers = {"x-origin": "wingman-ai"}
        """Requireds header for the StarHead API"""

        self.timeout = 5
        """Global timeout for calls to the the StarHead API (in seconds)"""

        self.vehicles = []
        self.ship_names = []
        self.celestial_objects = []
        self.celestial_object_names = []
        self.quantum_drives = []

    def validate(self):
        # collect errors from the base class (if any)
        errors: list[str] = super().validate()

        # add custom errors
        if not self.config.get("starhead_api_url"):
            errors.append("Missing 'starhead_api_url' in config.yaml")

        return errors

    def prepare(self):
        # here validate() already ran, so we can safely access the config
        self.star_head_url = self.config.get("starhead_api_url")

        self.start_execution_benchmark()

        self.vehicles = self._fetch_data("vehicle")
        self.ship_names = [
            self._format_ship_name(vehicle)
            for vehicle in self.vehicles
            if vehicle["type"] == "Ship"
        ]

        self.celestial_objects = self._fetch_data("celestialobject")
        self.celestial_object_names = [
            celestial_object["name"] for celestial_object in self.celestial_objects
        ]

        self.quantum_drives = self._fetch_data("vehiclecomponent", {"typeFilter": 8})

    def _fetch_data(
        self, endpoint: str, params: Optional[dict[str, any]] = None
    ) -> list[dict[str, any]]:
        url = f"{self.star_head_url}/{endpoint}"

        if self.debug:
            printr.print(f"Retrieving {url}", tags="info")

        response = requests.get(
            url, params=params, timeout=self.timeout, headers=self.headers
        )
        response.raise_for_status()
        if self.debug:
            self.print_execution_time(reset_timer=True)

        return response.json()

    def _format_ship_name(self, vehicle: dict[str, any]) -> str:
        """Formats name by combining model and name, avoiding repetition"""
        return (
            f"{vehicle['model']} {vehicle['name']}"
            if vehicle["name"] != vehicle["model"]
            else vehicle["name"]
        )

    async def _execute_command_by_function_call(
        self, function_name: str, function_args: dict[str, any]
    ) -> tuple[str, str]:
        """Execute commands passed from the base class and handles the 'get_best_trading_route'."""
        (
            function_response,
            instant_response,
        ) = await super()._execute_command_by_function_call(
            function_name, function_args
        )
        if function_name == "get_best_trading_route":
            function_response = self._get_best_trading_route(**function_args)
        return function_response, instant_response

    def _build_tools(self) -> list[dict[str, any]]:
        """Builds the toolset for execution, adding custom function 'get_best_trading_route'."""
        tools = super()._build_tools()
        tools.append(
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
                            "moneyToSpend": {"type": "number"},
                        },
                        "required": ["ship", "position", "moneyToSpend"],
                    },
                },
            }
        )
        return tools

    def _get_best_trading_route(
        self, ship: str, position: str, moneyToSpend: float
    ) -> str:
        """Calculates the best trading route for the specified ship and position.
        Note that the function arguments have to match the funtion_args from OpenAI, hence the camelCase!
        """

        cargo, qd = self._get_ship_details(ship)
        if not cargo or not qd:
            return f"Could not find ship '{ship}' in the StarHead database."

        celestial_object_id = self._get_celestial_object_id(position)
        if not celestial_object_id:
            return f"Could not find celestial object '{position}' in the StarHead database."

        data = {
            "startCelestialObjectId": celestial_object_id,
            "quantumDriveId": qd["id"] if qd else None,
            "maxAvailablScu": cargo,
            "maxAvailableMoney": moneyToSpend,
            "useOnlyWeaponFreeZones": False,
            "onlySingleSections": True,
        }
        url = f"{self.star_head_url}/trading"
        response = requests.post(
            url=url,
            json=data,
            timeout=self.timeout,
            headers=self.headers,
        )
        response.raise_for_status()

        parsed_response = response.json()
        if parsed_response:
            section = parsed_response[0]
            return json.dumps(section)
        return "No route found. This might be an issue with the StarHead API."

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

    def _get_ship_details(
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
            loadouts = self._get_ship_loadout(vehicle.get("id"))
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

    def _get_ship_loadout(self, ship_id: Optional[int]) -> Optional[dict[str, any]]:
        """Retrieves loadout data for a given ship ID."""
        if ship_id:
            try:
                loadout = self._fetch_data(f"vehicle/{ship_id}/loadout")
                return loadout or None
            except requests.HTTPError:
                printr.print(
                    f"Failed to fetch loadout data for ship with ID: {ship_id}",
                    tags="err",
                )
        return None
