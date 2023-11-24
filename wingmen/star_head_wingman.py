import json
import requests
from services.printr import Printr
from wingmen.open_ai_wingman import OpenAiWingman


class StarHeadWingman(OpenAiWingman):
    def __init__(self, name: str, config: dict[str, any]):
        super().__init__(name, config)

        self.star_head_url = "https://api-test.star-head.de"
        """The base URL of the StarHead API"""
        self.headers = {
            "x-origin": "wingman-ai",
        }

        self.timeout = 30
        """The global timeout for all requests to StarHead"""

        # fetch all the data..
        self.start_execution_benchmark()

        Printr.info_print("Retrieving vehicles...")
        self.vehicles = self._fetch_data("vehicle")
        """All vehicles from the StarHead API"""

        self.ship_names = [
            self.__concatenate_model_and_name(vehicle)
            for vehicle in self.vehicles
            if vehicle["type"] == "Ship"
        ]
        """The names of all ships from the StarHead API"""

        Printr.info_print("Retrieving celestial objects...")
        self.celestial_objects = self._fetch_data("celestialobject")
        """All celestial objects from the StarHead API"""

        self.celestial_object_names = [
            celestial_object["name"] for celestial_object in self.celestial_objects
        ]
        """The names of all celestial objects from the StarHead API"""

        Printr.info_print("Retrieving vehicle component (quantum drives)...")
        self.quantum_drives = self._fetch_data("vehiclecomponent", {"typeFilter": 8})

    def _fetch_data(self, endpoint, params=None):
        url = f"{self.star_head_url}/{endpoint}"
        response = requests.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()

        if self.debug:
            self.print_execution_time(reset_timer=True)

        return response.json()

    def __concatenate_model_and_name(self, vehicle):
        """Combines model and name, avoids repetition if they are the same"""
        return (
            f"{vehicle['model']} {vehicle['name']}"
            if vehicle["model"] != vehicle["name"]
            else vehicle["name"]
        )

    def _execute_command_by_function_call(
        self, function_name: str, function_args: dict[str, any]
    ) -> tuple[str, str]:
        """Does what the base class does, but also handles custom function "get_best_trading_route"."""

        function_response, instant_response = super()._execute_command_by_function_call(
            function_name, function_args
        )

        if function_name == "get_best_trading_route":
            # get the best trading route based on the arguments passed by GPT
            function_response = self.__get_best_trading_route(**function_args)

        return function_response, instant_response

    def _build_tools(self) -> list[dict[str, any]]:
        """Does what the base class does, but also adds the custom function "get_best_trading_route"."""

        tools = super()._build_tools()
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "get_best_trading_route",
                    "description": "Determines the (best) trade route for a spaceship and its current position.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ship": {
                                "type": "string",
                                "description": "The spaceship for which the trade route is to be determined.",
                                "enum": self.ship_names,
                            },
                            "position": {
                                "type": "string",
                                "description": "The current position of the spaceship.",
                                "enum": self.celestial_object_names,
                            },
                            "moneyToSpend": {
                                "type": "number",
                                "description": "The maximum amount of money to spend on the trade route.",
                            },
                        },
                        "required": ["ship", "position", "moneyToSpend"],
                    },
                },
            },
        )
        return tools

    def __get_best_trading_route(self, ship, position, money_to_spend):
        Printr.info_print(
            f"❖ Call StarHead - Ship: {ship}, Position: {position} - Money: {money_to_spend}"
        )
        cargo, qd = self.__get_ship_details(ship)
        celestial_object_id = self.__get_celestial_object_id(position)

        data = {
            "startCelestialObjectId": celestial_object_id,
            "quantumDriveId": qd.get("id"),
            "maxAvailablScu": cargo,
            "maxAvailableMoney": money_to_spend,
            "useOnlyWeaponFreeZones": False,
            "onlySingleSections": True,
        }

        response = requests.post(
            f"{self.star_head_url}/trading", json=data, timeout=self.timeout
        )
        section = response.json()[0]

        return json.dumps(section)

    def __get_celestial_object_id(self, name: str):
        for celestial_object in self.celestial_objects:
            if celestial_object["name"].lower() == name.lower():
                return celestial_object["id"]
        return None

    def __get_ship_details(self, ship_name: str):
        for vehicle in self.vehicles:
            # Construct a ship identifier that includes both model and name if they're different
            constructed_name = (
                f"{vehicle['model']} {vehicle['name']}"
                if vehicle["model"] != vehicle["name"]
                else vehicle["name"]
            )

            if constructed_name.lower() == ship_name.lower():
                cargo = vehicle.get("scuCargo")
                loadouts = self.__get_ship_loadout(vehicle.get("id"))
                if loadouts:
                    loadout = next(
                        (l for l in loadouts.get("loadouts") if l["isDefaultLayout"]),
                        None,
                    )
                    if loadout:
                        for qd in self.quantum_drives:
                            for item in loadout.get("data"):
                                if item.get("componentId") == qd.get("id"):
                                    return cargo, qd
        return None, None

    def __get_ship_loadout(self, ship_id):
        if not ship_id:
            return None

        response = requests.get(
            f"{self.star_head_url}/vehicle/{ship_id}/loadout", timeout=self.timeout
        )
        if response.status_code == 200:
            return response.json()

        return None
