from datetime import datetime
try:
    from skills.uexcorp_beta.uexcorp.model.data_model import DataModel
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.model.data_model import DataModel

class RefineryMethod(DataModel):

    required_keys = ["id"]

    def __init__(
        self,
        id: int, # int(11)
        name: str | None = None, # varchar(255)
        code: str | None = None,  # varchar(255)
        rating_yield: int | None = None,  # int(1)
        rating_cost: int | None = None,  # int(1)
        rating_speed: int | None = None,  # int(1)
        date_added: int | None = None, # int(11)
        date_modified: int | None = None, # int(11)
        load: bool = False,
    ):
        super().__init__("refinery_method")
        self.data = {
            "id": id,
            "name": name,
            "code": code,
            "rating_yield": rating_yield,
            "rating_cost": rating_cost,
            "rating_speed": rating_speed,
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

    def get_name(self) -> str | None:
        return self.data["name"]

    def get_code(self) -> str | None:
        return self.data["code"]

    def get_rating_yield(self) -> int | None:
        return self.data["rating_yield"]

    def get_rating_cost(self) -> int | None:
        return self.data["rating_cost"]

    def get_rating_speed(self) -> int | None:
        return self.data["rating_speed"]

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