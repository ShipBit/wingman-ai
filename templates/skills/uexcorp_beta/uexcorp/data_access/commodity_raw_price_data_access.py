try:
    from skills.uexcorp_beta.uexcorp.data_access.data_access import DataAccess
    from skills.uexcorp_beta.uexcorp.model.commodity_raw_price import CommodityRawPrice
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.data_access.data_access import DataAccess
    from uexcorp_beta.uexcorp.model.commodity_raw_price import CommodityRawPrice


class CommodityRawPriceDataAccess(DataAccess):
    def __init__(
            self,
    ):
        super().__init__(
            table="commodity_raw_price",
            model=CommodityRawPrice
        )
        self.fields = [
            "id",
            "id_commodity",
            "id_terminal",
            "price_sell",
            "price_sell_avg",
            "date_added",
            "date_modified",
            "commodity_name",
            "commodity_code",
            "commodity_slug",
            "terminal_name",
            "terminal_code",
            "terminal_slug",
        ]

    def load(self, **params) -> list[CommodityRawPrice]:
        return super().load(**params)

    def load_by_property(self, property: str, value: any) -> CommodityRawPrice | None:
        return super().load_by_property(property, value)

    def add_filter_by_id_commodity(self, id_commodity: int | list[int], **params) -> "CommodityRawPriceDataAccess":
        self.filter.where("id_commodity", id_commodity, **params)
        return self

    def add_filter_by_id_terminal(self, id_terminal: int | list[int], **params) -> "CommodityRawPriceDataAccess":
        self.filter.where("id_terminal", id_terminal, **params)
        return self

    def add_filter_by_price_sell(self, price_sell: float | list[float], **params) -> "CommodityRawPriceDataAccess":
        self.filter.where("price_sell", price_sell, **params)
        return self

    def add_filter_by_price_sell_avg(self, price_sell_avg: float | list[float], **params) -> "CommodityRawPriceDataAccess":
        self.filter.where("price_sell_avg", price_sell_avg, **params)
        return self

    def add_filter_by_date_added(self, date_added: int | list[int], **params) -> "CommodityRawPriceDataAccess":
        self.filter.where("date_added", date_added, **params)
        return self

    def add_filter_by_date_modified(self, date_modified: int | list[int], **params) -> "CommodityRawPriceDataAccess":
        self.filter.where("date_modified", date_modified, **params)
        return self

    def add_filter_by_commodity_name(self, commodity_name: str | list[str], **params) -> "CommodityRawPriceDataAccess":
        self.filter.where("commodity_name", commodity_name, **params)
        return self

    def add_filter_by_commodity_code(self, commodity_code: str | list[str], **params) -> "CommodityRawPriceDataAccess":
        self.filter.where("commodity_code", commodity_code, **params)
        return self

    def add_filter_by_commodity_slug(self, commodity_slug: str | list[str], **params) -> "CommodityRawPriceDataAccess":
        self.filter.where("commodity_slug", commodity_slug, **params)
        return self

    def add_filter_by_terminal_name(self, terminal_name: str | list[str], **params) -> "CommodityRawPriceDataAccess":
        self.filter.where("terminal_name", terminal_name, **params)
        return self

    def add_filter_by_terminal_code(self, terminal_code: str | list[str], **params) -> "CommodityRawPriceDataAccess":
        self.filter.where("terminal_code", terminal_code, **params)
        return self

    def add_filter_by_terminal_slug(self, terminal_slug: str | list[str], **params) -> "CommodityRawPriceDataAccess":
        self.filter.where("terminal_slug", terminal_slug, **params)
        return self
