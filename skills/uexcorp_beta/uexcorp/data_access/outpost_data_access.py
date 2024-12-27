try:
    from skills.uexcorp_beta.uexcorp.database.filter import Filter
    from skills.uexcorp_beta.uexcorp.data_access.data_access import DataAccess
    from skills.uexcorp_beta.uexcorp.model.outpost import Outpost
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.database.filter import Filter
    from uexcorp_beta.uexcorp.data_access.data_access import DataAccess
    from uexcorp_beta.uexcorp.model.outpost import Outpost


class OutpostDataAccess(DataAccess):
    def __init__(
            self,
    ):
        super().__init__(
            table="outpost",
            model=Outpost
        )
        self.fields = [
            "id",
            "id_star_system",
            "id_planet",
            "id_orbit",
            "id_moon",
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
            "faction_name",
            "jurisdiction_name"
        ]

    def load(self, **params) -> list[Outpost]:
        return super().load(**params)

    def load_by_property(self, property: str, value: any) -> Outpost | None:
        return super().load_by_property(property, value)

    def add_filter_by_location_name_whitelist(self, location_names: str | list[str]) -> "OutpostDataAccess":
        grouped_filter = Filter()
        grouped_filter.where("star_system_name", location_names, is_or=True)
        grouped_filter.where("planet_name", location_names, is_or=True)
        grouped_filter.where("orbit_name", location_names, is_or=True)
        grouped_filter.where("moon_name", location_names, is_or=True)
        grouped_filter.where("name", location_names, is_or=True)
        self.filter.apply_filter(grouped_filter)
        return self

    def add_filter_by_id_star_system(self, id_star_system: int | list[int]) -> "OutpostDataAccess":
        self.filter.where("id_star_system", id_star_system)
        return self
    
    def add_filter_by_id_planet(self, id_planet: int | list[int]) -> "OutpostDataAccess":
        self.filter.where("id_planet", id_planet)
        return self
    
    def add_filter_by_id_orbit(self, id_orbit: int | list[int]) -> "OutpostDataAccess":
        self.filter.where("id_orbit", id_orbit)
        return self

    def add_filter_by_id_moon(self, id_moon: int | list[int]) -> "OutpostDataAccess":
        self.filter.where("id_moon", id_moon)
        return self

    def add_filter_by_id_faction(self, id_faction: int | list[int]) -> "OutpostDataAccess":
        self.filter.where("id_faction", id_faction)
        return self

    def add_filter_by_id_jurisdiction(self, id_jurisdiction: int | list[int]) -> "OutpostDataAccess":
        self.filter.where("id_jurisdiction", id_jurisdiction)
        return self

    def add_filter_by_name(self, name: str | list[str]) -> "OutpostDataAccess":
        self.filter.where("name", name)
        return self

    def add_filter_by_nickname(self, nickname: str | list[str]) -> "OutpostDataAccess":
        self.filter.where("nickname", nickname)
        return self

    def add_filter_by_is_available(self, is_available: bool) -> "OutpostDataAccess":
        self.filter.where("is_available", int(is_available))
        return self

    def add_filter_by_is_available_live(self, is_available_live: bool) -> "OutpostDataAccess":
        self.filter.where("is_available_live", int(is_available_live))
        return self

    def add_filter_by_is_visible(self, is_visible: bool) -> "OutpostDataAccess":
        self.filter.where("is_visible", int(is_visible))
        return self

    def add_filter_by_is_default(self, is_default: bool) -> "OutpostDataAccess":
        self.filter.where("is_default", int(is_default))
        return self

    def add_filter_by_is_monitored(self, is_monitored: bool) -> "OutpostDataAccess":
        self.filter.where("is_monitored", int(is_monitored))
        return self

    def add_filter_by_is_armistice(self, is_armistice: bool) -> "OutpostDataAccess":
        self.filter.where("is_armistice", int(is_armistice))
        return self

    def add_filter_by_is_landable(self, is_landable: bool) -> "OutpostDataAccess":
        self.filter.where("is_landable", int(is_landable))
        return self

    def add_filter_by_is_decommissioned(self, is_decommissioned: bool) -> "OutpostDataAccess":
        self.filter.where("is_decommissioned", int(is_decommissioned))
        return self

    def add_filter_by_has_quantum_marker(self, has_quantum_marker: bool) -> "OutpostDataAccess":
        self.filter.where("has_quantum_marker", int(has_quantum_marker))
        return self

    def add_filter_by_has_trade_terminal(self, has_trade_terminal: bool) -> "OutpostDataAccess":
        self.filter.where("has_trade_terminal", int(has_trade_terminal))
        return self

    def add_filter_by_has_habitation(self, has_habitation: bool) -> "OutpostDataAccess":
        self.filter.where("has_habitation", int(has_habitation))
        return self

    def add_filter_by_has_refinery(self, has_refinery: bool) -> "OutpostDataAccess":
        self.filter.where("has_refinery", int(has_refinery))
        return self

    def add_filter_by_has_cargo_center(self, has_cargo_center: bool) -> "OutpostDataAccess":
        self.filter.where("has_cargo_center", int(has_cargo_center))
        return self

    def add_filter_by_has_clinic(self, has_clinic: bool) -> "OutpostDataAccess":
        self.filter.where("has_clinic", int(has_clinic))
        return self

    def add_filter_by_has_food(self, has_food: bool) -> "OutpostDataAccess":
        self.filter.where("has_food", int(has_food))
        return self

    def add_filter_by_has_shops(self, has_shops: bool) -> "OutpostDataAccess":
        self.filter.where("has_shops", int(has_shops))
        return self

    def add_filter_by_has_refuel(self, has_refuel: bool) -> "OutpostDataAccess":
        self.filter.where("has_refuel", int(has_refuel))
        return self

    def add_filter_by_has_repair(self, has_repair: bool) -> "OutpostDataAccess":
        self.filter.where("has_repair", int(has_repair))
        return self

    def add_filter_by_has_gravity(self, has_gravity: bool) -> "OutpostDataAccess":
        self.filter.where("has_gravity", int(has_gravity))
        return self

    def add_filter_by_has_loading_dock(self, has_loading_dock: bool) -> "OutpostDataAccess":
        self.filter.where("has_loading_dock", int(has_loading_dock))
        return self

    def add_filter_by_has_docking_port(self, has_docking_port: bool) -> "OutpostDataAccess":
        self.filter.where("has_docking_port", int(has_docking_port))
        return self

    def add_filter_by_has_freight_elevator(self, has_freight_elevator: bool) -> "OutpostDataAccess":
        self.filter.where("has_freight_elevator", int(has_freight_elevator))
        return self

    def add_filter_by_pad_types(self, pad_types: str | list[str]) -> "OutpostDataAccess":
        self.filter.where("pad_types", pad_types)
        return self

    def add_filter_by_date_added(self, date_added: str | list[str]) -> "OutpostDataAccess":
        self.filter.where("date_added", date_added)
        return self

    def add_filter_by_date_modified(self, date_modified: str | list[str]) -> "OutpostDataAccess":
        self.filter.where("date_modified", date_modified)
        return self

    def add_filter_by_star_system_name(self, star_system_name: str | list[str]) -> "OutpostDataAccess":
        self.filter.where("star_system_name", star_system_name)
        return self

    def add_filter_by_planet_name(self, planet_name: str | list[str]) -> "OutpostDataAccess":
        self.filter.where("planet_name", planet_name)
        return self

    def add_filter_by_orbit_name(self, orbit_name: str | list[str]) -> "OutpostDataAccess":
        self.filter.where("orbit_name", orbit_name)
        return self

    def add_filter_by_moon_name(self, moon_name: str | list[str]) -> "OutpostDataAccess":
        self.filter.where("moon_name", moon_name)
        return self

    def add_filter_by_faction_name(self, faction_name: str | list[str]) -> "OutpostDataAccess":
        self.filter.where("faction_name", faction_name)
        return self

    def add_filter_by_jurisdiction_name(self, jurisdiction_name: str | list[str]) -> "OutpostDataAccess":
        self.filter.where("jurisdiction_name", jurisdiction_name)
        return self
