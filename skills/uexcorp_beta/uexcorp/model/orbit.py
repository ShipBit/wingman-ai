from datetime import datetime
try:
    from skills.uexcorp_beta.uexcorp.model.data_model import DataModel
except ImportError:
    from uexcorp_beta.uexcorp.model.data_model import DataModel

class Orbit(DataModel):

    required_keys = ["id"]

    def __init__(
        self,
        id: int, # int(11)
        id_star_system: int | None = None,  # int(11)
        id_faction: int | None = None,  # int(11)
        id_jurisdiction: int | None = None,  # int(11)
        name: str | None = None, # varchar(255)
        name_origin: str | None = None,  # varchar(255)
        code: str | None = None,  # varchar(10)
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
        super().__init__("orbit")
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
        try:
            from skills.uexcorp_beta.uexcorp.model.star_system import StarSystem
            from skills.uexcorp_beta.uexcorp.model.faction import Faction
            from skills.uexcorp_beta.uexcorp.model.jurisdiction import Jurisdiction
            from skills.uexcorp_beta.uexcorp.data_access.space_station_data_access import SpaceStationDataAccess
            from skills.uexcorp_beta.uexcorp.data_access.planet_data_access import PlanetDataAccess
        except ImportError:
            from uexcorp_beta.uexcorp.model.star_system import StarSystem
            from uexcorp_beta.uexcorp.model.faction import Faction
            from uexcorp_beta.uexcorp.model.jurisdiction import Jurisdiction
            from uexcorp_beta.uexcorp.data_access.space_station_data_access import SpaceStationDataAccess
            from uexcorp_beta.uexcorp.data_access.planet_data_access import PlanetDataAccess

        star_system = StarSystem(self.get_id_star_system(), load=True) if self.get_id_star_system() else None
        space_stations = SpaceStationDataAccess().add_filter_by_id_orbit(self.get_id()).load()
        planets = PlanetDataAccess().add_filter_by_name(self.get_name()).load() if self.get_name() else []
        faction = Faction(self.get_id_faction(), load=True) if self.get_id_faction() else None
        jurisdiction = Jurisdiction(self.get_id_jurisdiction(), load=True) if self.get_id_jurisdiction() else None

        information = {
            "name": self.get_name(),
            "locations_type": "Orbit",
            "space_stations_in_orbit": [space_station.get_data_for_ai_minimal() for space_station in space_stations],
            "planets_in_orbit": [planet.get_data_for_ai_minimal() for planet in planets],
            "star_system": star_system.get_data_for_ai_minimal() if star_system else None,
            "is_lagrange": self.get_is_lagrange(),
            "faction": faction.get_data_for_ai_minimal() if faction else None,
            "jurisdiction": jurisdiction.get_data_for_ai_minimal() if jurisdiction else None,
        }

        return information

    def get_data_for_ai_minimal(self) -> dict:
        try:
            from skills.uexcorp_beta.uexcorp.data_access.space_station_data_access import SpaceStationDataAccess
            from skills.uexcorp_beta.uexcorp.data_access.planet_data_access import PlanetDataAccess
        except ImportError:
            from uexcorp_beta.uexcorp.data_access.space_station_data_access import SpaceStationDataAccess
            from uexcorp_beta.uexcorp.data_access.planet_data_access import PlanetDataAccess

        space_stations = SpaceStationDataAccess().add_filter_by_id_orbit(self.get_id()).load()
        planets = PlanetDataAccess().add_filter_by_name(self.get_name()).load()

        information = {
            "name": self.get_name(),
            "locations_type": "Orbit",
            "space_stations_in_orbit": [str(space_station) for space_station in space_stations],
            "planets_in_orbit": [str(planet) for planet in planets],
            "star_system": self.get_star_system_name(),
            "is_lagrange": self.get_is_lagrange(),
            "faction": self.get_faction_name() if self.get_faction_name() else None,
            "jurisdiction": self.get_jurisdiction_name() if self.get_jurisdiction_name() else None,
        }

        return information

    def get_id(self) -> int:
        return self.data["id"]

    def get_id_star_system(self) -> int | None:
        return self.data["id_star_system"]

    def get_id_faction(self) -> int | None:
        return self.data["id_faction"]

    def get_id_jurisdiction(self) -> int | None:
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