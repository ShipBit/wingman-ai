from datetime import datetime
try:
    from skills.uexcorp_beta.uexcorp.model.data_model import DataModel
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.model.data_model import DataModel

class FuelPrice(DataModel):

    required_keys = ["id"]

    def __init__(
            self,
            id: int, # int(11)
            id_commodity: int | None = None,  # int(11)
            id_terminal: int | None = None,  # int(11)
            price_buy: float | None = None,  # float(11) // last reported price per SCU
            price_buy_avg: float | None = None,  # float(11) // average price per SCU
            date_added: int | None = None,  # int(11) // timestamp, first time added
            date_modified: int | None = None,  # int(11) // timestamp, last price update
            commodity_name: str | None = None,  # string(255)
            commodity_code: str | None = None,  # string(255)
            commodity_slug: str | None = None,  # string(255)
            terminal_name: str | None = None,  # string(255)
            terminal_code: str | None = None,  # string(255)
            terminal_slug: str | None = None,  # string(255)
            load: bool = False,
    ):
        super().__init__("fuel_price")
        self.data = {
            "id": id,
            "id_commodity": id_commodity,
            "id_terminal": id_terminal,
            "price_buy": price_buy,
            "price_buy_avg": price_buy_avg,
            "date_added": date_added,
            "date_modified": date_modified,
            "commodity_name": commodity_name,
            "commodity_code": commodity_code,
            "commodity_slug": commodity_slug,
            "terminal_name": terminal_name,
            "terminal_code": terminal_code,
            "terminal_slug": terminal_slug,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["id"]:
                raise Exception("ID is required to load data")
            self.load_by_value("id", self.data["id"])

    def get_data_for_ai(self) -> dict:
        try:
            from skills.uexcorp_beta.uexcorp.model.commodity import Commodity
            from skills.uexcorp_beta.uexcorp.model.terminal import Terminal
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.model.commodity import Commodity
            from uexcorp_beta.uexcorp.model.terminal import Terminal

        commodity = Commodity(self.get_id_commodity(), load=True) if self.get_id_commodity() else None
        terminal = Terminal(self.get_id_terminal(), load=True) if self.get_id_terminal() else None

        return {
            "commodity": commodity.get_data_for_ai_minimal() if commodity else None,
            "terminal": terminal.get_data_for_ai_minimal() if terminal else None,
            "price_buy": self.get_price_buy(),
            "price_buy_avg": self.get_price_buy_avg(),
        }

    def get_data_for_ai_minimal(self) -> dict:
        return {
            "commodity": self.get_commodity_name(),
            "terminal": self.get_terminal_name(),
            "price_buy": self.get_price_buy(),
        }

    def get_id(self) -> int:
        return self.data["id"]

    def get_id_commodity(self) -> int | None:
        return self.data["id_commodity"]

    def get_id_terminal(self) -> int | None:
        return self.data["id_terminal"]

    def get_price_buy(self) -> float | None:
        return self.data["price_buy"]

    def get_price_buy_avg(self) -> float | None:
        return self.data["price_buy_avg"]

    def get_date_added(self) -> int | None:
        return self.data["date_added"]

    def get_date_added_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_added"])

    def get_date_modified(self) -> int | None:
        return self.data["date_modified"]

    def get_date_modified_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_modified"])

    def get_commodity_name(self) -> str | None:
        return self.data["commodity_name"]

    def get_commodity_code(self) -> str | None:
        return self.data["commodity_code"]

    def get_commodity_slug(self) -> str | None:
        return self.data["commodity_slug"]

    def get_terminal_name(self) -> str | None:
        return self.data["terminal_name"]

    def get_terminal_code(self) -> str | None:
        return self.data["terminal_code"]

    def get_terminal_slug(self) -> str | None:
        return self.data["terminal_slug"]

    def __str__(self):
        return f"{self.data['commodity_name']} at {self.data['terminal_name']}"
