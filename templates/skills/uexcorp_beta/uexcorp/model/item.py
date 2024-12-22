from datetime import datetime
try:
    from skills.uexcorp_beta.uexcorp.model.data_model import DataModel
except ImportError:
    from uexcorp_beta.uexcorp.model.data_model import DataModel

class Item(DataModel):

    required_keys = ["id"]

    def __init__(
        self,
        id: int,  # int(11) // route ID, may change during website updates
        id_parent: int | None = None,  # int(11)
        id_category: int | None = None,  # int(11) // category
        id_vehicle: int | None = None,  # int(11) // if item is linked to a vehicle
        name: str | None = None,  # string(255)
        section: str | None = None,  # string(255) // coming from categories
        category: str | None = None,  # string(255) // coming from categories
        slug: str | None = None,  # string(255) // used by UEX item URLs
        url_store: str | None = None,  # string(255) // pledge store URL
        is_exclusive_pledge: int | None = None,  # int(1)
        is_exclusive_subscriber: int | None = None,  # int(1)
        is_exclusive_concierge: int | None = None,  # int(1)
        screenshot: str | None = None,  # string(255) // item image URL
        attributes: dict | None = None,  # json // item specifications (ids) are associated with categories_attributes
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
            "id_vehicle": id_vehicle,
            "name": name,
            "section": section,
            "category": category,
            "slug": slug,
            "url_store": url_store,
            "is_exclusive_pledge": is_exclusive_pledge,
            "is_exclusive_subscriber": is_exclusive_subscriber,
            "is_exclusive_concierge": is_exclusive_concierge,
            "screenshot": screenshot,
            "attributes": attributes,
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
        try:
            from skills.uexcorp_beta.uexcorp.model.category import Category
            from skills.uexcorp_beta.uexcorp.model.category_attribute import CategoryAttribute
            from skills.uexcorp_beta.uexcorp.model.vehicle import Vehicle
            from skills.uexcorp_beta.uexcorp.data_access.item_price_data_access import ItemPriceDataAccess
        except ImportError:
            from uexcorp_beta.uexcorp.model.category import Category
            from uexcorp_beta.uexcorp.model.category_attribute import CategoryAttribute
            from uexcorp_beta.uexcorp.model.vehicle import Vehicle
            from uexcorp_beta.uexcorp.data_access.item_price_data_access import ItemPriceDataAccess

        category = Category(self.get_id_category(), load=True) if self.get_id_category() else None

        information = {
            "name": self.get_name(),
            "category": category.get_data_for_ai_minimal() if category else None,
            "is_exclusive_pledge": self.get_is_exclusive_pledge(),
            "is_exclusive_subscriber": self.get_is_exclusive_subscriber(),
            "is_exclusive_concierge": self.get_is_exclusive_concierge(),
            "notes": self.get_notification(),
        }

        if self.get_id_parent():
            parent = Item(self.get_id_parent(), load=True)
            information["parent"] = parent.get_data_for_ai_minimal()

        if self.get_id_vehicle():
            vehicle = Vehicle(self.get_id_vehicle(), load=True)
            information["for_vehicle"] = vehicle.get_data_for_ai_minimal()

        if self.get_attributes():
            attributes = {}
            for id_category_attribute, value in self.get_attributes().items():
                category_attribute = CategoryAttribute(id_category_attribute, load=True)
                attributes[category_attribute.get_name()] = value

        prices = ItemPriceDataAccess().add_filter_by_id_item(self.get_id()).load()
        offers = []
        for price in prices:
            offers.append(price.get_data_for_ai_minimal())
        if offers:
            information["offers"] = offers

        return information

    def get_data_for_ai_minimal(self) -> dict:
        try:
            from skills.uexcorp_beta.uexcorp.model.category_attribute import CategoryAttribute
            from skills.uexcorp_beta.uexcorp.data_access.item_price_data_access import ItemPriceDataAccess
            from skills.uexcorp_beta.uexcorp.model.vehicle import Vehicle
        except ImportError:
            from uexcorp_beta.uexcorp.model.category_attribute import CategoryAttribute
            from uexcorp_beta.uexcorp.data_access.item_price_data_access import ItemPriceDataAccess
            from uexcorp_beta.uexcorp.model.vehicle import Vehicle

        information = {
            "name": self.get_name(),
            "section": self.get_section(),
            "category": self.get_category(),
        }

        if self.get_id_parent():
            parent = Item(self.get_id_parent(), load=True)
            information["parent"] = parent.get_name()

        if self.get_id_vehicle():
            vehicle = Vehicle(self.get_id_vehicle(), load=True)
            information["for_vehicle"] = vehicle.get_name()

        if self.get_attributes():
            attributes = {}
            for id_category_attribute, value in self.get_attributes().items():
                category_attribute = CategoryAttribute(id_category_attribute, load=True)
                attributes[category_attribute.get_name()] = value

        prices = ItemPriceDataAccess().add_filter_by_id_item(self.get_id()).load()
        offers = []
        for price in prices:
            offers.append(str(price))
        if offers:
            information["offers"] = offers

        return information

    def get_id(self) -> int:
        return self.data["id"]

    def get_id_parent(self) -> int | None:
        return self.data["id_parent"]

    def get_id_category(self) -> int | None:
        return self.data["id_category"]

    def get_id_vehicle(self) -> int | None:
        return self.data["id_vehicle"]

    def get_name(self) -> str | None:
        return self.data["name"]

    def get_section(self) -> str | None:
        return self.data["section"]

    def get_category(self) -> str | None:
        return self.data["category"]

    def get_slug(self) -> str | None:
        return self.data["slug"]

    def get_url_store(self) -> str | None:
        return self.data["url_store"]

    def get_is_exclusive_pledge(self) -> bool | None:
        return bool(self.data["is_exclusive_pledge"])

    def get_is_exclusive_subscriber(self) -> bool | None:
        return bool(self.data["is_exclusive_subscriber"])

    def get_is_exclusive_concierge(self) -> bool | None:
        return bool(self.data["is_exclusive_concierge"])

    def get_screenshot(self) -> str | None:
        return self.data["screenshot"]

    def get_attributes(self) -> dict | None:
        return self.data["attributes"]

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