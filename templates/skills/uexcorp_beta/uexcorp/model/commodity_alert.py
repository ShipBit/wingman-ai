from datetime import datetime
try:
    from skills.uexcorp_beta.uexcorp.model.data_model import DataModel
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.model.data_model import DataModel

class CommodityAlert(DataModel):

    required_keys = ["id_commodity"]

    def __init__(
            self,
            id_commodity: int|None = None, # int(11)
            id_terminal: int|None = None, # int(11)
            price_buy: int|None = None, # int(11)
            price_sell: int|None = None, # int(11)
            scu_buy: float|None = None, # float(11)
            scu_sell: float|None = None, # float(11)
            status_buy: int|None = None, # int(11)
            status_sell: int|None = None, # int(11)
            date_added: int|None = None, # int(11)
            game_version: str|None = None, # string(255)
            commodity_name: str|None = None, # string(255)
            commodity_code: str|None = None, # string(255)
            commodity_slug: str|None = None, # string(255)
            star_system_name: str|None = None, # string(255)
            planet_name: str|None = None, # string(255)
            orbit_name: str|None = None, # string(255)
            moon_name: str|None = None, # string(255)
            space_station_name: str|None = None, # string(255)
            outpost_name: str|None = None, # string(255)
            city_name: str|None = None, # string(255)
            faction_name: str|None = None, # string(255)
            terminal_name: str|None = None, # string(255)
            terminal_code: str|None = None, # string(255)
            terminal_slug: str|None = None, # string(255)
    ):
        super().__init__("commodity_alert")
        self.data = {
            "id_commodity": id_commodity,
            "id_terminal": id_terminal,
            "price_buy": price_buy,
            "price_sell": price_sell,
            "scu_buy": scu_buy,
            "scu_sell": scu_sell,
            "status_buy": status_buy,
            "status_sell": status_sell,
            "date_added": date_added,
            "game_version": game_version,
            "commodity_name": commodity_name,
            "commodity_code": commodity_code,
            "commodity_slug": commodity_slug,
            "star_system_name": star_system_name,
            "planet_name": planet_name,
            "orbit_name": orbit_name,
            "moon_name": moon_name,
            "space_station_name": space_station_name,
            "outpost_name": outpost_name,
            "city_name": city_name,
            "faction_name": faction_name,
            "terminal_name": terminal_name,
            "terminal_code": terminal_code,
            "terminal_slug": terminal_slug,
            "last_import_run_id": None,
        }

    def get_id_commodity(self) -> int | None:
        return self.data["id_commodity"]

    def get_id_terminal(self) -> int | None:
        return self.data["id_terminal"]

    def get_price_buy(self) -> int | None:
        return self.data["price_buy"]

    def get_price_sell(self) -> int | None:
        return self.data["price_sell"]

    def get_scu_buy(self) -> float | None:
        return self.data["scu_buy"]

    def get_scu_sell(self) -> float | None:
        return self.data["scu_sell"]

    def get_status_buy(self) -> int | None:
        return self.data["status_buy"]

    def get_status_sell(self) -> int | None:
        return self.data["status_sell"]

    def get_date_added(self) -> int | None:
        return self.data["date_added"]

    def get_date_added_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_added"])

    def get_game_version(self) -> str | None:
        return self.data["game_version"]

    def get_commodity_name(self) -> str | None:
        return self.data["commodity_name"]

    def get_commodity_code(self) -> str | None:
        return self.data["commodity_code"]

    def get_commodity_slug(self) -> str | None:
        return self.data["commodity_slug"]

    def get_star_system_name(self) -> str | None:
        return self.data["star_system_name"]

    def get_planet_name(self) -> str | None:
        return self.data["planet_name"]

    def get_orbit_name(self) -> str | None:
        return self.data["orbit_name"]

    def get_moon_name(self) -> str | None:
        return self.data["moon_name"]

    def get_space_station_name(self) -> str | None:
        return self.data["space_station_name"]

    def get_outpost_name(self) -> str | None:
        return self.data["outpost_name"]

    def get_city_name(self) -> str | None:
        return self.data["city_name"]

    def get_faction_name(self) -> str | None:
        return self.data["faction_name"]

    def get_terminal_name(self) -> str | None:
        return self.data["terminal_name"]

    def get_terminal_code(self) -> str | None:
        return self.data["terminal_code"]

    def get_terminal_slug(self) -> str | None:
        return self.data["terminal_slug"]

    def __str__(self):
        return str(self.data["name"])
