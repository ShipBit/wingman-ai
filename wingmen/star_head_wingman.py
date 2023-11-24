import json
import requests
from wingmen.open_ai_wingman import OpenAiWingman


class StarHeadWingman(OpenAiWingman):
    def __init__(self, name: str, config: dict[str, any]):
        super().__init__(name, config)

        self.__init_star_head()

    def __init_star_head(self):
        # Setup StarHead
        # The API endpoint URL
        self.star_head_url = "https://api.star-head.de"
        self.headers = {
            "x-origin": "wingman-ai",
        }

        # GET all ships
        response = requests.get(f"{self.star_head_url}/vehicle", headers=self.headers)
        # Check if the request was successful
        if response.status_code == 200:
            # Parse the JSON response
            self.vehicles = response.json()

            # Extract a list of ship names
            self.ship_names = [
                vehicle["model"] + " " + vehicle["name"]
                if vehicle["model"] != vehicle["name"]
                else vehicle["name"]
                for vehicle in self.vehicles
                if vehicle["type"] == "Ship"
            ]
        else:
            print(f"Failed to retrieve vehicles. Status code: {response.status_code}")

        # Get all celestial objects
        response = requests.get(
            f"{self.star_head_url}/celestialobject", headers=self.headers
        )
        # Check if the request was successful
        if response.status_code == 200:
            # Parse the JSON response
            self.celestial_objects = response.json()

            # Extract a list of celestial object names
            self.celestial_object_names = [
                celestial_object["name"] for celestial_object in self.celestial_objects
            ]
        else:
            print(
                f"Failed to retrieve celestial objects. Status code: {response.status_code}"
            )

        # Get all quantum drives
        params = {
            "typeFilter": "8",
        }
        response = requests.get(
            f"{self.star_head_url}/vehiclecomponent",
            params=params,
            headers=self.headers,
        )
        # Check if the request was successful
        if response.status_code == 200:
            # Parse the JSON response
            self.quantum_drives = response.json()
        else:
            print(
                f"Failed to retrieve quantum drives. Status code: {response.status_code}"
            )

    def _get_function_response(
        self, function_name: str, function_args: dict[str, any]
    ) -> tuple[str, str]:
        function_response, instant_response = super()._get_function_response(
            function_name, function_args
        )

        if function_name == "get_best_trading_route":
            # get the best trading route based on the arguments passed by GPT
            function_response = self.__get_best_trading_route(**function_args)

        return function_response, instant_response

    def __get_best_trading_route(self, ship, position, moneyToSpend):
        print(
            f"Call StarHead - Ship: {ship}, Position: {position} - Money to spend: {moneyToSpend}"
        )
        cargo, qd = self.__get_ship_details(ship)
        celestial_object_id = self.__get_celestial_object_id(position)

        data = {
            "startCelestialObjectId": celestial_object_id,
            "quantumDriveId": qd.get("id"),
            "maxAvailablScu": cargo,
            "maxAvailableMoney": moneyToSpend,
            "useOnlyWeaponFreeZones": False,
            "onlySingleSections": True,
        }

        response = requests.post(
            f"{self.star_head_url}/trading", json=data, headers=self.headers
        )

        section = response.json()[0]

        return json.dumps(section)

    def __get_celestial_object_id(self, name):
        for celestial_object in self.celestial_objects:
            if celestial_object["name"].lower() == name.lower():
                return celestial_object["id"]
        return None

    def __get_ship_details(self, ship_name):
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
            f"{self.star_head_url}/vehicle/{ship_id}/loadout", headers=self.headers
        )
        # Check if the request was successful
        if response.status_code == 200:
            # Parse the JSON response
            return response.json()
        else:
            return None

    def _get_tools(self) -> list[dict[str, any]]:
        tools = super()._get_tools()
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
