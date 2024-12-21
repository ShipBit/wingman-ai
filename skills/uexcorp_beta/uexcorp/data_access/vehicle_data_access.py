from skills.uexcorp_beta.uexcorp.data_access.data_access import DataAccess
from skills.uexcorp_beta.uexcorp.model.data_model import DataModel
from skills.uexcorp_beta.uexcorp.model.vehicle import Vehicle


class VehicleDataAccess(DataAccess):
    def __init__(
            self,
    ):
        super().__init__(
            table="vehicle",
            model=Vehicle
        )
        self.fields = [
            "id",
            "id_company",
            "id_parent",
            "ids_vehicles_loaners",
            "name",
            "name_full",
            "scu",
            "crew",
            "mass",
            "width",
            "height",
            "length",
            "fuel_quantum",
            "fuel_hydrogen",
            "container_sizes",
            "is_addon",
            "is_boarding",
            "is_bomber",
            "is_cargo",
            "is_carrier",
            "is_civilian",
            "is_concept",
            "is_construction",
            "is_datarunner",
            "is_docking",
            "is_emp",
            "is_exploration",
            "is_ground_vehicle",
            "is_hangar",
            "is_industrial",
            "is_interdiction",
            "is_loading_dock",
            "is_medical",
            "is_military",
            "is_mining",
            "is_passenger",
            "is_qed",
            "is_racing",
            "is_refinery",
            "is_refuel",
            "is_repair",
            "is_research",
            "is_salvage",
            "is_scanning",
            "is_science",
            "is_showdown_winner",
            "is_spaceship",
            "is_starter",
            "is_stealth",
            "is_tractor_beam",
            "url_store",
            "url_brochure",
            "url_hotsite",
            "url_video",
            "url_photos",
            "pad_type",
            "game_version",
            "date_added",
            "date_modified",
            "company_name"
        ]

    def load(self) -> list[Vehicle]:
        return super().load()

    def load_by_property(self, property: str, value: any) -> Vehicle | None:
        return super().load_by_property(property, value)

    def add_filter_by_is_spaceship(self, is_spaceship: bool) -> "VehicleDataAccess":
        self.filter.where("is_spaceship", is_spaceship)
        return self

    def add_filter_by_name_full(self, name_full: str | list[str]) -> "VehicleDataAccess":
        self.filter.where("name_full", name_full)
        return self
