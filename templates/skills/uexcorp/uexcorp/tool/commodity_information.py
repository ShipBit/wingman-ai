import json

try:
    from skills.uexcorp.uexcorp.tool.tool import Tool
    from skills.uexcorp.uexcorp.tool.validator import Validator
except ModuleNotFoundError:
    from uexcorp.uexcorp.tool.tool import Tool
    from uexcorp.uexcorp.tool.validator import Validator


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
            filter_profit_absolute_per_scu: list[(int, str)] | None = None,
            filter_profit_margin_percent: list[(int, str)] | None = None,
            filter_base_profit_percent: list[(int, str)] | None = None,
    ) -> (str, str):
        try:
            from skills.uexcorp.uexcorp.data_access.commodity_data_access import CommodityDataAccess
            from skills.uexcorp.uexcorp.data_access.commodity_price_data_access import CommodityPriceDataAccess
            from skills.uexcorp.uexcorp.data_access.terminal_data_access import TerminalDataAccess
            from skills.uexcorp.uexcorp.model.terminal import Terminal
            from skills.uexcorp.uexcorp.helper import Helper
        except ModuleNotFoundError:
            from uexcorp.uexcorp.data_access.commodity_data_access import CommodityDataAccess
            from uexcorp.uexcorp.data_access.commodity_price_data_access import CommodityPriceDataAccess
            from uexcorp.uexcorp.data_access.terminal_data_access import TerminalDataAccess
            from uexcorp.uexcorp.model.terminal import Terminal
            from uexcorp.uexcorp.helper import Helper

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
            if filter_profit_margin_percent:
                temp_commodities = []
                for percentage, operation in filter_profit_margin_percent:
                    for commodity in commodities:
                        if commodity.get_profit_margin_max() is not None and operation in ["=", "!=", ">=", "<=", "<", ">"]:
                            try:
                                if eval(f"{commodity.get_profit_margin_max()} {operation} {percentage}"):
                                    temp_commodities.append(commodity)
                            except Exception:
                                self._helper.get_handler_debug().write("Unable to evaluate profit margin percentage filter.")
                                self._helper.get_handler_debug().write(f"eval: {commodity.get_profit_margin_max()} {operation} {percentage}")
                                pass
                commodities = temp_commodities

            if filter_profit_absolute_per_scu:
                temp_commodities = []
                for absolute_per_scu, operation in filter_profit_absolute_per_scu:
                    for commodity in commodities:
                        if commodity.get_profit_max() is not None and operation in ["=", "!=", ">=", "<=", "<", ">"]:
                            try:
                                if eval(f"{commodity.get_profit_max()} {operation} {absolute_per_scu}"):
                                    temp_commodities.append(commodity)
                            except Exception:
                                self._helper.get_handler_debug().write("Unable to evaluate profit absolute per SCU filter.")
                                self._helper.get_handler_debug().write(f"eval: {commodity.get_profit_max()} {operation} {absolute_per_scu}")
                                pass
                commodities = temp_commodities

            if filter_base_profit_percent:
                temp_commodities = []
                for percentage, operation in filter_base_profit_percent:
                    for commodity in commodities:
                        if commodity.get_base_profit_max() is not None and operation in ["=", "!=", ">=", "<=", "<", ">"]:
                            try:
                                if eval(f"{commodity.get_base_profit_max()} {operation} {percentage}"):
                                    temp_commodities.append(commodity)
                            except Exception:
                                self._helper.get_handler_debug().write("Unable to evaluate base profit percentage filter.")
                                self._helper.get_handler_debug().write(f"eval: {commodity.get_base_profit_max()} {operation} {percentage}")
                                pass
                commodities = temp_commodities

            if filter_profit_margin_percent or filter_base_profit_percent:
                commodities = sorted(commodities, key=lambda x: x.get_profit_margin_max(), reverse=True)
                helper.get_handler_tool().add_note("Commodities are sorted by profit margin percentage DESC")
            elif filter_profit_absolute_per_scu:
                commodities = sorted(commodities, key=lambda x: x.get_profit_max(), reverse=True)
                helper.get_handler_tool().add_note("Commodities are sorted by absolute profit per SCU DESC")

        helper.get_handler_tool().add_note("Even though profit, profit margin and base profit may be given by this function, use uex_calculate_profit afterwards to calculate correct profit with user values.")

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
            output_commodities = []
            for commodity in commodities:
                commodity_str = str(commodity)
                additional_info = []

                if filter_profit_absolute_per_scu:
                    additional_info.append(
                        f"Max profit per SCU: {commodity.get_profit_max()} aUEC"
                    )

                if filter_profit_margin_percent:
                    additional_info.append(
                        f"Max profit margin: {commodity.get_profit_margin_max()}%"
                    )

                if filter_base_profit_percent:
                    additional_info.append(
                        f"Max base profit margin: {commodity.get_base_profit_max()}%"
                    )

                if additional_info:
                    commodity_str += f" ({' | '.join(additional_info)})"

                output_commodities.append(commodity_str)
            commodities = output_commodities
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
            "filter_profit_margin_percent": Validator(
                Validator.VALIDATE_OPERATION_INT,
                multiple=True,
                prompt="Filter for commodities for profit margin percentage. For 50%, use '50' NOT '0.5'. Multiples are combined by AND.",
            ),
            "filter_base_profit_percent": Validator(
                Validator.VALIDATE_OPERATION_INT,
                multiple=True,
                prompt="Filter for commodities for base profit percentage. For 50%, use '50' NOT '0.5'. Multiples are combined by AND.",
            ),
            "filter_profit_absolute_per_scu": Validator(
                Validator.VALIDATE_OPERATION_INT,
                multiple=True,
                prompt="Filter for commodities for profit margin absolute per SCU. Multiples are combined by AND.",
            ),
        }

    def get_description(self) -> str:
        return "Gives back information about commodities. Preferable over uex_get_trade_routes if looking into buy or sell actions specifically and not a route. filter_commodities overwrites all other filters. Important: Must includes for buy/sell options are: Terminal location, Price AND terminal status percentage."

    def get_prompt(self) -> str:
        return "Get all information's about all commodities, filterable. When asked for drop off (sell) or pick up (buy) locations, prefer this over uex_get_trade_routes. filter_commodities overwrites all other filters. Important: Must includes for buy/sell options are: Terminal location, Price AND terminal status percentage and description (e.g., Out of Stock, Full Inventory). If users gives specific buy or sell price and asks for profit margin, always use uex_calculate_profit function afterwards to calculate correct profit with user values."
