from skills.uexcorp.uexcorp import compression
from skills.uexcorp.uexcorp.tool.tool import Tool
from skills.uexcorp.uexcorp.tool.validator import Validator


class VehicleInformation(Tool):
    REQUIRES_AUTHENTICATION = False
    TOOL_NAME = "uex_get_vehicle_information"

    def __init__(self):
        super().__init__()

    def execute(
        self,
        filter_vehicles: list[str] | None = None,
        filter_vehicle_roles: list[str] | None = None,
        filter_vehicle_company: list[str] | None = None,
        filter_vehicle_cargo_size_in_scu_min: int | None = None,
        filter_vehicle_cargo_size_in_scu_max: int | None = None,
        limit: int | None = None,
        offset: int | None = None
    ) -> (str, str):
        from skills.uexcorp.uexcorp.data_access.vehicle_data_access import VehicleDataAccess
        from skills.uexcorp.uexcorp.helper import Helper

        helper = Helper.get_instance()

        if not any([
            filter_vehicles,
            filter_vehicle_roles,
            filter_vehicle_company,
            filter_vehicle_cargo_size_in_scu_min,
            filter_vehicle_cargo_size_in_scu_max,
        ]):
            return "At least one filter_X option must be provided.", ""

        vehicle_data_access = VehicleDataAccess()

        if filter_vehicles:
            vehicle_data_access.add_filter_by_name_full(filter_vehicles)
        else:
            if filter_vehicle_roles:
                vehicle_data_access.add_filter_by_role_strings(filter_vehicle_roles)

            if filter_vehicle_company:
                vehicle_data_access.add_filter_by_company_name(filter_vehicle_company)

            if filter_vehicle_cargo_size_in_scu_min:
                vehicle_data_access.add_filter_by_scu(filter_vehicle_cargo_size_in_scu_min, operation=">=")

            if filter_vehicle_cargo_size_in_scu_max:
                vehicle_data_access.add_filter_by_scu(filter_vehicle_cargo_size_in_scu_max, operation="<=")

            if limit:
                vehicle_data_access.limit(limit)
                helper.get_handler_tool().add_note(
                    f"You must clearly communicate to the user that a limit of {limit} is used"
                )

            if offset:
                vehicle_data_access.offset(offset)

        vehicles = vehicle_data_access.load()

        data = [vehicle.get_data_for_ai() for vehicle in vehicles]

        if filter_vehicles:
            for entry, vehicle in zip(data, vehicles):
                photos = vehicle.get_url_photos()
                if photos:
                    entry["image_url"] = photos[0]

        return compression.dumps(data), ""

    def get_mandatory_fields(self) -> dict[str, Validator]:
        return {}

    def get_optional_fields(self) -> dict[str, Validator]:
        return {
            "filter_vehicles": Validator(
                Validator.VALIDATE_VEHICLE,
                multiple=True,
                prompt="Ship or vehicle names, best with manufacturer, e.g. [\"Drake Cutlass Black\", \"Crusader C2 Hercules Starlifter\"]. If set, all other filters are ignored.",
            ),
            "filter_vehicle_roles": Validator(
                Validator.VALIDATE_VEHICLE_ROLE,
                multiple=True,
                prompt="Only vehicles with all of these roles, e.g. [\"mining\"] or [\"cargo transporter\", \"starter\"].",
            ),
            "filter_vehicle_company": Validator(
                Validator.VALIDATE_COMPANY,
                multiple=True,
                config={"is_vehicle_manufacturer": True},
                prompt="Only vehicles built by these manufacturers, e.g. [\"Aegis Dynamics\"].",
            ),
            "filter_vehicle_cargo_size_in_scu_min": Validator(
                Validator.VALIDATE_NUMBER,
                prompt="Only vehicles with at least this cargo capacity in SCU, e.g. 100.",
            ),
            "filter_vehicle_cargo_size_in_scu_max": Validator(
                Validator.VALIDATE_NUMBER,
                prompt="Only vehicles with at most this cargo capacity in SCU, e.g. 250.",
            ),

            # Currently unreliable handling by AI
            # "limit": Validator(Validator.VALIDATE_NUMBER),
            # "offset": Validator(Validator.VALIDATE_NUMBER),
        }

    def get_description(self) -> str:
        return (
            "Look up Star Citizen ships and ground vehicles: cargo capacity (SCU), crew, size, roles, manufacturer, "
            "and where to buy or rent them with prices. Use it for questions about a specific ship, "
            "or to find ships by role, manufacturer or cargo capacity. At least one filter is required."
        )

    def get_prompt(self) -> str:
        return (
            "Ship and vehicle data: specs, cargo capacity, buy and rent locations with prices. "
            "With filter_vehicles, a result may include an 'image_url' with a photo of the ship; "
            "you may show it as a markdown image or link."
        )
