from datetime import datetime
try:
    from skills.uexcorp.uexcorp.model.data_model import DataModel
except ModuleNotFoundError:
    from uexcorp.uexcorp.model.data_model import DataModel

class RefineryAudit(DataModel):

    required_keys = ["id"]

    def __init__(
        self,
        id: int, # int(11)
        id_commodity: int | None = None,  # int(11)
        id_star_system: int | None = None,  # int(11)
        id_planet: int | None = None,  # int(11)
        id_orbit: int | None = None,  # int(11)
        id_moon: int | None = None,  # int(11)
        id_city: int | None = None,  # int(11)
        id_outpost: int | None = None,  # int(11)
        id_poi: int | None = None,  # int(11)
        id_faction: int | None = None,  # int(11)
        id_terminal: int | None = None,  # int(11)
        yield_: int | None = None,  # int(11)
        capacity: int | None = None,  # int(11)
        method: int | None = None,  # int(11)
        quantity: int | None = None,  # int(11)
        quantity_yield: int | None = None,  # int(11)
        quantity_inert: int | None = None,  # int(11)
        total_cost: int | None = None,  # int(11)
        total_time: int | None = None,  # int(11)
        date_added: int | None = None, # int(11)
        date_reported: int | None = None,  # int(11)
        game_version: str | None = None,  # string(255)
        datarunner: str | None = None,  # string(255)
        commodity_name: str | None = None,  # string(255)
        star_system_name: str | None = None,  # string(255)
        planet_name: str | None = None,  # string(255)
        orbit_name: str | None = None,  # string(255)
        moon_name: str | None = None,  # string(255)
        space_station_name: str | None = None,  # string(255)
        city_name: str | None = None,  # string(255)
        outpost_name: str | None = None,  # string(255)
        terminal_name: str | None = None,  # string(255)
        load: bool = False,
    ):
        super().__init__("refinery_audit")
        self.data = {
            "id": id,
            "id_commodity": id_commodity,
            "id_star_system": id_star_system,
            "id_planet": id_planet,
            "id_orbit": id_orbit,
            "id_moon": id_moon,
            "id_city": id_city,
            "id_outpost": id_outpost,
            "id_poi": id_poi,
            "id_faction": id_faction,
            "id_terminal": id_terminal,
            "yield": yield_,
            "capacity": capacity,
            "method": method,
            "quantity": quantity,
            "quantity_yield": quantity_yield,
            "quantity_inert": quantity_inert,
            "total_cost": total_cost,
            "total_time": total_time,
            "date_added": date_added,
            "date_reported": date_reported,
            "game_version": game_version,
            "datarunner": datarunner,
            "commodity_name": commodity_name,
            "star_system_name": star_system_name,
            "planet_name": planet_name,
            "orbit_name": orbit_name,
            "moon_name": moon_name,
            "space_station_name": space_station_name,
            "city_name": city_name,
            "outpost_name": outpost_name,
            "terminal_name": terminal_name,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["id"]:
                raise Exception("ID is required to load data")
            self.load_by_value("id", self.data["id"])

    def get_id(self) -> int:
        return self.data["id"]

    def get_id_commodity(self) -> int | None:
        return self.data["id_commodity"]

    def get_id_star_system(self) -> int | None:
        return self.data["id_star_system"]

    def get_id_planet(self) -> int | None:
        return self.data["id_planet"]

    def get_id_orbit(self) -> int | None:
        return self.data["id_orbit"]

    def get_id_moon(self) -> int | None:
        return self.data["id_moon"]

    def get_id_city(self) -> int | None:
        return self.data["id_city"]

    def get_id_outpost(self) -> int | None:
        return self.data["id_outpost"]

    def get_id_poi(self) -> int | None:
        return self.data["id_poi"]

    def get_id_faction(self) -> int | None:
        return self.data["id_faction"]

    def get_id_terminal(self) -> int | None:
        return self.data["id_terminal"]

    def get_yield(self) -> int | None:
        return self.data["yield"]

    def get_capacity(self) -> int | None:
        return self.data["capacity"]

    def get_method(self) -> int | None:
        return self.data["method"]

    def get_quantity(self) -> int | None:
        return self.data["quantity"]

    def get_quantity_yield(self) -> int | None:
        return self.data["quantity_yield"]

    def get_quantity_inert(self) -> int | None:
        return self.data["quantity_inert"]

    def get_total_cost(self) -> int | None:
        return self.data["total_cost"]

    def get_total_time(self) -> int | None:
        return self.data["total_time"]

    def get_date_added(self) -> int | None:
        return self.data["date_added"]

    def get_date_added_readable(self) -> datetime:
        return datetime.fromtimestamp(self.data["date_added"])

    def get_date_reported(self) -> int | None:
        return self.data["date_reported"]

    def get_date_reported_readable(self) -> datetime:
        return datetime.fromtimestamp(self.data["date_reported"])

    def get_game_version(self) -> str | None:
        return self.data["game_version"]

    def get_datarunner(self) -> str | None:
        return self.data["datarunner"]

    def get_commodity_name(self) -> str | None:
        return self.data["commodity_name"]

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

    def get_city_name(self) -> str | None:
        return self.data["city_name"]

    def get_outpost_name(self) -> str | None:
        return self.data["outpost_name"]

    def get_terminal_name(self) -> str | None:
        return self.data["terminal_name"]