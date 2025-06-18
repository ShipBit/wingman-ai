import json
try:
    from skills.uexcorp.uexcorp.model.data_model import DataModel
    from skills.uexcorp.uexcorp.tool.tool import Tool
    from skills.uexcorp.uexcorp.tool.validator import Validator
except ModuleNotFoundError:
    from uexcorp.uexcorp.model.data_model import DataModel
    from uexcorp.uexcorp.tool.tool import Tool
    from uexcorp.uexcorp.tool.validator import Validator


class ItemInformation(Tool):
    REQUIRES_AUTHENTICATION = False
    TOOL_NAME = "uex_get_item_information"

    def __init__(self):
        super().__init__()

    def execute(
        self,
        filter_exact_items: list[str] | None = None,
        filter_name_search: list[str] | None = None,
        filter_category: list[str] | None = None,
        filter_buy_location: list[str] | None = None,
        filter_company: list[str] | None = None,
        filter_attribute: list[dict[str, str, str]] | None = None,
    ) -> (str, str):
        try:
            from skills.uexcorp.uexcorp.data_access.item_data_acceess import ItemDataAccess
            from skills.uexcorp.uexcorp.data_access.category_data_access import CategoryDataAccess
            from skills.uexcorp.uexcorp.data_access.terminal_data_access import TerminalDataAccess
            from skills.uexcorp.uexcorp.data_access.item_price_data_access import ItemPriceDataAccess
            from skills.uexcorp.uexcorp.data_access.company_data_access import CompanyDataAccess
            from skills.uexcorp.uexcorp.data_access.item_attribute_data_access import ItemAttributeDataAccess
            from skills.uexcorp.uexcorp.database.filter import Filter
            from skills.uexcorp.uexcorp.model.terminal import Terminal
            from skills.uexcorp.uexcorp.helper import Helper
        except ModuleNotFoundError:
            from uexcorp.uexcorp.data_access.item_data_acceess import ItemDataAccess
            from uexcorp.uexcorp.data_access.category_data_access import CategoryDataAccess
            from uexcorp.uexcorp.data_access.terminal_data_access import TerminalDataAccess
            from uexcorp.uexcorp.data_access.item_price_data_access import ItemPriceDataAccess
            from uexcorp.uexcorp.data_access.company_data_access import CompanyDataAccess
            from uexcorp.uexcorp.data_access.item_attribute_data_access import ItemAttributeDataAccess
            from uexcorp.uexcorp.database.filter import Filter
            from uexcorp.uexcorp.model.terminal import Terminal
            from uexcorp.uexcorp.helper import Helper

        helper = Helper().get_instance()
        item_data_access = ItemDataAccess()

        if filter_exact_items:
            item_data_access.add_filter_by_name(filter_exact_items)
        else:
            if filter_name_search:
                filter_name = Filter()
                for name_search in filter_name_search:
                    for name_part in name_search.split(" "):
                        for name_part_part in name_part.split("-"):
                            filter_name.where("LOWER(name)", f"%{name_part_part.lower()}%", operation="LIKE", is_or=True)
                item_data_access.apply_filter(filter_name)

            categories = []
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

            if filter_attribute:
                attribute_unavailable = False
                attribute_operator_error = False
                if filter_category:
                    # check if attribute filter is compatible
                    item_attribute_data_access = ItemAttributeDataAccess()
                    item_attribute_data_access.add_filter_by_id_category([category.get_id() for category in categories])
                    possible_item_attributes = item_attribute_data_access.load(debug=True)
                    possible_item_attribute_names = []
                    for possible_item_attribute in possible_item_attributes:
                        if possible_item_attribute.get_attribute_name() not in possible_item_attribute_names:
                            possible_item_attribute_names.append(possible_item_attribute.get_attribute_name())

                    for attribute in filter_attribute:
                        if attribute["attribute"] not in possible_item_attribute_names:
                            helper.get_handler_tool().add_note(
                                f"Attribute {attribute['attribute']} is not available for the selected categories. Returning no results, try again with a different attribute."
                            )
                            attribute_unavailable = True

                    if attribute_unavailable:
                        helper.get_handler_tool().add_note(
                            f"Possible attributes for selected categories: {', '.join(possible_item_attribute_names)}"
                        )

                attribute_filters = []
                for attribute in filter_attribute:
                    attribute_filter = Filter()
                    operator = attribute["operator"]
                    if operator in ["<", ">", "<=", ">="]:
                        if not attribute["value"].lstrip('-').isdigit():
                            helper.get_handler_tool().add_note(
                                f"Operator '{operator}' is only allowed for numerical values (effects value for {attribute['attribute']}). Returning no results, try again with a numerical value for this attribute or a different operator."
                            )
                            attribute_operator_error = True
                            continue
                        else:
                            if attribute["value"].lstrip('-') != attribute["value"]:
                                attribute["value"] = -int(attribute["value"].lstrip('-'))
                            else:
                                attribute["value"] = int(attribute["value"])
                            attribute_filter.where("CAST(item_attribute.value AS INTEGER)", attribute["value"], operation=operator)
                    else:
                        attribute_filter.where("value", attribute["value"], operation=operator)
                    attribute_filter.where("attribute_name", attribute["attribute"])
                    attribute_filters.append(attribute_filter)

                if not attribute_unavailable and not attribute_operator_error:
                    item_attribute_data_access = ItemAttributeDataAccess()
                    for attribute_filter in attribute_filters:
                        item_attribute_data_access.apply_filter(attribute_filter, is_or=True)
                    item_attributes = item_attribute_data_access.load(debug=True)
                    item_ids = []
                    for item_attribute in item_attributes:
                        if item_attribute.get_id_item() not in item_ids:
                            item_ids.append(item_attribute.get_id_item())
                    item_data_access.add_filter_by_id(item_ids)

        items = item_data_access.load(debug=True)

        if not items:
            helper.get_handler_tool().add_note(
                "No matching items found. Please check filter criteria."
            )
            return [], ""
        elif len(items) <= 10:
            items = [item.get_data_for_ai() for item in items]
        elif len(items) <= 30:
            items = [item.get_data_for_ai_minimal() for item in items]
            helper.get_handler_tool().add_note(
                f"Found {len(items)} matching items. Filter criteria are somewhat broad. (max 10 items for advanced information)"
            )
        elif len(items) <= 60:
            items = [f"{str(item)} ({item.get_section()} {item.get_category()})" for item in items]
            helper.get_handler_tool().add_note(
                f"Found {len(items)} matching items. Filter criteria are very broad. (max 30 items for more than just name information)"
            )
        else:
            helper.get_handler_tool().add_note(
                f"Found {len(items)} matching items. Filter criteria are too broad. (max 60 items for names and max 30 for information about each item)"
            )
            items = []

        return json.dumps(items), ""

    def get_mandatory_fields(self) -> dict[str, Validator]:
        return {}

    def get_optional_fields(self) -> dict[str, Validator]:
        return {
            "filter_exact_items": Validator(
                Validator.VALIDATE_ITEM,
                multiple=True,
                prompt="Provide one or multiple exact item names to filter by name. If this filter is used, others have no effect. (e.g. \"Omnisky VI\" or \"P4-AR\"). May be used if user knows the exact name of an item. Overwrites other filters.",
            ),
            "filter_name_search": Validator(
                Validator.VALIDATE_STRING,
                multiple=True,
                prompt="Provide one or multiple partial item names to search for. (e.g. \"Omnisky\" or \"Desert\"). May be used if user is not sure about the exact name of an item or searches for similar items. Only use meaningful keywords, like \"FBL\" instead of \"FBL-8a Arms Imperial Red\" for example to find all parts of the \"FBL\" series.",
            ),
            "filter_category": Validator(
                Validator.VALIDATE_CATEGORY,
                multiple=True,
                config={
                    "is_game_related": True,
                },
                prompt="Provide one or multiple item categories to look up. (e.g. \"Systems Quantum Drives\")",
            ),
            "filter_buy_location": Validator(
                Validator.VALIDATE_LOCATION,
                multiple=True,
                prompt="Provide one or multiple locations to filter for items able to buy there. (e.g. \"Hurston\" or \"ARC-L4\")"
            ),
            "filter_company": Validator(
                Validator.VALIDATE_COMPANY,
                multiple=True,
                prompt="Provide one or multiple companies to filter for items produced by them. (e.g. \"Klaus & Werner\")"
            ),
            "filter_attribute": Validator(
                Validator.VALIDATE_ITEM_ATTRIBUTE,
                multiple=True,
                prompt="Provide a attribute name a value and a comparison operator to filter items by. (e.g. {attribute: \"Rate of Fire\", value: \"200\", operator: \"<\"} to find all items with a rate of fire lower than 200.)",
            ),
        }

    def get_description(self) -> str:
        return "Gives back information about a items and their purchase options. Items range from suits, over vehicle and personal weapons to tools and ship components. An item is not a commodity."

    def get_prompt(self) -> str:
        return "Get all information's about all items, filterable. Items are not commodities, therefore if item information is requests, this is the function. Includes item buy prices and locations."
