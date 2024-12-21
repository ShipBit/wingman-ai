from skills.uexcorp_beta.uexcorp.data_access.data_access import DataAccess
from skills.uexcorp_beta.uexcorp.model.vehicle_rental_price import VehicleRentalPrice


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

    def load(self) -> list[VehicleRentalPrice]:
        return super().load()

    def add_filter_by_id_vehicle(self, id_vehicle: int | list[int]) -> "VehicleRentalPriceDataAccess":
        self.filter.where("id_vehicle", id_vehicle)
        return self

    def add_filter_by_id_terminal(self, id_terminal: int | list[int]) -> "VehicleRentalPriceDataAccess":
        self.filter.where("id_terminal", id_terminal)
        return self
