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
            filter_is_tradeable: bool | None = None,
            filter_is_legal: bool | None = None,
            filter_location_whitelist: list[str] | None = None,
            filter_location_blacklist: list[str] | None = None,
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
            if filter_is_tradeable is not None:
                commodity_data_access.add_filter_by_is_buyable(filter_is_tradeable).add_filter_by_is_sellable(filter_is_tradeable)

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

        commodities = commodity_data_access.load()

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
            if filter_location_whitelist is not None or filter_location_blacklist is not None:
                commodities_temp = []
                for commodity in commodities:
                    buy = False
                    sell = False
                    for price in commodity_prices:
                        if price.get_id_commodity() == commodity.get_id() and price.get_id_terminal() in terminal_ids:
                            if price.get_price_sell() > 0:
                                sell = True
                            if price.get_price_buy() > 0:
                                buy = True
                    if buy and sell:
                        commodities_temp.append(f"{str(commodity)} (Buy/Sell)")
                    elif buy:
                        commodities_temp.append(f"{str(commodity)} (Buy)")
                    elif sell:
                        commodities_temp.append(f"{str(commodity)} (Sell)")
                    else:
                        commodities_temp.append(str(commodity))
                commodities = commodities_temp
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
            "filter_is_tradeable": Validator(
                Validator.VALIDATE_BOOL,
                prompt="If true, only commodities with buy and sell options are shown.",
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

            # Didn't really make sense
            # "filter_location_blacklist": Validator(Validator.VALIDATE_LOCATION, multiple=True),
        }

    def get_description(self) -> str:
        return "Gives back information about commodities. Preferable over uex_get_trade_routes if looking into buy or sell actions specifically and not a route. Important: Must includes for buy/sell options are: Terminal location, Price AND terminal status percentage."

    def get_prompt(self) -> str:
        return "Get all information's about all commodities, filterable. When asked for drop off (sell) or pick up (buy) locations, prefer this over uex_get_trade_routes.Important: Must includes for buy/sell options are: Terminal location, Price AND terminal status percentage and description (e.g., Out of Stock, Full Inventory)."
