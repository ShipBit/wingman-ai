from skills.uexcorp_beta.uexcorp.data_access.data_access import DataAccess
from skills.uexcorp_beta.uexcorp.model.star_system import StarSystem


class StarSystemDataAccess(DataAccess):
    def __init__(
            self,
    ):
        super().__init__(
            table="star_system",
            model=StarSystem
        )
        self.fields = [
            "id",
            "id_faction",
            "id_jurisdiction",
            "name",
            "code",
            "is_available",
            "is_available_live",
            "is_visible",
            "is_default",
            "wiki",
            "date_added",
            "date_modified",
            "faction_name",
            "jurisdiction_name",
        ]

    def load(self) -> list[StarSystem]:
        return super().load()

    def load_by_property(self, property: str, value: any) -> StarSystem | None:
        return super().load_by_property(property, value)

    def add_filter_by_id_faction(self, id_faction: int) -> "StarSystemDataAccess":
        self.filter.where("id_faction", id_faction)
        return self

    def add_filter_by_id_jurisdiction(self, id_jurisdiction: int) -> "StarSystemDataAccess":
        self.filter.where("id_jurisdiction", id_jurisdiction)
        return self

    def add_filter_by_name(self, name: str) -> "StarSystemDataAccess":
        self.filter.where("name", name)
        return self

    def add_filter_by_code(self, code: str) -> "StarSystemDataAccess":
        self.filter.where("code", code)
        return self

    def add_filter_by_is_available(self, is_available: bool) -> "StarSystemDataAccess":
        self.filter.where("is_available", is_available)
        return self

    def add_filter_by_is_available_live(self, is_available_live: bool) -> "StarSystemDataAccess":
        self.filter.where("is_available_live", is_available_live)
        return self

    def add_filter_by_is_visible(self, is_visible: bool) -> "StarSystemDataAccess":
        self.filter.where("is_visible", is_visible)
        return self

    def add_filter_by_is_default(self, is_default: bool) -> "StarSystemDataAccess":
        self.filter.where("is_default", is_default)
        return self
