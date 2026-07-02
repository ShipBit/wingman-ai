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

    # The raw UEX status names describe the terminal's fill level ("High
    # Inventory", "Out of Stock") for both trade directions. On sell options
    # that reading is inverted for the player - a full terminal is the WORST
    # place to sell - and LLMs regularly trip over it. So never expose the raw
    # names to the AI; translate the code into what the player cares about:
    # stock when buying, demand when selling.
    _BUY_STOCK_LABELS = {
        1: "out of stock",
        2: "very low stock",
        3: "low stock",
        4: "medium stock",
        5: "high stock",
        6: "very high stock",
        7: "full stock",
    }
    _SELL_DEMAND_LABELS = {
        1: "extremely high demand",
        2: "very high demand",
        3: "high demand",
        4: "medium demand",
        5: "low demand",
        6: "very low demand",
        7: "no demand",
    }

    def get_data_for_ai(self) -> dict:
        return {
            "status": self.get_data_for_ai_minimal(),
            "type": "buy" if self.get_is_buy() else "sell",
        }

    def get_data_for_ai_minimal(self) -> str:
        labels = self._BUY_STOCK_LABELS if self.get_is_buy() else self._SELL_DEMAND_LABELS
        label = labels.get(self.get_code())
        if label is None:
            if self.get_percentage() is not None:
                return f"{self.get_name()} ({self.get_percentage()})"
            return self.get_name()
        if self.get_percentage() is not None:
            if self.get_is_buy():
                return f"{label} ({self.get_percentage()})"
            return f"{label} (terminal {self.get_percentage()} full)"
        return label

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
