try:
    from skills.uexcorp.uexcorp.database.filter import Filter
    from skills.uexcorp.uexcorp.data_access.data_access import DataAccess
    from skills.uexcorp.uexcorp.model.poi import Poi
except ModuleNotFoundError:
    from uexcorp.uexcorp.database.filter import Filter
    from uexcorp.uexcorp.data_access.data_access import DataAccess
    from uexcorp.uexcorp.model.poi import Poi


class PoiDataAccess(DataAccess):
    def __init__(
            self,
    ):
        super().__init__(
            table="poi",
            model=Poi
        )
        self.fields = [
            "id",
            "id_star_system",
            "id_planet",
            "id_orbit",
            "id_moon",
            "id_space_station",
            "id_city",
            "id_outpost",
            "id_faction",
            "id_jurisdiction",
            "name",
            "nickname",
            "is_available",
            "is_available_live",
            "is_visible",
            "is_default",
            "is_monitored",
            "is_armistice",
            "is_landable",
            "is_decommissioned",
            "has_quantum_marker",
            "has_trade_terminal",
            "has_habitation",
            "has_refinery",
            "has_cargo_center",
            "has_clinic",
            "has_food",
            "has_shops",
            "has_refuel",
            "has_repair",
            "has_gravity",
            "has_loading_dock",
            "has_docking_port",
            "has_freight_elevator",
            "pad_types",
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
            "jurisdiction_name"
        ]

    def load(self, **params) -> list[Poi]:
        return super().load(**params)

    def load_by_property(self, property: str, value: any) -> Poi | None:
        return super().load_by_property(property, value)

    def add_filter_by_location_name_whitelist(self, location_names: str | list[str]) -> "PoiDataAccess":
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

    def add_filter_by_id_star_system(self, id_star_system: int | list[int]) -> "PoiDataAccess":
        self.filter.where("id_star_system", id_star_system)
        return self
    
    def add_filter_by_id_planet(self, id_planet: int | list[int]) -> "PoiDataAccess":
        self.filter.where("id_planet", id_planet)
        return self
    
    def add_filter_by_id_orbit(self, id_orbit: int | list[int]) -> "PoiDataAccess":
        self.filter.where("id_orbit", id_orbit)
        return self

    def add_filter_by_id_moon(self, id_moon: int | list[int]) -> "PoiDataAccess":
        self.filter.where("id_moon", id_moon)
        return self

    def add_filter_by_id_space_station(self, id_space_station: int | list[int]) -> "PoiDataAccess":
        self.filter.where("id_space_station", id_space_station)
        return self

    def add_filter_by_id_city(self, id_city: int | list[int]) -> "PoiDataAccess":
        self.filter.where("id_city", id_city)
        return self

    def add_filter_by_id_outpost(self, id_outpost: int | list[int]) -> "PoiDataAccess":
        self.filter.where("id_outpost", id_outpost)
        return self

    def add_filter_by_id_faction(self, id_faction: int | list[int]) -> "PoiDataAccess":
        self.filter.where("id_faction", id_faction)
        return self

    def add_filter_by_id_jurisdiction(self, id_jurisdiction: int | list[int]) -> "PoiDataAccess":
        self.filter.where("id_jurisdiction", id_jurisdiction)
        return self

    def add_filter_by_name(self, name: str | list[str]) -> "PoiDataAccess":
        self.filter.where("name", name)
        return self

    def add_filter_by_is_monitored(self, is_monitored: bool) -> "PoiDataAccess":
        self.filter.where("is_monitored", is_monitored)
        return self

    def add_filter_by_is_armistice(self, is_armistice: bool) -> "PoiDataAccess":
        self.filter.where("is_armistice", is_armistice)
        return self

    def add_filter_by_is_landable(self, is_landable: bool) -> "PoiDataAccess":
        self.filter.where("is_landable", is_landable)
        return self

    def add_filter_by_is_decommissioned(self, is_decommissioned: bool) -> "PoiDataAccess":
        self.filter.where("is_decommissioned", is_decommissioned)
        return self

    def add_filter_by_has_quantum_marker(self, has_quantum_marker: bool) -> "PoiDataAccess":
        self.filter.where("has_quantum_marker", has_quantum_marker)
        return self

    def add_filter_by_has_trade_terminal(self, has_trade_terminal: bool) -> "PoiDataAccess":
        self.filter.where("has_trade_terminal", has_trade_terminal)
        return self

    def add_filter_by_has_habitation(self, has_habitation: bool) -> "PoiDataAccess":
        self.filter.where("has_habitation", has_habitation)
        return self

    def add_filter_by_has_refinery(self, has_refinery: bool) -> "PoiDataAccess":
        self.filter.where("has_refinery", has_refinery)
        return self

    def add_filter_by_has_cargo_center(self, has_cargo_center: bool) -> "PoiDataAccess":
        self.filter.where("has_cargo_center", has_cargo_center)
        return self

    def add_filter_by_has_clinic(self, has_clinic: bool) -> "PoiDataAccess":
        self.filter.where("has_clinic", has_clinic)
        return self

    def add_filter_by_has_food(self, has_food: bool) -> "PoiDataAccess":
        self.filter.where("has_food", has_food)
        return self

    def add_filter_by_has_shops(self, has_shops: bool) -> "PoiDataAccess":
        self.filter.where("has_shops", has_shops)
        return self

    def add_filter_by_has_refuel(self, has_refuel: bool) -> "PoiDataAccess":
        self.filter.where("has_refuel", has_refuel)
        return self

    def add_filter_by_has_repair(self, has_repair: bool) -> "PoiDataAccess":
        self.filter.where("has_repair", has_repair)
        return self

    def add_filter_by_has_gravity(self, has_gravity: bool) -> "PoiDataAccess":
        self.filter.where("has_gravity", has_gravity)
        return self

    def add_filter_by_has_loading_dock(self, has_loading_dock: bool) -> "PoiDataAccess":
        self.filter.where("has_loading_dock", has_loading_dock)
        return self

    def add_filter_by_has_docking_port(self, has_docking_port: bool) -> "PoiDataAccess":
        self.filter.where("has_docking_port", has_docking_port)
        return self

    def add_filter_by_has_freight_elevator(self, has_freight_elevator: bool) -> "PoiDataAccess":
        self.filter.where("has_freight_elevator", has_freight_elevator)
        return self

    def add_filter_by_is_available(self, is_available: bool) -> "PoiDataAccess":
        self.filter.where("is_available", is_available)
        return self

    def add_filter_by_is_available_live(self, is_available_live: bool) -> "PoiDataAccess":
        self.filter.where("is_available_live", is_available_live)
        return self

    def add_filter_by_is_visible(self, is_visible: bool) -> "PoiDataAccess":
        self.filter.where("is_visible", is_visible)
        return self

    def add_filter_by_is_default(self, is_default: bool) -> "PoiDataAccess":
        self.filter.where("is_default", is_default)
        return self

    def add_filter_by_is_lagrange(self, is_lagrange: bool) -> "PoiDataAccess":
        self.filter.where("is_lagrange", is_lagrange)
        return self

    def add_filter_by_star_system_name(self, star_system_name: str | list[str]) -> "PoiDataAccess":
        self.filter.where("star_system_name", star_system_name)
        return self

    def add_filter_by_planet_name(self, planet_name: str | list[str]) -> "PoiDataAccess":
        self.filter.where("planet_name", planet_name)
        return self

    def add_filter_by_orbit_name(self, orbit_name: str | list[str]) -> "PoiDataAccess":
        self.filter.where("orbit_name", orbit_name)
        return self

    def add_filter_by_faction_name(self, faction_name: str | list[str]) -> "PoiDataAccess":
        self.filter.where("faction_name", faction_name)
        return self

    def add_filter_by_jurisdiction_name(self, jurisdiction_name: str | list[str]) -> "PoiDataAccess":
        self.filter.where("jurisdiction_name", jurisdiction_name)
        return self
