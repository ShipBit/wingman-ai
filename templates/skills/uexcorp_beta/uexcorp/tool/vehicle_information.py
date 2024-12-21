import json

from skills.uexcorp_beta.uexcorp.tool.tool import Tool
from skills.uexcorp_beta.uexcorp.tool.validator import Validator


class VehicleInformation(Tool):

    def __init__(self):
        super().__init__()

    def execute(
        self,
        vehicles: list[str],
    ) -> (str, str):
        from skills.uexcorp_beta.uexcorp.data_access.vehicle_data_access import VehicleDataAccess

        vehicles = VehicleDataAccess().add_filter_by_name_full(vehicles).load()
        vehicle_data = []
        for vehicle in vehicles:
            vehicle_data.append(vehicle.get_data_for_ai())

        return json.dumps(vehicle_data), ""

    def get_mandatory_fields(self) -> dict[str, Validator]:
        return {
            "vehicles": Validator(Validator.VALIDATE_VEHICLE, multiple=True),
        }

    def get_optional_fields(self) -> dict[str, Validator]:
        return {}

    def get_description(self) -> str:
        return "Gives information about the given vehicles. Can be used with one or multiple ship names. A vehicle name should include the short manufacturer, the model, and the variant, if given by user."