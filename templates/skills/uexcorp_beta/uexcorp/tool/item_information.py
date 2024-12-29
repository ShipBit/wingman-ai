import json
try:
    from skills.uexcorp_beta.uexcorp.model.data_model import DataModel
    from skills.uexcorp_beta.uexcorp.tool.tool import Tool
    from skills.uexcorp_beta.uexcorp.tool.validator import Validator
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.model.data_model import DataModel
    from uexcorp_beta.uexcorp.tool.tool import Tool
    from uexcorp_beta.uexcorp.tool.validator import Validator


class ItemInformation(Tool):

    def __init__(self):
        super().__init__()

    def execute(
        self,
        filter_items: list[str] | None = None,
        filter_category: list[str] | None = None,
        filter_buy_location: list[str] | None = None,
        filter_company: list[str] | None = None,
    ) -> (str, str):
        try:
            from skills.uexcorp_beta.uexcorp.data_access.item_data_acceess import ItemDataAccess
            from skills.uexcorp_beta.uexcorp.data_access.category_data_access import CategoryDataAccess
            from skills.uexcorp_beta.uexcorp.data_access.terminal_data_access import TerminalDataAccess
            from skills.uexcorp_beta.uexcorp.data_access.item_price_data_access import ItemPriceDataAccess
            from skills.uexcorp_beta.uexcorp.data_access.company_data_access import CompanyDataAccess
            from skills.uexcorp_beta.uexcorp.model.terminal import Terminal
            from skills.uexcorp_beta.uexcorp.helper import Helper
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.data_access.item_data_acceess import ItemDataAccess
            from uexcorp_beta.uexcorp.data_access.category_data_access import CategoryDataAccess
            from uexcorp_beta.uexcorp.data_access.terminal_data_access import TerminalDataAccess
            from uexcorp_beta.uexcorp.data_access.item_price_data_access import ItemPriceDataAccess
            from uexcorp_beta.uexcorp.data_access.company_data_access import CompanyDataAccess
            from uexcorp_beta.uexcorp.model.terminal import Terminal
            from uexcorp_beta.uexcorp.helper import Helper

        helper = Helper().get_instance()
        item_data_access = ItemDataAccess()

        if filter_items:
            item_data_access.add_filter_by_name(filter_items)
        else:
            if filter_category:
                category_data_access = CategoryDataAccess()
                category_data_access.add_filter_by_combined_name(filter_category)
                category_data_access.add_filter_by_is_game_related(True)
                categories = category_data_access.load(debug=True)
                item_data_access.add_filter_by_id_category([category.get_id() for category in categories])

            if filter_buy_location:
                terminal_data_access = TerminalDataAccess()
                terminal_data_access.add_filter_by_location_name_whitelist(filter_buy_location)
                terminal_data_access.add_filter_by_type(Terminal.TYPE_ITEM)
                terminals = terminal_data_access.load(debug=True)

                item_price_data_access = ItemPriceDataAccess()
                item_price_data_access.add_filter_by_id_terminal([terminal.get_id() for terminal in terminals])
                item_price_data_access.add_filter_by_price_buy(0, operation=">")
                item_prices = item_price_data_access.load(debug=True)
                item_price_item_ids = []
                for item_price in item_prices:
                    if item_price.get_id_item() not in item_price_item_ids:
                        item_price_item_ids.append(item_price.get_id_item())

                item_data_access.add_filter_by_id(item_price_item_ids)

            if filter_company:
                company_data_access = CompanyDataAccess()
                company_data_access.add_filter_by_name(filter_company)
                companies = company_data_access.load(debug=True)
                item_data_access.add_filter_by_id_company([company.get_id() for company in companies])

        items = item_data_access.load(debug=True)

        if not items:
            helper.get_handler_tool().add_note(
                "No matching items found. Please check filter criteria."
            )
            return [], ""
        elif len(items) <= 10:
            items = [item.get_data_for_ai() for item in items]
        elif len(items) <= 20:
            items = [item.get_data_for_ai_minimal() for item in items]
            helper.get_handler_tool().add_note(
                f"Found {len(items)} matching items. Filter criteria are somewhat broad. (max 10 items for advanced information)"
            )
        elif len(items) <= 50:
            items = [str(item) for item in items]
            helper.get_handler_tool().add_note(
                f"Found {len(items)} matching items. Filter criteria are very broad. (max 20 items for more than just name information)"
            )
        else:
            helper.get_handler_tool().add_note(
                f"Found {len(items)} matching items. Filter criteria are too broad. (max 50 items for names and max 20 for information about each item)"
            )
            items = []

        return json.dumps(items), ""

    def get_mandatory_fields(self) -> dict[str, Validator]:
        return {}

    def get_optional_fields(self) -> dict[str, Validator]:
        return {
            "filter_items": Validator(Validator.VALIDATE_ITEM, multiple=True),
            "filter_category": Validator(Validator.VALIDATE_CATEGORY, multiple=True, config={
                "is_game_related": True,
            }),
            "filter_buy_location": Validator(Validator.VALIDATE_LOCATION, multiple=True),
            "filter_company": Validator(Validator.VALIDATE_COMPANY, multiple=True),
        }

    def get_description(self) -> str:
        return "Gives back information about a items and their purchase options. Items range from Suits, over vehicle and personal weapons to tools and ship systems. An item is not a commodity."
