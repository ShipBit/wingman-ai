from skills.uexcorp_beta.uexcorp.data_access.data_access import DataAccess
from skills.uexcorp_beta.uexcorp.model.vehicle_purchase_price import VehiclePurchasePrice


class VehiclePurchasePriceDataAccess(DataAccess):
    def __init__(
            self,
    ):
        super().__init__(
            table="vehicle_purchase_price",
            model=VehiclePurchasePrice
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

    def load(self) -> list[VehiclePurchasePrice]:
        return super().load()

    def add_filter_by_id_vehicle(self, id_vehicle: int | list[int]) -> "VehiclePurchasePriceDataAccess":
        self.filter.where("id_vehicle", id_vehicle)
        return self

    def add_filter_by_id_terminal(self, id_terminal: int | list[int]) -> "VehiclePurchasePriceDataAccess":
        self.filter.where("id_terminal", id_terminal)
        return self
