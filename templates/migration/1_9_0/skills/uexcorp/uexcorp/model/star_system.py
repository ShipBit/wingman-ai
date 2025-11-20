from datetime import datetime
try:
    from skills.uexcorp.uexcorp.model.data_model import DataModel
except ModuleNotFoundError:
    from uexcorp.uexcorp.model.data_model import DataModel

class StarSystem(DataModel):

    required_keys = ["id"]

    def __init__(
            self,
            id: int, # int(11)
            id_faction: int | None = None,  # int(11)
            id_jurisdiction: int | None = None,  # int(11)
            name: str | None = None, # varchar(255)
            code: str | None = None,  # varchar(2)
            is_available: int | None = None,  # tinyint(1)
            is_available_live: int | None = None,  # tinyint(1)
            is_visible: int | None = None,  # tinyint(1)
            is_default: int | None = None,  # tinyint(1)
            wiki: str | None = None,  # varchar(255)
            date_added: int | None = None, # int(11)
            date_modified: int | None = None, # int(11)
            faction_name: str | None = None,  # varchar(255)
            jurisdiction_name: str | None = None,  # varchar(255)
            load: bool = False,
    ):
        super().__init__("star_system")
        self.data = {
            "id": id,
            "id_faction": id_faction,
            "id_jurisdiction": id_jurisdiction,
            "name": name,
            "code": code,
            "is_available": is_available,
            "is_available_live": is_available_live,
            "is_visible": is_visible,
            "is_default": is_default,
            "wiki": wiki,
            "date_added": date_added,
            "date_modified": date_modified,
            "faction_name": faction_name,
            "jurisdiction_name": jurisdiction_name,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["id"]:
                raise Exception("ID is required to load data")
            self.load_by_value("id", self.data["id"])

    def get_data_for_ai(self) -> dict:
        try:
            from skills.uexcorp.uexcorp.data_access.planet_data_access import PlanetDataAccess
            from skills.uexcorp.uexcorp.data_access.space_station_data_access import SpaceStationDataAccess
            from skills.uexcorp.uexcorp.model.faction import Faction
            from skills.uexcorp.uexcorp.model.jurisdiction import Jurisdiction
        except ModuleNotFoundError:
            from uexcorp.uexcorp.data_access.planet_data_access import PlanetDataAccess
            from uexcorp.uexcorp.data_access.space_station_data_access import SpaceStationDataAccess
            from uexcorp.uexcorp.model.faction import Faction
            from uexcorp.uexcorp.model.jurisdiction import Jurisdiction

        faction = Faction(self.get_id_faction(), load=True) if self.get_id_faction() else None
        jurisdiction = Jurisdiction(self.get_id_jurisdiction(), load=True) if self.get_id_jurisdiction() else None

        information = {
            "name": self.get_name(),
            "location_type": "Star System",
            "faction": faction.get_data_for_ai_minimal() if faction else None,
            "jurisdiction": jurisdiction.get_data_for_ai_minimal() if jurisdiction else None,
            "planets": [],
            "space_stations": [],
        }

        planets = PlanetDataAccess().add_filter_by_id_star_system(self.get_id()).load()
        for planet in planets:
            information["planets"].append(planet.get_data_for_ai_minimal())

        space_station_data_access = SpaceStationDataAccess()
        space_station_data_access.add_filter_by_id_star_system(self.get_id())
        space_station_data_access.add_filter_by_id_planet(0)
        space_stations = space_station_data_access.load()
        for space_station in space_stations:
            information["space_stations"].append(space_station.get_data_for_ai_minimal())

        return information

    def get_data_for_ai_minimal(self) -> dict:
        try:
            from skills.uexcorp.uexcorp.data_access.planet_data_access import PlanetDataAccess
            from skills.uexcorp.uexcorp.data_access.space_station_data_access import SpaceStationDataAccess
        except ModuleNotFoundError:
            from uexcorp.uexcorp.data_access.planet_data_access import PlanetDataAccess
            from uexcorp.uexcorp.data_access.space_station_data_access import SpaceStationDataAccess

        planets = PlanetDataAccess().add_filter_by_id_star_system(self.get_id()).load()
        space_station_data_access = SpaceStationDataAccess()
        space_station_data_access.add_filter_by_id_star_system(self.get_id())
        space_station_data_access.add_filter_by_id_planet(0)
        space_stations = space_station_data_access.load()

        return {
            "name": self.get_name(),
            "location_type": "Star System",
            "planets": [str(planet) for planet in planets],
            "space_stations": [str(space_station) for space_station in space_stations],
            "jurisdiction_name": self.get_jurisdiction_name(),
            "faction_name": self.get_faction_name(),
        }

    def get_id(self) -> int:
        return self.data["id"]

    def get_id_faction(self) -> int | None:
        return self.data["id_faction"]

    def get_id_jurisdiction(self) -> int | None:
        return self.data["id_jurisdiction"]

    def get_name(self) -> str | None:
        return self.data["name"]

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

    def get_wiki(self) -> str | None:
        return self.data["wiki"]

    def get_date_added(self) -> int | None:
        return self.data["date_added"]

    def get_date_added_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_added"])

    def get_date_modified(self) -> int | None:
        return self.data["date_modified"]

    def get_date_modified_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_modified"])

    def get_faction_name(self) -> str | None:
        return self.data["faction_name"]

    def get_jurisdiction_name(self) -> str | None:
        return self.data["jurisdiction_name"]

    def __str__(self):
        return str(self.data["name"])