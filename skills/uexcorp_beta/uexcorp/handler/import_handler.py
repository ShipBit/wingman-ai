from skills.uexcorp_beta.uexcorp.api.uex import Uex
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from skills.uexcorp_beta.uexcorp.helper import Helper


class ImportHandler:

    def __init__(
            self,
            helper: "Helper"
    ):
        self.__helper = helper
        self.__api = Uex(helper)
        self.__importers = {
            "category": self.__import_data_category,
            "category_attribute": self.__import_data_category_attribute,
            "city": self.__import_data_city,
            "commodity": self.__import_data_commodity,
            "company": self.__import_data_company,
            "faction": self.__import_data_faction,
            "item": self.__import_data_item,
            "jurisdiction": self.__import_data_jurisdiction,
            "star_system": self.__import_data_star_system,
            "moon": self.__import_data_moon,
            "orbit": self.__import_data_orbit,
            "orbit_distance": self.__import_data_orbit_distance,
            "outpost": self.__import_data_outpost,
            "planet": self.__import_data_planet,
            "poi": self.__import_data_poi,
            "refinery_method": self.__import_data_refinery_method,
            "space_station": self.__import_data_space_station,
            "terminal": self.__import_data_terminal,
            "vehicle": self.__import_data_vehicle,
            "commodity_status": self.__import_data_commodity_status,
            "item_price": self.__import_data_item_price,
            "refinery_audit": self.__import_data_refinery_audit,
            "fuel_price": self.__import_data_fuel_price,
            "vehicle_purchase_price": self.__import_data_vehicle_purchase_price,
            "vehicle_rental_price": self.__import_data_vehicle_rental_price,
            "commodity_alert": self.__import_data_commodity_alert,
            "commodity_price": self.__import_data_commodity_price,
            "commodity_raw_price": self.__import_data_commodity_raw_price,
            "commodity_route": self.__import_data_commodity_route,
            "game_version": self.__import_data_game_version,
        }
        self.__common_data = {
            "last_import_run_id": 0,
        }
        self.__imported_percent: int = 0

        self.generate_import_session()

    def prepare(self):
        self.__helper.ensure_version_parity(True)
        self.import_data(True)

    def generate_import_session(self) -> int:
        self.__common_data["last_import_run_id"] = self.__helper.get_timestamp()
        self.__helper.get_handler_debug().write(f"Generated new import session: {self.__common_data['last_import_run_id']}")
        return self.__common_data["last_import_run_id"]

    def import_data(self, force: bool = False):
        if not force and self.get_imported_percent() < 100:
            self.__helper.get_handler_debug().write("Blocked new import as previous import wasn't finished")
            return

        self.__common_data["last_import_run_id"] = self.__helper.get_timestamp()

        self.__helper.get_handler_debug().write("Importing UEX api data (may take a while) ...")
        self.__helper.start_timer("import_total")
        total_count = self.__import_data()
        self.__helper.get_handler_debug().write(
            f"UEX api data imported: {total_count} record(s) in {self.__helper.end_timer("import_total")}s"
        )
        self.__helper.on_import_completed(total_count)

    def get_common_data(self) -> dict[str, any]:
        return self.__common_data

    def get_version_uex(self, force_check: bool = False) -> str:
        from skills.uexcorp_beta.uexcorp.model.game_version import GameVersion
        self.__import_data_game_version(force_check)
        return GameVersion(load=True).get_live()

    def get_imported_percent(self) -> int:
        return self.__imported_percent

    def __import_data(self) -> int:
        total_count = 0
        self.__imported_percent = 0
        for importer in self.__importers.values():
            total_count += int(importer() or 0)
            self.__imported_percent = int(min(self.__imported_percent + 100 / len(self.__importers), 100))
        return total_count

    def __import_data_category(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.category import Category
        if not self.__helper.get_database().table_exists("category"):
            return False

        category_import = ImportData("category", load=True)
        if not category_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_long()):
            return False

        self.__helper.start_timer("import")

        category_data = self.__api.fetch(self.__api.CATEGORIES)
        if category_data:
            for index, data in enumerate(category_data):
                category = Category(data["id"])
                category.set_data(data)
                category.persist(index < len(category_data) - 1)

        category_import.set_date_imported(self.__helper.get_timestamp())
        category_import.set_dataset_count(len(category_data))
        category_import.set_time_taken(self.__helper.end_timer("import"))
        category_import.persist()
        self.__helper.get_handler_debug().write(
            f"Category data imported: {category_import.get_dataset_count()} record(s) in {category_import.get_time_taken()}s"
        )
        return len(category_data)

    def __import_data_category_attribute(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.category_attribute import CategoryAttribute
        if not self.__helper.get_database().table_exists("category_attribute"):
            return False

        category_attribute_import = ImportData("category_attribute", load=True)
        if not category_attribute_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_long()):
            return False

        self.__helper.start_timer("import")

        category_attribute_data = self.__api.fetch(self.__api.CATEGORIES_ATTRIBUTES)
        if category_attribute_data:
            for index, data in enumerate(category_attribute_data):
                category_attribute = CategoryAttribute(data["id"])
                category_attribute.set_data(data)
                category_attribute.persist(index < len(category_attribute_data) - 1)

        category_attribute_import.set_date_imported(self.__helper.get_timestamp())
        category_attribute_import.set_dataset_count(len(category_attribute_data))
        category_attribute_import.set_time_taken(self.__helper.end_timer("import"))
        category_attribute_import.persist()
        self.__helper.get_handler_debug().write(
            f"Category Attribute data imported: {category_attribute_import.get_dataset_count()} record(s) in {category_attribute_import.get_time_taken()}s"
        )
        return len(category_attribute_data)

    def __import_data_city(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.city import City
        if not self.__helper.get_database().table_exists("city"):
            return False

        city_import = ImportData("city", load=True)
        if not city_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_long()):
            return False

        self.__helper.start_timer("import")

        city_data = self.__api.fetch(self.__api.CITIES)
        if city_data:
            for index, data in enumerate(city_data):
                city = City(data["id"])
                city.set_data(data)
                city.persist(index < len(city_data) - 1)

        city_import.set_date_imported(self.__helper.get_timestamp())
        city_import.set_dataset_count(len(city_data))
        city_import.set_time_taken(self.__helper.end_timer("import"))
        city_import.persist()
        self.__helper.get_handler_debug().write(
            f"City data imported: {city_import.get_dataset_count()} record(s) in {city_import.get_time_taken()}s"
        )
        return len(city_data)

    def __import_data_commodity(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.commodity import Commodity
        if not self.__helper.get_database().table_exists("commodity"):
            return False

        commodity_import = ImportData("commodity", load=True)
        if not commodity_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_long()):
            return False

        self.__helper.start_timer("import")

        commodity_data = self.__api.fetch(self.__api.COMMODITIES)
        if commodity_data:
            for index, data in enumerate(commodity_data):
                commodity = Commodity(data["id"])
                commodity.set_data(data)
                commodity.persist(index < len(commodity_data) - 1)

        commodity_import.set_date_imported(self.__helper.get_timestamp())
        commodity_import.set_dataset_count(len(commodity_data))
        commodity_import.set_time_taken(self.__helper.end_timer("import"))
        commodity_import.persist()
        self.__helper.get_handler_debug().write(
            f"Commodity data imported: {commodity_import.get_dataset_count()} record(s) in {commodity_import.get_time_taken()}s"
        )
        return len(commodity_data)

    def __import_data_commodity_alert(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.commodity_alert import CommodityAlert
        if not self.__helper.get_database().table_exists("commodity_alert"):
            return False

        commodity_alert_import = ImportData("commodity_alert", load=True)
        if not commodity_alert_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_short()):
            return False

        self.__helper.start_timer("import")

        commodity_alert_data = self.__api.fetch(self.__api.COMMODITIES_ALERTS)
        if commodity_alert_data:
            for index, data in enumerate(commodity_alert_data):
                commodity_alert = CommodityAlert(data["id"])
                commodity_alert.set_data(data)
                commodity_alert.persist(index < len(commodity_alert_data) - 1)

        commodity_alert_import.set_date_imported(self.__helper.get_timestamp())
        commodity_alert_import.set_dataset_count(len(commodity_alert_data))
        commodity_alert_import.set_time_taken(self.__helper.end_timer("import"))
        commodity_alert_import.persist()
        self.__helper.get_handler_debug().write(
            f"Commodity Alert data imported: {commodity_alert_import.get_dataset_count()} record(s) in {commodity_alert_import.get_time_taken()}s"
        )
        return len(commodity_alert_data)

    def __import_data_commodity_price(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.commodity_price import CommodityPrice
        if not self.__helper.get_database().table_exists("commodity_price"):
            return False

        commodity_price_import = ImportData("commodity_price", load=True)
        if not commodity_price_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_short()):
            return False

        self.__helper.start_timer("import")

        commodity_price_data = self.__api.fetch(self.__api.COMMODITIES_PRICES)
        if commodity_price_data:
            for index, data in enumerate(commodity_price_data):
                commodity_price = CommodityPrice(data["id"])
                commodity_price.set_data(data)
                commodity_price.persist(index < len(commodity_price_data) - 1)

        commodity_price_import.set_date_imported(self.__helper.get_timestamp())
        commodity_price_import.set_dataset_count(len(commodity_price_data))
        commodity_price_import.set_time_taken(self.__helper.end_timer("import"))
        commodity_price_import.persist()
        self.__helper.get_handler_debug().write(
            f"Commodity Price data imported: {commodity_price_import.get_dataset_count()} record(s) in {commodity_price_import.get_time_taken()}s"
        )
        return len(commodity_price_data)

    def __import_data_commodity_raw_price(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.commodity_raw_price import CommodityRawPrice
        if not self.__helper.get_database().table_exists("commodity_raw_price"):
            return False

        commodity_raw_price_import = ImportData("commodity_raw_price", load=True)
        if not commodity_raw_price_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_short()):
            return False

        self.__helper.start_timer("import")

        commodity_raw_price_data = self.__api.fetch(self.__api.COMMODITIES_RAW_PRICES)
        if commodity_raw_price_data:
            for index, data in enumerate(commodity_raw_price_data):
                commodity_raw_price = CommodityRawPrice(data["id"])
                commodity_raw_price.set_data(data)
                commodity_raw_price.persist(index < len(commodity_raw_price_data) - 1)

        commodity_raw_price_import.set_date_imported(self.__helper.get_timestamp())
        commodity_raw_price_import.set_dataset_count(len(commodity_raw_price_data))
        commodity_raw_price_import.set_time_taken(self.__helper.end_timer("import"))
        commodity_raw_price_import.persist()
        self.__helper.get_handler_debug().write(
            f"Commodity Raw Price data imported: {commodity_raw_price_import.get_dataset_count()} record(s) in {commodity_raw_price_import.get_time_taken()}s"
        )
        return len(commodity_raw_price_data)

    def __import_data_commodity_status(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.commodity_status import CommodityStatus
        if not self.__helper.get_database().table_exists("commodity_status"):
            return False

        commodity_status_import = ImportData("commodity_status", load=True)
        if not commodity_status_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_mid()):
            return False

        self.__helper.start_timer("import")

        commodity_status_data = self.__api.fetch(self.__api.COMMODITIES_STATUS)
        if commodity_status_data:
            if "buy" in commodity_status_data:
                for index, data in enumerate(commodity_status_data["buy"]):
                    commodity_status = CommodityStatus(data["code"], True)
                    commodity_status.set_data(data)
                    commodity_status.persist(index < len(commodity_status_data["buy"]) - 1)
            if "sell" in commodity_status_data:
                for index, data in enumerate(commodity_status_data["sell"]):
                    commodity_status = CommodityStatus(data["code"], False)
                    commodity_status.set_data(data)
                    commodity_status.persist(index < len(commodity_status_data["sell"]) - 1)

        commodity_status_import.set_date_imported(self.__helper.get_timestamp())
        commodity_status_import.set_dataset_count(len(commodity_status_data))
        commodity_status_import.set_time_taken(self.__helper.end_timer("import"))
        commodity_status_import.persist()
        self.__helper.get_handler_debug().write(
            f"Commodity Status data imported: {commodity_status_import.get_dataset_count()} record(s) in {commodity_status_import.get_time_taken()}s"
        )
        return len(commodity_status_data)

    def __import_data_commodity_route(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.commodity_route import CommodityRoute
        from skills.uexcorp_beta.uexcorp.data_access.commodity_data_access import CommodityDataAccess
        if not self.__helper.get_database().table_exists("commodity_route"):
            return False

        commodity_route_import = ImportData("commodity_route", load=True)
        if not commodity_route_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_short()):
            return False

        # Depends on commodity data
        self.__import_data_commodity()

        self.__helper.start_timer("import")

        commodities = CommodityDataAccess().add_filter_has_buy_price().add_filter_has_sell_price().load()
        commodity_ids = []
        for commodity in commodities:
            commodity_ids.append(commodity.get_id())

        commodity_route_data = self.__api.fetch(self.__api.COMMODITIES_ROUTES, {"id_commodity": commodity_ids})
        if commodity_route_data:
            for index, data in enumerate(commodity_route_data):
                commodity_route = CommodityRoute(data["id"])
                commodity_route.set_data(data)
                commodity_route.persist(index < len(commodity_route_data) - 1)

        commodity_route_import.set_date_imported(self.__helper.get_timestamp())
        commodity_route_import.set_dataset_count(len(commodity_route_data))
        commodity_route_import.set_time_taken(self.__helper.end_timer("import"))
        commodity_route_import.persist()
        self.__helper.get_handler_debug().write(
            f"Commodity Route data imported: {commodity_route_import.get_dataset_count()} record(s) in {commodity_route_import.get_time_taken()}s"
        )
        return len(commodity_route_data)

    def __import_data_company(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.company import Company
        if not self.__helper.get_database().table_exists("company"):
            return False

        company_import = ImportData("company", load=True)
        if not company_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_long()):
            return False

        self.__helper.start_timer("import")

        company_data = self.__api.fetch(self.__api.COMPANIES)
        if company_data:
            for index, data in enumerate(company_data):
                company = Company(data["id"])
                company.set_data(data)
                company.persist(index < len(company_data) - 1)

        company_import.set_date_imported(self.__helper.get_timestamp())
        company_import.set_dataset_count(len(company_data))
        company_import.set_time_taken(self.__helper.end_timer("import"))
        company_import.persist()
        self.__helper.get_handler_debug().write(
            f"Company data imported: {company_import.get_dataset_count()} record(s) in {company_import.get_time_taken()}s"
        )
        return len(company_data)

    def __import_data_faction(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.faction import Faction
        if not self.__helper.get_database().table_exists("faction"):
            return False

        faction_import = ImportData("faction", load=True)
        if not faction_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_long()):
            return False

        self.__helper.start_timer("import")

        faction_data = self.__api.fetch(self.__api.FACTIONS)
        if faction_data:
            for index, data in enumerate(faction_data):
                faction = Faction(data["id"])
                faction.set_data(data)
                faction.persist(index < len(faction_data) - 1)

        faction_import.set_date_imported(self.__helper.get_timestamp())
        faction_import.set_dataset_count(len(faction_data))
        faction_import.set_time_taken(self.__helper.end_timer("import"))
        faction_import.persist()
        self.__helper.get_handler_debug().write(
            f"Faction data imported: {faction_import.get_dataset_count()} record(s) in {faction_import.get_time_taken()}s"
        )
        return len(faction_data)

    def __import_data_fuel_price(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.fuel_price import FuelPrice
        if not self.__helper.get_database().table_exists("fuel_price"):
            return False

        fuel_price_import = ImportData("fuel_price", load=True)
        if not fuel_price_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_mid()):
            return False

        self.__helper.start_timer("import")

        fuel_price_data = self.__api.fetch(self.__api.FUEL_PRICES)
        if fuel_price_data:
            for index, data in enumerate(fuel_price_data):
                fuel_price = FuelPrice(data["id"])
                fuel_price.set_data(data)
                fuel_price.persist(index < len(fuel_price_data) - 1)

        fuel_price_import.set_date_imported(self.__helper.get_timestamp())
        fuel_price_import.set_dataset_count(len(fuel_price_data))
        fuel_price_import.set_time_taken(self.__helper.end_timer("import"))
        fuel_price_import.persist()
        self.__helper.get_handler_debug().write(
            f"Fuel Price data imported: {fuel_price_import.get_dataset_count()} record(s) in {fuel_price_import.get_time_taken()}s"
        )
        return len(fuel_price_data)

    def __import_data_game_version(self, force_check: bool = False) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.game_version import GameVersion
        if not self.__helper.get_database().table_exists("game_version"):
            return False

        game_version_import = ImportData("game_version", load=True)
        if not force_check and not game_version_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_short()):
            return False

        self.__helper.start_timer("import")

        game_version_data = self.__api.fetch(self.__api.GAME_VERSIONS)
        if game_version_data:
            game_version = GameVersion()
            game_version.set_data(game_version_data)
            game_version.persist()

        game_version_import.set_date_imported(self.__helper.get_timestamp())
        game_version_import.set_dataset_count(len(game_version_data))
        game_version_import.set_time_taken(self.__helper.end_timer("import"))
        game_version_import.persist()
        self.__helper.get_handler_debug().write(
            f"Game Version data imported: {game_version_import.get_dataset_count()} record(s) in {game_version_import.get_time_taken()}s"
        )
        return len(game_version_data)

    def __import_data_item(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.item import Item
        from skills.uexcorp_beta.uexcorp.data_access.category_data_access import CategoryDataAccess
        if not self.__helper.get_database().table_exists("item"):
            return False

        item_import = ImportData("item", load=True)
        if not item_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_long()):
            return False

        self.__helper.start_timer("import")

        category_ids = []
        categories = CategoryDataAccess().load()
        for category in categories:
            category_ids.append(category.get_id())

        item_data = self.__api.fetch(self.__api.ITEMS, {"id_category": category_ids})
        if item_data:
            for index, data in enumerate(item_data):
                item = Item(data["id"])
                item.set_data(data)
                item.persist(index < len(item_data) - 1)

        item_import.set_date_imported(self.__helper.get_timestamp())
        item_import.set_dataset_count(len(item_data))
        item_import.set_time_taken(self.__helper.end_timer("import"))
        item_import.persist()
        self.__helper.get_handler_debug().write(
            f"Item data imported: {item_import.get_dataset_count()} record(s) in {item_import.get_time_taken()}s"
        )
        return len(item_data)

    def __import_data_item_price(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.item_price import ItemPrice
        if not self.__helper.get_database().table_exists("item_price"):
            return False

        item_price_import = ImportData("item_price", load=True)
        if not item_price_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_mid()):
            return False

        self.__helper.start_timer("import")

        item_price_data = self.__api.fetch(self.__api.ITEMS_PRICES)
        if item_price_data:
            for index, data in enumerate(item_price_data):
                item_price = ItemPrice(data["id"])
                item_price.set_data(data)
                item_price.persist(index < len(item_price_data) - 1)

        item_price_import.set_date_imported(self.__helper.get_timestamp())
        item_price_import.set_dataset_count(len(item_price_data))
        item_price_import.set_time_taken(self.__helper.end_timer("import"))
        item_price_import.persist()
        self.__helper.get_handler_debug().write(
            f"Item Price data imported: {item_price_import.get_dataset_count()} record(s) in {item_price_import.get_time_taken()}s"
        )
        return len(item_price_data)

    def __import_data_jurisdiction(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.jurisdiction import Jurisdiction
        if not self.__helper.get_database().table_exists("jurisdiction"):
            return False

        jurisdiction_import = ImportData("jurisdiction", load=True)
        if not jurisdiction_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_long()):
            return False

        self.__helper.start_timer("import")

        jurisdiction_data = self.__api.fetch(self.__api.JURISDICTIONS)
        if jurisdiction_data:
            for index, data in enumerate(jurisdiction_data):
                jurisdiction = Jurisdiction(data["id"])
                jurisdiction.set_data(data)
                jurisdiction.persist(index < len(jurisdiction_data) - 1)

        jurisdiction_import.set_date_imported(self.__helper.get_timestamp())
        jurisdiction_import.set_dataset_count(len(jurisdiction_data))
        jurisdiction_import.set_time_taken(self.__helper.end_timer("import"))
        jurisdiction_import.persist()
        self.__helper.get_handler_debug().write(
            f"Jurisdiction data imported: {jurisdiction_import.get_dataset_count()} record(s) in {jurisdiction_import.get_time_taken()}s"
        )
        return len(jurisdiction_data)

    def __import_data_moon(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.moon import Moon
        if not self.__helper.get_database().table_exists("moon"):
            return False

        moon_import = ImportData("moon", load=True)
        if not moon_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_long()):
            return False

        self.__helper.start_timer("import")

        moon_data = self.__api.fetch(self.__api.MOONS)
        if moon_data:
            for index, data in enumerate(moon_data):
                moon = Moon(data["id"])
                moon.set_data(data)
                moon.persist(index < len(moon_data) - 1)

        moon_import.set_date_imported(self.__helper.get_timestamp())
        moon_import.set_dataset_count(len(moon_data))
        moon_import.set_time_taken(self.__helper.end_timer("import"))
        moon_import.persist()
        self.__helper.get_handler_debug().write(
            f"Moon data imported: {moon_import.get_dataset_count()} record(s) in {moon_import.get_time_taken()}s"
        )
        return len(moon_data)

    def __import_data_orbit(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.orbit import Orbit
        if not self.__helper.get_database().table_exists("orbit"):
            return False

        orbit_import = ImportData("orbit", load=True)
        if not orbit_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_long()):
            return False

        self.__helper.start_timer("import")

        orbit_data = self.__api.fetch(self.__api.ORBITS)
        if orbit_data:
            for index, data in enumerate(orbit_data):
                orbit = Orbit(data["id"])
                orbit.set_data(data)
                orbit.persist(index < len(orbit_data) - 1)

        orbit_import.set_date_imported(self.__helper.get_timestamp())
        orbit_import.set_dataset_count(len(orbit_data))
        orbit_import.set_time_taken(self.__helper.end_timer("import"))
        orbit_import.persist()
        self.__helper.get_handler_debug().write(
            f"Orbit data imported: {orbit_import.get_dataset_count()} record(s) in {orbit_import.get_time_taken()}s"
        )
        return len(orbit_data)

    def __import_data_orbit_distance(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.orbit_distance import OrbitDistance
        from skills.uexcorp_beta.uexcorp.data_access.star_system_data_access import StarSystemDataAccess
        if not self.__helper.get_database().table_exists("orbit_distance"):
            return False

        orbit_distance_import = ImportData("orbit_distance", load=True)
        if not orbit_distance_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_long()):
            return False

        # Depends on star_system data
        self.__import_data_star_system()

        self.__helper.start_timer("import")

        star_system_ids = []
        star_systems = StarSystemDataAccess().add_filter_by_is_available(True).load()
        for star_system in star_systems:
            star_system_ids.append(star_system.get_id())

        orbit_distance_data = self.__api.fetch(self.__api.ORBITS_DISTANCES, {"id_star_system": star_system_ids})
        if orbit_distance_data:
            for index, data in enumerate(orbit_distance_data):
                orbit_distance = OrbitDistance(data["id"])
                orbit_distance.set_data(data)
                orbit_distance.persist(index < len(orbit_distance_data) - 1)

        orbit_distance_import.set_date_imported(self.__helper.get_timestamp())
        orbit_distance_import.set_dataset_count(len(orbit_distance_data))
        orbit_distance_import.set_time_taken(self.__helper.end_timer("import"))
        orbit_distance_import.persist()
        self.__helper.get_handler_debug().write(
            f"Orbit Distance data imported: {orbit_distance_import.get_dataset_count()} record(s) in {orbit_distance_import.get_time_taken()}s"
        )
        return len(orbit_distance_data)

    def __import_data_outpost(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.outpost import Outpost
        if not self.__helper.get_database().table_exists("outpost"):
            return False

        outpost_import = ImportData("outpost", load=True)
        if not outpost_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_long()):
            return False

        self.__helper.start_timer("import")

        outpost_data = self.__api.fetch(self.__api.OUTPOSTS)
        if outpost_data:
            for index, data in enumerate(outpost_data):
                outpost = Outpost(data["id"])
                outpost.set_data(data)
                outpost.persist(index < len(outpost_data) - 1)

        outpost_import.set_date_imported(self.__helper.get_timestamp())
        outpost_import.set_dataset_count(len(outpost_data))
        outpost_import.set_time_taken(self.__helper.end_timer("import"))
        outpost_import.persist()
        self.__helper.get_handler_debug().write(
            f"Outpost data imported: {outpost_import.get_dataset_count()} record(s) in {outpost_import.get_time_taken()}s"
        )
        return len(outpost_data)

    def __import_data_planet(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.planet import Planet
        if not self.__helper.get_database().table_exists("planet"):
            return False

        planet_import = ImportData("planet", load=True)
        if not planet_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_long()):
            return False

        self.__helper.start_timer("import")

        planet_data = self.__api.fetch(self.__api.PLANETS)
        if planet_data:
            for index, data in enumerate(planet_data):
                planet = Planet(data["id"])
                planet.set_data(data)
                planet.persist(index < len(planet_data) - 1)

        planet_import.set_date_imported(self.__helper.get_timestamp())
        planet_import.set_dataset_count(len(planet_data))
        planet_import.set_time_taken(self.__helper.end_timer("import"))
        planet_import.persist()
        self.__helper.get_handler_debug().write(
            f"Planet data imported: {planet_import.get_dataset_count()} record(s) in {planet_import.get_time_taken()}s"
        )
        return len(planet_data)

    def __import_data_poi(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.poi import Poi
        if not self.__helper.get_database().table_exists("poi"):
            return False

        poi_import = ImportData("poi", load=True)
        if not poi_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_long()):
            return False

        self.__helper.start_timer("import")

        poi_data = self.__api.fetch(self.__api.POI)
        if poi_data:
            for index, data in enumerate(poi_data):
                poi = Poi(data["id"])
                poi.set_data(data)
                poi.persist(index < len(poi_data) - 1)

        poi_import.set_date_imported(self.__helper.get_timestamp())
        poi_import.set_dataset_count(len(poi_data))
        poi_import.set_time_taken(self.__helper.end_timer("import"))
        poi_import.persist()
        self.__helper.get_handler_debug().write(
            f"POI data imported: {poi_import.get_dataset_count()} record(s) in {poi_import.get_time_taken()}s"
        )
        return len(poi_data)

    def __import_data_refinery_audit(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.refinery_audit import RefineryAudit
        if not self.__helper.get_database().table_exists("refinery_audit"):
            return False

        refinery_audit_import = ImportData("refinery_audit", load=True)
        if not refinery_audit_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_mid()):
            return False

        self.__helper.start_timer("import")

        refinery_audit_data = self.__api.fetch(self.__api.REFINERIES_AUDITS)
        if refinery_audit_data:
            for index, data in enumerate(refinery_audit_data):
                refinery_audit = RefineryAudit(data["id"])
                refinery_audit.set_data(data)
                refinery_audit.persist(index < len(refinery_audit_data) - 1)

        refinery_audit_import.set_date_imported(self.__helper.get_timestamp())
        refinery_audit_import.set_dataset_count(len(refinery_audit_data))
        refinery_audit_import.set_time_taken(self.__helper.end_timer("import"))
        refinery_audit_import.persist()
        self.__helper.get_handler_debug().write(
            f"Refinery Audit data imported: {refinery_audit_import.get_dataset_count()} record(s) in {refinery_audit_import.get_time_taken()}s"
        )
        return len(refinery_audit_data)

    def __import_data_refinery_method(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.refinery_method import RefineryMethod
        if not self.__helper.get_database().table_exists("refinery_method"):
            return False

        refinery_method_import = ImportData("refinery_method", load=True)
        if not refinery_method_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_long()):
            return False

        self.__helper.start_timer("import")

        refinery_method_data = self.__api.fetch(self.__api.REFINERIES_METHODS)
        if refinery_method_data:
            for index, data in enumerate(refinery_method_data):
                refinery_method = RefineryMethod(data["id"])
                refinery_method.set_data(data)
                refinery_method.persist(index < len(refinery_method_data) - 1)

        refinery_method_import.set_date_imported(self.__helper.get_timestamp())
        refinery_method_import.set_dataset_count(len(refinery_method_data))
        refinery_method_import.set_time_taken(self.__helper.end_timer("import"))
        refinery_method_import.persist()
        self.__helper.get_handler_debug().write(
            f"Refinery Method data imported: {refinery_method_import.get_dataset_count()} record(s) in {refinery_method_import.get_time_taken()}s"
        )
        return len(refinery_method_data)

    def __import_data_space_station(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.space_station import SpaceStation
        if not self.__helper.get_database().table_exists("space_station"):
            return False

        space_station_import = ImportData("space_station", load=True)
        if not space_station_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_long()):
            return False

        self.__helper.start_timer("import")

        space_station_data = self.__api.fetch(self.__api.SPACE_STATIONS)
        if space_station_data:
            for index, data in enumerate(space_station_data):
                space_station = SpaceStation(data["id"])
                space_station.set_data(data)
                space_station.persist(index < len(space_station_data) - 1)

        space_station_import.set_date_imported(self.__helper.get_timestamp())
        space_station_import.set_dataset_count(len(space_station_data))
        space_station_import.set_time_taken(self.__helper.end_timer("import"))
        space_station_import.persist()
        self.__helper.get_handler_debug().write(
            f"Space Station data imported: {space_station_import.get_dataset_count()} record(s) in {space_station_import.get_time_taken()}s"
        )
        return len(space_station_data)

    def __import_data_star_system(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.star_system import StarSystem
        if not self.__helper.get_database().table_exists("star_system"):
            return False

        star_system_import = ImportData("star_system", load=True)
        if not star_system_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_long()):
            return False

        self.__helper.start_timer("import")

        star_system_data = self.__api.fetch(self.__api.STAR_SYSTEMS)
        if star_system_data:
            for index, data in enumerate(star_system_data):
                star_system = StarSystem(data["id"])
                star_system.set_data(data)
                star_system.persist(index < len(star_system_data) - 1)

        star_system_import.set_date_imported(self.__helper.get_timestamp())
        star_system_import.set_dataset_count(len(star_system_data))
        star_system_import.set_time_taken(self.__helper.end_timer("import"))
        star_system_import.persist()
        self.__helper.get_handler_debug().write(
            f"Star System data imported: {star_system_import.get_dataset_count()} record(s) in {star_system_import.get_time_taken()}s"
        )
        return len(star_system_data)

    def __import_data_terminal(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.terminal import Terminal
        if not self.__helper.get_database().table_exists("terminal"):
            return False

        terminal_import = ImportData("terminal", load=True)
        if not terminal_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_long()):
            return False

        self.__helper.start_timer("import")

        terminal_data = self.__api.fetch(self.__api.TERMINALS)
        if terminal_data:
            for index, data in enumerate(terminal_data):
                terminal = Terminal(data["id"])
                terminal.set_data(data)
                terminal.persist(index < len(terminal_data) - 1)

        terminal_import.set_date_imported(self.__helper.get_timestamp())
        terminal_import.set_dataset_count(len(terminal_data))
        terminal_import.set_time_taken(self.__helper.end_timer("import"))
        terminal_import.persist()
        self.__helper.get_handler_debug().write(
            f"Terminal data imported: {terminal_import.get_dataset_count()} record(s) in {terminal_import.get_time_taken()}s"
        )
        return len(terminal_data)

    def __import_data_vehicle(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.vehicle import Vehicle
        if not self.__helper.get_database().table_exists("vehicle"):
            return False

        vehicle_import = ImportData("vehicle", load=True)
        if not vehicle_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_long()):
            return False

        self.__helper.start_timer("import")

        vehicle_data = self.__api.fetch(self.__api.VEHICLES)
        if vehicle_data:
            for index, data in enumerate(vehicle_data):
                vehicle = Vehicle(data["id"])
                vehicle.set_data(data)
                vehicle.persist(index < len(vehicle_data) - 1)

        vehicle_import.set_date_imported(self.__helper.get_timestamp())
        vehicle_import.set_dataset_count(len(vehicle_data))
        vehicle_import.set_time_taken(self.__helper.end_timer("import"))
        vehicle_import.persist()
        self.__helper.get_handler_debug().write(
            f"Vehicle data imported: {vehicle_import.get_dataset_count()} record(s) in {vehicle_import.get_time_taken()}s"
        )
        return len(vehicle_data)

    def __import_data_vehicle_purchase_price(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.vehicle_purchase_price import VehiclePurchasePrice
        if not self.__helper.get_database().table_exists("vehicle_purchase_price"):
            return False

        vehicle_price_import = ImportData("vehicle_purchase_price", load=True)
        if not vehicle_price_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_mid()):
            return False

        self.__helper.start_timer("import")

        vehicle_price_data = self.__api.fetch(self.__api.VEHICLES_PURCHASES_PRICES)
        if vehicle_price_data:
            for index, data in enumerate(vehicle_price_data):
                vehicle_price = VehiclePurchasePrice(data["id"])
                vehicle_price.set_data(data)
                vehicle_price.persist(index < len(vehicle_price_data) - 1)

        vehicle_price_import.set_date_imported(self.__helper.get_timestamp())
        vehicle_price_import.set_dataset_count(len(vehicle_price_data))
        vehicle_price_import.set_time_taken(self.__helper.end_timer("import"))
        vehicle_price_import.persist()
        self.__helper.get_handler_debug().write(
            f"Vehicle Price data imported: {vehicle_price_import.get_dataset_count()} record(s) in {vehicle_price_import.get_time_taken()}s"
        )
        return len(vehicle_price_data)

    def __import_data_vehicle_rental_price(self) -> bool | int:
        from skills.uexcorp_beta.uexcorp.model.import_data import ImportData
        from skills.uexcorp_beta.uexcorp.model.vehicle_rental_price import VehicleRentalPrice
        if not self.__helper.get_database().table_exists("vehicle_rental_price"):
            return False

        vehicle_rental_import = ImportData("vehicle_rental_price", load=True)
        if not vehicle_rental_import.needs_import(self.__helper.get_handler_config().get_cache_lifetime_mid()):
            return False

        self.__helper.start_timer("import")

        vehicle_rental_data = self.__api.fetch(self.__api.VEHICLES_RENTALS_PRICES)
        if vehicle_rental_data:
            for index, data in enumerate(vehicle_rental_data):
                vehicle_rental = VehicleRentalPrice(data["id"])
                vehicle_rental.set_data(data)
                vehicle_rental.persist(index < len(vehicle_rental_data) - 1)

        vehicle_rental_import.set_date_imported(self.__helper.get_timestamp())
        vehicle_rental_import.set_dataset_count(len(vehicle_rental_data))
        vehicle_rental_import.set_time_taken(self.__helper.end_timer("import"))
        vehicle_rental_import.persist()
        self.__helper.get_handler_debug().write(
            f"Vehicle Rental data imported: {vehicle_rental_import.get_dataset_count()} record(s) in {vehicle_rental_import.get_time_taken()}s"
        )
        return len(vehicle_rental_data)
