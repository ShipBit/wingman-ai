import json
try:
    from skills.uexcorp_beta.uexcorp.model.data_model import DataModel
    from skills.uexcorp_beta.uexcorp.tool.tool import Tool
    from skills.uexcorp_beta.uexcorp.tool.validator import Validator
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.model.data_model import DataModel
    from uexcorp_beta.uexcorp.tool.tool import Tool
    from uexcorp_beta.uexcorp.tool.validator import Validator


class LocationInformation(Tool):

    LOCATION_TYPE_STAR_SYSTEM = "star_system"
    LOCATION_TYPE_SPACE_STATION = "space_station"
    LOCATION_TYPE_GATEWAY = "gateway"
    LOCATION_TYPE_PLANET = "planet"
    LOCATION_TYPE_POI = "point_of_interest"
    LOCATION_TYPE_OUTPOST = "outpost"
    LOCATION_TYPE_MOON = "moon"
    LOCATION_TYPE_CITY = "city"
    LOCATION_TYPE_TERMINAL = "terminal"

    def __init__(self):
        super().__init__()
        self.__locations = []
        self.__filter_locations = []
        self.__filter_location_types = []
        self.__filter_is_monitored = None
        self.__filter_has_quantum_marker = None

    def execute(
        self,
        filter_locations: list[str] | None = None,
        filter_location_types: list[str] | None = None,
        is_monitored: bool | None = None,
        has_quantum_marker: bool | None = None,
    ) -> (str, str):
        try:
            from skills.uexcorp_beta.uexcorp.helper import Helper
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.helper import Helper

        self.__filter_locations = filter_locations or []
        self.__filter_location_types = filter_location_types or []
        self.__filter_is_monitored = is_monitored
        self.__filter_has_quantum_marker = has_quantum_marker
        helper = Helper().get_instance()

        locations = []

        if not filter_location_types or self.LOCATION_TYPE_STAR_SYSTEM in filter_location_types:
            locations.extend(self.__get_star_systems())

        if not filter_location_types or (self.LOCATION_TYPE_SPACE_STATION in filter_location_types or self.LOCATION_TYPE_GATEWAY in filter_location_types):
            locations.extend(self.__get_space_stations())

        if not filter_location_types or self.LOCATION_TYPE_PLANET in filter_location_types:
            locations.extend(self.__get_planets())

        if not filter_location_types or self.LOCATION_TYPE_POI in filter_location_types:
            locations.extend(self.__get_pois())

        if not filter_location_types or self.LOCATION_TYPE_OUTPOST in filter_location_types:
            locations.extend(self.__get_outposts())

        if not filter_location_types or self.LOCATION_TYPE_MOON in filter_location_types:
            locations.extend(self.__get_moons())

        if not filter_location_types or self.LOCATION_TYPE_CITY in filter_location_types:
            locations.extend(self.__get_cities())

        if not filter_location_types or self.LOCATION_TYPE_TERMINAL in filter_location_types:
            locations.extend(self.__get_terminals())

        if not locations:
            helper.get_handler_tool().add_note(
                "No matching locations found. Please check filter criteria."
            )
            return [], ""
        elif len(locations) <= 10:
            locations = [location.get_data_for_ai() for location in locations]
        elif len(locations) <= 20:
            locations = [location.get_data_for_ai_minimal() for location in locations]
            helper.get_handler_tool().add_note(
                f"Found {len(locations)} matching locations. Filter criteria are somewhat broad. (max 10 locations for advanced information)"
            )
        elif len(locations) <= 50:
            locations = [str(location) for location in locations]
            helper.get_handler_tool().add_note(
                f"Found {len(locations)} matching locations. Filter criteria are very broad. (max 20 locations for more than just name information)"
            )
        else:
            helper.get_handler_tool().add_note(
                f"Found {len(locations)} matching locations. Filter criteria are too broad. (max 50 locations for names and max 20 for information about each location)"
            )
            locations = []

        return json.dumps(locations), ""

    def __get_star_systems(self) -> list[DataModel]:
        try:
            from skills.uexcorp_beta.uexcorp.data_access.star_system_data_access import StarSystemDataAccess
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.data_access.star_system_data_access import StarSystemDataAccess

        star_system_data_access = StarSystemDataAccess()
        star_system_data_access.add_filter_by_is_available(True)
        if self.__filter_locations:
            star_system_data_access.add_filter_by_name(self.__filter_locations)

        return star_system_data_access.load()

    def __get_space_stations(self) -> list[DataModel]:
        try:
            from skills.uexcorp_beta.uexcorp.data_access.space_station_data_access import SpaceStationDataAccess
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.data_access.space_station_data_access import SpaceStationDataAccess

        space_station_data_access = SpaceStationDataAccess()
        space_station_data_access.add_filter_by_is_available(True)
        if self.__filter_locations and not self.__filter_location_types:
            space_station_data_access.add_filter_by_name(self.__filter_locations)
        elif self.__filter_locations and (self.LOCATION_TYPE_SPACE_STATION in self.__filter_location_types or self.LOCATION_TYPE_GATEWAY in self.__filter_location_types):
            space_station_data_access.add_filter_by_location_name_whitelist(self.__filter_locations)
        if self.LOCATION_TYPE_GATEWAY in self.__filter_location_types:
            space_station_data_access.add_filter_by_name("%Gateway%", operation="LIKE")

        return space_station_data_access.load()

    def __get_planets(self) -> list[DataModel]:
        try:
            from skills.uexcorp_beta.uexcorp.data_access.planet_data_access import PlanetDataAccess
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.data_access.planet_data_access import PlanetDataAccess

        planet_data_access = PlanetDataAccess()
        planet_data_access.add_filter_by_is_available(True)
        if self.__filter_locations and not self.__filter_location_types:
            planet_data_access.add_filter_by_name(self.__filter_locations)
        elif self.__filter_locations and self.LOCATION_TYPE_PLANET in self.__filter_location_types:
            planet_data_access.add_filter_by_location_name_whitelist(self.__filter_locations)

        return planet_data_access.load()

    def __get_pois(self) -> list[DataModel]:
        try:
            from skills.uexcorp_beta.uexcorp.data_access.poi_data_access import PoiDataAccess
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.data_access.poi_data_access import PoiDataAccess

        poi_data_access = PoiDataAccess()
        poi_data_access.add_filter_by_is_available(True)
        if self.__filter_locations and not self.__filter_location_types:
            poi_data_access.add_filter_by_name(self.__filter_locations)
        elif self.__filter_locations and self.LOCATION_TYPE_POI in self.__filter_location_types:
            poi_data_access.add_filter_by_location_name_whitelist(self.__filter_locations)

        return poi_data_access.load()

    def __get_outposts(self) -> list[DataModel]:
        try:
            from skills.uexcorp_beta.uexcorp.data_access.outpost_data_access import OutpostDataAccess
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.data_access.outpost_data_access import OutpostDataAccess

        outpost_data_access = OutpostDataAccess()
        outpost_data_access.add_filter_by_is_available(True)
        if self.__filter_locations and not self.__filter_location_types:
            outpost_data_access.add_filter_by_name(self.__filter_locations)
        elif self.__filter_locations and self.LOCATION_TYPE_OUTPOST in self.__filter_location_types:
            outpost_data_access.add_filter_by_location_name_whitelist(self.__filter_locations)

        return outpost_data_access.load()

    def __get_moons(self) -> list[DataModel]:
        try:
            from skills.uexcorp_beta.uexcorp.data_access.moon_data_access import MoonDataAccess
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.data_access.moon_data_access import MoonDataAccess

        moon_data_access = MoonDataAccess()
        moon_data_access.add_filter_by_is_available(True)
        if self.__filter_locations and not self.__filter_location_types:
            moon_data_access.add_filter_by_name(self.__filter_locations)
        elif self.__filter_locations and self.LOCATION_TYPE_MOON in self.__filter_location_types:
            moon_data_access.add_filter_by_location_name_whitelist(self.__filter_locations)

        return moon_data_access.load()

    def __get_cities(self) -> list[DataModel]:
        try:
            from skills.uexcorp_beta.uexcorp.data_access.city_data_access import CityDataAccess
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.data_access.city_data_access import CityDataAccess

        city_data_access = CityDataAccess()
        city_data_access.add_filter_by_is_available(True)
        if self.__filter_locations and not self.__filter_location_types:
            city_data_access.add_filter_by_name(self.__filter_locations)
        elif self.__filter_locations and self.LOCATION_TYPE_CITY in self.__filter_location_types:
            city_data_access.add_filter_by_location_name_whitelist(self.__filter_locations)

        return city_data_access.load()

    def __get_terminals(self) -> list[DataModel]:
        try:
            from skills.uexcorp_beta.uexcorp.data_access.terminal_data_access import TerminalDataAccess
            from skills.uexcorp_beta.uexcorp.model.terminal import Terminal
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.data_access.terminal_data_access import TerminalDataAccess
            from uexcorp_beta.uexcorp.model.terminal import Terminal

        terminal_data_access = TerminalDataAccess()
        terminal_data_access.add_filter_by_type(Terminal.TYPE_COMMODITY)
        terminal_data_access.add_filter_by_is_available(True)
        if self.__filter_locations and not self.__filter_location_types:
            terminal_data_access.add_filter_by_name(self.__filter_locations)
        elif self.__filter_locations and self.LOCATION_TYPE_TERMINAL in self.__filter_location_types:
            terminal_data_access.add_filter_by_location_name_whitelist(self.__filter_locations)

        return terminal_data_access.load()

    def get_mandatory_fields(self) -> dict[str, Validator]:
        return {}

    def get_optional_fields(self) -> dict[str, Validator]:
        return {
            "filter_locations": Validator(Validator.VALIDATE_LOCATION, multiple=True),
            "filter_location_types": Validator(Validator.VALIDATE_ENUM, multiple=True, config={
                "enum": [
                    self.LOCATION_TYPE_STAR_SYSTEM,
                    self.LOCATION_TYPE_SPACE_STATION,
                    self.LOCATION_TYPE_GATEWAY,
                    self.LOCATION_TYPE_PLANET,
                    self.LOCATION_TYPE_OUTPOST,
                    self.LOCATION_TYPE_POI,
                    self.LOCATION_TYPE_MOON,
                    self.LOCATION_TYPE_CITY,
                    self.LOCATION_TYPE_TERMINAL,
                ],
            }),

            # Will be added later
            # "is_monitored": Validator(Validator.VALIDATE_BOOL),
            # "has_quantum_marker": Validator(Validator.VALIDATE_BOOL),
        }

    def get_description(self) -> str:
        return "Gives back information about a locations, their related locations and, if available, it's shopping options and other services/properties."
