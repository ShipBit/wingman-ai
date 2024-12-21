from datetime import datetime
from skills.uexcorp_beta.uexcorp.model.data_model import DataModel

class SpaceStation(DataModel):

    required_keys = ["id"]

    def __init__(
            self,
            id: int, # int(11)
            id_star_system: int | None = None,  # int(11)
            id_planet: int | None = None,  # int(11)
            id_orbit: int | None = None,  # int(11)
            id_moon: int | None = None,  # int(11)
            id_city: int | None = None,  # int(11)  # city next to space station
            id_faction: int | None = None,  # int(11)
            id_jurisdiction: int | None = None,  # int(11)
            name: str | None = None, # varchar(255)
            nickname: str | None = None,  # varchar(255)  # our nickname
            is_available: int | None = None,  # tinyint(1)  # UEX website
            is_available_live: int | None = None,  # tinyint(1)  # Star Citizen (LIVE servers)
            is_visible: int | None = None,  # tinyint(1)  # UEX website (visible to everyone)
            is_default: int | None = None,  # tinyint(1)
            is_monitored: int | None = None,  # tinyint(1)
            is_armistice: int | None = None,  # tinyint(1)
            is_landable: int | None = None,  # tinyint(1)
            is_decommissioned: int | None = None,  # tinyint(1)
            is_lagrange: int | None = None,  # tinyint(1)
            has_quantum_marker: int | None = None,  # tinyint(1)
            has_trade_terminal: int | None = None,  # tinyint(1)
            has_habitation: int | None = None,  # tinyint(1)
            has_refinery: int | None = None,  # tinyint(1)
            has_cargo_center: int | None = None,  # tinyint(1)
            has_clinic: int | None = None,  # tinyint(1)
            has_food: int | None = None,  # tinyint(1)
            has_shops: int | None = None,  # tinyint(1)
            has_refuel: int | None = None,  # tinyint(1)
            has_repair: int | None = None,  # tinyint(1)
            has_gravity: int | None = None,  # int
            has_loading_dock: int | None = None,  # tinyint(1)
            has_docking_port: int | None = None,  # tinyint(1)
            has_freight_elevator: int | None = None,  # tinyint(1)
            pad_types: str | None = None,  # varchar(255)  # XS, S, M, L, XL
            date_added: int | None = None,  # int(11)  # timestamp
            date_modified: int | None = None,  # int(11)  # timestamp
            star_system_name: str | None = None,  # varchar(255)
            planet_name: str | None = None,  # varchar(255)
            orbit_name: str | None = None,  # varchar(255)
            city_name: str | None = None,  # varchar(255)
            faction_name: str | None = None,  # varchar(255)
            jurisdiction_name: str | None = None,  # varchar(255)
            load: bool = False,
    ):
        super().__init__("space_station")
        self.data = {
            "id": id,
            "id_star_system": id_star_system,
            "id_planet": id_planet,
            "id_orbit": id_orbit,
            "id_moon": id_moon,
            "id_city": id_city,
            "id_faction": id_faction,
            "id_jurisdiction": id_jurisdiction,
            "name": name,
            "nickname": nickname,
            "is_available": is_available,
            "is_available_live": is_available_live,
            "is_visible": is_visible,
            "is_default": is_default,
            "is_monitored": is_monitored,
            "is_armistice": is_armistice,
            "is_landable": is_landable,
            "is_decommissioned": is_decommissioned,
            "is_lagrange": is_lagrange,
            "has_quantum_marker": has_quantum_marker,
            "has_trade_terminal": has_trade_terminal,
            "has_habitation": has_habitation,
            "has_refinery": has_refinery,
            "has_cargo_center": has_cargo_center,
            "has_clinic": has_clinic,
            "has_food": has_food,
            "has_shops": has_shops,
            "has_refuel": has_refuel,
            "has_repair": has_repair,
            "has_gravity": has_gravity,
            "has_loading_dock": has_loading_dock,
            "has_docking_port": has_docking_port,
            "has_freight_elevator": has_freight_elevator,
            "pad_types": pad_types,
            "date_added": date_added,
            "date_modified": date_modified,
            "star_system_name": star_system_name,
            "planet_name": planet_name,
            "orbit_name": orbit_name,
            "city_name": city_name,
            "faction_name": faction_name,
            "jurisdiction_name": jurisdiction_name,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["id"]:
                raise Exception("ID is required to load data")
            self.load_by_value("id", self.data["id"])

    def get_id(self) -> int:
        return self.data["id"]

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

    def get_id_faction(self) -> int | None:
        return self.data["id_faction"]

    def get_id_jurisdiction(self) -> int | None:
        return self.data["id_jurisdiction"]

    def get_name(self) -> str | None:
        return self.data["name"]

    def get_nickname(self) -> str | None:
        return self.data["nickname"]

    def get_is_available(self) -> int | None:
        return self.data["is_available"]

    def get_is_available_live(self) -> int | None:
        return self.data["is_available_live"]

    def get_is_visible(self) -> int | None:
        return self.data["is_visible"]

    def get_is_default(self) -> int | None:
        return self.data["is_default"]

    def get_is_monitored(self) -> int | None:
        return self.data["is_monitored"]

    def get_is_armistice(self) -> int | None:
        return self.data["is_armistice"]

    def get_is_landable(self) -> int | None:
        return self.data["is_landable"]

    def get_is_decommissioned(self) -> int | None:
        return self.data["is_decommissioned"]

    def get_is_lagrange(self) -> int | None:
        return self.data["is_lagrange"]

    def get_has_quantum_marker(self) -> int | None:
        return self.data["has_quantum_marker"]

    def get_has_trade_terminal(self) -> int | None:
        return self.data["has_trade_terminal"]

    def get_has_habitation(self) -> int | None:
        return self.data["has_habitation"]

    def get_has_refinery(self) -> int | None:
        return self.data["has_refinery"]

    def get_has_cargo_center(self) -> int | None:
        return self.data["has_cargo_center"]

    def get_has_clinic(self) -> int | None:
        return self.data["has_clinic"]

    def get_has_food(self) -> int | None:
        return self.data["has_food"]

    def get_has_shops(self) -> int | None:
        return self.data["has_shops"]

    def get_has_refuel(self) -> int | None:
        return self.data["has_refuel"]

    def get_has_repair(self) -> int | None:
        return self.data["has_repair"]

    def get_has_gravity(self) -> int | None:
        return self.data["has_gravity"]

    def get_has_loading_dock(self) -> int | None:
        return self.data["has_loading_dock"]

    def get_has_docking_port(self) -> int | None:
        return self.data["has_docking_port"]

    def get_has_freight_elevator(self) -> int | None:
        return self.data["has_freight_elevator"]

    def get_pad_types(self) -> str | None:
        return self.data["pad_types"]

    def get_date_added(self) -> int | None:
        return self.data["date_added"]

    def get_date_modified(self) -> int | None:
        return self.data["date_modified"]

    def get_star_system_name(self) -> str | None:
        return self.data["star_system_name"]

    def get_planet_name(self) -> str | None:
        return self.data["planet_name"]

    def get_orbit_name(self) -> str | None:
        return self.data["orbit_name"]

    def get_city_name(self) -> str | None:
        return self.data["city_name"]

    def get_faction_name(self) -> str | None:
        return self.data["faction_name"]

    def get_jurisdiction_name(self) -> str | None:
        return self.data["jurisdiction_name"]

    def __str__(self):
        return str(self.data["name"])