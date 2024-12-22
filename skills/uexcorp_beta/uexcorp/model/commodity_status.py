try:
    from skills.uexcorp_beta.uexcorp.model.data_model import DataModel
except ImportError:
    from uexcorp_beta.uexcorp.model.data_model import DataModel

class CommodityStatus(DataModel):

    required_keys = ["code"]

    def __init__(
            self,
            code: str, # string(255)
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
            if not self.data["code"] or not self.data["is_buy"]:
                raise Exception("code and is_buy is required to load data")
            self.load_by_value("code", self.data["code"], "is_buy", self.data["is_buy"])

    def get_data_for_ai(self) -> dict:
        return {
            "name": self.get_name(),
            "percentage": self.get_percentage(),
            "type": "buy" if self.get_is_buy() else "sell",
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
        return str(self.data["name"])
