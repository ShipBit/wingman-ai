from datetime import datetime
try:
    from skills.uexcorp.uexcorp.model.data_model import DataModel
except ModuleNotFoundError:
    from uexcorp.uexcorp.model.data_model import DataModel

class Commodity(DataModel):

    required_keys = ["id"]

    def __init__(
            self,
            id: int, # int(11)
            id_parent: int|None = None, # int(11)
            name: str|None = None, # string(255)
            code: str|None = None, # string(5)
            slug: str|None = None, # string(255)
            kind: str|None = None, # string(255)
            weight_scu: int|None = None, # int(11)
            price_buy: float|None = None, # float
            price_sell: float|None = None, # float
            is_available: int|None = None, # int(1)
            is_available_live: int|None = None, # int(1)
            is_visible: int|None = None, # int(1)
            is_raw: int|None = None, # int(1)
            is_refined: int|None = None, # int(1)
            is_mineral: int|None = None, # int(1)
            is_harvestable: int|None = None, # int(1)
            is_buyable: int|None = None, # int(1)
            is_sellable: int|None = None, # int(1)
            is_temporary: int|None = None, # int(1)
            is_illegal: int|None = None, # int(1)
            is_fuel: int|None = None, # int(1)
            wiki: str|None = None, # string(255)
            date_added: int|None = None, # int(11)
            date_modified: int|None = None, # int(11)

            is_blacklisted: int|None = None, # int(1) # own property
            load: bool = False,
    ):
        super().__init__("commodity")
        self.data = {
            "id": id,
            "id_parent": id_parent,
            "name": name,
            "code": code,
            "slug": slug,
            "kind": kind,
            "weight_scu": weight_scu,
            "price_buy": price_buy,
            "price_sell": price_sell,
            "is_available": is_available,
            "is_available_live": is_available_live,
            "is_visible": is_visible,
            "is_raw": is_raw,
            "is_refined": is_refined,
            "is_mineral": is_mineral,
            "is_harvestable": is_harvestable,
            "is_buyable": is_buyable,
            "is_sellable": is_sellable,
            "is_temporary": is_temporary,
            "is_illegal": is_illegal,
            "is_fuel": is_fuel,
            "wiki": wiki,
            "date_added": date_added,
            "date_modified": date_modified,
            "is_blacklisted": is_blacklisted,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["id"]:
                raise Exception("ID is required to load data")
            self.load_by_value("id", self.data["id"])

        self.profit_calculated = False
        self.profit_min = None
        self.profit_max = None
        self.profit_margin_min = None
        self.profit_margin_max = None
        self.base_profit_min = None
        self.base_profit_max = None

    def get_properties(self) -> list[str]:
        properties = []

        if self.get_is_raw():
            properties.append("raw")
        if self.get_is_refined():
            properties.append("refined")
        if self.get_is_mineral():
            properties.append("mineral")
        if self.get_is_harvestable():
            properties.append("harvestable")
        if self.get_is_temporary():
            properties.append("temporary")
        if self.get_is_illegal():
            properties.append("illegal")
        else:
            properties.append("legal")
        if self.get_is_fuel():
            properties.append("fuel")
        if self.get_is_blacklisted():
            properties.append("Blacklisted for trade recommendations through advanced uex skill configuration")

        return properties

    def get_data_for_ai(self) -> dict:
        try:
            from skills.uexcorp.uexcorp.data_access.commodity_price_data_access import CommodityPriceDataAccess
            from skills.uexcorp.uexcorp.data_access.commodity_raw_price_data_access import CommodityRawPriceDataAccess
        except ModuleNotFoundError:
            from uexcorp.uexcorp.data_access.commodity_price_data_access import CommodityPriceDataAccess
            from uexcorp.uexcorp.data_access.commodity_raw_price_data_access import CommodityRawPriceDataAccess

        information = {
            "name": self.get_name(),
            "weight_scu": self.get_weight_scu() or "unknown",
            "properties": self.get_properties(),
            "profit_per_scu_min": f"{self.get_profit_min()} aUEC" if self.get_profit_min() else "N/A",
            "profit_per_scu_max": f"{self.get_profit_max()} aUEC" if self.get_profit_max() else "N/A",
            "profit_margin_min": f"{self.get_profit_margin_min()}%" if self.get_profit_min() else "N/A",
            "profit_margin_max": f"{self.get_profit_margin_max()}%" if self.get_profit_max() else "N/A",
            "base_profit_min": f"{self.get_base_profit_min()}%" if self.get_profit_min() else "N/A",
            "base_profit_max": f"{self.get_base_profit_max()}%" if self.get_profit_max() else "N/A",
            "buy_sell_options": [],
        }

        if self.get_id_parent():
            parent = Commodity(self.get_id_parent(), load=True)
            information["parent"] = parent.get_data_for_ai_minimal()

        if self.get_is_buyable() or self.get_is_sellable():
            prices = CommodityPriceDataAccess().add_filter_by_id_commodity(self.get_id()).load()
            for price in prices:
                information["buy_sell_options"].append(price.get_data_for_ai_minimal(show_commodity_information=False))

            prices_raw = CommodityRawPriceDataAccess().add_filter_by_id_commodity(self.get_id()).load()
            for price_raw in prices_raw:
                information["buy_sell_options"].append(price_raw.get_data_for_ai_minimal())

        return information

    def get_data_for_ai_minimal(self) -> dict:
        try:
            from skills.uexcorp.uexcorp.data_access.commodity_price_data_access import CommodityPriceDataAccess
            from skills.uexcorp.uexcorp.data_access.commodity_raw_price_data_access import CommodityRawPriceDataAccess
        except ModuleNotFoundError:
            from uexcorp.uexcorp.data_access.commodity_price_data_access import CommodityPriceDataAccess
            from uexcorp.uexcorp.data_access.commodity_raw_price_data_access import CommodityRawPriceDataAccess

        information = {
            "name": self.get_name(),
            "properties": self.get_properties(),
            "profit_per_scu_max": f"{self.get_profit_max()} aUEC" if self.get_profit_max() else "N/A",
            "profit_margin_max": f"{self.get_profit_margin_max()}%" if self.get_profit_max() else "N/A",
            "base_profit_max": f"{self.get_base_profit_max()}%" if self.get_profit_max() else "N/A",
            "buy_sell_options": [],
        }

        if self.get_id_parent() and self.get_id_parent() != self.get_id():
            parent = Commodity(self.get_id_parent(), load=True)
            information["parent"] = str(parent)

        if self.get_is_buyable() or self.get_is_sellable():
            prices = CommodityPriceDataAccess().add_filter_by_id_commodity(self.get_id()).load()
            for price in prices:
                information["buy_sell_options"].append(str(price))

            prices_raw = CommodityRawPriceDataAccess().add_filter_by_id_commodity(self.get_id()).load()
            for price_raw in prices_raw:
                information["buy_sell_options"].append(str(price_raw))

        return information

    def __calculate_profit(self) -> None:
        try:
            from skills.uexcorp.uexcorp.data_access.commodity_price_data_access import CommodityPriceDataAccess
        except ModuleNotFoundError:
            from uexcorp.uexcorp.data_access.commodity_price_data_access import CommodityPriceDataAccess

        buy_min = None
        buy_max = None
        sell_min = None
        sell_max = None
        prices = CommodityPriceDataAccess().add_filter_by_id_commodity(self.get_id()).load()
        for price in prices:
            if price.get_price_buy() and (buy_min is None or price.get_price_buy() < buy_min):
                buy_min = price.get_price_buy()
            if price.get_price_buy() and (buy_max is None or price.get_price_buy() > buy_max):
                buy_max = price.get_price_buy()
            if price.get_price_sell() and (sell_min is None or price.get_price_sell() < sell_min):
                sell_min = price.get_price_sell()
            if price.get_price_sell() and (sell_max is None or price.get_price_sell() > sell_max):
                sell_max = price.get_price_sell()

        self.profit_calculated = True
        self.profit_margin_max = 0
        self.profit_margin_min = 0
        self.profit_max = 0
        self.profit_min = 0
        self.base_profit_max = 0
        self.base_profit_min = 0

        if buy_min is not None and buy_min > 0 and sell_max is not None and sell_max > 0:
            self.profit_max = sell_max - buy_min
            self.profit_margin_max = self.profit_max / sell_max
            self.base_profit_max = (sell_max / buy_min) - 1
        if buy_max is not None and buy_max > 0 and sell_min is not None and sell_min > 0:
            self.profit_min = sell_min - buy_max
            self.profit_margin_min = self.profit_min / sell_min
            self.base_profit_min = (sell_min / buy_max) - 1

    def get_id(self) -> int:
        return self.data["id"]

    def get_id_parent(self) -> int | None:
        return self.data["id_parent"]

    def get_name(self) -> str | None:
        return self.data["name"]

    def get_code(self) -> str | None:
        return self.data["code"]

    def get_slug(self) -> str | None:
        return self.data["slug"]

    def get_kind(self) -> str | None:
        return self.data["kind"]

    def get_weight_scu(self) -> int | None:
        return self.data["weight_scu"]

    def get_price_buy(self) -> float | None:
        return self.data["price_buy"]

    def get_price_sell(self) -> float | None:
        return self.data["price_sell"]

    def get_is_available(self) -> int | None:
        return self.data["is_available"]

    def get_is_available_live(self) -> int | None:
        return self.data["is_available_live"]

    def get_is_visible(self) -> int | None:
        return self.data["is_visible"]

    def get_is_raw(self) -> int | None:
        return self.data["is_raw"]

    def get_is_refined(self) -> int | None:
        return self.data["is_refined"]

    def get_is_mineral(self) -> int | None:
        return self.data["is_mineral"]

    def get_is_harvestable(self) -> int | None:
        return self.data["is_harvestable"]

    def get_is_buyable(self) -> int | None:
        return self.data["is_buyable"]

    def get_is_sellable(self) -> int | None:
        return self.data["is_sellable"]

    def get_is_temporary(self) -> int | None:
        return self.data["is_temporary"]

    def get_is_illegal(self) -> int | None:
        return self.data["is_illegal"]

    def get_is_fuel(self) -> int | None:
        return self.data["is_fuel"]

    def get_wiki(self) -> str | None:
        return self.data["wiki"]

    def get_date_added(self) -> int | None:
        return self.data["date_added"]

    def get_date_added_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_added"])

    def get_date_modified(self) -> int | None:
        return self.data["date_modified"]

    def get_date_modified_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_modified"])

    def get_is_blacklisted(self) -> int | None:
        return self.data["is_blacklisted"]

    def set_is_blacklisted(self, is_blacklisted: int):
        self.data["is_blacklisted"] = is_blacklisted

    def get_profit_min(self) -> float | None:
        if self.profit_calculated is False:
            self.__calculate_profit()
        return self.profit_min

    def get_profit_max(self) -> float | None:
        if self.profit_calculated is False:
            self.__calculate_profit()
        return self.profit_max

    def get_profit_margin_min(self) -> float | None:
        if self.profit_calculated is False:
            self.__calculate_profit()
        return round(self.profit_margin_min * 100, 2)

    def get_profit_margin_max(self) -> float | None:
        if self.profit_calculated is False:
            self.__calculate_profit()
        return round(self.profit_margin_max * 100, 2)

    def get_base_profit_min(self) -> float | None:
        if self.profit_calculated is False:
            self.__calculate_profit()
        return round(self.base_profit_min * 100, 2)

    def get_base_profit_max(self) -> float | None:
        if self.profit_calculated is False:
            self.__calculate_profit()
        return round(self.base_profit_max * 100, 2)

    def __str__(self):
        return str(self.data["name"])
