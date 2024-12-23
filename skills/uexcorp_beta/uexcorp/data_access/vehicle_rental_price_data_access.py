try:
    from skills.uexcorp_beta.uexcorp.data_access.data_access import DataAccess
    from skills.uexcorp_beta.uexcorp.model.vehicle_rental_price import VehicleRentalPrice
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.data_access.data_access import DataAccess
    from uexcorp_beta.uexcorp.model.vehicle_rental_price import VehicleRentalPrice


class VehicleRentalPriceDataAccess(DataAccess):
    def __init__(
            self,
    ):
        super().__init__(
            table="vehicle_purchase_price",
            model=VehicleRentalPrice
        )
        self.fields = [
            "id",
            "id_vehicle",
            "id_terminal",
            "price_buy",
            "date_added",
            "date_modified",
            "vehicle_name",
            "terminal_name",
        ]

    def load(self, **params) -> list[VehicleRentalPrice]:
        return super().load(**params)

    def add_filter_by_id_vehicle(self, id_vehicle: int | list[int]) -> "VehicleRentalPriceDataAccess":
        self.filter.where("id_vehicle", id_vehicle)
        return self

    def add_filter_by_id_terminal(self, id_terminal: int | list[int]) -> "VehicleRentalPriceDataAccess":
        self.filter.where("id_terminal", id_terminal)
        return self

    def add_filter_by_price_buy(self, price_buy: float | list[float]) -> "VehicleRentalPriceDataAccess":
        self.filter.where("price_buy", price_buy)
        return self

    def add_filter_by_date_added(self, date_added: int | list[int]) -> "VehicleRentalPriceDataAccess":
        self.filter.where("date_added", date_added)
        return self

    def add_filter_by_date_modified(self, date_modified: int | list[int]) -> "VehicleRentalPriceDataAccess":
        self.filter.where("date_modified", date_modified)
        return self

    def add_filter_by_vehicle_name(self, vehicle_name: str | list[str]) -> "VehicleRentalPriceDataAccess":
        self.filter.where("vehicle_name", vehicle_name)
        return self

    def add_filter_by_terminal_name(self, terminal_name: str | list[str]) -> "VehicleRentalPriceDataAccess":
        self.filter.where("terminal_name", terminal_name)
        return self
