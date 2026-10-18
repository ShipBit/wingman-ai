from skills.uexcorp.uexcorp import compression
from skills.uexcorp.uexcorp.model.data_model import DataModel
from skills.uexcorp.uexcorp.tool.tool import Tool
from skills.uexcorp.uexcorp.tool.validator import Validator


class LocationInformation(Tool):
    REQUIRES_AUTHENTICATION = False
    TOOL_NAME: str = "uex_get_location_or_terminal_information"

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
        from skills.uexcorp.uexcorp.helper import Helper

        self.__filter_locations = filter_locations or []
        self.__filter_location_types = filter_location_types or []
        self.__filter_is_monitored = is_monitored
        self.__filter_has_quantum_marker = has_quantum_marker
        helper = Helper.get_instance()

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

        # Orbits (e.g. Lagrange points) have no location type, but filter_locations can name them
        if filter_locations and not filter_location_types:
            locations.extend(self.__get_orbits(locations))

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

        return compression.dumps(locations), ""

    def __get_star_systems(self) -> list[DataModel]:
        from skills.uexcorp.uexcorp.data_access.star_system_data_access import StarSystemDataAccess

        star_system_data_access = StarSystemDataAccess()
        star_system_data_access.add_filter_by_is_available(True)
        if self.__filter_locations:
            star_system_data_access.add_filter_by_name(self.__filter_locations)

        return star_system_data_access.load()

    def __get_space_stations(self) -> list[DataModel]:
        from skills.uexcorp.uexcorp.data_access.space_station_data_access import SpaceStationDataAccess

        space_station_data_access = SpaceStationDataAccess()
        space_station_data_access.add_filter_by_is_available(True)
        if self.__filter_locations and not self.__filter_location_types:
            space_station_data_access.add_filter_by_name(self.__filter_locations)
        elif self.__filter_locations and (self.LOCATION_TYPE_SPACE_STATION in self.__filter_location_types or self.LOCATION_TYPE_GATEWAY in self.__filter_location_types):
            space_station_data_access.add_filter_by_location_name_whitelist(self.__filter_locations)
        # Gateways are space stations, so with both types the stations must not be narrowed to gateways
        if self.LOCATION_TYPE_GATEWAY in self.__filter_location_types and self.LOCATION_TYPE_SPACE_STATION not in self.__filter_location_types:
            space_station_data_access.add_filter_by_name("%Gateway%", operation="LIKE")

        return space_station_data_access.load()

    def __get_planets(self) -> list[DataModel]:
        from skills.uexcorp.uexcorp.data_access.planet_data_access import PlanetDataAccess

        planet_data_access = PlanetDataAccess()
        planet_data_access.add_filter_by_is_available(True)
        if self.__filter_locations and not self.__filter_location_types:
            planet_data_access.add_filter_by_name(self.__filter_locations)
        elif self.__filter_locations and self.LOCATION_TYPE_PLANET in self.__filter_location_types:
            planet_data_access.add_filter_by_location_name_whitelist(self.__filter_locations)

        return planet_data_access.load()

    def __get_pois(self) -> list[DataModel]:
        from skills.uexcorp.uexcorp.data_access.poi_data_access import PoiDataAccess

        poi_data_access = PoiDataAccess()
        poi_data_access.add_filter_by_is_available(True)
        if self.__filter_locations and not self.__filter_location_types:
            poi_data_access.add_filter_by_name(self.__filter_locations)
        elif self.__filter_locations and self.LOCATION_TYPE_POI in self.__filter_location_types:
            poi_data_access.add_filter_by_location_name_whitelist(self.__filter_locations)

        return poi_data_access.load()

    def __get_outposts(self) -> list[DataModel]:
        from skills.uexcorp.uexcorp.data_access.outpost_data_access import OutpostDataAccess

        outpost_data_access = OutpostDataAccess()
        outpost_data_access.add_filter_by_is_available(True)
        if self.__filter_locations and not self.__filter_location_types:
            outpost_data_access.add_filter_by_name(self.__filter_locations)
        elif self.__filter_locations and self.LOCATION_TYPE_OUTPOST in self.__filter_location_types:
            outpost_data_access.add_filter_by_location_name_whitelist(self.__filter_locations)

        return outpost_data_access.load()

    def __get_moons(self) -> list[DataModel]:
        from skills.uexcorp.uexcorp.data_access.moon_data_access import MoonDataAccess

        moon_data_access = MoonDataAccess()
        moon_data_access.add_filter_by_is_available(True)
        if self.__filter_locations and not self.__filter_location_types:
            moon_data_access.add_filter_by_name(self.__filter_locations)
        elif self.__filter_locations and self.LOCATION_TYPE_MOON in self.__filter_location_types:
            moon_data_access.add_filter_by_location_name_whitelist(self.__filter_locations)

        return moon_data_access.load()

    def __get_cities(self) -> list[DataModel]:
        from skills.uexcorp.uexcorp.data_access.city_data_access import CityDataAccess

        city_data_access = CityDataAccess()
        city_data_access.add_filter_by_is_available(True)
        if self.__filter_locations and not self.__filter_location_types:
            city_data_access.add_filter_by_name(self.__filter_locations)
        elif self.__filter_locations and self.LOCATION_TYPE_CITY in self.__filter_location_types:
            city_data_access.add_filter_by_location_name_whitelist(self.__filter_locations)

        return city_data_access.load()

    def __get_orbits(self, found_locations: list[DataModel]) -> list[DataModel]:
        from skills.uexcorp.uexcorp.data_access.orbit_data_access import OrbitDataAccess

        # Planets and moons are orbits too, they are already covered by their own lookups
        orbits = OrbitDataAccess().add_filter_by_name(self.__filter_locations).load()
        found = {str(location) for location in found_locations}
        return [orbit for orbit in orbits if str(orbit) not in found]

    def __get_terminals(self) -> list[DataModel]:
        from skills.uexcorp.uexcorp.data_access.terminal_data_access import TerminalDataAccess
        from skills.uexcorp.uexcorp.model.terminal import Terminal

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
            "filter_locations": Validator(
                Validator.VALIDATE_LOCATION,
                multiple=True,
                prompt="Location names, e.g. [\"Hurston\"] or [\"Port Tressler\"]. Without filter_location_types: returns these locations themselves. With filter_location_types: returns locations of those types inside these locations.",
            ),
            "filter_location_types": Validator(
                Validator.VALIDATE_ENUM,
                multiple=True,
                config={
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
                },
                prompt="Types of locations to return, e.g. filter_locations [\"Hurston\"] + filter_location_types [\"moon\"] = all moons of Hurston. \"terminal\" means commodity trading terminals."
            ),

            # Will be added later
            # "is_monitored": Validator(Validator.VALIDATE_BOOL),
            # "has_quantum_marker": Validator(Validator.VALIDATE_BOOL),
        }

    def get_description(self) -> str:
        return (
            "Look up places in Star Citizen: star systems, planets, moons, space stations, gateways, cities, outposts, "
            "points of interest and trading terminals. Returns what is there (sub-locations, terminals, services, "
            "landing pads, faction). Use it for 'what is at X' or 'list all Y in Z'. Narrow filters give more details per location."
        )

    def get_prompt(self) -> str:
        return (
            "Information about places and what they offer. "
            "Use it for questions about a location, not for trade routes."
        )
