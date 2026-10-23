import re

from skills.uexcorp.uexcorp import compression
from skills.uexcorp.uexcorp.tool.tool import Tool
from skills.uexcorp.uexcorp.tool.validator import Validator


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
        from skills.uexcorp.uexcorp.data_access.item_data_acceess import ItemDataAccess
        from skills.uexcorp.uexcorp.data_access.category_data_access import CategoryDataAccess
        from skills.uexcorp.uexcorp.data_access.terminal_data_access import TerminalDataAccess
        from skills.uexcorp.uexcorp.data_access.item_price_data_access import ItemPriceDataAccess
        from skills.uexcorp.uexcorp.data_access.company_data_access import CompanyDataAccess
        from skills.uexcorp.uexcorp.data_access.item_attribute_data_access import ItemAttributeDataAccess
        from skills.uexcorp.uexcorp.database.filter import Filter
        from skills.uexcorp.uexcorp.model.terminal import Terminal
        from skills.uexcorp.uexcorp.helper import Helper

        helper = Helper.get_instance()
        item_data_access = ItemDataAccess()

        if filter_exact_items:
            item_data_access.add_filter_by_name(filter_exact_items)
        else:
            if filter_name_search:
                # All words of one search term must match, any of the search terms may match
                name_search_item_ids = set()
                for name_search in filter_name_search:
                    name_parts = [part for part in re.split(r"[\s-]+", name_search.lower()) if part]
                    if not name_parts:
                        continue
                    name_search_data_access = ItemDataAccess()
                    for name_part in name_parts:
                        name_search_data_access.filter.where("LOWER(name)", f"%{name_part}%", operation="LIKE")
                    name_search_item_ids.update(item.get_id() for item in name_search_data_access.load())
                item_data_access.add_filter_by_id(list(name_search_item_ids))

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
                        if not re.fullmatch(r"-?\d+(\.\d+)?", attribute["value"].strip()):
                            helper.get_handler_tool().add_note(
                                f"Operator '{operator}' is only allowed for numerical values (effects value for {attribute['attribute']}). Returning no results, try again with a numerical value for this attribute or a different operator."
                            )
                            attribute_operator_error = True
                            continue
                        # Only compare stored values that are numbers: CAST turns '' or 'N/A (Beam)' into 0
                        attribute_filter.where("item_attribute.value", "*[0-9]*", operation="GLOB")
                        attribute_filter.where("item_attribute.value", "*[^0-9.-]*", operation="NOT GLOB")
                        attribute_filter.where("CAST(item_attribute.value AS REAL)", float(attribute["value"]), operation=operator)
                    else:
                        attribute_filter.where("value", attribute["value"], operation=operator)
                    attribute_filter.where("attribute_name", attribute["attribute"])
                    attribute_filters.append(attribute_filter)

                if not attribute_unavailable and not attribute_operator_error:
                    # Every attribute filter must match: intersect the items found for each
                    item_ids = None
                    for attribute_filter in attribute_filters:
                        item_attribute_data_access = ItemAttributeDataAccess()
                        item_attribute_data_access.apply_filter(attribute_filter)
                        found = {item_attribute.get_id_item() for item_attribute in item_attribute_data_access.load(debug=True)}
                        item_ids = found if item_ids is None else item_ids & found
                    item_data_access.add_filter_by_id(list(item_ids or []))

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

        return compression.dumps(items), ""

    def get_mandatory_fields(self) -> dict[str, Validator]:
        return {}

    def get_optional_fields(self) -> dict[str, Validator]:
        return {
            "filter_exact_items": Validator(
                Validator.VALIDATE_ITEM,
                multiple=True,
                prompt="Exact item names, e.g. [\"Omnisky VI Cannon\"]. Use only if the exact name is known, otherwise use filter_name_search. If set, all other filters are ignored.",
            ),
            "filter_name_search": Validator(
                Validator.VALIDATE_STRING,
                multiple=True,
                prompt="Short keywords of an item name, e.g. [\"Omnisky\"] or [\"FBL\"] (not \"FBL-8a Arms Imperial Red\"). Finds items whose name contains any of the words. Use when the exact name is unknown.",
            ),
            "filter_category": Validator(
                Validator.VALIDATE_CATEGORY,
                multiple=True,
                config={
                    "is_game_related": True,
                },
                prompt="Item categories as \"<section> <category>\", e.g. [\"Systems Quantum Drives\"] or [\"Armor Helmets\"].",
            ),
            "filter_buy_location": Validator(
                Validator.VALIDATE_LOCATION,
                multiple=True,
                prompt="Only items that can be bought at these locations, e.g. [\"Hurston\"] or [\"ARC-L4\"]."
            ),
            "filter_company": Validator(
                Validator.VALIDATE_COMPANY,
                multiple=True,
                prompt="Only items made by these manufacturers, e.g. [\"Klaus & Werner\"]."
            ),
            "filter_attribute": Validator(
                Validator.VALIDATE_ITEM_ATTRIBUTE,
                multiple=True,
                prompt="Filter by an item stat, e.g. [{\"attribute\": \"Rate of Fire\", \"value\": \"200\", \"operator\": \"<\"}] = rate of fire below 200. <, >, <= and >= only work with numbers. Best combined with filter_category.",
            ),
        }

    def get_description(self) -> str:
        return (
            "Look up items: armor, clothing, personal and ship weapons, ship components (e.g. quantum drives, shields), "
            "tools and more. Returns stats and where to buy them with prices. "
            "Items are not commodities: for trade goods use uex_get_commodity_information. Narrow filters give more details per item."
        )

    def get_prompt(self) -> str:
        return (
            "Items (gear, weapons, ship components): stats, buy locations and prices. "
            "Use it for any question about items, not for commodities."
        )
