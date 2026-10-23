from skills.uexcorp.uexcorp.data_access.data_access import DataAccess
from skills.uexcorp.uexcorp.model.commodity_route import CommodityRoute


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
            "price_roi",
            "scu_reachable",
            "container_sizes_origin",
            "container_sizes_destination",
            "game_version_origin",
            "game_version_destination",
            "container_size_min_origin",
            "container_size_min_destination",
        ]

    def load(self, **params) -> list[CommodityRoute]:
        return super().load(**params)

    def load_by_property(self, property: str, value: any) -> CommodityRoute:
        return super().load_by_property(property, value)

    def add_filter_by_commodity_name_whitelist(self, commodity_name_whitelist: list[str]) -> "CommodityRouteDataAccess":
        self.filter.where("commodity_name", commodity_name_whitelist)
        return self

    def add_filter_by_id_commodity(self, id_commodity: int | list[int], **params) -> "CommodityRouteDataAccess":
        self.filter.where("id_commodity", id_commodity, **params)
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

    def add_filter_by_max_container_size(self, max_container_size: int) -> "CommodityRouteDataAccess":
        # Drops routes where a terminal only handles containers larger than the ship carries.
        # Unknown sizes (NULL) count as 0 and keep the route.
        self.filter.where(f"COALESCE({self.filter.get_table()}.container_size_min_origin, 0)", max_container_size, "<=")
        self.filter.where(f"COALESCE({self.filter.get_table()}.container_size_min_destination, 0)", max_container_size, "<=")
        return self

    def load_legs(self, columns: list[str]) -> list[dict]:
        """Filtered rows as plain dicts: the route planner reads thousands of legs per call,
        building a model object for each would only cost time. Only the given columns are
        read: copying all ~80 columns of every leg took most of the tool's time."""
        return [dict(row) for row in self._fetch_all(columns=columns)]

    def add_filter_by_has_availability(self, has_availability: bool) -> "CommodityRouteDataAccess":
        # No availability = zero stock at origin or zero demand at destination.
        # Unknown values (NULL) count as available, so they never hide a route.
        table = self.filter.get_table()
        # Each side on its own: MIN() with a NULL argument is NULL and would hide a zero.
        self.filter.where(
            f"(COALESCE({table}.scu_origin, 1) > 0 AND COALESCE({table}.scu_destination, 1) > 0)",
            has_availability,
        )
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
