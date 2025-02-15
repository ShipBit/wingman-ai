try:
    from skills.uexcorp.uexcorp.data_access.data_access import DataAccess
    from skills.uexcorp.uexcorp.model.item_attribute import ItemAttribute
except ModuleNotFoundError:
    from uexcorp.uexcorp.data_access.data_access import DataAccess
    from uexcorp.uexcorp.model.item_attribute import ItemAttribute


class ItemAttributeDataAccess(DataAccess):
    def __init__(
            self,
    ):
        super().__init__(
            table="item_attribute",
            model=ItemAttribute,
        )
        self.fields = [
            "id",
            "id_item",
            "id_category",
            "id_category_attribute",
            "category_name",
            "item_name",
            "attribute_name",
            "value",
            "unit",
            "date_added",
            "date_modified",
        ]

    def load(self, **params) -> list[ItemAttribute]:
        return super().load(**params)

    def load_by_property(self, property: str, value: any) -> ItemAttribute | None:
        return super().load_by_property(property, value)

    def add_filter_by_id_item(self, id_item: int | list[int], **params) -> "ItemAttributeDataAccess":
        self.filter.where("id_item", id_item, **params)
        return self

    def add_filter_by_id_category(self, id_category: int | list[int], **params) -> "ItemAttributeDataAccess":
        self.filter.where("id_category", id_category, **params)
        return self

    def add_filter_by_id_category_attribute(self, id_category_attribute: int | list[int], **params) -> "ItemAttributeDataAccess":
        self.filter.where("id_category_attribute", id_category_attribute, **params)
        return self

    def add_filter_by_category_name(self, category_name: str | list[str], **params) -> "ItemAttributeDataAccess":
        self.filter.where("category_name", category_name, **params)
        return self

    def add_filter_by_item_name(self, item_name: str | list[str], **params) -> "ItemAttributeDataAccess":
        self.filter.where("item_name", item_name, **params)
        return self

    def add_filter_by_attribute_name(self, attribute_name: str | list[str], **params) -> "ItemAttributeDataAccess":
        self.filter.where("attribute_name", attribute_name, **params)
        return self

    def add_filter_by_value(self, value: str | list[str], **params) -> "ItemAttributeDataAccess":
        self.filter.where("value", value, **params)
        return self

    def add_filter_by_unit(self, unit: str | list[str], **params) -> "ItemAttributeDataAccess":
        self.filter.where("unit", unit, **params)
        return self

    def add_filter_by_date_added(self, date_added: int | list[int], **params) -> "ItemAttributeDataAccess":
        self.filter.where("date_added", date_added, **params)
        return self

    def add_filter_by_date_modified(self, date_modified: int | list[int], **params) -> "ItemAttributeDataAccess":
        self.filter.where("date_modified", date_modified, **params)
        return self
