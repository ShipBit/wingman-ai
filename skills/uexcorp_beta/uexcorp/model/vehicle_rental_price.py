from datetime import datetime
try:
    from skills.uexcorp_beta.uexcorp.model.data_model import DataModel
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.model.data_model import DataModel

class VehicleRentalPrice(DataModel):

    required_keys = ["id"]

    def __init__(
            self,
            id: int, # int(11)
            id_vehicle: int | None = None,  # int(11)
            id_terminal: int | None = None,  # int(11)
            price_rent: float | None = None,  # float(11)
            date_added: int | None = None, # int(11)
            date_modified: int | None = None, # int(11)
            vehicle_name: str | None = None,  # varchar(255)
            terminal_name: str | None = None,  # varchar(255)
            load: bool = False,
    ):
        super().__init__("vehicle_rental_price")
        self.data = {
            "id": id,
            "id_vehicle": id_vehicle,
            "id_terminal": id_terminal,
            "price_rent": price_rent,
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

    def get_data_for_ai(self, show_vehicle_data: bool = True) -> dict:
        try:
            from skills.uexcorp_beta.uexcorp.model.vehicle import Vehicle
            from skills.uexcorp_beta.uexcorp.model.terminal import Terminal
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.model.vehicle import Vehicle
            from uexcorp_beta.uexcorp.model.terminal import Terminal


        terminal = Terminal(self.get_id_terminal(), load=True) if self.get_id_terminal() else None

        information = {
            "terminal": terminal.get_data_for_ai_minimal() if terminal else None,
            "price_rent": self.get_price_rent(),
        }

        if show_vehicle_data:
            vehicle = Vehicle(self.get_id_vehicle(), load=True) if self.get_id_vehicle() else None
            information.update({
                "vehicle": vehicle.get_data_for_ai_minimal() if vehicle else None,
            })

        return information

    def get_data_for_ai_minimal(self) -> dict:
        return {
            "terminal": self.get_terminal_name(),
            "vehicle": self.get_vehicle_name(),
            "price_rent": self.get_price_rent(),
        }

    def get_id(self) -> int:
        return self.data["id"]

    def get_id_vehicle(self) -> int | None:
        return self.data["id_vehicle"]

    def get_id_terminal(self) -> int | None:
        return self.data["id_terminal"]

    def get_price_rent(self) -> float | None:
        return self.data["price_rent"]

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
        return f"Rent {self.get_vehicle_name()} at {self.get_terminal_name()} for {self.get_price_rent()}"