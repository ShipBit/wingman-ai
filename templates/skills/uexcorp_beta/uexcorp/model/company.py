from datetime import datetime
try:
    from skills.uexcorp_beta.uexcorp.model.data_model import DataModel
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.model.data_model import DataModel

class Company(DataModel):

    required_keys = ["id"]

    def __init__(
            self,
            id: int, # int(11)
            id_faction: int | None = None, # int(11)
            name: str | None = None, # varchar(255)
            nickname: str | None = None, # varchar(255)
            wiki: str | None = None, # varchar(255)
            industry: str | None = None, # varchar(255)
            is_item_manufacturer: int | None = None, # tinyint(1)
            is_vehicle_manufacturer: int | None = None, # tinyint(1)
            date_added: int | None = None, # int(11)
            date_modified: int | None = None, # int(11)
            load: bool = False,
    ):
        super().__init__("company")
        self.data = {
            "id": id,
            "id_faction": id_faction,
            "name": name,
            "nickname": nickname,
            "wiki": wiki,
            "industry": industry,
            "is_item_manufacturer": is_item_manufacturer,
            "is_vehicle_manufacturer": is_vehicle_manufacturer,
            "date_added": date_added,
            "date_modified": date_modified,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["id"]:
                raise Exception("ID is required to load data")
            self.load_by_value("id", self.data["id"])

    def get_data_for_ai(self) -> dict:
        try:
            from skills.uexcorp_beta.uexcorp.data_access.vehicle_data_access import VehicleDataAccess
            from skills.uexcorp_beta.uexcorp.model.faction import Faction
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.data_access.vehicle_data_access import VehicleDataAccess
            from uexcorp_beta.uexcorp.model.faction import Faction

        faction = Faction(self.get_id_faction(), load=True) if self.get_id_faction() else None

        information = {
            "name": self.get_name(),
            "industry": self.get_industry(),
            "faction": faction.get_data_for_ai_minimal() if faction else None,
            "is_item_manufacturer": self.get_is_item_manufacturer(),
            "is_vehicle_manufacturer": self.get_is_vehicle_manufacturer(),
        }

        if self.get_is_vehicle_manufacturer():
            vehicles = VehicleDataAccess().add_filter_by_id_company(self.get_id()).load()
            information["vehicles"] = [vehicle.get_data_for_ai_minimal() for vehicle in vehicles]

        return information

    def get_data_for_ai_minimal(self) -> dict:
        try:
            from skills.uexcorp_beta.uexcorp.data_access.vehicle_data_access import VehicleDataAccess
            from skills.uexcorp_beta.uexcorp.model.faction import Faction
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.data_access.vehicle_data_access import VehicleDataAccess
            from uexcorp_beta.uexcorp.model.faction import Faction

        faction = Faction(self.get_id_faction(), load=True) if self.get_id_faction() else None

        information = {
            "name": self.get_name(),
            "industry": self.get_industry(),
            "faction": str(faction) if faction else None,
            "is_item_manufacturer": self.get_is_item_manufacturer(),
            "is_vehicle_manufacturer": self.get_is_vehicle_manufacturer(),
        }

        if self.get_is_vehicle_manufacturer():
            vehicles = VehicleDataAccess().add_filter_by_id_company(self.get_id()).load()
            information["vehicles"] = [str(vehicle) for vehicle in vehicles]

        return information

    def get_id(self) -> int:
        return self.data["id"]

    def get_id_faction(self) -> int:
        return self.data["id_faction"]

    def get_name(self) -> str | None:
        return self.data["name"]

    def get_nickname(self) -> str | None:
        return self.data["nickname"]

    def get_wiki(self) -> str | None:
        return self.data["wiki"]

    def get_industry(self) -> str | None:
        return self.data["industry"]

    def get_is_item_manufacturer(self) -> bool | None:
        return bool(self.data["is_item_manufacturer"])

    def get_is_vehicle_manufacturer(self) -> bool | None:
        return bool(self.data["is_vehicle_manufacturer"])

    def get_date_added(self) -> int | None:
        return self.data["date_added"]

    def get_date_added_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_added"])

    def get_date_modified(self) -> int | None:
        return self.data["date_modified"]

    def get_date_modified_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_modified"])

    def __str__(self):
        return str(self.get_name())
