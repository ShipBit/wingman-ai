import json
from skills.uexcorp_beta.uexcorp.tool.tool import Tool
from skills.uexcorp_beta.uexcorp.tool.validator import Validator


class LocationInformation(Tool):

    def __init__(self):
        super().__init__()

    def execute(
            self,
            location_name: list[str] | None = None,
    ) -> (str, str):
        from skills.uexcorp_beta.uexcorp.data_access.star_system_data_access import StarSystemDataAccess
        from skills.uexcorp_beta.uexcorp.data_access.planet_data_access import PlanetDataAccess
        from skills.uexcorp_beta.uexcorp.data_access.moon_data_access import MoonDataAccess
        from skills.uexcorp_beta.uexcorp.data_access.space_station_data_access import SpaceStationDataAccess
        from skills.uexcorp_beta.uexcorp.data_access.terminal_data_access import TerminalDataAccess
        from skills.uexcorp_beta.uexcorp.data_access.city_data_access import CityDataAccess
        from skills.uexcorp_beta.uexcorp.data_access.poi_data_access import PoiDataAccess
        from skills.uexcorp_beta.uexcorp.data_access.outpost_data_access import OutpostDataAccess
        from skills.uexcorp_beta.uexcorp.data_access.orbit_data_access import OrbitDataAccess

        locations = []

        locations.extend(
            StarSystemDataAccess().add_filter_by_is_available(True).add_filter_by_name(location_name).load()
        )
        locations.extend(
            PlanetDataAccess().add_filter_by_is_available(True).add_filter_by_name(location_name).load()
        )
        locations.extend(
            MoonDataAccess().add_filter_by_is_available(True).add_filter_by_name(location_name).load()
        )
        locations.extend(
            SpaceStationDataAccess().add_filter_by_is_available(True).add_filter_by_name(location_name).load()
        )
        locations.extend(
            TerminalDataAccess().add_filter_by_is_available(True).add_filter_by_name(location_name).load()
        )
        locations.extend(
            CityDataAccess().add_filter_by_is_available(True).add_filter_by_name(location_name).load()
        )
        locations.extend(
            PoiDataAccess().add_filter_by_is_available(True).add_filter_by_name(location_name).load()
        )
        locations.extend(
            OutpostDataAccess().add_filter_by_is_available(True).add_filter_by_name(location_name).load()
        )
        locations.extend(
            OrbitDataAccess().add_filter_by_is_available(True).add_filter_by_name(location_name).load()
        )

        locations = [location.get_data_for_ai() for location in locations]
        return json.dumps(locations), ""

    def get_mandatory_fields(self) -> dict[str, Validator]:
        return {
            "location_names": Validator(Validator.VALIDATE_LOCATION, multiple=True)
        }

    def get_optional_fields(self) -> dict[str, Validator]:
        return {}

    def get_description(self) -> str:
        return "Gives back information about a location, its related locations and, if available, it's shopping options."
