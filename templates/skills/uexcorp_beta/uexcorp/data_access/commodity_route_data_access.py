try:
    from skills.uexcorp_beta.uexcorp.data_access.data_access import DataAccess
    from skills.uexcorp_beta.uexcorp.model.commodity_route import CommodityRoute
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.data_access.data_access import DataAccess
    from uexcorp_beta.uexcorp.model.commodity_route import CommodityRoute


class CommodityRouteDataAccess(DataAccess):
    def __init__(
            self,
    ):
        super().__init__(
            table="commodity_route",
            model=CommodityRoute
        )
        self.fields = [
            "id",
            "id_commodity",
            "id_star_system_origin",
            "id_star_system_destination",
            "id_planet_origin",
            "id_planet_destination",
            "id_orbit_origin",
            "id_orbit_destination",
            "id_terminal_origin",
            "id_terminal_destination",
            "id_faction_origin",
            "id_faction_destination",
            "code",
            "price_origin",
            "price_origin_users",
            "price_origin_users_rows",
            "price_destination",
            "price_destination_users",
            "price_destination_users_rows",
            "price_margin",
            "scu_origin",
            "scu_origin_users",
            "scu_origin_users_rows",
            "scu_destination",
            "scu_destination_users",
            "scu_destination_users_rows",
            "scu_margin",
            "volatility_origin",
            "volatility_destination",
            "status_origin",
            "status_destination",
            "investment",
            "profit",
            "distance",
            "score",
            "has_docking_port_origin",
            "has_docking_port_destination",
            "has_freight_elevator_origin",
            "has_freight_elevator_destination",
            "has_loading_dock_origin",
            "has_loading_dock_destination",
            "has_refuel_origin",
            "has_refuel_destination",
            "has_cargo_center_origin",
            "has_cargo_center_destination",
            "has_quantum_marker_origin",
            "has_quantum_marker_destination",
            "is_monitored_origin",
            "is_monitored_destination",
            "is_space_station_origin",
            "is_space_station_destination",
            "is_on_ground_origin",
            "is_on_ground_destination",
            "commodity_name",
            "commodity_code",
            "commodity_slug",
            "origin_star_system_name",
            "origin_planet_name",
            "origin_orbit_name",
            "origin_terminal_name",
            "origin_terminal_code",
            "origin_terminal_slug",
            "origin_terminal_is_player_owned",
            "origin_faction_name",
            "destination_star_system_name",
            "destination_planet_name",
            "destination_orbit_name",
            "destination_terminal_name",
            "destination_terminal_code",
            "destination_terminal_slug",
            "destination_terminal_is_player_owned",
            "destination_faction_name",
            "date_added",
        ]

    def load(self, **params) -> list[CommodityRoute]:
        return super().load(**params)

    def load_by_property(self, property: str, value: any) -> CommodityRoute:
        return super().load_by_property(property, value)

    def add_filter_by_commodity_name_whitelist(self, commodity_name_whitelist: list[str]) -> "CommodityRouteDataAccess":
        self.filter.where("commodity_name", commodity_name_whitelist)
        return self

    def add_filter_by_commodity_name_blacklist(self, commodity_name_blacklist: list[str]) -> "CommodityRouteDataAccess":
        self.filter.where("commodity_name", commodity_name_blacklist, 'NOT IN')
        return self

    def add_filter_by_star_system_name_whitelist(self, star_system_name_whitelist: list[str]) -> "CommodityRouteDataAccess":
        self.filter.where("origin_star_system_name", star_system_name_whitelist)
        self.filter.where("destination_star_system_name", star_system_name_whitelist)
        return self

    def add_filter_by_star_system_name_blacklist(self, star_system_name_blacklist: list[str]) -> "CommodityRouteDataAccess":
        self.filter.where("origin_star_system_name", star_system_name_blacklist, 'NOT IN')
        self.filter.where("destination_star_system_name", star_system_name_blacklist, 'NOT IN')
        return self

    def add_filter_by_has_loading_dock(self) -> "CommodityRouteDataAccess":
        self.filter.where("has_loading_dock_origin", True)
        self.filter.where("has_loading_dock_destination", True)
        return self

    def add_filter_by_is_profitable(self) -> "CommodityRouteDataAccess":
        self.filter.where("price_margin", 0, '>')
        return self

    def add_filter_by_in_same_star_system(self) -> "CommodityRouteDataAccess":
        self.filter.where("origin_star_system_name", "destination_star_system_name", value_is_field=True)
        return self

    def add_filter_by_id_star_system_origin(self, id_star_system_origin: int | list[int], **params) -> "CommodityRouteDataAccess":
        self.filter.where("id_star_system_origin", id_star_system_origin, **params)
        return self

    def add_filter_by_id_star_system_destination(self, id_star_system_destination: int | list[int], **params) -> "CommodityRouteDataAccess":
        self.filter.where("id_star_system_destination", id_star_system_destination, **params)
        return self

    def add_filter_by_id_planet_origin(self, id_planet_origin: int | list[int], **params) -> "CommodityRouteDataAccess":
        self.filter.where("id_planet_origin", id_planet_origin, **params)
        return self

    def add_filter_by_id_planet_destination(self, id_planet_destination: int | list[int], **params) -> "CommodityRouteDataAccess":
        self.filter.where("id_planet_destination", id_planet_destination, **params)
        return self

    def add_filter_by_id_orbit_origin(self, id_orbit_origin: int | list[int], **params) -> "CommodityRouteDataAccess":
        self.filter.where("id_orbit_origin", id_orbit_origin, **params)
        return self

    def add_filter_by_id_orbit_destination(self, id_orbit_destination: int | list[int], **params) -> "CommodityRouteDataAccess":
        self.filter.where("id_orbit_destination", id_orbit_destination, **params)
        return self

    def add_filter_by_id_terminal_origin(self, id_terminal_origin: int | list[int], **params) -> "CommodityRouteDataAccess":
        self.filter.where("id_terminal_origin", id_terminal_origin, **params)
        return self

    def add_filter_by_id_terminal_destination(self, id_terminal_destination: int | list[int], **params) -> "CommodityRouteDataAccess":
        self.filter.where("id_terminal_destination", id_terminal_destination, **params)
        return self

    def add_filter_has_buy_price(self):
        self.filter.where("price_buy", 0, '>')
        return self

    def add_filter_has_sell_price(self):
        self.filter.where("price_sell", 0, '>')
        return self
