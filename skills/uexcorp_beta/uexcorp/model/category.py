from datetime import datetime
try:
    from skills.uexcorp_beta.uexcorp.model.data_model import DataModel
except ImportError:
    from uexcorp_beta.uexcorp.model.data_model import DataModel

class Category(DataModel):

    required_keys = ["id"]

    def __init__(
            self,
            id: int, # int(11)
            type: str | None = None, # varchar(255)
            section: str | None = None, # varchar(255)
            name: str | None = None, # varchar(255)
            is_game_related: int | None = None, # tinyint(1)
            is_mining: int | None = None, # tinyint(1)
            date_added: int | None = None, # int(11)
            date_modified: int | None = None, # int(11)
            load: bool = False,
    ):
        super().__init__("category")
        self.data = {
            "id": id,
            "type": type,
            "section": section,
            "name": name,
            "is_game_related": is_game_related,
            "is_mining": is_mining,
            "date_added": date_added,
            "date_modified": date_modified,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["id"]:
                raise Exception("ID is required to load data")
            self.load_by_value("id", self.data["id"])

    def get_data_for_ai(self) -> dict:
        return {
            "name": self.get_name(),
            "type": self.get_type(),
            "section": self.get_section(),
            "is_game_related": self.get_is_game_related(),
            "is_mining": self.get_is_mining(),
        }

    def get_data_for_ai_minimal(self) -> dict:
        return self.get_data_for_ai()

    def get_id(self) -> int:
        return self.data["id"]

    def get_type(self) -> str | None:
        return self.data["type"]

    def get_section(self) -> str | None:
        return self.data["section"]

    def get_name(self) -> str | None:
        return self.data["name"]

    def get_is_game_related(self) -> bool | None:
        return bool(self.data["is_game_related"])

    def get_is_mining(self) -> bool | None:
        return bool(self.data["is_mining"])

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
