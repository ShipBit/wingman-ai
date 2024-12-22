import json
from skills.uexcorp_beta.uexcorp.tool.tool import Tool
from skills.uexcorp_beta.uexcorp.tool.validator import Validator


class CommodityRoute(Tool):

    def __init__(self):
        super().__init__()

    def execute(
            self,
            filter_commodity_whitelist: list[str] | None = None,
            filter_commodity_blacklist: list[str] | None = None,
            filter_allow_illegal_commodities: bool | None = None,
            filter_star_system_whitelist: list[str] | None = None,
            filter_star_system_blacklist: list[str] | None = None,
            limit: int | None = None,
            offset: int | None = None,
            used_ship: str | None = None,
            available_money: int | None = None,
            available_cargo_space_scu: int | None = None,
            filter_allow_star_system_change: bool | None = None,
            filter_start_location: str | None = None,
            filter_destination_location: str | None = None,
            filter_location_blacklist: list[str] | None = None,
    ) -> (str, str):
        from skills.uexcorp_beta.uexcorp.data_access.vehicle_data_access import VehicleDataAccess
        from skills.uexcorp_beta.uexcorp.data_access.terminal_data_access import TerminalDataAccess
        from skills.uexcorp_beta.uexcorp.data_access.commodity_data_access import CommodityDataAccess
        from skills.uexcorp_beta.uexcorp.data_access.commodity_route_data_access import CommodityRouteDataAccess
        from skills.uexcorp_beta.uexcorp.helper import Helper
        helper = Helper.get_instance()

        commodity_route_data_access = CommodityRouteDataAccess()
        start_terminal_ids = []
        end_terminals_ids = []
        terminal_ids_exclude = []
        commodity_ids_exclude = []
        max_scu = None
        example_route = False

        if available_cargo_space_scu:
            max_scu = available_cargo_space_scu

        if filter_commodity_whitelist:
            commodity_route_data_access.add_filter_by_commodity_name_whitelist(filter_commodity_whitelist)

        if filter_commodity_blacklist:
            commodity_route_data_access.add_filter_by_commodity_name_blacklist(filter_commodity_blacklist)

        commodity_data_access = CommodityDataAccess()
        commodity_data_access.add_filter_by_is_blacklisted(True)
        if filter_allow_illegal_commodities is not None and not filter_allow_illegal_commodities:
            commodity_data_access.add_filter_by_is_illegal(True)
        for commodity in commodity_data_access.load():
            commodity_ids_exclude.append(commodity.get_id())

        if filter_star_system_whitelist:
            commodity_route_data_access.add_filter_by_star_system_name_whitelist(filter_star_system_whitelist)

        if filter_star_system_blacklist:
            commodity_route_data_access.add_filter_by_star_system_name_blacklist(filter_star_system_blacklist)

        if filter_allow_star_system_change is False:
            commodity_route_data_access.add_filter_by_in_same_star_system()

        if limit:
            commodity_route_data_access.limit(limit)
        else:
            commodity_route_data_access.limit(helper.get_handler_config().get_behavior_commodity_route_default_count())

        if offset:
            commodity_route_data_access.offset(offset)

        if used_ship:
            ship = VehicleDataAccess().load_by_property("name_full", used_ship)
            if ship and ship.get_is_loading_dock():
                commodity_route_data_access.add_filter_by_has_loading_dock()
            if max_scu is not None:
                max_scu = min(max_scu, ship.get_scu() if ship.get_scu() else 0)
            else:
                max_scu = ship.get_scu() if ship.get_scu() else 0

        if filter_location_blacklist:
            terminal_data_access = TerminalDataAccess()
            terminal_data_access.add_filter_by_location_name_blacklist(filter_location_blacklist)
            terminal_data_access.add_filter_by_type("commodity")
            terminal_data_access.add_filter_by_is_available(True)
            for terminal in terminal_data_access.load():
                terminal_ids_exclude.append(terminal.get_id())

        if filter_start_location:
            terminal_data_access = TerminalDataAccess()
            terminal_data_access.add_filter_by_location_name_whitelist(filter_start_location)
            terminal_data_access.add_filter_by_type("commodity")
            terminal_data_access.add_filter_by_is_available(True)
            for terminal in terminal_data_access.load():
                start_terminal_ids.append(terminal.get_id())

        if filter_destination_location:
            terminal_data_access = TerminalDataAccess()
            terminal_data_access.add_filter_by_location_name_whitelist(filter_destination_location)
            terminal_data_access.add_filter_by_type("commodity")
            terminal_data_access.add_filter_by_is_available(True)
            for terminal in terminal_data_access.load():
                end_terminals_ids.append(terminal.get_id())

        if terminal_ids_exclude:
            commodity_route_data_access.add_filter_by_id_terminal_origin(terminal_ids_exclude, operation="NOT IN")
            commodity_route_data_access.add_filter_by_id_terminal_destination(terminal_ids_exclude, operation="NOT IN")

        if start_terminal_ids:
            commodity_route_data_access.add_filter_by_id_terminal_origin(start_terminal_ids)

        if end_terminals_ids:
            commodity_route_data_access.add_filter_by_id_terminal_destination(end_terminals_ids)

        if commodity_ids_exclude:
            pass # TODO add if permanent blacklist is available

        if max_scu is None and available_money is None:
            max_scu = 1 # search for an example with 1 scu
            example_route = True
            helper.get_handler_tool().add_note("Example route for 1 SCU with best uex score. User should refine search with ship or/and budget information for better results.")

        max_scu = f"{max_scu}, " if max_scu is not None else ""
        available_money = f"CAST(({int(available_money)} / price_origin) AS INTEGER), " if available_money else ""
        commodity_route_data_access.add_col(f"MIN({available_money}{max_scu}scu_origin, scu_destination) as 'scu_origin'")
        commodity_route_data_access.add_col(f"(MIN({available_money}{max_scu}scu_origin, scu_destination) * (price_destination - price_origin)) as 'profit'")

        if example_route:
            commodity_route_data_access.order_by("score", "DESC")
        else:
            commodity_route_data_access.order_by("profit", "DESC")

        commodity_route_data_access.order_by("id_star_system_origin = id_star_system_destination", "DESC")
        commodity_route_data_access.order_by("distance", "ASC")
        routes = commodity_route_data_access.load(debug=True) # TODO remove debug=True

        routes = [route.get_data_for_ai() for route in routes]
        return json.dumps(routes), ""

    def get_mandatory_fields(self) -> dict[str, Validator]:
        from skills.uexcorp_beta.uexcorp.helper import Helper
        helper = Helper.get_instance()

        fields = {}

        if helper.get_handler_config().get_behavior_commodity_route_start_location_mandatory():
            fields["filter_start_location"] = Validator(Validator.VALIDATE_LOCATION, config={"for_trading": True})

        return fields

    def get_optional_fields(self) -> dict[str, Validator]:
        from skills.uexcorp_beta.uexcorp.helper import Helper
        helper = Helper.get_instance()

        fields = {
            "filter_commodity_whitelist": Validator(Validator.VALIDATE_COMMODITY, multiple=True, config={"for_trading": True}),
            "filter_commodity_blacklist": Validator(Validator.VALIDATE_COMMODITY, multiple=True, config={"for_trading": True}),
            "filter_allow_illegal_commodities": Validator(Validator.VALIDATE_BOOL),
            "limit": Validator(Validator.VALIDATE_NUMBER, config={"min": 1, "max": 15}),
            "offset": Validator(Validator.VALIDATE_NUMBER, config={"min": 0}),
            "used_ship": Validator(Validator.VALIDATE_SHIP),
            "available_money": Validator(Validator.VALIDATE_NUMBER, config={"min": 1}),
            "available_cargo_space_scu": Validator(Validator.VALIDATE_NUMBER, config={"min": 1}),
            "filter_allow_star_system_change": Validator(Validator.VALIDATE_BOOL),
            "filter_location_blacklist": Validator(Validator.VALIDATE_LOCATION, multiple=True, config={"for_trading": True}),
            "filter_destination_location": Validator(Validator.VALIDATE_LOCATION, config={"for_trading": True}),

            # Currently used unreliably by AI
            # "filter_star_system_whitelist": Validator(Validator.VALIDATE_STAR_SYSTEM, multiple=True),
            # "filter_star_system_blacklist": Validator(Validator.VALIDATE_STAR_SYSTEM, multiple=True),
        }

        if not helper.get_handler_config().get_behavior_commodity_route_start_location_mandatory():
            fields["filter_start_location"] = Validator(Validator.VALIDATE_LOCATION, config={"for_trading": True})

        return fields

    def get_description(self) -> str:
        return "Gives back trading routes for commodities based on the filters given."