from datetime import datetime
try:
    from skills.uexcorp_beta.uexcorp.model.data_model import DataModel
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.model.data_model import DataModel

class Faction(DataModel):

    required_keys = ["id"]

    def __init__(
            self,
            id: int, # int(11)
            ids_star_systems: str | None = None, # comma separated
            ids_factions_friendly: str | None = None, # comma separated
            ids_factions_hostile: str | None = None, # comma separated
            name: str | None = None, # varchar(255)
            wiki: str | None = None, # varchar(255)
            is_piracy: int | None = None, # tinyint(1)
            is_bounty_hunting: int | None = None, # tinyint(1)
            date_added: int | None = None, # int(11)
            date_modified: int | None = None, # int(11)
            load: bool = False,
    ):
        super().__init__("faction")
        self.data = {
            "id": id,
            "ids_star_systems": ids_star_systems,
            "ids_factions_friendly": ids_factions_friendly,
            "ids_factions_hostile": ids_factions_hostile,
            "name": name,
            "wiki": wiki,
            "is_piracy": is_piracy,
            "is_bounty_hunting": is_bounty_hunting,
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
            from skills.uexcorp_beta.uexcorp.model.star_system import StarSystem
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.model.star_system import StarSystem

        information = {
            "name": self.data["name"],
            "star_systems": [],
            "is_piracy": self.data["is_piracy"],
            "is_bounty_hunting": self.data["is_bounty_hunting"],
            "friendly_factions": [],
            "hostile_factions": [],
        }

        if self.get_ids_star_systems():
            for id_star_system in self.get_ids_star_systems().split(","):
                star_system = StarSystem(int(id_star_system), load=True)
                information["star_systems"].append(star_system.get_data_for_ai_minimal())

        if self.get_ids_factions_friendly():
            for id_faction in self.get_ids_factions_friendly().split(","):
                faction = Faction(int(id_faction), load=True)
                information["friendly_factions"].append(faction.get_data_for_ai_minimal())

        if self.get_ids_factions_hostile():
            for id_faction in self.get_ids_factions_hostile().split(","):
                faction = Faction(int(id_faction), load=True)
                information["hostile_factions"].append(faction.get_data_for_ai_minimal())

        return information

    def get_data_for_ai_minimal(self) -> dict:
        try:
            from skills.uexcorp_beta.uexcorp.model.star_system import StarSystem
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.model.star_system import StarSystem

        information = {
            "name": self.data["name"],
            "star_systems": [],
            "is_piracy": self.data["is_piracy"],
            "is_bounty_hunting": self.data["is_bounty_hunting"],
            "friendly_factions": [],
            "hostile_factions": [],
        }

        if self.get_ids_star_systems():
            for id_star_system in self.get_ids_star_systems().split(","):
                star_system = StarSystem(int(id_star_system), load=True)
                if star_system.get_is_available():
                    information["star_systems"].append(str(star_system))

        if self.get_ids_factions_friendly():
            for id_faction in self.get_ids_factions_friendly().split(","):
                faction = Faction(int(id_faction), load=True)
                information["friendly_factions"].append(str(faction))

        if self.get_ids_factions_hostile():
            for id_faction in self.get_ids_factions_hostile().split(","):
                faction = Faction(int(id_faction), load=True)
                information["hostile_factions"].append(str(faction))

        return information

    def get_id(self) -> int:
        return self.data["id"]

    def get_ids_star_systems(self) -> str | None:
        return self.data["ids_star_systems"]

    def get_ids_factions_friendly(self) -> str | None:
        return self.data["ids_factions_friendly"]

    def get_ids_factions_hostile(self) -> str | None:
        return self.data["ids_factions_hostile"]

    def get_name(self) -> str | None:
        return self.data["name"]

    def get_wiki(self) -> str | None:
        return self.data["wiki"]

    def get_is_piracy(self) -> bool | None:
        return bool(self.data["is_piracy"])

    def get_is_bounty_hunting(self) -> bool | None:
        return bool(self.data["is_bounty_hunting"])

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