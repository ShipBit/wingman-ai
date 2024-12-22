from datetime import datetime
from skills.uexcorp_beta.uexcorp.model.category import Category
from skills.uexcorp_beta.uexcorp.model.data_model import DataModel

class CategoryAttribute(DataModel):

    required_keys = ["id"]

    def __init__(
            self,
            id: int,  # int(11)
            id_category: int | None = None, # int(11)
            name: str | None = None, # varchar(255)
            category_name: str | None = None, # varchar(255)
            date_added: int | None = None, # int(11)
            date_modified: int | None = None, # int(11)
            load: bool = False,
    ):
        super().__init__("category_attribute")
        self.data = {
            "id": id,
            "id_category": id_category,
            "name": name,
            "category_name": category_name,
            "date_added": date_added,
            "date_modified": date_modified,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["id"]:
                raise Exception("ID is required to load data")
            self.load_by_value("id", self.data["id"])

    def get_data_for_ai(self) -> dict:
        from skills.uexcorp_beta.uexcorp.model.category import Category

        category = Category(self.get_id_category(), load=True) if self.get_id_category() else None

        return {
            "name": self.get_name(),
            "category": category.get_data_for_ai_minimal() if category else None,
        }

    def get_data_for_ai_minimal(self) -> dict:
        return {
            "name": self.get_name(),
            "category": self.get_category_name(),
        }

    def get_id(self) -> int:
        return self.data["id"]

    def get_name(self) -> str | None:
        return self.data["name"]

    def get_id_category(self) -> int | None:
        return self.data["id_category"]

    def get_category_name(self) -> str | None:
        return self.data["category_name"]

    def get_category(self) -> Category | None:
        if not self.data["id_category"]:
            return None
        return Category(self.data["id_category"], load=True)

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
