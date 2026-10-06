from datetime import datetime
from skills.uexcorp.uexcorp.model.data_model import DataModel

class CommodityPrice(DataModel):

    required_keys = ["id"]

    def __init__(
            self,
            id: int, # int(11)
            id_commodity: int | None = None, # int(11)
            id_terminal: int | None = None, # int(11)
            price_buy: float | None = None, # float(11)
            price_buy_avg: float | None = None, # float(11)
            price_sell: float | None = None, # float(11)
            price_sell_avg: float | None = None, # float(11)
            scu_buy: float | None = None, # float(11)
            scu_buy_avg: float | None = None, # float(11)
            scu_sell_stock: float | None = None, # float(11)
            scu_sell_stock_avg: float | None = None, # float(11)
            scu_sell: float | None = None, # float(11)
            scu_sell_avg: float | None = None, # float(11)
            status_buy: int | None = None, # int(11)
            status_sell: int | None = None, # int(11)
            date_added: int | None = None, # int(11)
            date_modified: int | None = None, # int(11)
            commodity_name: str | None = None, # string(255)
            commodity_code: str | None = None, # string(255)
            commodity_slug: str | None = None, # string(255)
            terminal_name: str | None = None, # string(255)
            terminal_code: str | None = None, # string(255)
            terminal_slug: str | None = None, # string(255)
            load: bool = False,
    ):
        super().__init__("commodity_price")
        self.data = {
            "id": id,
            "id_commodity": id_commodity,
            "id_terminal": id_terminal,
            "price_buy": price_buy,
            "price_buy_avg": price_buy_avg,
            "price_sell": price_sell,
            "price_sell_avg": price_sell_avg,
            "scu_buy": scu_buy,
            "scu_buy_avg": scu_buy_avg,
            "scu_sell_stock": scu_sell_stock,
            "scu_sell_stock_avg": scu_sell_stock_avg,
            "scu_sell": scu_sell,
            "scu_sell_avg": scu_sell_avg,
            "status_buy": status_buy,
            "status_sell": status_sell,
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
        from skills.uexcorp.uexcorp.model.terminal import Terminal
        from skills.uexcorp.uexcorp.model.commodity_status import CommodityStatus

        terminal = Terminal(self.get_id_terminal(), load=True) if self.get_id_terminal() else None

        commodity_status_buy = CommodityStatus(self.get_status_buy(), True, load=True) if self.get_status_buy() else None
        commodity_status_sell = CommodityStatus(self.get_status_sell(), False, load=True) if self.get_status_sell() else None

        return {
            "commodity": self.get_commodity_name(),
            "terminal": terminal.get_ai_location_string() if terminal else self.get_terminal_name(),
            "buy_price_from_terminal": self.get_price_buy(),
            "sell_price_to_terminal": self.get_price_sell(),
            "buy_status": commodity_status_buy.get_data_for_ai_minimal() if commodity_status_buy else None,
            "sell_status": commodity_status_sell.get_data_for_ai_minimal() if commodity_status_sell else None,
            "buy_stock_in_scu": self.get_scu_buy(),
            "buy_stock_in_scu_avg": self.get_scu_buy_avg(),
            "sell_demand_in_scu": self.get_scu_sell_stock(),
            "sell_demand_in_scu_avg": self.get_scu_sell_stock_avg(),
        }

    def get_data_for_ai_minimal(self, show_terminal_information: bool = True, show_commodity_information: bool = True) -> dict:
        from skills.uexcorp.uexcorp.model.terminal import Terminal
        from skills.uexcorp.uexcorp.model.commodity_status import CommodityStatus

        commodity_status_buy = CommodityStatus(self.get_status_buy(), True, load=True) if self.get_status_buy() else None
        commodity_status_sell = CommodityStatus(self.get_status_sell(), False, load=True) if self.get_status_sell() else None

        information = {}

        if show_commodity_information:
            # Name only: embedding the full commodity view here would drag in
            # that commodity's buy/sell options at every other terminal.
            information["commodity"] = self.get_commodity_name()

        if show_terminal_information:
            terminal = Terminal(self.get_id_terminal(), load=True) if self.get_id_terminal() else None
            information["terminal"] = terminal.get_ai_location_string() if terminal else self.get_terminal_name()

        if self.get_price_buy():
            information.update({
                "buy_price_from_terminal": self.get_price_buy(),
                "buy_status": commodity_status_buy.get_data_for_ai_minimal() if commodity_status_buy else None,
                "buy_stock_in_scu": self.get_scu_buy(),
            })

        if self.get_price_sell():
            information.update({
                "sell_price_to_terminal": self.get_price_sell(),
                "sell_status": commodity_status_sell.get_data_for_ai_minimal() if commodity_status_sell else None,
                "sell_demand_in_scu": self.get_scu_sell_stock(),
            })

        return information

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

    def get_price_sell(self) -> float | None:
        return self.data["price_sell"]

    def get_price_sell_avg(self) -> float | None:
        return self.data["price_sell_avg"]

    def get_scu_buy(self) -> float | None:
        return self.data["scu_buy"]

    def get_scu_buy_avg(self) -> float | None:
        return self.data["scu_buy_avg"]

    def get_scu_sell_stock(self) -> float | None:
        return self.data["scu_sell_stock"]

    def get_scu_sell_stock_avg(self) -> float | None:
        return self.data["scu_sell_stock_avg"]

    def get_scu_sell(self) -> float | None:
        return self.data["scu_sell"]

    def get_scu_sell_avg(self) -> float | None:
        return self.data["scu_sell_avg"]

    def get_status_buy(self) -> int | None:
        return self.data["status_buy"]

    def get_status_sell(self) -> int | None:
        return self.data["status_sell"]

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

    def get_ai_string(self, show_commodity: bool = True) -> str:
        # show_commodity=False when embedded under the commodity itself, so the
        # name is not repeated in every option line.
        commodity = f" {self.get_commodity_name()}" if show_commodity else ""
        if self.get_price_sell():
            return f"Sell{commodity} to {self.get_terminal_name()} for {self.get_price_sell()}"
        return f"Buy{commodity} from {self.get_terminal_name()} for {self.get_price_buy()}"

    def __str__(self):
        return self.get_ai_string()
