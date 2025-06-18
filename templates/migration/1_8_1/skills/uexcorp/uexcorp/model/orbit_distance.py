from datetime import datetime
try:
    from skills.uexcorp.uexcorp.model.data_model import DataModel
except ModuleNotFoundError:
    from uexcorp.uexcorp.model.data_model import DataModel

class OrbitDistance(DataModel):

    required_keys = ["id"]

    def __init__(
        self,
        id: int, # int(11)
        # id_star_system: int | None = None, # int(11) # deprecated
        id_star_system_origin: int | None = None, # int(11)
        id_star_system_destination: int | None = None, # int(11)
        id_orbit_origin: int | None = None, # int(11)
        id_orbit_destination: int | None = None, # int(11)
        distance: float | None = None, # float(11)
        game_version: str | None = None, # varchar(255)
        date_added: int | None = None, # int(11)
        date_modified: int | None = None, # int(11)
        star_system_name: str | None = None, # varchar(255)
        orbit_origin_name: str | None = None, # varchar(255)
        orbit_destination_name: str | None = None, # varchar(255)
        load: bool = False,
    ):
        super().__init__("orbit_distance")
        self.data = {
            "id": id,
            "id_star_system_origin": id_star_system_origin,
            "id_star_system_destination": id_star_system_destination,
            "id_orbit_origin": id_orbit_origin,
            "id_orbit_destination": id_orbit_destination,
            "distance": distance,
            "game_version": game_version,
            "date_added": date_added,
            "date_modified": date_modified,
            "star_system_name": star_system_name,
            "orbit_origin_name": orbit_origin_name,
            "orbit_destination_name": orbit_destination_name,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["id"]:
                raise Exception("ID is required to load data")
            self.load_by_value("id", self.data["id"])

    def get_data_for_ai(self) -> dict:
        try:
            from skills.uexcorp.uexcorp.model.star_system import StarSystem
            from skills.uexcorp.uexcorp.model.orbit import Orbit
        except ModuleNotFoundError:
            from uexcorp.uexcorp.model.star_system import StarSystem
            from uexcorp.uexcorp.model.orbit import Orbit

        star_system_origin = StarSystem(self.get_id_star_system_origin(), load=True) if self.get_id_star_system_origin() else None
        star_system_destination = StarSystem(self.get_id_star_system_destination(), load=True) if self.get_id_star_system_destination() else None
        orbit_origin = Orbit(self.get_id_orbit_origin(), load=True) if self.get_id_orbit_origin() else None
        orbit_destination = Orbit(self.get_id_orbit_destination(), load=True) if self.get_id_orbit_destination() else None

        information = {
            "star_system_origin": star_system_origin.get_data_for_ai_minimal() if star_system_origin else None,
            "star_system_destination": star_system_destination.get_data_for_ai_minimal() if star_system_destination else None,
            "orbit_origin": orbit_origin.get_data_for_ai_minimal() if orbit_origin else None,
            "orbit_destination": orbit_destination.get_data_for_ai_minimal() if orbit_destination else None,
            "distance_in_giga_meters": self.get_distance(),
        }

        return information

    def get_data_for_ai_minimal(self) -> dict:
        try:
            from skills.uexcorp.uexcorp.model.star_system import StarSystem
        except ModuleNotFoundError:
            from uexcorp.uexcorp.model.star_system import StarSystem

        star_system_origin = StarSystem(self.get_id_star_system_origin(), load=True) if self.get_id_star_system_origin() else None
        star_system_destination = StarSystem(self.get_id_star_system_destination(), load=True) if self.get_id_star_system_destination() else None

        return {
            "star_system_origin": str(star_system_origin) if star_system_origin else None,
            "star_system_destination": str(star_system_destination) if star_system_destination else None,
            "orbit_origin": self.get_orbit_origin_name(),
            "orbit_destination": self.get_orbit_destination_name(),
            "distance_in_giga_meters": self.get_distance(),
        }

    def get_id(self) -> int:
        return self.data["id"]

    def get_id_star_system_origin(self) -> int | None:
        return self.data["id_star_system_origin"]

    def get_id_star_system_destination(self) -> int | None:
        return self.data["id_star_system_destination"]

    def get_id_orbit_origin(self) -> int | None:
        return self.data["id_orbit_origin"]

    def get_id_orbit_destination(self) -> int | None:
        return self.data["id_orbit_destination"]

    def get_distance(self) -> float | None:
        return self.data["distance"]

    def get_game_version(self) -> str | None:
        return self.data["game_version"]

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

    def get_orbit_origin_name(self) -> str | None:
        return self.data["orbit_origin_name"]

    def get_orbit_destination_name(self) -> str | None:
        return self.data["orbit_destination_name"]

    def __str__(self):
        return f"Orbit Distance from {self.data['orbit_origin_name']} to {self.data['orbit_destination_name']}"
