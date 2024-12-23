try:
    from skills.uexcorp_beta.uexcorp.model.data_model import DataModel
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.model.data_model import DataModel

class GameVersion(DataModel):

    required_keys = []

    def __init__(
            self,
            live: str | None = None, # varchar(255)
            ptu: str | None = None, # varchar(255)
            load: bool = False,
    ):
        super().__init__("game_version")
        self.data = {
            "id": 1,
            "live": live,
            "ptu": ptu,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["id"]:
                raise Exception("ID is required to load data")
            self.load_by_value("id", self.data["id"])

    def get_id(self) -> int:
        return self.data["id"]

    def get_live(self) -> str | None:
        return self.data["live"]

    def get_ptu(self) -> str | None:
        return self.data["ptu"]

    def __str__(self):
        return str(self.data["name"])
