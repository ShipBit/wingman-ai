from datetime import datetime
try:
    from skills.uexcorp_beta.uexcorp.model.data_model import DataModel
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.model.data_model import DataModel

class Terminal(DataModel):

    required_keys = ["id"]

    def __init__(
            self,
            id: int, # int(11)
            id_star_system: int | None = None,  # int(11)
            id_planet: int | None = None,  # int(11)
            id_orbit: int | None = None,  # int(11)
            id_moon: int | None = None,  # int(11)
            id_space_station: int | None = None,  # int(11)
            id_outpost: int | None = None,  # int(11)
            id_poi: int | None = None,  # int(11)
            id_city: int | None = None,  # int(11)
            id_faction: int | None = None,  # int(11)
            id_company: int | None = None,  # int(11)
            name: str | None = None, # varchar(255)
            nickname: str | None = None,  # varchar(255)
            code: str | None = None,  # varchar(6)
            type: str | None = None,  # varchar(20)
            screenshot: str | None = None,  # varchar(255)
            screenshot_thumbnail: str | None = None,  # varchar(255)
            screenshot_author: str | None = None,  # varchar(255)
            # mcs: int | None = None,  # int(11) - deprecated
            is_available: str | None = None,  # varchar(255)
            is_available_live: int | None = None,  # tinyint(1)
            is_visible: int | None = None,  # tinyint(1)
            is_default_system: int | None = None,  # tinyint(1)
            is_affinity_influenceable: int | None = None,  # tinyint(1)
            is_habitation: int | None = None,  # tinyint(1)
            is_refinery: int | None = None,  # tinyint(1)
            is_cargo_center: int | None = None,  # tinyint(1)
            is_medical: int | None = None,  # tinyint(1)
            is_food: int | None = None,  # tinyint(1)
            is_shop_fps: int | None = None,  # tinyint(1)
            is_shop_vehicle: int | None = None,  # tinyint(1)
            is_refuel: int | None = None,  # tinyint(1)
            is_repair: int | None = None,  # tinyint(1)
            is_nqa: int | None = None,  # tinyint(1)
            is_player_owned: int | None = None,  # tinyint(1)
            is_auto_load: int | None = None,  # tinyint(1)
            has_loading_dock: int | None = None,  # tinyint(1)
            has_docking_port: int | None = None,  # tinyint(1)
            has_freight_elevator: int | None = None,  # tinyint(1)
            date_added: int | None = None, # int(11)
            date_modified: int | None = None, # int(11)
            star_system_name: str | None = None,  # varchar(255)
            planet_name: str | None = None,  # varchar(255)
            orbit_name: str | None = None,  # varchar(255)
            moon_name: str | None = None,  # varchar(255)
            space_station_name: str | None = None,  # varchar(255)
            outpost_name: str | None = None,  # varchar(255)
            city_name: str | None = None,  # varchar(255)
            faction_name: str | None = None,  # varchar(255)
            company_name: str | None = None,  # varchar(255)
            max_container_size: int | None = None,  # int(11)

            is_blacklisted: int | None = None,  # tinyint(1) # own property
            load: bool = False,
    ):
        super().__init__("terminal")
        self.data = {
            "id": id,
            "id_star_system": id_star_system,
            "id_planet": id_planet,
            "id_orbit": id_orbit,
            "id_moon": id_moon,
            "id_space_station": id_space_station,
            "id_outpost": id_outpost,
            "id_poi": id_poi,
            "id_city": id_city,
            "id_faction": id_faction,
            "id_company": id_company,
            "name": name,
            "nickname": nickname,
            "code": code,
            "type": type,
            "screenshot": screenshot,
            "screenshot_thumbnail": screenshot_thumbnail,
            "screenshot_author": screenshot_author,
            # "mcs": mcs, # int(11) - deprecated
            "is_available": is_available,
            "is_available_live": is_available_live,
            "is_visible": is_visible,
            "is_default_system": is_default_system,
            "is_affinity_influenceable": is_affinity_influenceable,
            "is_habitation": is_habitation,
            "is_refinery": is_refinery,
            "is_cargo_center": is_cargo_center,
            "is_medical": is_medical,
            "is_food": is_food,
            "is_shop_fps": is_shop_fps,
            "is_shop_vehicle": is_shop_vehicle,
            "is_refuel": is_refuel,
            "is_repair": is_repair,
            "is_nqa": is_nqa,
            "is_player_owned": is_player_owned,
            "is_auto_load": is_auto_load,
            "has_loading_dock": has_loading_dock,
            "has_docking_port": has_docking_port,
            "has_freight_elevator": has_freight_elevator,
            "date_added": date_added,
            "date_modified": date_modified,
            "star_system_name": star_system_name,
            "planet_name": planet_name,
            "orbit_name": orbit_name,
            "moon_name": moon_name,
            "space_station_name": space_station_name,
            "outpost_name": outpost_name,
            "city_name": city_name,
            "faction_name": faction_name,
            "company_name": company_name,
            "max_container_size": max_container_size,
            "is_blacklisted": is_blacklisted,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["id"]:
                raise Exception("ID is required to load data")
            self.load_by_value("id", self.data["id"])

    def get_types(self) -> list[str]:
        types = [self.get_type()]
        if self.get_is_habitation():
            types.append("Habitation")
        if self.get_is_refinery():
            types.append("Refinery")
        if self.get_is_cargo_center():
            types.append("Cargo Center")
        if self.get_is_medical():
            types.append("Medical")
        if self.get_is_food():
            types.append("Food")
        if self.get_is_shop_fps():
            types.append("Shop FPS")
        if self.get_is_shop_vehicle():
            types.append("Shop Vehicle")
        if self.get_is_refuel():
            types.append("Refuel")
        if self.get_is_repair():
            types.append("Repair")
        if self.get_is_nqa():
            types.append("NQA")
        return types

    def get_extras(self) -> list[str]:
        extras = []
        if self.get_has_docking_port():
            extras.append("Docking Port")
        if self.get_has_loading_dock():
            extras.append("Loading Dock")
        if self.get_has_freight_elevator():
            extras.append("Freight Elevator")
        if self.get_is_blacklisted():
            extras.append("Blacklisted for trade recommendations through advanced uex skill configuration")
        if self.get_is_affinity_influenceable():
            extras.append("Faction Affinity Influenceable")
        return extras

    def get_offerings(self) -> dict:
        try:
            from skills.uexcorp_beta.uexcorp.data_access.vehicle_rental_price_data_access import VehicleRentalPriceDataAccess
            from skills.uexcorp_beta.uexcorp.data_access.vehicle_purchase_price_data_access import VehiclePurchasePriceDataAccess
            from skills.uexcorp_beta.uexcorp.data_access.item_price_data_access import ItemPriceDataAccess
            from skills.uexcorp_beta.uexcorp.data_access.commodity_price_data_access import CommodityPriceDataAccess
            from skills.uexcorp_beta.uexcorp.data_access.commodity_raw_price_data_access import CommodityRawPriceDataAccess
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.data_access.vehicle_rental_price_data_access import VehicleRentalPriceDataAccess
            from uexcorp_beta.uexcorp.data_access.vehicle_purchase_price_data_access import VehiclePurchasePriceDataAccess
            from uexcorp_beta.uexcorp.data_access.item_price_data_access import ItemPriceDataAccess
            from uexcorp_beta.uexcorp.data_access.commodity_price_data_access import CommodityPriceDataAccess
            from uexcorp_beta.uexcorp.data_access.commodity_raw_price_data_access import CommodityRawPriceDataAccess

        offerings = {}

        vehicle_rental_prices = VehicleRentalPriceDataAccess().add_filter_by_id_terminal(self.get_id()).load()
        if vehicle_rental_prices:
            offerings['vehicle_rental'] = [vehicle_rental_price.get_data_for_ai_minimal() for vehicle_rental_price in vehicle_rental_prices]

        vehicle_purchase_prices = VehiclePurchasePriceDataAccess().add_filter_by_id_terminal(self.get_id()).load()
        if vehicle_purchase_prices:
            offerings['vehicle_purchase'] = [vehicle_purchase_price.get_data_for_ai_minimal() for vehicle_purchase_price in vehicle_purchase_prices]

        item_prices = ItemPriceDataAccess().add_filter_by_id_terminal(self.get_id()).load()
        if item_prices:
            offerings['item'] = [item_price.get_data_for_ai_minimal() for item_price in item_prices]

        commodity_prices = CommodityPriceDataAccess().add_filter_by_id_terminal(self.get_id()).load()
        if commodity_prices:
            offerings['commodity'] = [commodity_price.get_data_for_ai_minimal() for commodity_price in commodity_prices]

        commodity_raw_prices = CommodityRawPriceDataAccess().add_filter_by_id_terminal(self.get_id()).load()
        if commodity_raw_prices:
            offerings['commodity_raw'] = [commodity_raw_price.get_data_for_ai_minimal() for commodity_raw_price in commodity_raw_prices]

        return offerings

    def get_data_for_ai(self) -> dict:
        try:
            from skills.uexcorp_beta.uexcorp.model.city import City
            from skills.uexcorp_beta.uexcorp.model.poi import Poi
            from skills.uexcorp_beta.uexcorp.model.outpost import Outpost
            from skills.uexcorp_beta.uexcorp.model.space_station import SpaceStation
            from skills.uexcorp_beta.uexcorp.model.faction import Faction
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.model.city import City
            from uexcorp_beta.uexcorp.model.poi import Poi
            from uexcorp_beta.uexcorp.model.outpost import Outpost
            from uexcorp_beta.uexcorp.model.space_station import SpaceStation
            from uexcorp_beta.uexcorp.model.faction import Faction

        faction = Faction(self.get_id_faction(), load=True) if self.get_id_faction() else None

        information = {
            "name": self.get_name(),
            "location_type": "Terminal",
            "terminal_types": self.get_types(),
            "terminal_extras": self.get_extras(),
            "parent_location": {},
            "company_name": self.get_company_name(),
            "faction": faction.get_data_for_ai_minimal() if faction else None,
            "offerings": self.get_offerings(),
        }

        if self.get_max_container_size():
            information["max_container_size_in_scu"] = self.get_max_container_size()

        parent_location = None
        if self.get_id_city():
            parent_location = City(self.get_id_city(), load=True)
        elif self.get_id_poi():
            parent_location = Poi(self.get_id_poi(), load=True)
        elif self.get_id_outpost():
            parent_location = Outpost(self.get_id_outpost(), load=True)
        elif self.get_id_space_station():
            parent_location = SpaceStation(self.get_id_space_station(), load=True)
        if parent_location:
            information["parent_location"] = parent_location.get_data_for_ai_minimal()

        return information

    def get_data_for_ai_minimal(self) -> dict:
        try:
            from skills.uexcorp_beta.uexcorp.model.poi import Poi
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.model.poi import Poi

        information = {
            "name": self.get_name(),
            "location_type": "Terminal",
            "terminal_types": self.get_types(),
            "terminal_extras": self.get_extras(),
            "parent_location": "",
            "company_name": self.get_company_name(),
            "faction_name": self.get_faction_name(),
            # "offerings": self.get_offerings(), # TODO: decide if we want to include this in minimal data
        }

        if self.get_id_city():
            information["parent_location"] = self.get_city_name()
        elif self.get_id_poi():
            poi = Poi(self.get_id_poi(), load=True)
            information["parent_location"] = str(poi)
        elif self.get_id_outpost():
            information["parent_location"] = self.get_outpost_name()
        elif self.get_id_space_station():
            information["parent_location"] = self.get_space_station_name()

        return information

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

    def get_id_space_station(self) -> int | None:
        return self.data["id_space_station"]

    def get_id_outpost(self) -> int | None:
        return self.data["id_outpost"]

    def get_id_poi(self) -> int | None:
        return self.data["id_poi"]

    def get_id_city(self) -> int | None:
        return self.data["id_city"]

    def get_id_faction(self) -> int | None:
        return self.data["id_faction"]

    def get_id_company(self) -> int | None:
        return self.data["id_company"]

    def get_name(self) -> str | None:
        return self.data["name"]

    def get_nickname(self) -> str | None:
        return self.data["nickname"]

    def get_code(self) -> str | None:
        return self.data["code"]

    def get_type(self) -> str | None:
        return self.data["type"]

    def get_screenshot(self) -> str | None:
        return self.data["screenshot"]

    def get_screenshot_thumbnail(self) -> str | None:
        return self.data["screenshot_thumbnail"]

    def get_screenshot_author(self) -> str | None:
        return self.data["screenshot_author"]

    def get_is_available(self) -> str | None:
        return self.data["is_available"]

    def get_is_available_live(self) -> int | None:
        return self.data["is_available_live"]

    def get_is_visible(self) -> int | None:
        return self.data["is_visible"]

    def get_is_default_system(self) -> int | None:
        return self.data["is_default_system"]

    def get_is_affinity_influenceable(self) -> int | None:
        return self.data["is_affinity_influenceable"]

    def get_is_habitation(self) -> int | None:
        return self.data["is_habitation"]

    def get_is_refinery(self) -> int | None:
        return self.data["is_refinery"]

    def get_is_cargo_center(self) -> int | None:
        return self.data["is_cargo_center"]

    def get_is_medical(self) -> int | None:
        return self.data["is_medical"]

    def get_is_food(self) -> int | None:
        return self.data["is_food"]

    def get_is_shop_fps(self) -> int | None:
        return self.data["is_shop_fps"]

    def get_is_shop_vehicle(self) -> int | None:
        return self.data["is_shop_vehicle"]

    def get_is_refuel(self) -> int | None:
        return self.data["is_refuel"]

    def get_is_repair(self) -> int | None:
        return self.data["is_repair"]

    def get_is_nqa(self) -> int | None:
        return self.data["is_nqa"]

    def get_is_player_owned(self) -> int | None:
        return self.data["is_player_owned"]

    def get_is_auto_load(self) -> int | None:
        return self.data["is_auto_load"]

    def get_has_loading_dock(self) -> int | None:
        return self.data["has_loading_dock"]

    def get_has_docking_port(self) -> int | None:
        return self.data["has_docking_port"]

    def get_has_freight_elevator(self) -> int | None:
        return self.data["has_freight_elevator"]

    def get_date_added(self) -> int | None:
        return self.data["date_added"]

    def get_date_added_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_added"])

    def get_date_modified(self) -> int | None:
        return self.data["date_modified"]

    def get_date_modified_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_modified"])

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

    def get_company_name(self) -> str | None:
        return self.data["company_name"]

    def get_max_container_size(self) -> int | None:
        return self.data["max_container_size"]

    def get_is_blacklisted(self) -> int | None:
        return self.data["is_blacklisted"]

    def set_is_blacklisted(self, is_blacklisted: int):
        self.data["is_blacklisted"] = is_blacklisted

    def __str__(self):
        return str(self.data["name"])