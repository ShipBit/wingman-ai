from datetime import datetime
try:
    from skills.uexcorp_beta.uexcorp.model.data_model import DataModel
except ImportError:
    from uexcorp_beta.uexcorp.model.data_model import DataModel

class CommodityRoute(DataModel):

    required_keys = ["id"]

    def __init__(
            self,
            id: int, # int(11)
            id_commodity: int | None = None,
            id_star_system_origin: int | None = None,
            id_star_system_destination: int | None = None,
            id_planet_origin: int | None = None,
            id_planet_destination: int | None = None,
            id_orbit_origin: int | None = None,
            id_orbit_destination: int | None = None,
            id_terminal_origin: int | None = None,
            id_terminal_destination: int | None = None,
            id_faction_origin: int | None = None,
            id_faction_destination: int | None = None,
            code: str | None = None,
            price_origin: float | None = None,
            price_origin_users: float | None = None,
            price_origin_users_rows: float | None = None,
            price_destination: float | None = None,
            price_destination_users: float | None = None,
            price_destination_users_rows: float | None = None,
            price_margin: float | None = None,
            scu_origin: float | None = None,
            scu_origin_users: float | None = None,
            scu_origin_users_rows: float | None = None,
            scu_destination: float | None = None,
            scu_destination_users: float | None = None,
            scu_destination_users_rows: float | None = None,
            scu_margin: float | None = None,
            volatility_origin: float | None = None,
            volatility_destination: float | None = None,
            status_origin: int | None = None,
            status_destination: int | None = None,
            investment: float | None = None,
            profit: float | None = None,
            distance: float | None = None,
            score: int | None = None,
            has_docking_port_origin: int | None = None,
            has_docking_port_destination: int | None = None,
            has_freight_elevator_origin: int | None = None,
            has_freight_elevator_destination: int | None = None,
            has_loading_dock_origin: int | None = None,
            has_loading_dock_destination: int | None = None,
            has_refuel_origin: int | None = None,
            has_refuel_destination: int | None = None,
            has_cargo_center_origin: int | None = None,
            has_cargo_center_destination: int | None = None,
            has_quantum_marker_origin: int | None = None,
            has_quantum_marker_destination: int | None = None,
            is_monitored_origin: int | None = None,
            is_monitored_destination: int | None = None,
            is_space_station_origin: int | None = None,
            is_space_station_destination: int | None = None,
            is_on_ground_origin: int | None = None,
            is_on_ground_destination: int | None = None,
            commodity_name: str | None = None,
            commodity_code: str | None = None,
            commodity_slug: str | None = None,
            origin_star_system_name: str | None = None,
            origin_planet_name: str | None = None,
            origin_orbit_name: str | None = None,
            origin_terminal_name: str | None = None,
            origin_terminal_code: str | None = None,
            origin_terminal_slug: str | None = None,
            origin_terminal_is_player_owned: int | None = None,
            origin_faction_name: str | None = None,
            destination_star_system_name: str | None = None,
            destination_planet_name: str | None = None,
            destination_orbit_name: str | None = None,
            destination_terminal_name: str | None = None,
            destination_terminal_code: str | None = None,
            destination_terminal_slug: str | None = None,
            destination_terminal_is_player_owned: int | None = None,
            destination_faction_name: str | None = None,
            date_added: int | None = None,
            load: bool = False,
    ):
        super().__init__("commodity_route")
        self.data = {
            "id": id,
            "id_commodity": id_commodity,
            "id_star_system_origin": id_star_system_origin,
            "id_star_system_destination": id_star_system_destination,
            "id_planet_origin": id_planet_origin,
            "id_planet_destination": id_planet_destination,
            "id_orbit_origin": id_orbit_origin,
            "id_orbit_destination": id_orbit_destination,
            "id_terminal_origin": id_terminal_origin,
            "id_terminal_destination": id_terminal_destination,
            "id_faction_origin": id_faction_origin,
            "id_faction_destination": id_faction_destination,
            "code": code,
            "price_origin": price_origin,
            "price_origin_users": price_origin_users,
            "price_origin_users_rows": price_origin_users_rows,
            "price_destination": price_destination,
            "price_destination_users": price_destination_users,
            "price_destination_users_rows": price_destination_users_rows,
            "price_margin": price_margin,
            "scu_origin": scu_origin,
            "scu_origin_users": scu_origin_users,
            "scu_origin_users_rows": scu_origin_users_rows,
            "scu_destination": scu_destination,
            "scu_destination_users": scu_destination_users,
            "scu_destination_users_rows": scu_destination_users_rows,
            "scu_margin": scu_margin,
            "volatility_origin": volatility_origin,
            "volatility_destination": volatility_destination,
            "status_origin": status_origin,
            "status_destination": status_destination,
            "investment": investment,
            "profit": profit,
            "distance": distance,
            "score": score,
            "has_docking_port_origin": has_docking_port_origin,
            "has_docking_port_destination": has_docking_port_destination,
            "has_freight_elevator_origin": has_freight_elevator_origin,
            "has_freight_elevator_destination": has_freight_elevator_destination,
            "has_loading_dock_origin": has_loading_dock_origin,
            "has_loading_dock_destination": has_loading_dock_destination,
            "has_refuel_origin": has_refuel_origin,
            "has_refuel_destination": has_refuel_destination,
            "has_cargo_center_origin": has_cargo_center_origin,
            "has_cargo_center_destination": has_cargo_center_destination,
            "has_quantum_marker_origin": has_quantum_marker_origin,
            "has_quantum_marker_destination": has_quantum_marker_destination,
            "is_monitored_origin": is_monitored_origin,
            "is_monitored_destination": is_monitored_destination,
            "is_space_station_origin": is_space_station_origin,
            "is_space_station_destination": is_space_station_destination,
            "is_on_ground_origin": is_on_ground_origin,
            "is_on_ground_destination": is_on_ground_destination,
            "commodity_name": commodity_name,
            "commodity_code": commodity_code,
            "commodity_slug": commodity_slug,
            "origin_star_system_name": origin_star_system_name,
            "origin_planet_name": origin_planet_name,
            "origin_orbit_name": origin_orbit_name,
            "origin_terminal_name": origin_terminal_name,
            "origin_terminal_code": origin_terminal_code,
            "origin_terminal_slug": origin_terminal_slug,
            "origin_terminal_is_player_owned": origin_terminal_is_player_owned,
            "origin_faction_name": origin_faction_name,
            "destination_star_system_name": destination_star_system_name,
            "destination_planet_name": destination_planet_name,
            "destination_orbit_name": destination_orbit_name,
            "destination_terminal_name": destination_terminal_name,
            "destination_terminal_code": destination_terminal_code,
            "destination_terminal_slug": destination_terminal_slug,
            "destination_terminal_is_player_owned": destination_terminal_is_player_owned,
            "destination_faction_name": destination_faction_name,
            "date_added": date_added,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["id"]:
                raise Exception("ID is required to load data")
            self.load_by_value("id", self.data["id"])

    def get_data_for_ai(self) -> dict:
        try:
            from skills.uexcorp_beta.uexcorp.helper import Helper
        except ImportError:
            from uexcorp_beta.uexcorp.helper import Helper

        helper = Helper.get_instance()

        data = {
            "commodity": self.get_commodity_name(),
            "buy_for_in_auec": self.get_price_origin() * self.get_scu_origin(),
            "buy_at": self.get_origin_terminal_name(),
            "buy_volume_in_scu": self.get_scu_origin(),
            "sell_for_in_auec": self.get_price_destination() * self.get_scu_origin(),
            "sell_at": self.get_destination_terminal_name(),
            "estimated_profit_in_auec": self.get_profit(),
            "origin_star_system_name": self.get_origin_star_system_name(),
            "origin_planet_name": self.get_origin_planet_name(),
            "destination_star_system_name": self.get_destination_star_system_name(),
            "destination_planet_name": self.get_destination_planet_name(),
        }

        if helper.get_handler_config().get_behavior_commodity_route_advanced_info():
            data.update({
                "distance_in_giga_meters": self.get_distance(),
                "profit_margin": self.get_price_margin(),
                "origin_orbit_name": self.get_origin_orbit_name(),
                "origin_faction_name": self.get_origin_faction_name(),
                "destination_orbit_name": self.get_destination_orbit_name(),
                "destination_faction_name": self.get_destination_faction_name(),
                "uex_score": self.get_score(),
                "has_refuel_origin": self.get_has_refuel_origin(),
                "has_refuel_destination": self.get_has_refuel_destination(),
                "is_monitored_origin": self.get_is_monitored_origin(),
                "is_monitored_destination": self.get_is_monitored_destination(),
            })

        return data

    def get_id(self) -> int:
        return self.data["id"]

    def get_id_commodity(self) -> int:
        return self.data["id_commodity"]

    def get_id_star_system_origin(self) -> int:
        return self.data["id_star_system_origin"]

    def get_id_planet_origin(self) -> int:
        return self.data["id_planet_origin"]

    def get_id_planet_destination(self) -> int:
        return self.data["id_planet_destination"]

    def get_id_orbit_origin(self) -> int:
        return self.data["id_orbit_origin"]

    def get_id_orbit_destination(self) -> int:
        return self.data["id_orbit_destination"]

    def get_id_terminal_origin(self) -> int:
        return self.data["id_terminal_origin"]

    def get_id_terminal_destination(self) -> int:
        return self.data["id_terminal_destination"]

    def get_id_faction_origin(self) -> int:
        return self.data["id_faction_origin"]

    def get_id_faction_destination(self) -> int:
        return self.data["id_faction_destination"]

    def get_code(self) -> str:
        return self.data["code"]

    def get_price_origin(self) -> float:
        return self.data["price_origin"]

    def get_price_origin_users(self) -> float:
        return self.data["price_origin_users"]

    def get_price_origin_users_rows(self) -> float:
        return self.data["price_origin_users_rows"]

    def get_price_destination(self) -> float:
        return self.data["price_destination"]

    def get_price_destination_users(self) -> float:
        return self.data["price_destination_users"]

    def get_price_destination_users_rows(self) -> float:
        return self.data["price_destination_users_rows"]

    def get_price_margin(self) -> float:
        return self.data["price_margin"]

    def get_scu_origin(self) -> float:
        return self.data["scu_origin"]

    def get_scu_origin_users(self) -> float:
        return self.data["scu_origin_users"]

    def get_scu_origin_users_rows(self) -> float:
        return self.data["scu_origin_users_rows"]

    def get_scu_destination(self) -> float:
        return self.data["scu_destination"]

    def get_scu_destination_users(self) -> float:
        return self.data["scu_destination_users"]

    def get_scu_destination_users_rows(self) -> float:
        return self.data["scu_destination_users_rows"]

    def get_scu_margin(self) -> float:
        return self.data["scu_margin"]

    def get_volatility_origin(self) -> float:
        return self.data["volatility_origin"]

    def get_volatility_destination(self) -> float:
        return self.data["volatility_destination"]

    def get_status_origin(self) -> int:
        return self.data["status_origin"]

    def get_status_destination(self) -> int:
        return self.data["status_destination"]

    def get_investment(self) -> float:
        return self.data["investment"]

    def get_profit(self) -> float:
        return self.data["profit"]

    def get_distance(self) -> float:
        return self.data["distance"]

    def get_score(self) -> int:
        return self.data["score"]

    def get_has_docking_port_origin(self) -> int:
        return self.data["has_docking_port_origin"]

    def get_has_docking_port_destination(self) -> int:
        return self.data["has_docking_port_destination"]

    def get_has_freight_elevator_origin(self) -> int:
        return self.data["has_freight_elevator_origin"]

    def get_has_freight_elevator_destination(self) -> int:
        return self.data["has_freight_elevator_destination"]

    def get_has_loading_dock_origin(self) -> int:
        return self.data["has_loading_dock_origin"]

    def get_has_loading_dock_destination(self) -> int:
        return self.data["has_loading_dock_destination"]

    def get_has_refuel_origin(self) -> int:
        return self.data["has_refuel_origin"]

    def get_has_refuel_destination(self) -> int:
        return self.data["has_refuel_destination"]

    def get_has_cargo_center_origin(self) -> int:
        return self.data["has_cargo_center_origin"]

    def get_has_cargo_center_destination(self) -> int:
        return self.data["has_cargo_center_destination"]

    def get_has_quantum_marker_origin(self) -> int:
        return self.data["has_quantum_marker_origin"]

    def get_has_quantum_marker_destination(self) -> int:
        return self.data["has_quantum_marker_destination"]

    def get_is_monitored_origin(self) -> int:
        return self.data["is_monitored_origin"]

    def get_is_monitored_destination(self) -> int:
        return self.data["is_monitored_destination"]

    def get_is_space_station_origin(self) -> int:
        return self.data["is_space_station_origin"]

    def get_is_space_station_destination(self) -> int:
        return self.data["is_space_station_destination"]

    def get_is_on_ground_origin(self) -> int:
        return self.data["is_on_ground_origin"]

    def get_is_on_ground_destination(self) -> int:
        return self.data["is_on_ground_destination"]

    def get_commodity_name(self) -> str:
        return self.data["commodity_name"]

    def get_commodity_code(self) -> str:
        return self.data["commodity_code"]

    def get_commodity_slug(self) -> str:
        return self.data["commodity_slug"]

    def get_origin_star_system_name(self) -> str:
        return self.data["origin_star_system_name"]

    def get_origin_planet_name(self) -> str:
        return self.data["origin_planet_name"]

    def get_origin_orbit_name(self) -> str:
        return self.data["origin_orbit_name"]

    def get_origin_terminal_name(self) -> str:
        return self.data["origin_terminal_name"]

    def get_origin_terminal_code(self) -> str:
        return self.data["origin_terminal_code"]

    def get_origin_terminal_slug(self) -> str:
        return self.data["origin_terminal_slug"]

    def get_origin_terminal_is_player_owned(self) -> int:
        return self.data["origin_terminal_is_player_owned"]

    def get_origin_faction_name(self) -> str:
        return self.data["origin_faction_name"]

    def get_destination_star_system_name(self) -> str:
        return self.data["destination_star_system_name"]

    def get_destination_planet_name(self) -> str:
        return self.data["destination_planet_name"]

    def get_destination_orbit_name(self) -> str:
        return self.data["destination_orbit_name"]

    def get_destination_terminal_name(self) -> str:
        return self.data["destination_terminal_name"]

    def get_destination_terminal_code(self) -> str:
        return self.data["destination_terminal_code"]

    def get_destination_terminal_slug(self) -> str:
        return self.data["destination_terminal_slug"]

    def get_destination_terminal_is_player_owned(self) -> int:
        return self.data["destination_terminal_is_player_owned"]

    def get_destination_faction_name(self) -> str:
        return self.data["destination_faction_name"]

    def get_date_added(self) -> int:
        return self.data["date_added"]

    def get_date_added_readable(self) -> datetime:
        return datetime.fromtimestamp(self.data["date_added"])

    def __str__(self):
        return str(self.data["code"])