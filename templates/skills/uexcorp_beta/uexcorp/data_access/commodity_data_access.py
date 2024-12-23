try:
    from skills.uexcorp_beta.uexcorp.data_access.data_access import DataAccess
    from skills.uexcorp_beta.uexcorp.model.commodity import Commodity
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.data_access.data_access import DataAccess
    from uexcorp_beta.uexcorp.model.commodity import Commodity


class CommodityDataAccess(DataAccess):
    def __init__(
            self,
    ):
        super().__init__(
            table="commodity",
            model=Commodity
        )
        self.fields = [
            "id",
            "id_parent",
            "name",
            "code",
            "slug",
            "kind",
            "weight_scu",
            "price_buy",
            "price_sell",
            "is_available",
            "is_available_live",
            "is_visible",
            "is_raw",
            "is_refined",
            "is_mineral",
            "is_harvestable",
            "is_buyable",
            "is_sellable",
            "is_temporary",
            "is_illegal",
            "is_fuel",
            "wiki",
            "date_added",
            "date_modified",
            "is_blacklisted",
        ]

    def load(self, **params) -> list[Commodity]:
        return super().load(**params)

    def load_by_property(self, property: str, value: any) -> Commodity:
        return super().load_by_property(property, value)

    def add_filter_by_name(self, name: str | list[str]) -> "CommodityDataAccess":
        self.filter.where("name", name)
        return self
    
    def add_filter_by_code(self, code: str | list[str]) -> "CommodityDataAccess":
        self.filter.where("code", code)
        return self
    
    def add_filter_by_slug(self, slug: str | list[str]) -> "CommodityDataAccess":
        self.filter.where("slug", slug)
        return self
    
    def add_filter_by_kind(self, kind: str | list[str]) -> "CommodityDataAccess":
        self.filter.where("kind", kind)
        return self
    
    def add_filter_by_weight_scu(self, weight_scu: int | list[int]) -> "CommodityDataAccess":
        self.filter.where("weight_scu", weight_scu)
        return self
    
    def add_filter_by_price_buy(self, price_buy: int | list[int]) -> "CommodityDataAccess":
        self.filter.where("price_buy", price_buy)
        return self
    
    def add_filter_by_price_sell(self, price_sell: int | list[int]) -> "CommodityDataAccess":
        self.filter.where("price_sell", price_sell)
        return self
    
    def add_filter_by_is_available(self, is_available: bool) -> "CommodityDataAccess":
        self.filter.where("is_available", is_available)
        return self
    
    def add_filter_by_is_available_live(self, is_available_live: bool) -> "CommodityDataAccess":
        self.filter.where("is_available_live", is_available_live)
        return self
    
    def add_filter_by_is_visible(self, is_visible: bool) -> "CommodityDataAccess":
        self.filter.where("is_visible", is_visible)
        return self
    
    def add_filter_by_is_raw(self, is_raw: bool) -> "CommodityDataAccess":
        self.filter.where("is_raw", is_raw)
        return self
    
    def add_filter_by_is_refined(self, is_refined: bool) -> "CommodityDataAccess":
        self.filter.where("is_refined", is_refined)
        return self
    
    def add_filter_by_is_mineral(self, is_mineral: bool) -> "CommodityDataAccess":
        self.filter.where("is_mineral", is_mineral)
        return self
    
    def add_filter_by_is_harvestable(self, is_harvestable: bool) -> "CommodityDataAccess":
        self.filter.where("is_harvestable", is_harvestable)
        return self
    
    def add_filter_by_is_buyable(self, is_buyable: bool) -> "CommodityDataAccess":
        self.filter.where("is_buyable", is_buyable)
        return self
    
    def add_filter_by_is_sellable(self, is_sellable: bool) -> "CommodityDataAccess":
        self.filter.where("is_sellable", is_sellable)
        return self
    
    def add_filter_by_is_temporary(self, is_temporary: bool) -> "CommodityDataAccess":
        self.filter.where("is_temporary", is_temporary)
        return self
    
    def add_filter_by_is_illegal(self, is_illegal: bool) -> "CommodityDataAccess":
        self.filter.where("is_illegal", is_illegal)
        return self
    
    def add_filter_by_is_fuel(self, is_fuel: bool) -> "CommodityDataAccess":
        self.filter.where("is_fuel", is_fuel)
        return self

    def add_filter_by_is_blacklisted(self, is_blacklisted: bool) -> "CommodityDataAccess":
        self.filter.where("is_blacklisted", is_blacklisted)
        return self

    def add_filter_has_buy_price(self, has_buy_price: bool = True) -> "CommodityDataAccess":
        self.filter.where("price_buy", 0, '>' if has_buy_price else '=')
        return self

    def add_filter_has_sell_price(self, has_sell_price: bool = True) -> "CommodityDataAccess":
        self.filter.where("price_sell", 0, '>' if has_sell_price else '=')
        return self
