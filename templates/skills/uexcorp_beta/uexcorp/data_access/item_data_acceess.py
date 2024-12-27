try:
    from skills.uexcorp_beta.uexcorp.data_access.data_access import DataAccess
    from skills.uexcorp_beta.uexcorp.model.item import Item
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.data_access.data_access import DataAccess
    from uexcorp_beta.uexcorp.model.item import Item


class ItemDataAccess(DataAccess):
    def __init__(
            self,
    ):
        super().__init__(
            table="item",
            model=Item
        )
        self.fields = [
            "id",
            "id_parent",
            "id_category",
            "id_company",
            "id_vehicle",
            "name",
            "section",
            "category",
            "company_name",
            "vehicle_name",
            "slug",
            "url_store",
            "is_exclusive_pledge",
            "is_exclusive_subscriber",
            "is_exclusive_concierge",
            # "attributes",
            "notification",
            "date_added",
            "date_modified",
            "last_import_run_id",
        ]

    def load(self, **params) -> list[Item]:
        return super().load(**params)

    def load_by_property(self, property: str, value: any) -> Item | None:
        return super().load_by_property(property, value)

    def add_filter_by_id_parent(self, id_parent: int | list[int], **params) -> "ItemDataAccess":
        self.filter.where("id_parent", id_parent, **params)
        return self

    def add_filter_by_id_category(self, id_category: int | list[int], **params) -> "ItemDataAccess":
        self.filter.where("id_category", id_category, **params)
        return self

    def add_filter_by_id_company(self, id_company: int | list[int], **params) -> "ItemDataAccess":
        self.filter.where("id_company", id_company, **params)
        return self

    def add_filter_by_id_vehicle(self, id_vehicle: int | list[int], **params) -> "ItemDataAccess":
        self.filter.where("id_vehicle", id_vehicle, **params)
        return self

    def add_filter_by_name(self, name: str | list[str], **params) -> "ItemDataAccess":
        self.filter.where("name", name, **params)
        return self

    def add_filter_by_section(self, section: str | list[str], **params) -> "ItemDataAccess":
        self.filter.where("section", section, **params)
        return self

    def add_filter_by_category(self, category: str | list[str], **params) -> "ItemDataAccess":
        self.filter.where("category", category, **params)
        return self

    def add_filter_by_company_name(self, company_name: str | list[str], **params) -> "ItemDataAccess":
        self.filter.where("company_name", company_name, **params)
        return self

    def add_filter_by_vehicle_name(self, vehicle_name: str | list[str], **params) -> "ItemDataAccess":
        self.filter.where("vehicle_name", vehicle_name, **params)
        return self

    def add_filter_by_slug(self, slug: str | list[str], **params) -> "ItemDataAccess":
        self.filter.where("slug", slug, **params)
        return self

    def add_filter_by_url_store(self, url_store: str | list[str], **params) -> "ItemDataAccess":
        self.filter.where("url_store", url_store, **params)
        return self

    def add_filter_by_is_exclusive_pledge(self, is_exclusive_pledge: bool | list[bool], **params) -> "ItemDataAccess":
        self.filter.where("is_exclusive_pledge", is_exclusive_pledge, **params)
        return self

    def add_filter_by_is_exclusive_subscriber(self, is_exclusive_subscriber: bool | list[bool], **params) -> "ItemDataAccess":
        self.filter.where("is_exclusive_subscriber", is_exclusive_subscriber, **params)
        return self

    def add_filter_by_is_exclusive_concierge(self, is_exclusive_concierge: bool | list[bool], **params) -> "ItemDataAccess":
        self.filter.where("is_exclusive_concierge", is_exclusive_concierge, **params)
        return self

    def add_filter_by_attributes(self, attributes: str | list[str], **params) -> "ItemDataAccess":
        self.filter.where("attributes", attributes, **params)
        return self

    def add_filter_by_notification(self, notification: str | list[str], **params) -> "ItemDataAccess":
        self.filter.where("notification", notification, **params)
        return self

    def add_filter_by_date_added(self, date_added: int | list[int], **params) -> "ItemDataAccess":
        self.filter.where("date_added", date_added, **params)
        return self

    def add_filter_by_date_modified(self, date_modified: int | list[int], **params) -> "ItemDataAccess":
        self.filter.where("date_modified", date_modified, **params)
        return self
