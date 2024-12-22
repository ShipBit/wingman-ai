from datetime import datetime
from skills.uexcorp_beta.uexcorp.model.data_model import DataModel

class Planet(DataModel):

    required_keys = ["id"]

    def __init__(
        self,
        id: int, # int(11)
        id_star_system: int | None = None,  # int(11)
        id_faction: int | None = None,  # int(11)
        id_jurisdiction: int | None = None,  # int(11)
        name: str | None = None, # varchar(255)
        name_origin: str | None = None,  # varchar(255)
        code: str | None = None,  # varchar(255)
        is_available: int | None = None,  # tinyint(1)
        is_available_live: int | None = None,  # tinyint(1)
        is_visible: int | None = None,  # tinyint(1)
        is_default: int | None = None,  # tinyint(1)
        is_lagrange: int | None = None,  # tinyint(1)
        date_added: int | None = None, # int(11)
        date_modified: int | None = None, # int(11)
        star_system_name: str | None = None,  # varchar(255)
        faction_name: str | None = None,  # varchar(255)
        jurisdiction_name: str | None = None,  # varchar(255)
        load: bool = False,
    ):
        super().__init__("planet")
        self.data = {
            "id": id,
            "id_star_system": id_star_system,
            "id_faction": id_faction,
            "id_jurisdiction": id_jurisdiction,
            "name": name,
            "name_origin": name_origin,
            "code": code,
            "is_available": is_available,
            "is_available_live": is_available_live,
            "is_visible": is_visible,
            "is_default": is_default,
            "is_lagrange": is_lagrange,
            "date_added": date_added,
            "date_modified": date_modified,
            "star_system_name": star_system_name,
            "faction_name": faction_name,
            "jurisdiction_name": jurisdiction_name,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["id"]:
                raise Exception("ID is required to load data")
            self.load_by_value("id", self.data["id"])

    def get_data_for_ai(self) -> dict:
        from skills.uexcorp_beta.uexcorp.model.star_system import StarSystem
        from skills.uexcorp_beta.uexcorp.data_access.city_data_access import CityDataAccess
        from skills.uexcorp_beta.uexcorp.data_access.moon_data_access import MoonDataAccess
        from skills.uexcorp_beta.uexcorp.data_access.space_station_data_access import SpaceStationDataAccess
        from skills.uexcorp_beta.uexcorp.data_access.poi_data_access import PoiDataAccess
        from skills.uexcorp_beta.uexcorp.data_access.outpost_data_access import OutpostDataAccess
        from skills.uexcorp_beta.uexcorp.model.faction import Faction
        from skills.uexcorp_beta.uexcorp.model.jurisdiction import Jurisdiction

        star_system = StarSystem(self.get_id_star_system(), load=True) if self.get_id_star_system() else None
        cities = CityDataAccess().add_filter_by_id_planet(self.get_id()).add_filter_by_id_moon(0).load()
        moons = MoonDataAccess().add_filter_by_id_planet(self.get_id()).load()
        pois = PoiDataAccess().add_filter_by_id_planet(self.get_id()).add_filter_by_id_moon(0).load()
        outposts = OutpostDataAccess().add_filter_by_id_planet(self.get_id()).add_filter_by_id_moon(0).load()
        space_stations = SpaceStationDataAccess().add_filter_by_id_planet(self.get_id()).add_filter_by_id_moon(0).load()
        faction = Faction(self.get_id_faction(), load=True) if self.get_id_faction() else None
        jurisdiction = Jurisdiction(self.get_id_jurisdiction(), load=True) if self.get_id_jurisdiction() else None

        information = {
            "name": self.get_name(),
            "location_type": "Planet",
            "faction": faction.get_data_for_ai_minimal() if faction else None,
            "jurisdiction": jurisdiction.get_data_for_ai_minimal() if jurisdiction else None,
            "star_system": star_system.get_data_for_ai_minimal() if star_system else None,
            "cities": [city.get_data_for_ai_minimal() for city in cities],
            "moons": [moon.get_data_for_ai_minimal() for moon in moons],
            "orbital_stations": [],
            "lagrange_stations": [],
            "points_of_interest": [poi.get_data_for_ai_minimal() for poi in pois],
            "outposts": [outpost.get_data_for_ai_minimal() for outpost in outposts],
        }

        for space_station in space_stations:
            if space_station.get_is_lagrange():
                information["lagrange_stations"].append(space_station.get_data_for_ai_minimal())
            else:
                information["orbital_stations"].append(space_station.get_data_for_ai_minimal())

        return information

    def get_data_for_ai_minimal(self) -> dict:
        from skills.uexcorp_beta.uexcorp.data_access.city_data_access import CityDataAccess
        from skills.uexcorp_beta.uexcorp.data_access.moon_data_access import MoonDataAccess
        from skills.uexcorp_beta.uexcorp.data_access.space_station_data_access import SpaceStationDataAccess
        from skills.uexcorp_beta.uexcorp.data_access.poi_data_access import PoiDataAccess
        from skills.uexcorp_beta.uexcorp.data_access.outpost_data_access import OutpostDataAccess

        cities = CityDataAccess().add_filter_by_id_planet(self.get_id()).add_filter_by_id_moon(0).load()
        moons = MoonDataAccess().add_filter_by_id_planet(self.get_id()).load()
        pois = PoiDataAccess().add_filter_by_id_planet(self.get_id()).add_filter_by_id_moon(0).load()
        outposts = OutpostDataAccess().add_filter_by_id_planet(self.get_id()).add_filter_by_id_moon(0).load()
        space_stations = SpaceStationDataAccess().add_filter_by_id_planet(self.get_id()).add_filter_by_id_moon(0).load()

        information = {
            "name": self.get_name(),
            "location_type": "Planet",
            "faction": self.get_faction_name(),
            "jurisdiction": self.get_jurisdiction_name(),
            "star_system": self.get_star_system_name(),
            "cities": [str(city) for city in cities],
            "moons": [str(moon) for moon in moons],
            "orbital_stations": [],
            "lagrange_stations": [],
            "points_of_interest": [str(poi) for poi in pois],
            "outposts": [str(outpost) for outpost in outposts],
        }

        for space_station in space_stations:
            if space_station.get_is_lagrange():
                information["lagrange_stations"].append(str(space_station))
            else:
                information["orbital_stations"].append(str(space_station))

        return information

    def get_id(self) -> int:
        return self.data["id"]

    def get_id_star_system(self) -> int:
        return self.data["id_star_system"]

    def get_id_faction(self) -> int:
        return self.data["id_faction"]

    def get_id_jurisdiction(self) -> int:
        return self.data["id_jurisdiction"]

    def get_name(self) -> str | None:
        return self.data["name"]

    def get_name_origin(self) -> str | None:
        return self.data["name_origin"]

    def get_code(self) -> str | None:
        return self.data["code"]

    def get_is_available(self) -> bool | None:
        return bool(self.data["is_available"])

    def get_is_available_live(self) -> bool | None:
        return bool(self.data["is_available_live"])

    def get_is_visible(self) -> bool | None:
        return bool(self.data["is_visible"])

    def get_is_default(self) -> bool | None:
        return bool(self.data["is_default"])

    def get_is_lagrange(self) -> bool | None:
        return bool(self.data["is_lagrange"])

    def get_date_added(self) -> int | None:
        return self.data["date_added"]

    def get_date_added_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_added"])

    def get_date_modified(self) -> int | None:
        return self.data["date_modified"]

    def get_date_modified_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_modified"])

    def get_star_system_name(self) -> str | None:
        return self.data["star_system_name"]

    def get_faction_name(self) -> str | None:
        return self.data["faction_name"]

    def get_jurisdiction_name(self) -> str | None:
        return self.data["jurisdiction_name"]

    def __str__(self):
        return str(self.data["name"])