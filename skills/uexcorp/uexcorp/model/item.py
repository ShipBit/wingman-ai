from datetime import datetime
from typing import TYPE_CHECKING
from skills.uexcorp.uexcorp.model.data_model import DataModel
if TYPE_CHECKING:
    from skills.uexcorp.uexcorp.model.item_attribute import ItemAttribute


class Item(DataModel):

    required_keys = ["id"]

    def __init__(
        self,
        id: int,  # int(11) // route ID, may change during website updates
        id_parent: int | None = None,  # int(11)
        id_category: int | None = None,  # int(11) // category
        id_company: int | None = None,  # int(11) // if item is linked to a company
        id_vehicle: int | None = None,  # int(11) // if item is linked to a vehicle
        name: str | None = None,  # string(255)
        section: str | None = None,  # string(255) // coming from categories
        category: str | None = None,  # string(255) // coming from categories
        company_name: str | None = None,  # string(255) // if item is linked to a company
        vehicle_name: str | None = None,  # string(255) // if item is linked to a vehicle
        slug: str | None = None,  # string(255) // used by UEX item URLs
        uuid: str | None = None,  # string(255) // star citizen uuid
        url_store: str | None = None,  # string(255) // pledge store URL
        is_exclusive_pledge: int | None = None,  # int(1)
        is_exclusive_subscriber: int | None = None,  # int(1)
        is_exclusive_concierge: int | None = None,  # int(1)
        notification: dict | None = None,  # json // heads up about an item, such as known bugs, etc.
        date_added: int | None = None,  # int(11) // timestamp
        date_modified: int | None = None,  # int(11) // timestamp
        load: bool = False,
    ):
        super().__init__("item")
        self.data = {
            "id": id,
            "id_parent": id_parent,
            "id_category": id_category,
            "id_company": id_company,
            "id_vehicle": id_vehicle,
            "name": name,
            "section": section,
            "category": category,
            "company_name": company_name,
            "vehicle_name": vehicle_name,
            "slug": slug,
            "uuid": uuid,
            "url_store": url_store,
            "is_exclusive_pledge": is_exclusive_pledge,
            "is_exclusive_subscriber": is_exclusive_subscriber,
            "is_exclusive_concierge": is_exclusive_concierge,
            "notification": notification,
            "date_added": date_added,
            "date_modified": date_modified,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["id"]:
                raise Exception("ID is required to load data")
            self.load_by_value("id", self.data["id"])

    def get_data_for_ai(self) -> dict:
        from skills.uexcorp.uexcorp.model.category import Category
        from skills.uexcorp.uexcorp.model.vehicle import Vehicle
        from skills.uexcorp.uexcorp.data_access.item_price_data_access import ItemPriceDataAccess

        category = Category(self.get_id_category(), load=True) if self.get_id_category() else None

        information = {
            "name": self.get_name(),
            "category": category.get_data_for_ai_minimal() if category else None,
            "exclusivity": self.get_exclusivity(),
            "notes": self.get_notification(),
        }

        if self.get_id_parent():
            # Name only: the parent's own view would drag in all of its offers.
            parent = Item(self.get_id_parent(), load=True)
            information["parent"] = parent.get_name()

        if self.get_id_vehicle():
            vehicle = Vehicle(self.get_id_vehicle(), load=True)
            information["for_vehicle"] = str(vehicle)

        attributes = {}
        for item_attribute in self.get_attributes():
            value = f"{item_attribute.get_value() or ''}{item_attribute.get_unit() or ''}"
            if value:
                attributes[item_attribute.get_attribute_name()] = value
        information["attributes"] = attributes

        offers = self.__get_offer_strings()
        if offers:
            information["offers"] = offers

        return information

    def __get_offer_strings(self) -> list[str]:
        # Many terminals share the same price, so offers are grouped by price
        # ("Buy for X at: A, B, C") instead of one entry per terminal.
        from skills.uexcorp.uexcorp import compression
        from skills.uexcorp.uexcorp.data_access.item_price_data_access import ItemPriceDataAccess

        buy_groups = {}
        sell_groups = {}
        for price in ItemPriceDataAccess().add_filter_by_id_item(self.get_id()).load():
            if price.get_price_buy():
                buy_groups.setdefault(price.get_price_buy(), []).append(price.get_terminal_name())
            if price.get_price_sell():
                sell_groups.setdefault(price.get_price_sell(), []).append(price.get_terminal_name())

        offers = []
        for value in sorted(buy_groups):  # cheapest buy first
            offers.append(f"Buy for {compression.number(value)} at: {', '.join(buy_groups[value])}")
        for value in sorted(sell_groups, reverse=True):  # best sell first
            offers.append(f"Sell for {compression.number(value)} at: {', '.join(sell_groups[value])}")
        return offers

    def get_data_for_ai_minimal(self) -> dict:
        information = {
            "name": self.get_name(),
            "section": self.get_section(),
            "category": self.get_category(),
        }

        if self.get_id_parent():
            parent = Item(self.get_id_parent(), load=True)
            information["parent"] = parent.get_name()

        if self.get_id_vehicle():
            information["for_vehicle"] = self.get_vehicle_name()

        attributes = {}
        for item_attribute in self.get_attributes():
            value = f"{item_attribute.get_value() or ''}{item_attribute.get_unit() or ''}"
            if value:
                attributes[item_attribute.get_attribute_name()] = value
        information["attributes"] = attributes

        offers = self.__get_offer_strings()
        if offers:
            information["offers"] = offers

        return information

    def get_exclusivity(self) -> list[str]:
        exclusivity = []
        if self.get_is_exclusive_pledge():
            exclusivity.append("pledge")
        if self.get_is_exclusive_subscriber():
            exclusivity.append("subscriber")
        if self.get_is_exclusive_concierge():
            exclusivity.append("concierge")
        return exclusivity

    def get_attributes(self) -> list["ItemAttribute"]:
        from skills.uexcorp.uexcorp.data_access.item_attribute_data_access import ItemAttributeDataAccess

        return ItemAttributeDataAccess().add_filter_by_id_item(self.get_id()).load()

    def get_id(self) -> int:
        return self.data["id"]

    def get_id_parent(self) -> int | None:
        return self.data["id_parent"]

    def get_id_category(self) -> int | None:
        return self.data["id_category"]

    def get_id_company(self) -> int | None:
        return self.data["id_company"]

    def get_id_vehicle(self) -> int | None:
        return self.data["id_vehicle"]

    def get_name(self) -> str | None:
        return self.data["name"]

    def get_section(self) -> str | None:
        return self.data["section"]

    def get_category(self) -> str | None:
        return self.data["category"]

    def get_company_name(self) -> str | None:
        return self.data["company_name"]

    def get_vehicle_name(self) -> str | None:
        return self.data["vehicle_name"]

    def get_slug(self) -> str | None:
        return self.data["slug"]

    def get_uuid(self) -> str | None:
        return self.data["uuid"]

    def get_url_store(self) -> str | None:
        return self.data["url_store"]

    def get_is_exclusive_pledge(self) -> bool | None:
        return bool(self.data["is_exclusive_pledge"])

    def get_is_exclusive_subscriber(self) -> bool | None:
        return bool(self.data["is_exclusive_subscriber"])

    def get_is_exclusive_concierge(self) -> bool | None:
        return bool(self.data["is_exclusive_concierge"])

    def get_notification(self) -> dict | None:
        return self.data["notification"]

    def get_date_added(self) -> int | None:
        return self.data["date_added"]

    def get_date_added_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_added"])

    def get_date_modified(self) -> int | None:
        return self.data["date_modified"]

    def get_date_modified_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_modified"])

    def __str__(self):
        return str(self.data["name"])