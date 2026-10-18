import operator

from skills.uexcorp.uexcorp import compression
from skills.uexcorp.uexcorp.tool.tool import Tool
from skills.uexcorp.uexcorp.tool.validator import Validator


class CommodityInformation(Tool):
    REQUIRES_AUTHENTICATION = False
    TOOL_NAME = "uex_get_commodity_information"

    OPERATIONS = {
        "=": operator.eq,
        "!=": operator.ne,
        ">=": operator.ge,
        "<=": operator.le,
        "<": operator.lt,
        ">": operator.gt,
    }

    def __init__(self):
        super().__init__()

    @staticmethod
    def __filter_by_prices(
        commodity_data_access,
        terminal_ids: list[int] | None,
        buy_conditions: list[tuple[int, str]] | None = None,
        sell_conditions: list[tuple[int, str]] | None = None,
        buyable: bool = False,
        sellable: bool = False,
    ) -> None:
        """Limit to commodities with a price row (at the given terminals) that meets all conditions."""
        from skills.uexcorp.uexcorp.data_access.commodity_price_data_access import CommodityPriceDataAccess

        commodity_price_data_access = CommodityPriceDataAccess()
        if terminal_ids is not None:
            commodity_price_data_access.add_filter_by_id_terminal(terminal_ids)
        if buy_conditions or buyable:
            commodity_price_data_access.add_filter_by_is_buyable(True)
            for price, operation in buy_conditions or []:
                commodity_price_data_access.add_filter_by_price_buy(price, operation=operation)
        if sell_conditions or sellable:
            commodity_price_data_access.add_filter_by_is_sellable(True)
            for price, operation in sell_conditions or []:
                commodity_price_data_access.add_filter_by_price_sell(price, operation=operation)
        commodity_data_access.add_filter_by_id(list({
            commodity_price.get_id_commodity() for commodity_price in commodity_price_data_access.load()
        }))

    @classmethod
    def __matches(cls, value: float | None, conditions: list[tuple[int, str]]) -> bool:
        return value is not None and all(cls.OPERATIONS[operation](value, number) for number, operation in conditions)

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
        from skills.uexcorp.uexcorp.data_access.commodity_data_access import CommodityDataAccess
        from skills.uexcorp.uexcorp.data_access.terminal_data_access import TerminalDataAccess
        from skills.uexcorp.uexcorp.model.terminal import Terminal
        from skills.uexcorp.uexcorp.helper import Helper

        helper = Helper.get_instance()

        commodity_data_access = CommodityDataAccess()

        if filter_commodities:
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

            # Locations limit the terminals that price filters look at, so "buy <= 150 at Lorville" means at Lorville
            terminal_ids = None
            if filter_location_whitelist or filter_location_blacklist:
                terminal_data_access = TerminalDataAccess()
                terminal_data_access.add_filter_by_type(Terminal.TYPE_COMMODITY)
                if filter_location_whitelist:
                    terminal_data_access.add_filter_by_location_name_whitelist(filter_location_whitelist)
                if filter_location_blacklist:
                    terminal_data_access.add_filter_by_location_name_blacklist(filter_location_blacklist)
                terminal_ids = [terminal.get_id() for terminal in terminal_data_access.load()]

            # Buy and sell conditions may match at different terminals (buy here, sell there)
            if filter_buy_price:
                self.__filter_by_prices(commodity_data_access, terminal_ids, buy_conditions=filter_buy_price)
            if filter_sell_price:
                self.__filter_by_prices(commodity_data_access, terminal_ids, sell_conditions=filter_sell_price)
            if terminal_ids is not None:
                # "Buy at Lorville": buyable there, not just somewhere
                if filter_is_buyable and not filter_buy_price:
                    self.__filter_by_prices(commodity_data_access, terminal_ids, buyable=True)
                if filter_is_sellable and not filter_sell_price:
                    self.__filter_by_prices(commodity_data_access, terminal_ids, sellable=True)
                if not (filter_buy_price or filter_sell_price or filter_is_buyable or filter_is_sellable):
                    self.__filter_by_prices(commodity_data_access, terminal_ids)

        commodities = commodity_data_access.load()

        if commodities and not filter_commodities:
            # Several conditions on one value must all match
            for conditions, get_value in (
                (filter_profit_margin_percent, lambda commodity: commodity.get_profit_margin_max()),
                (filter_profit_absolute_per_scu, lambda commodity: commodity.get_profit_max()),
                (filter_base_profit_percent, lambda commodity: commodity.get_base_profit_max()),
            ):
                if conditions:
                    commodities = [
                        commodity for commodity in commodities
                        if self.__matches(get_value(commodity), conditions)
                    ]

            if filter_profit_margin_percent or filter_base_profit_percent:
                commodities = sorted(commodities, key=lambda x: x.get_profit_margin_max() or 0, reverse=True)
                helper.get_handler_tool().add_note("Commodities are sorted by profit margin percentage DESC")
            elif filter_profit_absolute_per_scu:
                commodities = sorted(commodities, key=lambda x: x.get_profit_max() or 0, reverse=True)
                helper.get_handler_tool().add_note("Commodities are sorted by absolute profit per SCU DESC")

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

        return compression.dumps(commodities), ""

    def get_mandatory_fields(self) -> dict[str, Validator]:
        return {}

    def get_optional_fields(self) -> dict[str, Validator]:
        return {
            "filter_commodities": Validator(
                Validator.VALIDATE_COMMODITY,
                multiple=True,
                prompt="Commodity names, e.g. [\"Agricium\", \"Laranite\"]. Shows where each can be bought and sold. If set, all other filters are ignored.",
            ),
            "filter_is_buyable": Validator(
                Validator.VALIDATE_BOOL,
                prompt="If true, only commodities the player can buy: at the filter_location_whitelist locations if given, else anywhere.",
            ),
            "filter_is_sellable": Validator(
                Validator.VALIDATE_BOOL,
                prompt="If true, only commodities the player can sell: at the filter_location_whitelist locations if given, else anywhere.",
            ),
            "filter_is_legal": Validator(
                Validator.VALIDATE_BOOL,
                prompt="True = only legal commodities, false = only illegal (contraband) commodities. Leave out for both.",
            ),
            "filter_location_whitelist": Validator(
                Validator.VALIDATE_LOCATION,
                multiple=True,
                prompt="Only commodities that can be bought or sold at these locations (star system, planet, moon, station, city, outpost or terminal), e.g. [\"Hurston\", \"Bloom\"]. Price filters then only look at these locations."
            ),
            "filter_location_blacklist": Validator(
                Validator.VALIDATE_LOCATION,
                multiple=True,
                prompt="Ignore these locations (star system, planet, moon, station, city, outpost or terminal), e.g. [\"Pyro\"]: only commodities traded elsewhere, and price filters skip these locations."
            ),
            "filter_buy_price": Validator(
                Validator.VALIDATE_OPERATION_INT,
                multiple=True,
                prompt="Buy price per SCU in aUEC. Each entry is {operation, value}, e.g. [{\"operation\": \">=\", \"value\": 1000}]. Several entries must all match.",
            ),
            "filter_sell_price": Validator(
                Validator.VALIDATE_OPERATION_INT,
                multiple=True,
                prompt="Sell price per SCU in aUEC. Each entry is {operation, value}, e.g. [{\"operation\": \">=\", \"value\": 1000}]. Several entries must all match.",
            ),
            "filter_profit_margin_percent": Validator(
                Validator.VALIDATE_OPERATION_INT,
                multiple=True,
                prompt="Best profit margin in percent (profit divided by sell price). For 50% use 50, not 0.5. Each entry is {operation, value}, e.g. [{\"operation\": \">=\", \"value\": 50}].",
            ),
            "filter_base_profit_percent": Validator(
                Validator.VALIDATE_OPERATION_INT,
                multiple=True,
                prompt="Best base profit in percent (profit divided by buy price). For 50% use 50, not 0.5. Each entry is {operation, value}, e.g. [{\"operation\": \">=\", \"value\": 50}].",
            ),
            "filter_profit_absolute_per_scu": Validator(
                Validator.VALIDATE_OPERATION_INT,
                multiple=True,
                prompt="Best profit per SCU in aUEC (best sell price minus best buy price). Each entry is {operation, value}, e.g. [{\"operation\": \">=\", \"value\": 500}].",
            ),
        }

    def get_description(self) -> str:
        return (
            "Look up commodities (trade goods like Laranite or Medical Supplies): where to buy and sell them, "
            "prices per SCU, stock and demand, best profit per SCU. Use it for 'where can I buy/sell X' "
            "or 'what can I trade at Y'. For a full route from A to B use uex_get_trade_routes instead. "
            "Items like weapons or armor are not commodities: use uex_get_item_information."
        )

    def get_prompt(self) -> str:
        return (
            "Where to buy or sell a commodity, and what can be traded at a location. "
            "Always name for each buy/sell option: terminal, price AND stock/demand status (e.g. 'high stock' when buying, 'no demand' when selling). "
            "If the user gives own prices and asks for profit, call uex_calculate_profit afterwards."
        )
