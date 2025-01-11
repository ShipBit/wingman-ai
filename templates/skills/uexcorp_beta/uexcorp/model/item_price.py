from datetime import datetime
try:
    from skills.uexcorp_beta.uexcorp.model.data_model import DataModel
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.model.data_model import DataModel

class ItemPrice(DataModel):

    required_keys = ["id"]

    def __init__(
            self,
            id: int, # int(11)
            id_item: int | None = None,  # int(11)
            id_terminal: int | None = None,  # int(11)
            id_category: int | None = None,  # int(11)
            price_buy: float | None = None,  # float(11)
            price_sell: float | None = None,  # float(11)
            date_added: int | None = None, # int(11)
            date_modified: int | None = None, # int(11)
            item_name: str | None = None,  # varchar(255)
            item_uuid: str | None = None,  # varchar(255)
            terminal_name: str | None = None,  # varchar(255)
            load: bool = False,
    ):
        super().__init__("item_price")
        self.data = {
            "id": id,
            "id_item": id_item,
            "id_terminal": id_terminal,
            "id_category": id_category,
            "price_buy": price_buy,
            "price_sell": price_sell,
            "date_added": date_added,
            "date_modified": date_modified,
            "item_name": item_name,
            "item_uuid": item_uuid,
            "terminal_name": terminal_name,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["id"]:
                raise Exception("ID is required to load data")
            self.load_by_value("id", self.data["id"])

    def get_data_for_ai(self) -> dict:
        try:
            from skills.uexcorp_beta.uexcorp.model.item import Item
            from skills.uexcorp_beta.uexcorp.model.terminal import Terminal
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.model.item import Item
            from uexcorp_beta.uexcorp.model.terminal import Terminal

        terminal = Terminal(self.get_id_terminal(), load=True) if self.get_id_terminal() else None
        item = Item(self.get_id_item(), load=True) if self.get_id_item() else None

        return {
            "terminal": terminal.get_data_for_ai_minimal() if terminal else None,
            "item": item.get_data_for_ai_minimal() if item else None,
            "price_buy": self.get_price_buy(),
            "price_sell": self.get_price_sell(),
        }

    def get_data_for_ai_minimal(self) -> dict:
        return {
            "terminal": self.get_terminal_name(),
            "item_name": self.get_item_name(),
            "price_buy": self.get_price_buy(),
            "price_sell": self.get_price_sell(),
        }

    def get_id(self) -> int:
        return self.data["id"]

    def get_id_item(self) -> int | None:
        return self.data["id_item"]

    def get_id_terminal(self) -> int | None:
        return self.data["id_terminal"]

    def get_id_category(self) -> int | None:
        return self.data["id_category"]

    def get_price_buy(self) -> float | None:
        return self.data["price_buy"]

    def get_price_sell(self) -> float | None:
        return self.data["price_sell"]

    def get_date_added(self) -> int | None:
        return self.data["date_added"]

    def get_date_added_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_added"])

    def get_date_modified(self) -> int | None:
        return self.data["date_modified"]

    def get_date_modified_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_modified"])

    def get_item_name(self) -> str | None:
        return self.data["item_name"]

    def get_item_uuid(self) -> str | None:
        return self.data["item_uuid"]

    def get_terminal_name(self) -> str | None:
        return self.data["terminal_name"]

    def __str__(self):
        return f"{self.data['item_name']} at {self.data['terminal_name']}: Buy {self.data['price_buy']}, Sell {self.data['price_sell']}"