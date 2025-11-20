try:
    from skills.uexcorp.uexcorp.database.filter import Filter
    from skills.uexcorp.uexcorp.data_access.data_access import DataAccess
    from skills.uexcorp.uexcorp.model.planet import Planet
except ModuleNotFoundError:
    from uexcorp.uexcorp.database.filter import Filter
    from uexcorp.uexcorp.data_access.data_access import DataAccess
    from uexcorp.uexcorp.model.planet import Planet


class PlanetDataAccess(DataAccess):
    def __init__(
            self,
    ):
        super().__init__(
            table="planet",
            model=Planet
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

    def load(self, **params) -> list[Planet]:
        return super().load(**params)

    def load_by_property(self, property: str, value: any) -> Planet | None:
        return super().load_by_property(property, value)

    def add_filter_by_location_name_whitelist(self, location_names: str | list[str]) -> "PlanetDataAccess":
        grouped_filter = Filter()
        grouped_filter.where("star_system_name", location_names, is_or=True)
        grouped_filter.where("name", location_names, is_or=True)
        self.filter.apply_filter(grouped_filter)
        return self

    def add_filter_by_id_star_system(self, id_star_system: int | list[int]) -> "PlanetDataAccess":
        self.filter.where("id_star_system", id_star_system)
        return self

    def add_filter_by_id_faction(self, id_faction: int | list[int]) -> "PlanetDataAccess":
        self.filter.where("id_faction", id_faction)
        return self

    def add_filter_by_id_jurisdiction(self, id_jurisdiction: int | list[int]) -> "PlanetDataAccess":
        self.filter.where("id_jurisdiction", id_jurisdiction)
        return self

    def add_filter_by_name(self, name: str | list[str]) -> "PlanetDataAccess":
        self.filter.where("name", name)
        return self

    def add_filter_by_name_origin(self, name_origin: str | list[str]) -> "PlanetDataAccess":
        self.filter.where("name_origin", name_origin)
        return self

    def add_filter_by_code(self, code: str | list[str]) -> "PlanetDataAccess":
        self.filter.where("code", code)
        return self

    def add_filter_by_is_available(self, is_available: bool) -> "PlanetDataAccess":
        self.filter.where("is_available", is_available)
        return self

    def add_filter_by_is_available_live(self, is_available_live: bool) -> "PlanetDataAccess":
        self.filter.where("is_available_live", is_available_live)
        return self

    def add_filter_by_is_visible(self, is_visible: bool) -> "PlanetDataAccess":
        self.filter.where("is_visible", is_visible)
        return self

    def add_filter_by_is_default(self, is_default: bool) -> "PlanetDataAccess":
        self.filter.where("is_default", is_default)
        return self

    def add_filter_by_is_lagrange(self, is_lagrange: bool) -> "PlanetDataAccess":
        self.filter.where("is_lagrange", is_lagrange)
        return self

    def add_filter_by_star_system_name(self, star_system_name: str | list[str]) -> "PlanetDataAccess":
        self.filter.where("star_system_name", star_system_name)
        return self

    def add_filter_by_faction_name(self, faction_name: str | list[str]) -> "PlanetDataAccess":
        self.filter.where("faction_name", faction_name)
        return self

    def add_filter_by_jurisdiction_name(self, jurisdiction_name: str | list[str]) -> "PlanetDataAccess":
        self.filter.where("jurisdiction_name", jurisdiction_name)
        return self
