from datetime import datetime
from skills.uexcorp_beta.uexcorp.model.data_model import DataModel

class ItemAttribute(DataModel):

    required_keys = ["id"]

    def __init__(
            self,
            id: int, # int(11)
            id_item: int | None = None,  # int(11)
            id_category: int | None = None,  # int(11)
            id_category_attribute: int | None = None,  # int(11)
            category_name: str | None = None,  # varchar(255)
            item_name: str | None = None,  # varchar(255)
            attribute_name: str | None = None,  # varchar(255)
            value: str | None = None,  # varchar(255)
            unit: str | None = None,  # varchar(255)
            date_added: int | None = None, # int(11)
            date_modified: int | None = None, # int(11)
            load: bool = False,
    ):
        super().__init__("item_attribute")
        self.data = {
            "id": id,
            "id_item": id_item,
            "id_category": id_category,
            "id_category_attribute": id_category_attribute,
            "category_name": category_name,
            "item_name": item_name,
            "attribute_name": attribute_name,
            "value": value,
            "unit": unit,
            "date_added": date_added,
            "date_modified": date_modified,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["id"]:
                raise Exception("ID is required to load data")
            self.load_by_value("id", self.data["id"])

    def get_id(self) -> int:
        return self.data["id"]

    def get_id_item(self) -> int:
        return self.data["id_item"]

    def get_id_category(self) -> int:
        return self.data["id_category"]

    def get_id_category_attribute(self) -> int:
        return self.data["id_category_attribute"]

    def get_category_name(self) -> str | None:
        return self.data["category_name"]

    def get_item_name(self) -> str | None:
        return self.data["item_name"]

    def get_attribute_name(self) -> str | None:
        return self.data["attribute_name"]

    def get_value(self) -> str | None:
        return self.data["value"]

    def get_unit(self) -> str | None:
        return self.data["unit"]

    def get_date_added(self) -> int | None:
        return self.data["date_added"]

    def get_date_added_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_added"])

    def get_date_modified(self) -> int | None:
        return self.data["date_modified"]

    def get_date_modified_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_modified"])

    def __str__(self):
        return f"{self.data['item_name']} - {self.data['attribute_name']}: {self.data['value']} {self.data['unit']}"