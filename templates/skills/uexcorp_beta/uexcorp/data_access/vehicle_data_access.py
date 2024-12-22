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

    def load(self, **params) -> list[Vehicle]:
        return super().load(**params)

    def load_by_property(self, property: str, value: any) -> Vehicle | None:
        return super().load_by_property(property, value)

    def add_filter_by_role_strings(self, role_strings: str | list[str]) -> "VehicleDataAccess":
        if isinstance(role_strings, str):
            role_strings = [role_strings]

        roles = Vehicle.VEHICLE_ROLES # [role_str: is_role]
        for role_str, attribute in roles.items():
            if role_str in role_strings:
                self.filter.where(attribute, True)
        return self

    def add_filter_by_id_company(self, id_company: int | list[int], **kwargs) -> "VehicleDataAccess":
        self.filter.where("id_company", id_company, **kwargs)
        return self

    def add_filter_by_id_parent(self, id_parent: int | list[int], **kwargs) -> "VehicleDataAccess":
        self.filter.where("id_parent", id_parent, **kwargs)
        return self

    def add_filter_by_ids_vehicles_loaners(self, ids_vehicles_loaners: int | list[int], **kwargs) -> "VehicleDataAccess":
        self.filter.where("ids_vehicles_loaners", ids_vehicles_loaners, **kwargs)
        return self

    def add_filter_by_name(self, name: str | list[str], **kwargs) -> "VehicleDataAccess":
        self.filter.where("name", name, **kwargs)
        return self

    def add_filter_by_name_full(self, name_full: str | list[str], **kwargs) -> "VehicleDataAccess":
        self.filter.where("name_full", name_full, **kwargs)
        return self

    def add_filter_by_scu(self, scu: int | list[int], **kwargs) -> "VehicleDataAccess":
        self.filter.where("scu", scu, **kwargs)
        return self

    def add_filter_by_crew(self, crew: int | list[int], **kwargs) -> "VehicleDataAccess":
        self.filter.where("crew", crew, **kwargs)
        return self

    def add_filter_by_mass(self, mass: int | list[int], **kwargs) -> "VehicleDataAccess":
        self.filter.where("mass", mass, **kwargs)
        return self

    def add_filter_by_width(self, width: int | list[int], **kwargs) -> "VehicleDataAccess":
        self.filter.where("width", width, **kwargs)
        return self

    def add_filter_by_height(self, height: int | list[int], **kwargs) -> "VehicleDataAccess":
        self.filter.where("height", height, **kwargs)
        return self

    def add_filter_by_length(self, length: int | list[int], **kwargs) -> "VehicleDataAccess":
        self.filter.where("length", length, **kwargs)
        return self

    def add_filter_by_fuel_quantum(self, fuel_quantum: int | list[int], **kwargs) -> "VehicleDataAccess":
        self.filter.where("fuel_quantum", fuel_quantum, **kwargs)
        return self

    def add_filter_by_fuel_hydrogen(self, fuel_hydrogen: int | list[int], **kwargs) -> "VehicleDataAccess":
        self.filter.where("fuel_hydrogen", fuel_hydrogen, **kwargs)
        return self

    def add_filter_by_container_sizes(self, container_sizes: int | list[int], **kwargs) -> "VehicleDataAccess":
        self.filter.where("container_sizes", container_sizes, **kwargs)
        return self

    def add_filter_by_is_addon(self, is_addon: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_addon", is_addon, **kwargs)
        return self

    def add_filter_by_is_boarding(self, is_boarding: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_boarding", is_boarding, **kwargs)
        return self

    def add_filter_by_is_bomber(self, is_bomber: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_bomber", is_bomber, **kwargs)
        return self

    def add_filter_by_is_cargo(self, is_cargo: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_cargo", is_cargo, **kwargs)
        return self

    def add_filter_by_is_carrier(self, is_carrier: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_carrier", is_carrier, **kwargs)
        return self

    def add_filter_by_is_civilian(self, is_civilian: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_civilian", is_civilian, **kwargs)
        return self

    def add_filter_by_is_concept(self, is_concept: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_concept", is_concept, **kwargs)
        return self

    def add_filter_by_is_construction(self, is_construction: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_construction", is_construction, **kwargs)
        return self

    def add_filter_by_is_datarunner(self, is_datarunner: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_datarunner", is_datarunner, **kwargs)
        return self

    def add_filter_by_is_docking(self, is_docking: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_docking", is_docking, **kwargs)
        return self

    def add_filter_by_is_emp(self, is_emp: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_emp", is_emp, **kwargs)
        return self

    def add_filter_by_is_exploration(self, is_exploration: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_exploration", is_exploration, **kwargs)
        return self

    def add_filter_by_is_ground_vehicle(self, is_ground_vehicle: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_ground_vehicle", is_ground_vehicle, **kwargs)
        return self

    def add_filter_by_is_hangar(self, is_hangar: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_hangar", is_hangar, **kwargs)
        return self

    def add_filter_by_is_industrial(self, is_industrial: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_industrial", is_industrial, **kwargs)
        return self

    def add_filter_by_is_interdiction(self, is_interdiction: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_interdiction", is_interdiction, **kwargs)
        return self

    def add_filter_by_is_loading_dock(self, is_loading_dock: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_loading_dock", is_loading_dock, **kwargs)
        return self

    def add_filter_by_is_medical(self, is_medical: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_medical", is_medical, **kwargs)
        return self

    def add_filter_by_is_military(self, is_military: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_military", is_military, **kwargs)
        return self

    def add_filter_by_is_mining(self, is_mining: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_mining", is_mining, **kwargs)
        return self

    def add_filter_by_is_passenger(self, is_passenger: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_passenger", is_passenger, **kwargs)
        return self

    def add_filter_by_is_qed(self, is_qed: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_qed", is_qed, **kwargs)
        return self

    def add_filter_by_is_racing(self, is_racing: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_racing", is_racing, **kwargs)
        return self

    def add_filter_by_is_refinery(self, is_refinery: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_refinery", is_refinery, **kwargs)
        return self

    def add_filter_by_is_refuel(self, is_refuel: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_refuel", is_refuel, **kwargs)
        return self

    def add_filter_by_is_repair(self, is_repair: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_repair", is_repair, **kwargs)
        return self

    def add_filter_by_is_research(self, is_research: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_research", is_research, **kwargs)
        return self

    def add_filter_by_is_salvage(self, is_salvage: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_salvage", is_salvage, **kwargs)
        return self

    def add_filter_by_is_scanning(self, is_scanning: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_scanning", is_scanning, **kwargs)
        return self

    def add_filter_by_is_science(self, is_science: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_science", is_science, **kwargs)
        return self

    def add_filter_by_is_showdown_winner(self, is_showdown_winner: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_showdown_winner", is_showdown_winner, **kwargs)
        return self

    def add_filter_by_is_spaceship(self, is_spaceship: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_spaceship", is_spaceship, **kwargs)
        return self

    def add_filter_by_is_starter(self, is_starter: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_starter", is_starter, **kwargs)
        return self

    def add_filter_by_is_stealth(self, is_stealth: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_stealth", is_stealth, **kwargs)
        return self

    def add_filter_by_is_tractor_beam(self, is_tractor_beam: bool, **kwargs) -> "VehicleDataAccess":
        self.filter.where("is_tractor_beam", is_tractor_beam, **kwargs)
        return self

    def add_filter_by_url_store(self, url_store: str | list[str], **kwargs) -> "VehicleDataAccess":
        self.filter.where("url_store", url_store, **kwargs)
        return self

    def add_filter_by_url_brochure(self, url_brochure: str | list[str], **kwargs) -> "VehicleDataAccess":
        self.filter.where("url_brochure", url_brochure, **kwargs)
        return self

    def add_filter_by_url_hotsite(self, url_hotsite: str | list[str], **kwargs) -> "VehicleDataAccess":
        self.filter.where("url_hotsite", url_hotsite, **kwargs)
        return self

    def add_filter_by_url_video(self, url_video: str | list[str], **kwargs) -> "VehicleDataAccess":
        self.filter.where("url_video", url_video, **kwargs)
        return self

    def add_filter_by_url_photos(self, url_photos: str | list[str], **kwargs) -> "VehicleDataAccess":
        self.filter.where("url_photos", url_photos, **kwargs)
        return self

    def add_filter_by_pad_type(self, pad_type: str | list[str], **kwargs) -> "VehicleDataAccess":
        self.filter.where("pad_type", pad_type, **kwargs)
        return self

    def add_filter_by_game_version(self, game_version: str | list[str], **kwargs) -> "VehicleDataAccess":
        self.filter.where("game_version", game_version, **kwargs)
        return self

    def add_filter_by_date_added(self, date_added: int | list[int], **kwargs) -> "VehicleDataAccess":
        self.filter.where("date_added", date_added, **kwargs)
        return self

    def add_filter_by_date_modified(self, date_modified: int | list[int], **kwargs) -> "VehicleDataAccess":
        self.filter.where("date_modified", date_modified, **kwargs)
        return self

    def add_filter_by_company_name(self, company_name: str | list[str], **kwargs) -> "VehicleDataAccess":
        self.filter.where("company_name", company_name, **kwargs)
        return self
