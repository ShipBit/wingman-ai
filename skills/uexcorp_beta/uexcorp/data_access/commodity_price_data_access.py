try:
    from skills.uexcorp_beta.uexcorp.data_access.data_access import DataAccess
    from skills.uexcorp_beta.uexcorp.model.commodity_price import CommodityPrice
except ImportError:
    from uexcorp_beta.uexcorp.data_access.data_access import DataAccess
    from uexcorp_beta.uexcorp.model.commodity_price import CommodityPrice


class CommodityPriceDataAccess(DataAccess):
    def __init__(
            self,
    ):
        super().__init__(
            table="commodity_price",
            model=CommodityPrice
        )
        self.fields = [
            "id",
            "id_commodity",
            "id_terminal",
            "price_buy",
            "price_buy_avg",
            "price_sell",
            "price_sell_avg",
            "scu_buy",
            "scu_buy_avg",
            "scu_sell_stock",
            "scu_sell_stock_avg",
            "scu_sell",
            "scu_sell_avg",
            "status_buy",
            "status_sell",
            "date_added",
            "date_modified",
            "commodity_name",
            "commodity_code",
            "commodity_slug",
            "terminal_name",
            "terminal_code",
            "terminal_slug",
        ]

    def load(self, **params) -> list[CommodityPrice]:
        return super().load(**params)

    def load_by_property(self, property: str, value: any) -> CommodityPrice | None:
        return super().load_by_property(property, value)

    def add_filter_by_id_commodity(self, id_commodity: int | list[int], **params) -> "CommodityPriceDataAccess":
        self.filter.where("id_commodity", id_commodity, **params)
        return self

    def add_filter_by_id_terminal(self, id_terminal: int | list[int], **params) -> "CommodityPriceDataAccess":
        self.filter.where("id_terminal", id_terminal, **params)
        return self

    def add_filter_by_price_buy(self, price_buy: float | list[float], **params) -> "CommodityPriceDataAccess":
        self.filter.where("price_buy", price_buy, **params)
        return self

    def add_filter_by_price_buy_avg(self, price_buy_avg: float | list[float], **params) -> "CommodityPriceDataAccess":
        self.filter.where("price_buy_avg", price_buy_avg, **params)
        return self

    def add_filter_by_price_sell(self, price_sell: float | list[float], **params) -> "CommodityPriceDataAccess":
        self.filter.where("price_sell", price_sell, **params)
        return self

    def add_filter_by_price_sell_avg(self, price_sell_avg: float | list[float], **params) -> "CommodityPriceDataAccess":
        self.filter.where("price_sell_avg", price_sell_avg, **params)
        return self

    def add_filter_by_scu_buy(self, scu_buy: float | list[float], **params) -> "CommodityPriceDataAccess":
        self.filter.where("scu_buy", scu_buy, **params)
        return self

    def add_filter_by_scu_buy_avg(self, scu_buy_avg: float | list[float], **params) -> "CommodityPriceDataAccess":
        self.filter.where("scu_buy_avg", scu_buy_avg, **params)
        return self

    def add_filter_by_scu_sell_stock(self, scu_sell_stock: float | list[float], **params) -> "CommodityPriceDataAccess":
        self.filter.where("scu_sell_stock", scu_sell_stock, **params)
        return self

    def add_filter_by_scu_sell_stock_avg(self, scu_sell_stock_avg: float | list[float], **params) -> "CommodityPriceDataAccess":
        self.filter.where("scu_sell_stock_avg", scu_sell_stock_avg, **params)
        return self

    def add_filter_by_scu_sell(self, scu_sell: float | list[float], **params) -> "CommodityPriceDataAccess":
        self.filter.where("scu_sell", scu_sell, **params)
        return self

    def add_filter_by_scu_sell_avg(self, scu_sell_avg: float | list[float], **params) -> "CommodityPriceDataAccess":
        self.filter.where("scu_sell_avg", scu_sell_avg, **params)
        return self

    def add_filter_by_status_buy(self, status_buy: int | list[int], **params) -> "CommodityPriceDataAccess":
        self.filter.where("status_buy", status_buy, **params)
        return self

    def add_filter_by_status_sell(self, status_sell: int | list[int], **params) -> "CommodityPriceDataAccess":
        self.filter.where("status_sell", status_sell, **params)
        return self

    def add_filter_by_date_added(self, date_added: int | list[int], **params) -> "CommodityPriceDataAccess":
        self.filter.where("date_added", date_added, **params)
        return self

    def add_filter_by_date_modified(self, date_modified: int | list[int], **params) -> "CommodityPriceDataAccess":
        self.filter.where("date_modified", date_modified, **params)
        return self

    def add_filter_by_commodity_name(self, commodity_name: str | list[str], **params) -> "CommodityPriceDataAccess":
        self.filter.where("commodity_name", commodity_name, **params)
        return self

    def add_filter_by_commodity_code(self, commodity_code: str | list[str], **params) -> "CommodityPriceDataAccess":
        self.filter.where("commodity_code", commodity_code, **params)
        return self

    def add_filter_by_commodity_slug(self, commodity_slug: str | list[str], **params) -> "CommodityPriceDataAccess":
        self.filter.where("commodity_slug", commodity_slug, **params)
        return self

    def add_filter_by_terminal_name(self, terminal_name: str | list[str], **params) -> "CommodityPriceDataAccess":
        self.filter.where("terminal_name", terminal_name, **params)
        return self

    def add_filter_by_terminal_code(self, terminal_code: str | list[str], **params) -> "CommodityPriceDataAccess":
        self.filter.where("terminal_code", terminal_code, **params)
        return self

    def add_filter_by_terminal_slug(self, terminal_slug: str | list[str], **params) -> "CommodityPriceDataAccess":
        self.filter.where("terminal_slug", terminal_slug, **params)
        return self
