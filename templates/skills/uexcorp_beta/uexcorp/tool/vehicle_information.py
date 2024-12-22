import json

from skills.uexcorp_beta.uexcorp.tool.tool import Tool
from skills.uexcorp_beta.uexcorp.tool.validator import Validator


class VehicleInformation(Tool):

    def __init__(self):
        super().__init__()

    def execute(
        self,
        filter_vehicles: list[str] | None = None,
        filter_vehicle_roles: list[str] | None = None,
        filter_vehicle_company: list[str] | None = None,
        filter_vehicle_cargo_size_in_scu_min: int | None = None,
        filter_vehicle_cargo_size_in_scu_max: int | None = None,
    ) -> (str, str):
        from skills.uexcorp_beta.uexcorp.data_access.vehicle_data_access import VehicleDataAccess

        if not any([
            filter_vehicles,
            filter_vehicle_roles,
            filter_vehicle_company,
            filter_vehicle_cargo_size_in_scu_min,
            filter_vehicle_cargo_size_in_scu_max]
        ):
            return "At least one filter option must be provided.", ""

        vehicle_data_access = VehicleDataAccess()

        if filter_vehicles:
            vehicle_data_access.add_filter_by_name_full(filter_vehicles)

        if filter_vehicle_roles:
            vehicle_data_access.add_filter_by_role_strings(filter_vehicle_roles)

        if filter_vehicle_company:
            vehicle_data_access.add_filter_by_company_name(filter_vehicle_company)

        if filter_vehicle_cargo_size_in_scu_min:
            vehicle_data_access.add_filter_by_scu(filter_vehicle_cargo_size_in_scu_min, operation=">=")

        if filter_vehicle_cargo_size_in_scu_max:
            vehicle_data_access.add_filter_by_scu(filter_vehicle_cargo_size_in_scu_max, operation="<=")

        vehicles = vehicle_data_access.load(debug=True) # TODO remove debug=True
        return json.dumps([vehicle.get_data_for_ai() for vehicle in vehicles]), ""

    def get_mandatory_fields(self) -> dict[str, Validator]:
        return {}

    def get_optional_fields(self) -> dict[str, Validator]:
        return {
            "filter_vehicles": Validator(Validator.VALIDATE_VEHICLE, multiple=True),
            "filter_vehicle_roles": Validator(Validator.VALIDATE_VEHICLE_ROLE, multiple=True),
            "filter_vehicle_company": Validator(Validator.VALIDATE_COMPANY, multiple=True, config={"is_vehicle_manufacturer": True}),
            "filter_vehicle_cargo_size_in_scu_min": Validator(Validator.VALIDATE_NUMBER),
            "filter_vehicle_cargo_size_in_scu_max": Validator(Validator.VALIDATE_NUMBER),
        }

    def get_description(self) -> str:
        return "Holds information about all vehicles. May be filtered by at least one filter option."