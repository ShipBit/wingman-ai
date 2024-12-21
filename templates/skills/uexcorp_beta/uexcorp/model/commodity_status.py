from datetime import datetime
from skills.uexcorp_beta.uexcorp.model.data_model import DataModel

class CommodityStatus(DataModel):

    required_keys = ["code"]

    def __init__(
            self,
            code: str, # string(255)
            name: str | None = None, # string(255)
            name_short: str | None = None, # string(255)
            name_abbr: str | None = None, # string(255)
            percentage: str | None = None, # string(255)
            color_buy: str | None = None, # string(255)
            color_sell: str | None = None, # string(255)
            load: bool = False,
    ):
        super().__init__("commodity_status")
        self.data = {
            "code": code,
            "name": name,
            "name_short": name_short,
            "name_abbr": name_abbr,
            "percentage": percentage,
            "color_buy": color_buy,
            "color_sell": color_sell,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["code"]:
                raise Exception("code is required to load data")
            self.load_by_value("code", self.data["code"])

    def get_code(self) -> str:
        return self.data["code"]

    def get_name(self) -> str:
        return self.data["name"]

    def get_name_short(self) -> str:
        return self.data["name_short"]

    def get_name_abbr(self) -> str:
        return self.data["name_abbr"]

    def get_percentage(self) -> str:
        return self.data["percentage"]

    def get_color_buy(self) -> str:
        return self.data["color_buy"]

    def get_color_sell(self) -> str:
        return self.data["color_sell"]

    def __str__(self):
        return str(self.data["name"])
