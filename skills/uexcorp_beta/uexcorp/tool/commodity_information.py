import json

try:
    from skills.uexcorp_beta.uexcorp.tool.tool import Tool
    from skills.uexcorp_beta.uexcorp.tool.validator import Validator
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.tool.tool import Tool
    from uexcorp_beta.uexcorp.tool.validator import Validator


class CommodityInformation(Tool):
    REQUIRES_AUTHENTICATION = False
    TOOL_NAME = "uex_get_commodity_information"

    def __init__(self):
        super().__init__()

    def execute(
            self,
            filter_commodities: list[str] | None = None,
            filter_is_buyable: bool | None = None,
            filter_is_sellable: bool | None = None,
            filter_is_legal: bool | None = None,
            filter_location_whitelist: list[str] | None = None,
            filter_location_blacklist: list[str] | None = None,
            filter_buy_price: list[(int, str)] | None = None,
            filter_sell_price: list[(int, str)] | None = None,
            filter_profit_margin_percentage: list[(int, str)] | None = None,
            filter_profit_margin_absolute_per_scu: list[(int, str)] | None = None,
    ) -> (str, str):
        try:
            from skills.uexcorp_beta.uexcorp.data_access.commodity_data_access import CommodityDataAccess
            from skills.uexcorp_beta.uexcorp.data_access.commodity_price_data_access import CommodityPriceDataAccess
            from skills.uexcorp_beta.uexcorp.data_access.terminal_data_access import TerminalDataAccess
            from skills.uexcorp_beta.uexcorp.model.terminal import Terminal
            from skills.uexcorp_beta.uexcorp.helper import Helper
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.data_access.commodity_data_access import CommodityDataAccess
            from uexcorp_beta.uexcorp.data_access.commodity_price_data_access import CommodityPriceDataAccess
            from uexcorp_beta.uexcorp.data_access.terminal_data_access import TerminalDataAccess
            from uexcorp_beta.uexcorp.model.terminal import Terminal
            from uexcorp_beta.uexcorp.helper import Helper

        helper = Helper().get_instance()

        commodity_data_access = CommodityDataAccess()
        commodity_prices = []
        terminal_ids = []

        if filter_commodities is not None:
            # if names are given, other filters are no longer needed
            commodity_data_access.add_filter_by_name(filter_commodities)
        else:
            # only filter for further parameters if no names are given
            if filter_is_buyable is not None:
                commodity_data_access.add_filter_by_is_buyable(filter_is_buyable)

            if filter_is_sellable is not None:
                commodity_data_access.add_filter_by_is_sellable(filter_is_sellable)

            if filter_is_legal is not None:
                commodity_data_access.add_filter_by_is_illegal(not filter_is_legal)

            if filter_location_whitelist is not None or filter_location_blacklist is not None:
                terminal_data_access = TerminalDataAccess()
                terminal_data_access.add_filter_by_type(Terminal.TYPE_COMMODITY)
                # terminal_data_access.add_filter_by_is_available(True)

                if filter_location_whitelist is not None:
                    terminal_data_access.add_filter_by_location_name_whitelist(filter_location_whitelist)

                if filter_location_blacklist is not None:
                    terminal_data_access.add_filter_by_location_name_blacklist(filter_location_blacklist)

                for terminal in terminal_data_access.load():
                    terminal_ids.append(terminal.get_id())

                commodity_price_data_access = CommodityPriceDataAccess()
                commodity_price_data_access.add_filter_by_id_terminal(terminal_ids)
                commodity_prices = commodity_price_data_access.load()
                commodity_data_access.add_filter_by_id([
                    commodity_price.get_id_commodity() for commodity_price in commodity_prices
                ])

            if filter_buy_price:
                commodity_price_data_access = CommodityPriceDataAccess()
                commodity_price_data_access.add_filter_by_is_buyable(True)
                for price, operation in filter_buy_price:
                    commodity_price_data_access.add_filter_by_price_buy(price, operation=operation)
                commodity_prices = commodity_price_data_access.load(debug=True)
                commodity_data_access.add_filter_by_id([
                    commodity_price.get_id_commodity() for commodity_price in commodity_prices
                ])

            if filter_sell_price:
                commodity_price_data_access = CommodityPriceDataAccess()
                commodity_price_data_access.add_filter_by_is_sellable(True)
                for price, operation in filter_sell_price:
                    commodity_price_data_access.add_filter_by_price_sell(price, operation=operation)
                commodity_prices = commodity_price_data_access.load(debug=True)
                commodity_data_access.add_filter_by_id([
                    commodity_price.get_id_commodity() for commodity_price in commodity_prices
                ])

        commodities = commodity_data_access.load()

        if commodities and filter_commodities is None:
            if filter_profit_margin_percentage:
                temp_commodities = []
                for percentage, operation in filter_profit_margin_percentage:
                    for commodity in commodities:
                        if commodity.get_profit_percent_max() is not None and operation in ["=", "!=", ">=", "<=", "<", ">"]:
                            try:
                                if eval(f"{commodity.get_profit_percent_max()} {operation} {percentage}"):
                                    temp_commodities.append(commodity)
                            except Exception:
                                self._helper.get_handler_debug().write("Unable to evaluate profit margin percentage filter.")
                                self._helper.get_handler_debug().write(f"eval: {commodity.get_profit_percent_max()} {operation} {percentage}")
                                pass
                commodities = temp_commodities

            if filter_profit_margin_absolute_per_scu:
                temp_commodities = []
                for absolute_per_scu, operation in filter_profit_margin_absolute_per_scu:
                    for commodity in commodities:
                        if commodity.get_profit_absolute_per_scu_max() is not None and operation in ["=", "!=", ">=", "<=", "<", ">"]:
                            if eval(f"{commodity.get_profit_absolute_per_scu_max()} {operation} {absolute_per_scu}"):
                                temp_commodities.append(commodity)
                commodities = temp_commodities

            if filter_profit_margin_absolute_per_scu or filter_profit_margin_percentage:
                commodities = sorted(commodities, key=lambda x: x.get_profit_percent_max(), reverse=True)
                helper.get_handler_tool().add_note("Commodities are sorted by profit margin (percentage) DESC")

        if not commodities:
            helper.get_handler_tool().add_note(
                "No matching commodities found. Please check filter criteria."
            )
            return [], ""
        elif len(commodities) <= 10:
            commodities = [commodity.get_data_for_ai() for commodity in commodities]
        elif len(commodities) <= 20:
            commodities = [commodity.get_data_for_ai_minimal() for commodity in commodities]
            helper.get_handler_tool().add_note(
                f"Found {len(commodities)} matching commodities. Filter criteria are somewhat broad. (max 10 commodities for advanced information)"
            )
        else:
            if filter_profit_margin_absolute_per_scu or filter_profit_margin_percentage:
                commodities = [f"{str(commodity)} (Max margin: {commodity.get_profit_percent_max()}%)" for commodity in commodities]
            else:
                commodities = [str(commodity) for commodity in commodities]
            helper.get_handler_tool().add_note(
                f"Found {len(commodities)} matching commodities. Filter criteria are too broad. (max 20 commodities for information about each commodity)"
            )

        return json.dumps(commodities), ""

    def get_mandatory_fields(self) -> dict[str, Validator]:
        return {}

    def get_optional_fields(self) -> dict[str, Validator]:
        return {
            "filter_commodities": Validator(
                Validator.VALIDATE_COMMODITY,
                multiple=True,
                prompt="Provide one or multiple commodity names to filter by name. (e.g. \"Agricium\")",
            ),
            "filter_is_buyable": Validator(
                Validator.VALIDATE_BOOL,
                prompt="If true, only commodities with buy options are shown.",
            ),
            "filter_is_sellable": Validator(
                Validator.VALIDATE_BOOL,
                prompt="If true, only commodities with sell options are shown.",
            ),
            "filter_is_legal": Validator(
                Validator.VALIDATE_BOOL,
                prompt="If true, only legal commodities are shown, if false, only illegal commodities are shown.",
            ),
            "filter_location_whitelist": Validator(
                Validator.VALIDATE_LOCATION,
                multiple=True,
                prompt="Provide one or multiple locations to filter for commodities able to sell or buy there. (e.g. [\"Hurston\", \"Bloom\"])"
            ),
            "filter_buy_price": Validator(
                Validator.VALIDATE_OPERATION_INT,
                multiple=True,
                prompt="Filter for commodities for buy price. Multiples are combined by AND.",
            ),
            "filter_sell_price": Validator(
                Validator.VALIDATE_OPERATION_INT,
                multiple=True,
                prompt="Filter for commodities for sell price. Multiples are combined by AND.",
            ),
            "filter_profit_margin_percentage": Validator(
                Validator.VALIDATE_OPERATION_INT,
                multiple=True,
                prompt="Filter for commodities for profit margin percentage. For 50%, use '50' NOT '0.5'. Multiples are combined by AND.",
            ),
            "filter_profit_margin_absolute_per_scu": Validator(
                Validator.VALIDATE_OPERATION_INT,
                multiple=True,
                prompt="Filter for commodities for profit margin absolute per SCU. Multiples are combined by AND.",
            ),
        }

    def get_description(self) -> str:
        return "Gives back information about commodities. Preferable over uex_get_trade_routes if looking into buy or sell actions specifically and not a route. filter_commodities overwrites all other filters. Important: Must includes for buy/sell options are: Terminal location, Price AND terminal status percentage."

    def get_prompt(self) -> str:
        return "Get all information's about all commodities, filterable. When asked for drop off (sell) or pick up (buy) locations, prefer this over uex_get_trade_routes. filter_commodities overwrites all other filters. Important: Must includes for buy/sell options are: Terminal location, Price AND terminal status percentage and description (e.g., Out of Stock, Full Inventory)."
