from skills.uexcorp_beta.uexcorp.data_access.data_access import DataAccess
from skills.uexcorp_beta.uexcorp.database.filter import Filter
from skills.uexcorp_beta.uexcorp.model.terminal import Terminal


class TerminalDataAccess(DataAccess):
    def __init__(
            self,
    ):
        super().__init__(
            table="terminal",
            model=Terminal
        )
        self.fields = [
            "id",
            "id_star_system",
            "id_planet",
            "id_orbit",
            "id_moon",
            "id_space_station",
            "id_outpost",
            "id_poi",
            "id_city",
            "id_faction",
            "id_company",
            "name",
            "nickname",
            "code",
            "type",
            "screenshot",
            "screenshot_thumbnail",
            "screenshot_author",
            "is_available",
            "is_available_live",
            "is_visible",
            "is_default_system",
            "is_affinity_influenceable",
            "is_habitation",
            "is_refinery",
            "is_cargo_center",
            "is_medical",
            "is_food",
            "is_shop_fps",
            "is_shop_vehicle",
            "is_refuel",
            "is_repair",
            "is_nqa",
            "is_player_owned",
            "is_auto_load",
            "has_loading_dock",
            "has_docking_port",
            "has_freight_elevator",
            "date_added",
            "date_modified",
            "star_system_name",
            "planet_name",
            "orbit_name",
            "moon_name",
            "space_station_name",
            "outpost_name",
            "city_name",
            "faction_name",
            "company_name",
            "max_container_size",
            "is_blacklisted",
        ]

    def load(self, **params) -> list[Terminal]:
        return super().load(**params)

    def load_by_property(self, property: str, value: any) -> Terminal:
        return super().load_by_property(property, value)

    def add_filter_by_location_name_whitelist(self, location_names: str | list[str]) -> "TerminalDataAccess":
        grouped_filter = Filter()
        grouped_filter.where("star_system_name", location_names, is_or=True)
        grouped_filter.where("planet_name", location_names, is_or=True)
        grouped_filter.where("orbit_name", location_names, is_or=True)
        grouped_filter.where("moon_name", location_names, is_or=True)
        grouped_filter.where("space_station_name", location_names, is_or=True)
        grouped_filter.where("outpost_name", location_names, is_or=True)
        grouped_filter.where("city_name", location_names, is_or=True)
        grouped_filter.where("name", location_names, is_or=True)
        self.filter.apply_filter(grouped_filter)
        return self

    def add_filter_by_location_name_blacklist(self, location_names: str | list[str]) -> "TerminalDataAccess":
        self.filter.where("star_system_name", location_names, "!=")
        self.filter.where("planet_name", location_names, "!=")
        self.filter.where("orbit_name", location_names, "!=")
        self.filter.where("moon_name", location_names, "!=")
        self.filter.where("space_station_name", location_names, "!=")
        self.filter.where("outpost_name", location_names, "!=")
        self.filter.where("city_name", location_names, "!=")
        self.filter.where("name", location_names, "!=")
        return self

    def add_filter_by_id_star_system(self, id_star_system: int | list[int]) -> "TerminalDataAccess":
        self.filter.where("id_star_system", id_star_system)
        return self

    def add_filter_by_id_planet(self, id_planet: int | list[int]) -> "TerminalDataAccess":
        self.filter.where("id_planet", id_planet)
        return self

    def add_filter_by_id_orbit(self, id_orbit: int | list[int]) -> "TerminalDataAccess":
        self.filter.where("id_orbit", id_orbit)
        return self

    def add_filter_by_id_moon(self, id_moon: int | list[int]) -> "TerminalDataAccess":
        self.filter.where("id_moon", id_moon)
        return self

    def add_filter_by_id_space_station(self, id_space_station: int | list[int]) -> "TerminalDataAccess":
        self.filter.where("id_space_station", id_space_station)
        return self

    def add_filter_by_id_outpost(self, id_outpost: int | list[int]) -> "TerminalDataAccess":
        self.filter.where("id_outpost", id_outpost)
        return self

    def add_filter_by_id_poi(self, id_poi: int | list[int]) -> "TerminalDataAccess":
        self.filter.where("id_poi", id_poi)
        return self

    def add_filter_by_id_city(self, id_city: int | list[int]) -> "TerminalDataAccess":
        self.filter.where("id_city", id_city)
        return self

    def add_filter_by_id_faction(self, id_faction: int | list[int]) -> "TerminalDataAccess":
        self.filter.where("id_faction", id_faction)
        return self

    def add_filter_by_id_company(self, id_company: int | list[int]) -> "TerminalDataAccess":
        self.filter.where("id_company", id_company)
        return self

    def add_filter_by_name(self, name: str | list[str]) -> "TerminalDataAccess":
        self.filter.where("name", name)
        return self

    def add_filter_by_nickname(self, nickname: str | list[str]) -> "TerminalDataAccess":
        self.filter.where("nickname", nickname)
        return self

    def add_filter_by_code(self, code: str | list[str]) -> "TerminalDataAccess":
        self.filter.where("code", code)
        return self

    def add_filter_by_type(self, type: str | list[str]) -> "TerminalDataAccess":
        self.filter.where("type", type)
        return self

    def add_filter_by_is_available(self, is_available: bool) -> "TerminalDataAccess":
        self.filter.where("is_available", is_available)
        return self

    def add_filter_by_is_available_live(self, is_available_live: bool) -> "TerminalDataAccess":
        self.filter.where("is_available_live", is_available_live)
        return self

    def add_filter_by_is_visible(self, is_visible: bool) -> "TerminalDataAccess":
        self.filter.where("is_visible", is_visible)
        return self

    def add_filter_by_is_default_system(self, is_default_system: bool) -> "TerminalDataAccess":
        self.filter.where("is_default_system", is_default_system)
        return self

    def add_filter_by_is_affinity_influenceable(self, is_affinity_influenceable: bool) -> "TerminalDataAccess":
        self.filter.where("is_affinity_influenceable", is_affinity_influenceable)
        return self

    def add_filter_by_is_habitation(self, is_habitation: bool) -> "TerminalDataAccess":
        self.filter.where("is_habitation", is_habitation)
        return self

    def add_filter_by_is_refinery(self, is_refinery: bool) -> "TerminalDataAccess":
        self.filter.where("is_refinery", is_refinery)
        return self

    def add_filter_by_is_cargo_center(self, is_cargo_center: bool) -> "TerminalDataAccess":
        self.filter.where("is_cargo_center", is_cargo_center)
        return self

    def add_filter_by_is_medical(self, is_medical: bool) -> "TerminalDataAccess":
        self.filter.where("is_medical", is_medical)
        return self

    def add_filter_by_is_food(self, is_food: bool) -> "TerminalDataAccess":
        self.filter.where("is_food", is_food)
        return self

    def add_filter_by_is_shop_fps(self, is_shop_fps: bool) -> "TerminalDataAccess":
        self.filter.where("is_shop_fps", is_shop_fps)
        return self

    def add_filter_by_is_shop_vehicle(self, is_shop_vehicle: bool) -> "TerminalDataAccess":
        self.filter.where("is_shop_vehicle", is_shop_vehicle)
        return self

    def add_filter_by_is_refuel(self, is_refuel: bool) -> "TerminalDataAccess":
        self.filter.where("is_refuel", is_refuel)
        return self

    def add_filter_by_is_repair(self, is_repair: bool) -> "TerminalDataAccess":
        self.filter.where("is_repair", is_repair)
        return self

    def add_filter_by_is_nqa(self, is_nqa: bool) -> "TerminalDataAccess":
        self.filter.where("is_nqa", is_nqa)
        return self

    def add_filter_by_is_player_owned(self, is_player_owned: bool) -> "TerminalDataAccess":
        self.filter.where("is_player_owned", is_player_owned)
        return self

    def add_filter_by_is_auto_load(self, is_auto_load: bool) -> "TerminalDataAccess":
        self.filter.where("is_auto_load", is_auto_load)
        return self

    def add_filter_by_has_loading_dock(self, has_loading_dock: bool) -> "TerminalDataAccess":
        self.filter.where("has_loading_dock", has_loading_dock)
        return self

    def add_filter_by_has_docking_port(self, has_docking_port: bool) -> "TerminalDataAccess":
        self.filter.where("has_docking_port", has_docking_port)
        return self

    def add_filter_by_has_freight_elevator(self, has_freight_elevator: bool) -> "TerminalDataAccess":
        self.filter.where("has_freight_elevator", has_freight_elevator)
        return self

    def add_filter_by_date_added(self, date_added: str | list[str]) -> "TerminalDataAccess":
        self.filter.where("date_added", date_added)
        return self

    def add_filter_by_date_modified(self, date_modified: str | list[str]) -> "TerminalDataAccess":
        self.filter.where("date_modified", date_modified)
        return self

    def add_filter_by_star_system_name(self, star_system_name: str | list[str]) -> "TerminalDataAccess":
        self.filter.where("star_system_name", star_system_name)
        return self

    def add_filter_by_planet_name(self, planet_name: str | list[str]) -> "TerminalDataAccess":
        self.filter.where("planet_name", planet_name)
        return self

    def add_filter_by_orbit_name(self, orbit_name: str | list[str]) -> "TerminalDataAccess":
        self.filter.where("orbit_name", orbit_name)
        return self

    def add_filter_by_moon_name(self, moon_name: str | list[str]) -> "TerminalDataAccess":
        self.filter.where("moon_name", moon_name)
        return self

    def add_filter_by_space_station_name(self, space_station_name: str | list[str]) -> "TerminalDataAccess":
        self.filter.where("space_station_name", space_station_name)
        return self

    def add_filter_by_outpost_name(self, outpost_name: str | list[str]) -> "TerminalDataAccess":
        self.filter.where("outpost_name", outpost_name)
        return self

    def add_filter_by_city_name(self, city_name: str | list[str]) -> "TerminalDataAccess":
        self.filter.where("city_name", city_name)
        return self

    def add_filter_by_faction_name(self, faction_name: str | list[str]) -> "TerminalDataAccess":
        self.filter.where("faction_name", faction_name)
        return self

    def add_filter_by_company_name(self, company_name: str | list[str]) -> "TerminalDataAccess":
        self.filter.where("company_name", company_name)
        return self

    def add_filter_by_max_container_size(self, max_container_size: int | list[int]) -> "TerminalDataAccess":
        self.filter.where("max_container_size", max_container_size)
        return self

    def add_filter_by_is_blacklisted(self, is_blacklisted: bool) -> "TerminalDataAccess":
        self.filter.where("is_blacklisted", is_blacklisted)
        return self