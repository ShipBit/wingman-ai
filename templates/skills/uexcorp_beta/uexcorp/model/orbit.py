from datetime import datetime
from skills.uexcorp_beta.uexcorp.model.data_model import DataModel

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