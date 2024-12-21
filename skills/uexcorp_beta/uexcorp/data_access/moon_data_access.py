
from skills.uexcorp_beta.uexcorp.data_access.data_access import DataAccess
from skills.uexcorp_beta.uexcorp.model.moon import Moon


class MoonDataAccess(DataAccess):
    def __init__(
            self,
    ):
        super().__init__(
            table="moon",
            model=Moon
        )
        self.fields = [
            "id",
            "id_star_system",
            "id_planet",
            "id_orbit",
            "id_faction",
            "id_jurisdiction",
            "name",
            "name_origin",
            "code",
            "is_available",
            "is_available_live",
            "is_visible",
            "is_default",
            "date_added",
            "date_modified",
            "star_system_name",
            "planet_name",
            "orbit_name",
            "faction_name",
            "jurisdiction_name",
        ]

    def load(self) -> list[Moon]:
        return super().load()

    def load_by_property(self, property: str, value: any) -> Moon | None:
        return super().load_by_property(property, value)

    def add_filter_by_id_star_system(self, id_star_system: int) -> "MoonDataAccess":
        self.filter.where("id_star_system", id_star_system)
        return self
    
    def add_filter_by_id_planet(self, id_planet: int) -> "MoonDataAccess":
        self.filter.where("id_planet", id_planet)
        return self
    
    def add_filter_by_id_orbit(self, id_orbit: int) -> "MoonDataAccess":
        self.filter.where("id_orbit", id_orbit)
        return self

    def add_filter_by_id_faction(self, id_faction: int) -> "MoonDataAccess":
        self.filter.where("id_faction", id_faction)
        return self

    def add_filter_by_id_jurisdiction(self, id_jurisdiction: int) -> "MoonDataAccess":
        self.filter.where("id_jurisdiction", id_jurisdiction)
        return self

    def add_filter_by_name(self, name: str) -> "MoonDataAccess":
        self.filter.where("name", name)
        return self

    def add_filter_by_name_origin(self, name_origin: str) -> "MoonDataAccess":
        self.filter.where("name_origin", name_origin)
        return self

    def add_filter_by_code(self, code: str) -> "MoonDataAccess":
        self.filter.where("code", code)
        return self

    def add_filter_by_is_available(self, is_available: bool) -> "MoonDataAccess":
        self.filter.where("is_available", is_available)
        return self

    def add_filter_by_is_available_live(self, is_available_live: bool) -> "MoonDataAccess":
        self.filter.where("is_available_live", is_available_live)
        return self

    def add_filter_by_is_visible(self, is_visible: bool) -> "MoonDataAccess":
        self.filter.where("is_visible", is_visible)
        return self

    def add_filter_by_is_default(self, is_default: bool) -> "MoonDataAccess":
        self.filter.where("is_default", is_default)
        return self

    def add_filter_by_is_lagrange(self, is_lagrange: bool) -> "MoonDataAccess":
        self.filter.where("is_lagrange", is_lagrange)
        return self

    def add_filter_by_star_system_name(self, star_system_name: str) -> "MoonDataAccess":
        self.filter.where("star_system_name", star_system_name)
        return self

    def add_filter_by_planet_name(self, planet_name: str) -> "MoonDataAccess":
        self.filter.where("planet_name", planet_name)
        return self

    def add_filter_by_orbit_name(self, orbit_name: str) -> "MoonDataAccess":
        self.filter.where("orbit_name", orbit_name)
        return self

    def add_filter_by_faction_name(self, faction_name: str) -> "MoonDataAccess":
        self.filter.where("faction_name", faction_name)
        return self

    def add_filter_by_jurisdiction_name(self, jurisdiction_name: str) -> "MoonDataAccess":
        self.filter.where("jurisdiction_name", jurisdiction_name)
        return self
