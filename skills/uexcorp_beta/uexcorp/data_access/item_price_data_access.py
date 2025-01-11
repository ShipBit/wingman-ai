try:
    from skills.uexcorp_beta.uexcorp.data_access.data_access import DataAccess
    from skills.uexcorp_beta.uexcorp.model.item_price import ItemPrice
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.data_access.data_access import DataAccess
    from uexcorp_beta.uexcorp.model.item_price import ItemPrice



class ItemPriceDataAccess(DataAccess):
    def __init__(
            self,
    ):
        super().__init__(
            table="item_price",
            model=ItemPrice
        )
        self.fields = [
            "id",
            "id_item",
            "id_terminal",
            "id_category",
            "price_buy",
            "price_sell",
            "date_added",
            "date_modified",
            "item_name",
            "item_uuid",
            "terminal_name",
        ]

    def load(self, **params) -> list[ItemPrice]:
        return super().load(**params)

    def load_by_property(self, property: str, value: any) -> ItemPrice | None:
        return super().load_by_property(property, value)

    def add_filter_by_id_item(self, id_item: int | list[int], **params) -> "ItemPriceDataAccess":
        self.filter.where("id_item", id_item, **params)
        return self

    def add_filter_by_id_terminal(self, id_terminal: int | list[int], **params) -> "ItemPriceDataAccess":
        self.filter.where("id_terminal", id_terminal, **params)
        return self

    def add_filter_by_id_category(self, id_category: int | list[int], **params) -> "ItemPriceDataAccess":
        self.filter.where("id_category", id_category, **params)
        return self

    def add_filter_by_price_buy(self, price_buy: float | list[float], **params) -> "ItemPriceDataAccess":
        self.filter.where("price_buy", price_buy, **params)
        return self

    def add_filter_by_price_sell(self, price_sell: float | list[float], **params) -> "ItemPriceDataAccess":
        self.filter.where("price_sell", price_sell, **params)
        return self

    def add_filter_by_date_added(self, date_added: int | list[int], **params) -> "ItemPriceDataAccess":
        self.filter.where("date_added", date_added, **params)
        return self

    def add_filter_by_date_modified(self, date_modified: int | list[int], **params) -> "ItemPriceDataAccess":
        self.filter.where("date_modified", date_modified, **params)
        return self

    def add_filter_by_item_name(self, item_name: str | list[str], **params) -> "ItemPriceDataAccess":
        self.filter.where("item_name", item_name, **params)
        return self

    def add_filter_by_item_uuid(self, item_uuid: str | list[str], **params) -> "ItemPriceDataAccess":
        self.filter.where("item_uuid", item_uuid, **params)
        return self

    def add_filter_by_terminal_name(self, terminal_name: str | list[str], **params) -> "ItemPriceDataAccess":
        self.filter.where("terminal_name", terminal_name, **params)
        return self
