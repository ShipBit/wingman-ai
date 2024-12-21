from datetime import datetime

from skills.uexcorp_beta.uexcorp.data_access.terminal_data_access import TerminalDataAccess
from skills.uexcorp_beta.uexcorp.data_access.vehicle_purchase_price_data_access import VehiclePurchasePriceDataAccess
from skills.uexcorp_beta.uexcorp.data_access.vehicle_rental_price_data_access import VehicleRentalPriceDataAccess
from skills.uexcorp_beta.uexcorp.model.data_model import DataModel

class Vehicle(DataModel):

    required_keys = ["id"]

    def __init__(
            self,
            id: int, # int(11)
            id_company: int | None = None,  # int(11) // vehicle manufacturer
            id_parent: int | None = None,  # int(11) // parent ship series
            ids_vehicles_loaners: str | None = None,  # string(40) // vehicles loaned, comma separated
            name: str | None = None,  # string(255)
            name_full: str | None = None,  # string(255)
            scu: int | None = None,  # int(11)
            crew: str | None = None,  # string(10) // comma separated
            mass: int | None = None,  # int(11)
            width: int | None = None,  # int(11)
            height: int | None = None,  # int(11)
            length: int | None = None,  # int(11)
            fuel_quantum: int | None = None,  # int(11) // SCU
            fuel_hydrogen: int | None = None,  # int(11) // SCU
            container_sizes: str | None = None,  # string // SCU, comma separated
            is_addon: int | None = None,  # int(1) // e.g. RSI Galaxy Refinery Module
            is_boarding: int | None = None,  # int(1)
            is_bomber: int | None = None,  # int(1)
            is_cargo: int | None = None,  # int(1)
            is_carrier: int | None = None,  # int(1)
            is_civilian: int | None = None,  # int(1)
            is_concept: int | None = None,  # int(1)
            is_construction: int | None = None,  # int(1)
            is_datarunner: int | None = None,  # int(1)
            is_docking: int | None = None,  # int(1) // contains docking port
            is_emp: int | None = None,  # int(1)
            is_exploration: int | None = None,  # int(1)
            is_ground_vehicle: int | None = None,  # int(1)
            is_hangar: int | None = None,  # int(1) // contains hangar
            is_industrial: int | None = None,  # int(1)
            is_interdiction: int | None = None,  # int(1)
            is_loading_dock: int | None = None,  # int(1) // cargo can be loaded/unloaded via docking
            is_medical: int | None = None,  # int(1)
            is_military: int | None = None,  # int(1)
            is_mining: int | None = None,  # int(1)
            is_passenger: int | None = None,  # int(1)
            is_qed: int | None = None,  # int(1)
            is_racing: int | None = None,  # int(1)
            is_refinery: int | None = None,  # int(1)
            is_refuel: int | None = None,  # int(1)
            is_repair: int | None = None,  # int(1)
            is_research: int | None = None,  # int(1)
            is_salvage: int | None = None,  # int(1)
            is_scanning: int | None = None,  # int(1)
            is_science: int | None = None,  # int(1)
            is_showdown_winner: int | None = None,  # int(1)
            is_spaceship: int | None = None,  # int(1)
            is_starter: int | None = None,  # int(1)
            is_stealth: int | None = None,  # int(1)
            is_tractor_beam: int | None = None,  # int(1)
            url_store: str | None = None,  # string(255)
            url_brochure: str | None = None,  # string(255)
            url_hotsite: str | None = None,  # string(255)
            url_video: str | None = None,  # string(255)
            url_photos: list[str] | None = None,  # array(65535)
            pad_type: str | None = None,  # string(255) // XS, S, M, L, XL
            game_version: str | None = None,  # string(255) // version it was announced or updated
            date_added: int | None = None,  # int(11) // timestamp
            date_modified: int | None = None,  # int(11) // timestamp
            company_name: str | None = None,  # string(255) // manufacturer name
            load: bool = False,
    ):
        super().__init__("vehicle")
        self.data = {
            "id": id,
            "id_company": id_company,
            "id_parent": id_parent,
            "ids_vehicles_loaners": ids_vehicles_loaners,
            "name": name,
            "name_full": name_full,
            "scu": scu,
            "crew": crew,
            "mass": mass,
            "width": width,
            "height": height,
            "length": length,
            "fuel_quantum": fuel_quantum,
            "fuel_hydrogen": fuel_hydrogen,
            "container_sizes": container_sizes,
            "is_addon": is_addon,
            "is_boarding": is_boarding,
            "is_bomber": is_bomber,
            "is_cargo": is_cargo,
            "is_carrier": is_carrier,
            "is_civilian": is_civilian,
            "is_concept": is_concept,
            "is_construction": is_construction,
            "is_datarunner": is_datarunner,
            "is_docking": is_docking,
            "is_emp": is_emp,
            "is_exploration": is_exploration,
            "is_ground_vehicle": is_ground_vehicle,
            "is_hangar": is_hangar,
            "is_industrial": is_industrial,
            "is_interdiction": is_interdiction,
            "is_loading_dock": is_loading_dock,
            "is_medical": is_medical,
            "is_military": is_military,
            "is_mining": is_mining,
            "is_passenger": is_passenger,
            "is_qed": is_qed,
            "is_racing": is_racing,
            "is_refinery": is_refinery,
            "is_refuel": is_refuel,
            "is_repair": is_repair,
            "is_research": is_research,
            "is_salvage": is_salvage,
            "is_scanning": is_scanning,
            "is_science": is_science,
            "is_showdown_winner": is_showdown_winner,
            "is_spaceship": is_spaceship,
            "is_starter": is_starter,
            "is_stealth": is_stealth,
            "is_tractor_beam": is_tractor_beam,
            "url_store": url_store,
            "url_brochure": url_brochure,
            "url_hotsite": url_hotsite,
            "url_video": url_video,
            "url_photos": url_photos,
            "pad_type": pad_type,
            "game_version": game_version,
            "date_added": date_added,
            "date_modified": date_modified,
            "company_name": company_name,
            "last_import_run_id": None,
        }
        if load:
            if not self.data["id"]:
                raise Exception("ID is required to load data")
            self.load_by_value("id", self.data["id"])

    def get_data_for_ai(self) -> dict[str, any]:
        data = {
            "name_full": self.get_name_full(),
            "company_name": self.get_company_name(),
            "scu": self.get_scu() or "unknown",
            "crew": self.get_crew().replace(",", " - ") if self.get_crew else "unknown",
            "mass": self.get_mass() or "unknown",
            "width": self.get_width() or "unknown",
            "height": self.get_height() or "unknown",
            "length": self.get_length() or "unknown",
            "fuel_quantum": self.get_fuel_quantum() or "unknown",
            "fuel_hydrogen": self.get_fuel_hydrogen() or "unknown",
            "scu_container_compatibility": self.get_container_sizes() or "unknown",
            "needed_hangar_pad_size": self.get_pad_type(),
            "game_version": self.get_game_version(),
            "purchase_options": self.get_purchase_options(),
            "rental_options": self.get_rental_options(),
            "roles": [],
            "additional_information": [],
        }

        if self.get_is_spaceship():
            data["roles"].append("spaceship")
        if self.get_is_ground_vehicle():
            data["roles"].append("ground vehicle")
        if self.get_is_military():
            data["roles"].append("military")
        if self.get_is_civilian():
            data["roles"].append("civilian")
        if self.get_is_boarding():
            data["roles"].append("boarding vessel")
        if self.get_is_bomber():
            data["roles"].append("bomber")
        if self.get_is_cargo():
            data["roles"].append("cargo transporter")
        if self.get_is_carrier():
            data["roles"].append("vehicle carrier")
        if self.get_is_concept():
            data["additional_information"].append("currently in concept phase")
        if self.get_is_construction():
            data["roles"].append("construction")
        if self.get_is_datarunner():
            data["roles"].append("data runner")
        if self.get_is_docking():
            data["additional_information"].append("has docking port")
        if self.get_is_emp():
            data["additional_information"].append("has EMP")
        if self.get_is_exploration():
            data["roles"].append("exploration")
        # if self.get_is_hangar():
        #     data["roles"].append("hangar")
        if self.get_is_industrial():
            data["roles"].append("industrial")
        if self.get_is_interdiction():
            data["roles"].append("interdiction")
        if self.get_is_loading_dock():
            data["additional_information"].append("needs loading dock for loading/unloading")
        if self.get_is_medical():
            data["roles"].append("medical")
        if self.get_is_mining():
            data["roles"].append("mining")
        if self.get_is_passenger():
            data["roles"].append("passenger transport")
        if self.get_is_qed():
            data["additional_information"].append("has qed (quantum enforcement device)")
        if self.get_is_racing():
            data["roles"].append("racing")
        if self.get_is_refinery():
            data["roles"].append("refinery")
        if self.get_is_refuel():
            data["roles"].append("refuel")
        if self.get_is_repair():
            data["roles"].append("repair")
        if self.get_is_research():
            data["roles"].append("research")
        if self.get_is_salvage():
            data["roles"].append("salvage")
        if self.get_is_scanning():
            data["roles"].append("scanning")
        if self.get_is_science():
            data["roles"].append("science")
        if self.get_is_showdown_winner():
            data["additional_information"].append("showdown winner")
        if self.get_is_starter():
            data["roles"].append("starter")
        if self.get_is_stealth():
            data["roles"].append("stealth")
        if self.get_is_tractor_beam():
            data["additional_information"].append("has tractor beam")

        return data

    def get_purchase_options(self) -> list[dict[str, any]]:
        prices = VehiclePurchasePriceDataAccess().add_filter_by_id_vehicle(self.get_id()).load()
        price_data = []
        for price in prices:
            price_data.append(price.get_data_for_ai())

        return price_data

    def get_rental_options(self) -> list[dict[str, any]]:
        prices = VehicleRentalPriceDataAccess().add_filter_by_id_vehicle(self.get_id()).load()
        price_data = []
        for price in prices:
            price_data.append(price.get_data_for_ai())

        return price_data

    def get_id(self) -> int:
        return self.data["id"]

    def get_id_company(self) -> int | None:
        return self.data["id_company"]

    def get_id_parent(self) -> int | None:
        return self.data["id_parent"]

    def get_ids_vehicles_loaners(self) -> str | None:
        return self.data["ids_vehicles_loaners"]

    def get_name(self) -> str | None:
        return self.data["name"]

    def get_name_full(self) -> str | None:
        return self.data["name_full"]

    def get_scu(self) -> int | None:
        return self.data["scu"]

    def get_crew(self) -> str | None:
        return self.data["crew"]

    def get_mass(self) -> int | None:
        return self.data["mass"]

    def get_width(self) -> int | None:
        return self.data["width"]

    def get_height(self) -> int | None:
        return self.data["height"]

    def get_length(self) -> int | None:
        return self.data["length"]

    def get_fuel_quantum(self) -> int | None:
        return self.data["fuel_quantum"]

    def get_fuel_hydrogen(self) -> int | None:
        return self.data["fuel_hydrogen"]

    def get_container_sizes(self) -> str | None:
        return self.data["container_sizes"]

    def get_is_addon(self) -> bool | None:
        return bool(self.data["is_addon"])

    def get_is_boarding(self) -> bool | None:
        return bool(self.data["is_boarding"])

    def get_is_bomber(self) -> bool | None:
        return bool(self.data["is_bomber"])

    def get_is_cargo(self) -> bool | None:
        return bool(self.data["is_cargo"])

    def get_is_carrier(self) -> bool | None:
        return bool(self.data["is_carrier"])

    def get_is_civilian(self) -> bool | None:
        return bool(self.data["is_civilian"])

    def get_is_concept(self) -> bool | None:
        return bool(self.data["is_concept"])

    def get_is_construction(self) -> bool | None:
        return bool(self.data["is_construction"])

    def get_is_datarunner(self) -> bool | None:
        return bool(self.data["is_datarunner"])

    def get_is_docking(self) -> bool | None:
        return bool(self.data["is_docking"])

    def get_is_emp(self) -> bool | None:
        return bool(self.data["is_emp"])

    def get_is_exploration(self) -> bool | None:
        return bool(self.data["is_exploration"])

    def get_is_ground_vehicle(self) -> bool | None:
        return bool(self.data["is_ground_vehicle"])

    def get_is_hangar(self) -> bool | None:
        return bool(self.data["is_hangar"])

    def get_is_industrial(self) -> bool | None:
        return bool(self.data["is_industrial"])

    def get_is_interdiction(self) -> bool | None:
        return bool(self.data["is_interdiction"])

    def get_is_loading_dock(self) -> bool | None:
        return bool(self.data["is_loading_dock"])

    def get_is_medical(self) -> bool | None:
        return bool(self.data["is_medical"])

    def get_is_military(self) -> bool | None:
        return bool(self.data["is_military"])

    def get_is_mining(self) -> bool | None:
        return bool(self.data["is_mining"])

    def get_is_passenger(self) -> bool | None:
        return bool(self.data["is_passenger"])

    def get_is_qed(self) -> bool | None:
        return bool(self.data["is_qed"])

    def get_is_racing(self) -> bool | None:
        return bool(self.data["is_racing"])

    def get_is_refinery(self) -> bool | None:
        return bool(self.data["is_refinery"])

    def get_is_refuel(self) -> bool | None:
        return bool(self.data["is_refuel"])

    def get_is_repair(self) -> bool | None:
        return bool(self.data["is_repair"])

    def get_is_research(self) -> bool | None:
        return bool(self.data["is_research"])

    def get_is_salvage(self) -> bool | None:
        return bool(self.data["is_salvage"])

    def get_is_scanning(self) -> bool | None:
        return bool(self.data["is_scanning"])

    def get_is_science(self) -> bool | None:
        return bool(self.data["is_science"])

    def get_is_showdown_winner(self) -> bool | None:
        return bool(self.data["is_showdown_winner"])

    def get_is_spaceship(self) -> bool | None:
        return bool(self.data["is_spaceship"])

    def get_is_starter(self) -> bool | None:
        return bool(self.data["is_starter"])

    def get_is_stealth(self) -> bool | None:
        return bool(self.data["is_stealth"])

    def get_is_tractor_beam(self) -> bool | None:
        return bool(self.data["is_tractor_beam"])

    def get_url_store(self) -> str | None:
        return self.data["url_store"]

    def get_url_brochure(self) -> str | None:
        return self.data["url_brochure"]

    def get_url_hotsite(self) -> str | None:
        return self.data["url_hotsite"]

    def get_url_video(self) -> str | None:
        return self.data["url_video"]

    def get_url_photos(self) -> list[str] | None:
        return self.data["url_photos"]

    def get_pad_type(self) -> str | None:
        return self.data["pad_type"]

    def get_game_version(self) -> str | None:
        return self.data["game_version"]

    def get_date_added(self) -> int | None:
        return self.data["date_added"]

    def get_date_added_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_added"])

    def get_date_modified(self) -> int | None:
        return self.data["date_modified"]

    def get_date_modified_readable(self) -> datetime | None:
        return datetime.fromtimestamp(self.data["date_modified"])

    def get_company_name(self) -> str | None:
        return self.data["company_name"]

    def __str__(self):
        return str(self.get_name_full())
