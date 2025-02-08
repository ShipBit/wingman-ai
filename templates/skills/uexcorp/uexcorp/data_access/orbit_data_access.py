try:
    from skills.uexcorp.uexcorp.data_access.data_access import DataAccess
    from skills.uexcorp.uexcorp.model.orbit import Orbit
except ModuleNotFoundError:
    from uexcorp.uexcorp.data_access.data_access import DataAccess
    from uexcorp.uexcorp.model.orbit import Orbit


class OrbitDataAccess(DataAccess):
    def __init__(
            self,
    ):
        super().__init__(
            table="orbit",
            model=Orbit
        )
        self.fields = [
            "id",
            "id_star_system",
            "id_faction",
            "id_jurisdiction",
            "name",
            "name_origin",
            "code",
            "is_available",
            "is_available_live",
            "is_visible",
            "is_default",
            "is_lagrange",
            "date_added",
            "date_modified",
            "star_system_name",
            "faction_name",
            "jurisdiction_name",
        ]

    def load(self, **params) -> list[Orbit]:
        return super().load(**params)

    def load_by_property(self, property: str, value: any) -> Orbit | None:
        return super().load_by_property(property, value)

    def add_filter_by_id_star_system(self, id_star_system: int | list[int]) -> "OrbitDataAccess":
        self.filter.where("id_star_system", id_star_system)
        return self

    def add_filter_by_id_faction(self, id_faction: int | list[int]) -> "OrbitDataAccess":
        self.filter.where("id_faction", id_faction)
        return self

    def add_filter_by_id_jurisdiction(self, id_jurisdiction: int | list[int]) -> "OrbitDataAccess":
        self.filter.where("id_jurisdiction", id_jurisdiction)
        return self

    def add_filter_by_name(self, name: str | list[str]) -> "OrbitDataAccess":
        self.filter.where("name", name)
        return self

    def add_filter_by_name_origin(self, name_origin: str | list[str]) -> "OrbitDataAccess":
        self.filter.where("name_origin", name_origin)
        return self

    def add_filter_by_code(self, code: str | list[str]) -> "OrbitDataAccess":
        self.filter.where("code", code)
        return self

    def add_filter_by_is_available(self, is_available: bool) -> "OrbitDataAccess":
        self.filter.where("is_available", is_available)
        return self

    def add_filter_by_is_available_live(self, is_available_live: bool) -> "OrbitDataAccess":
        self.filter.where("is_available_live", is_available_live)
        return self

    def add_filter_by_is_visible(self, is_visible: bool) -> "OrbitDataAccess":
        self.filter.where("is_visible", is_visible)
        return self

    def add_filter_by_is_default(self, is_default: bool) -> "OrbitDataAccess":
        self.filter.where("is_default", is_default)
        return self

    def add_filter_by_is_lagrange(self, is_lagrange: bool) -> "OrbitDataAccess":
        self.filter.where("is_lagrange", is_lagrange)
        return self

    def add_filter_by_star_system_name(self, star_system_name: str | list[str]) -> "OrbitDataAccess":
        self.filter.where("star_system_name", star_system_name)
        return self

    def add_filter_by_faction_name(self, faction_name: str | list[str]) -> "OrbitDataAccess":
        self.filter.where("faction_name", faction_name)
        return self

    def add_filter_by_jurisdiction_name(self, jurisdiction_name: str | list[str]) -> "OrbitDataAccess":
        self.filter.where("jurisdiction_name", jurisdiction_name)
        return self
