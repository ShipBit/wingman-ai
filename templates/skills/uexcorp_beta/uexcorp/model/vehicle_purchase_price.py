from datetime import datetime
from skills.uexcorp_beta.uexcorp.model.data_model import DataModel

class VehiclePurchasePrice(DataModel):

    required_keys = ["id"]

    def __init__(
            self,
            id: int, # int(11)
            id_vehicle: int | None = None,  # int(11)
            id_terminal: int | None = None,  # int(11)
            price_buy: float | None = None,  # float(11)
            date_added: int | None = None, # int(11)
            date_modified: int | None = None, # int(11)
            vehicle_name: str | None = None,  # varchar(255)
            terminal_name: str | None = None,  # varchar(255)
            load: bool = False,
    ):
        super().__init__("vehicle_purchase_price")
        self.data = {
            "id": id,
            "id_vehicle": id_vehicle,
            "id_terminal": id_terminal,
            "price_buy": price_buy,
            "date_added": date_added,
            "date_modified": date_modified,
            "vehicle_name": vehicle_name,
            "terminal_name": terminal_name,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["id"]:
                raise Exception("ID is required to load data")
            self.load_by_value("id", self.data["id"])

    def get_data_for_ai(self):
        return {
            "terminal_name": self.data["terminal_name"],
            "vehicle_name": self.data["vehicle_name"],
            "price_buy": self.data["price_buy"],
            "date_modified": self.get_date_modified_readable().strftime("%Y-%m-%d %H:%M:%S") if self.get_date_modified() else self.get_date_added_readable().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def get_id(self) -> int:
        return self.data["id"]

    def get_id_vehicle(self) -> int | None:
        return self.data["id_vehicle"]

    def get_id_terminal(self) -> int | None:
        return self.data["id_terminal"]

    def get_price_buy(self) -> float | None:
        return self.data["price_buy"]

    def get_date_added(self) -> int | None:
        return self.data["date_added"]

    def get_date_added_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_added"])

    def get_date_modified(self) -> int | None:
        return self.data["date_modified"]

    def get_date_modified_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_modified"])

    def get_vehicle_name(self) -> str | None:
        return self.data["vehicle_name"]

    def get_terminal_name(self) -> str | None:
        return self.data["terminal_name"]

    def __str__(self):
        return str(self.data["vehicle_name"])