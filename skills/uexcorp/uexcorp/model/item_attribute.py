from datetime import datetime
from skills.uexcorp.uexcorp.model.data_model import DataModel

# UEX spells some units several ways, some in another scale: one unit each, so values compare
_UNITS = {
    "Mm/s": ("km/s", 1000),
    "μSCU": ("µSCU", 1), "μSCUI": ("µSCU", 1), "uSCU": ("µSCU", 1), "microSCU": ("µSCU", 1),
    "KµSCU": ("µSCU", 1000), "cSCU": ("µSCU", 10000),
    "mRem": ("REM", 0.001), "mRem/s": ("REM/s", 0.001), "REM/S": ("REM/s", 1),
    "RPM": ("rpm", 1), "KG": ("kg", 1), "Kg": ("kg", 1), "SUC/s": ("SCU/s", 1),
    "º C": ("°C", 1), "ºC": ("°C", 1), "℃": ("°C", 1), "C°": ("°C", 1), "degrees C": ("°C", 1),
}


# Currently unused, as information is included in the Item model
class ItemAttribute(DataModel):

    required_keys = ["id"]

    @staticmethod
    def normalize_unit(row: dict) -> None:
        """Rewrites value and unit of an imported row to the one unit of that quantity."""
        target = _UNITS.get(row.get("unit"))
        if not target:
            return
        unit, factor = target
        if factor != 1:
            try:
                number = float(str(row.get("value")).replace(",", "")) * factor
            except (TypeError, ValueError):
                return
            row["value"] = format(round(number, 6), "f").rstrip("0").rstrip(".")
        row["unit"] = unit

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
            item_uuid: str | None = None,  # string(255)
            item_wiki: str | None = None,  # string(255)
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
            "item_uuid": item_uuid,
            "item_wiki": item_wiki,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["id"]:
                raise Exception("ID is required to load data")
            self.load_by_value("id", self.data["id"])

    def get_data_for_ai(self) -> dict:
        from skills.uexcorp.uexcorp.model.item import Item
        from skills.uexcorp.uexcorp.model.category import Category
        from skills.uexcorp.uexcorp.model.category_attribute import CategoryAttribute

        item = Item(self.get_id_item(), load=True) if self.get_id_item() else None
        category = Category(self.get_id_category(), load=True) if self.get_id_category() else None
        category_attribute = CategoryAttribute(self.get_id_category_attribute(), load=True) if self.get_id_category_attribute() else None

        return {
            "item": item.get_data_for_ai_minimal() if item else None,
            "category": category.get_data_for_ai_minimal() if category else None,
            "category_attribute": category_attribute.get_data_for_ai_minimal() if category_attribute else None,
            "value": self.get_value(),
            "unit": self.get_unit(),
        }

    def get_data_for_ai_minimal(self) -> dict:
        return {
            "category_attribute": self.get_attribute_name(),
            "value": self.get_value(),
            "unit": self.get_unit(),
        }

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

    def get_item_uuid(self) -> str | None:
        return self.data["item_uuid"]

    def get_item_wiki(self) -> str | None:
        return self.data["item_wiki"]

    def __str__(self):
        return f"{self.data['item_name']} - {self.data['attribute_name']}: {self.data['value']} {self.data['unit']}"