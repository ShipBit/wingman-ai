try:
    from skills.uexcorp_beta.uexcorp.data_access.data_access import DataAccess
    from skills.uexcorp_beta.uexcorp.model.space_station import SpaceStation
except ImportError:
    from uexcorp_beta.uexcorp.data_access.data_access import DataAccess
    from uexcorp_beta.uexcorp.model.space_station import SpaceStation


class SpaceStationDataAccess(DataAccess):
    def __init__(
            self,
    ):
        super().__init__(
            table="space_station",
            model=SpaceStation
        )
        self.fields = [
            "id",
            "id_star_system",
            "id_planet",
            "id_orbit",
            "id_moon",
            "id_city",
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
            "is_lagrange",
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
            "city_name",
            "faction_name",
            "jurisdiction_name",
        ]

    def load(self, **params) -> list[SpaceStation]:
        return super().load(**params)

    def load_by_property(self, property: str, value: any) -> SpaceStation | None:
        return super().load_by_property(property, value)

    def add_filter_by_id_star_system(self, id_star_system: int | list[int]) -> "SpaceStationDataAccess":
        self.filter.where("id_star_system", id_star_system)
        return self
    
    def add_filter_by_id_planet(self, id_planet: int | list[int]) -> "SpaceStationDataAccess":
        self.filter.where("id_planet", id_planet)
        return self
    
    def add_filter_by_id_orbit(self, id_orbit: int | list[int]) -> "SpaceStationDataAccess":
        self.filter.where("id_orbit", id_orbit)
        return self

    def add_filter_by_id_moon(self, id_moon: int | list[int]) -> "SpaceStationDataAccess":
        self.filter.where("id_moon", id_moon)
        return self

    def add_filter_by_id_city(self, id_city: int | list[int]) -> "SpaceStationDataAccess":
        self.filter.where("id_city", id_city)
        return self

    def add_filter_by_id_faction(self, id_faction: int | list[int]) -> "SpaceStationDataAccess":
        self.filter.where("id_faction", id_faction)
        return self

    def add_filter_by_id_jurisdiction(self, id_jurisdiction: int | list[int]) -> "SpaceStationDataAccess":
        self.filter.where("id_jurisdiction", id_jurisdiction)
        return self

    def add_filter_by_name(self, name: str | list[str]) -> "SpaceStationDataAccess":
        self.filter.where("name", name)
        return self

    def add_filter_by_nickname(self, nickname: str | list[str]) -> "SpaceStationDataAccess":
        self.filter.where("nickname", nickname)
        return self

    def add_filter_by_is_available(self, is_available: bool) -> "SpaceStationDataAccess":
        self.filter.where("is_available", is_available)
        return self

    def add_filter_by_is_available_live(self, is_available_live: bool) -> "SpaceStationDataAccess":
        self.filter.where("is_available_live", is_available_live)
        return self

    def add_filter_by_is_visible(self, is_visible: bool) -> "SpaceStationDataAccess":
        self.filter.where("is_visible", is_visible)
        return self

    def add_filter_by_is_default(self, is_default: bool) -> "SpaceStationDataAccess":
        self.filter.where("is_default", is_default)
        return self

    def add_filter_by_is_monitored(self, is_monitored: bool) -> "SpaceStationDataAccess":
        self.filter.where("is_monitored", is_monitored)
        return self

    def add_filter_by_is_armistice(self, is_armistice: bool) -> "SpaceStationDataAccess":
        self.filter.where("is_armistice", is_armistice)
        return self

    def add_filter_by_is_landable(self, is_landable: bool) -> "SpaceStationDataAccess":
        self.filter.where("is_landable", is_landable)
        return self

    def add_filter_by_is_decommissioned(self, is_decommissioned: bool) -> "SpaceStationDataAccess":
        self.filter.where("is_decommissioned", is_decommissioned)
        return self

    def add_filter_by_is_lagrange(self, is_lagrange: bool) -> "SpaceStationDataAccess":
        self.filter.where("is_lagrange", is_lagrange)
        return self

    def add_filter_by_has_quantum_marker(self, has_quantum_marker: bool) -> "SpaceStationDataAccess":
        self.filter.where("has_quantum_marker", has_quantum_marker)
        return self

    def add_filter_by_has_trade_terminal(self, has_trade_terminal: bool) -> "SpaceStationDataAccess":
        self.filter.where("has_trade_terminal", has_trade_terminal)
        return self

    def add_filter_by_has_habitation(self, has_habitation: bool) -> "SpaceStationDataAccess":
        self.filter.where("has_habitation", has_habitation)
        return self

    def add_filter_by_has_refinery(self, has_refinery: bool) -> "SpaceStationDataAccess":
        self.filter.where("has_refinery", has_refinery)
        return self

    def add_filter_by_has_cargo_center(self, has_cargo_center: bool) -> "SpaceStationDataAccess":
        self.filter.where("has_cargo_center", has_cargo_center)
        return self

    def add_filter_by_has_clinic(self, has_clinic: bool) -> "SpaceStationDataAccess":
        self.filter.where("has_clinic", has_clinic)
        return self

    def add_filter_by_has_food(self, has_food: bool) -> "SpaceStationDataAccess":
        self.filter.where("has_food", has_food)
        return self

    def add_filter_by_has_shops(self, has_shops: bool) -> "SpaceStationDataAccess":
        self.filter.where("has_shops", has_shops)
        return self

    def add_filter_by_has_refuel(self, has_refuel: bool) -> "SpaceStationDataAccess":
        self.filter.where("has_refuel", has_refuel)
        return self

    def add_filter_by_has_repair(self, has_repair: bool) -> "SpaceStationDataAccess":
        self.filter.where("has_repair", has_repair)
        return self

    def add_filter_by_has_gravity(self, has_gravity: bool) -> "SpaceStationDataAccess":
        self.filter.where("has_gravity", has_gravity)
        return self

    def add_filter_by_has_loading_dock(self, has_loading_dock: bool) -> "SpaceStationDataAccess":
        self.filter.where("has_loading_dock", has_loading_dock)
        return self

    def add_filter_by_has_docking_port(self, has_docking_port: bool) -> "SpaceStationDataAccess":
        self.filter.where("has_docking_port", has_docking_port)
        return self

    def add_filter_by_has_freight_elevator(self, has_freight_elevator: bool) -> "SpaceStationDataAccess":
        self.filter.where("has_freight_elevator", has_freight_elevator)
        return self

    def add_filter_by_pad_types(self, pad_types: str | list[str]) -> "SpaceStationDataAccess":
        self.filter.where("pad_types", pad_types)
        return self

    def add_filter_by_date_added(self, date_added: str | list[str]) -> "SpaceStationDataAccess":
        self.filter.where("date_added", date_added)
        return self

    def add_filter_by_date_modified(self, date_modified: str | list[str]) -> "SpaceStationDataAccess":
        self.filter.where("date_modified", date_modified)
        return self

    def add_filter_by_star_system_name(self, star_system_name: str | list[str]) -> "SpaceStationDataAccess":
        self.filter.where("star_system_name", star_system_name)
        return self

    def add_filter_by_planet_name(self, planet_name: str | list[str]) -> "SpaceStationDataAccess":
        self.filter.where("planet_name", planet_name)
        return self

    def add_filter_by_orbit_name(self, orbit_name: str | list[str]) -> "SpaceStationDataAccess":
        self.filter.where("orbit_name", orbit_name)
        return self

    def add_filter_by_city_name(self, city_name: str | list[str]) -> "SpaceStationDataAccess":
        self.filter.where("city_name", city_name)
        return self

    def add_filter_by_faction_name(self, faction_name: str) -> "SpaceStationDataAccess":
        self.filter.where("faction_name", faction_name)
        return self

    def add_filter_by_jurisdiction_name(self, jurisdiction_name: str) -> "SpaceStationDataAccess":
        self.filter.where("jurisdiction_name", jurisdiction_name)
        return self
