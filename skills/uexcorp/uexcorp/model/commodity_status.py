from skills.uexcorp.uexcorp.model.data_model import DataModel

class CommodityStatus(DataModel):

    required_keys = ["code"]

    def __init__(
            self,
            code: int, # int(11)
            is_buy: bool, # int(1)
            name: str | None = None, # string(255)
            name_short: str | None = None, # string(255)
            name_abbr: str | None = None, # string(255)
            percentage: str | None = None, # string(255)
            colors: str | None = None, # string(255)
            load: bool = False,
    ):
        super().__init__("commodity_status")
        self.data = {
            "code": code,
            "name": name,
            "name_short": name_short,
            "name_abbr": name_abbr,
            "percentage": percentage,
            "colors": colors,
            "is_buy": is_buy,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["code"] or self.data["is_buy"] is None:
                raise Exception("code and is_buy is required to load data")
            self.load_by_value("code", self.data["code"], "is_buy", self.data["is_buy"])

    def get_data_for_ai(self) -> dict:
        return {
            "name": self.get_name(),
            "percentage": self.get_percentage(),
            "type": "buy (higher inventory means more can be bought here and is better)" if self.get_is_buy() else "sell (lower inventory means higher demand and is better)",
        }

    def get_data_for_ai_minimal(self) -> dict:
        return self.get_data_for_ai()

    def get_code(self) -> str:
        return self.data["code"]

    def get_is_buy(self) -> bool:
        return self.data["is_buy"]

    def get_name(self) -> str:
        return self.data["name"]

    def get_name_short(self) -> str:
        return self.data["name_short"]

    def get_name_abbr(self) -> str:
        return self.data["name_abbr"]

    def get_percentage(self) -> str:
        return self.data["percentage"]

    def get_colors(self) -> str:
        return self.data["color_sell"]

    def __str__(self):
        return f"{self.get_name_short()} ({self.get_percentage()})"
