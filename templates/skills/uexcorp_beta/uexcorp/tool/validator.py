import inspect
try:
    from skills.uexcorp_beta.uexcorp.data_access.city_data_access import CityDataAccess
    from skills.uexcorp_beta.uexcorp.data_access.moon_data_access import MoonDataAccess
    from skills.uexcorp_beta.uexcorp.data_access.orbit_data_access import OrbitDataAccess
    from skills.uexcorp_beta.uexcorp.data_access.outpost_data_access import OutpostDataAccess
    from skills.uexcorp_beta.uexcorp.data_access.planet_data_access import PlanetDataAccess
    from skills.uexcorp_beta.uexcorp.data_access.poi_data_access import PoiDataAccess
    from skills.uexcorp_beta.uexcorp.data_access.space_station_data_access import SpaceStationDataAccess
    from skills.uexcorp_beta.uexcorp.data_access.star_system_data_access import StarSystemDataAccess
    from skills.uexcorp_beta.uexcorp.data_access.terminal_data_access import TerminalDataAccess
    from skills.uexcorp_beta.uexcorp.data_access.vehicle_data_access import VehicleDataAccess
    from skills.uexcorp_beta.uexcorp.data_access.commodity_data_access import CommodityDataAccess
    from skills.uexcorp_beta.uexcorp.data_access.company_data_access import CompanyDataAccess
    from skills.uexcorp_beta.uexcorp.data_access.category_data_access import CategoryDataAccess
    from skills.uexcorp_beta.uexcorp.data_access.item_data_acceess import ItemDataAccess
    from skills.uexcorp_beta.uexcorp.helper import Helper
except ModuleNotFoundError:
    from uexcorp_beta.uexcorp.data_access.city_data_access import CityDataAccess
    from uexcorp_beta.uexcorp.data_access.moon_data_access import MoonDataAccess
    from uexcorp_beta.uexcorp.data_access.orbit_data_access import OrbitDataAccess
    from uexcorp_beta.uexcorp.data_access.outpost_data_access import OutpostDataAccess
    from uexcorp_beta.uexcorp.data_access.planet_data_access import PlanetDataAccess
    from uexcorp_beta.uexcorp.data_access.poi_data_access import PoiDataAccess
    from uexcorp_beta.uexcorp.data_access.space_station_data_access import SpaceStationDataAccess
    from uexcorp_beta.uexcorp.data_access.star_system_data_access import StarSystemDataAccess
    from uexcorp_beta.uexcorp.data_access.terminal_data_access import TerminalDataAccess
    from uexcorp_beta.uexcorp.data_access.vehicle_data_access import VehicleDataAccess
    from uexcorp_beta.uexcorp.data_access.commodity_data_access import CommodityDataAccess
    from uexcorp_beta.uexcorp.data_access.company_data_access import CompanyDataAccess
    from uexcorp_beta.uexcorp.data_access.category_data_access import CategoryDataAccess
    from uexcorp_beta.uexcorp.data_access.item_data_acceess import ItemDataAccess
    from uexcorp_beta.uexcorp.helper import Helper

class Validator:

    VALIDATE_NUMBER = "number"
    VALIDATE_BOOL = "bool"
    VALIDATE_SHIP = "ship"
    VALIDATE_VEHICLE = "vehicle"
    VALIDATE_VEHICLE_ROLE = "vehicle_role"
    VALIDATE_STAR_SYSTEM = "star_system"
    VALIDATE_COMMODITY = "commodity"
    VALIDATE_LOCATION = "location"
    VALIDATE_COMPANY = "company"
    VALIDATE_ENUM = "enum"
    VALIDATE_CATEGORY = "category"
    VALIDATE_ITEM = "item"

    def __init__(
        self,
        logic: str,
        multiple: bool = False,
        config: dict[str, any] | None = None,
    ):
        if logic not in [
            self.VALIDATE_NUMBER,
            self.VALIDATE_BOOL,
            self.VALIDATE_SHIP,
            self.VALIDATE_VEHICLE,
            self.VALIDATE_VEHICLE_ROLE,
            self.VALIDATE_STAR_SYSTEM,
            self.VALIDATE_COMMODITY,
            self.VALIDATE_LOCATION,
            self.VALIDATE_COMPANY,
            self.VALIDATE_ENUM,
            self.VALIDATE_CATEGORY,
            self.VALIDATE_ITEM,
        ]:
            raise ValueError("Invalid validation logic")
        self.__method_validate: callable = getattr(self, f"_Validator__validate_{logic}")
        self.__method_definition: callable = getattr(self, f"_Validator__definition_{logic}")
        self.__multiple: bool = multiple
        self.__config: dict[str, any] = config if config else {}
        self.__helper: Helper = Helper.get_instance()

    async def validate(self, values: any) -> any:
        validated_values = []

        if self.__multiple:
            if not isinstance(values, list):
                return None
        else:
            if isinstance(values, list):
                return None
            values = [values]

        for value in values:
            if inspect.iscoroutinefunction(self.__method_validate):
                validated = await self.__method_validate(value, **self.__config)
            else:
                validated = self.__method_validate(value, **self.__config)

            if validated is None:
                return None

            validated_values.append(validated)

        if self.__multiple:
            return validated_values
        else:
            return validated_values[0]

    def get_llm_definition(self) -> dict[str, any]:
        definition = self.__method_definition(**self.__config)
        if self.__multiple:
            definition = {
                "type": "array",
                "items": definition,
            }

        return definition

    def __validate_number(self, number: str | int, min: int | None = None, max: int | None = None) -> int | None:
        if not isinstance(number, int):
            if number.isdigit():
                number = int(number)
            else:
                return None

        if min and number < min:
            return None

        if max and number > max:
            return None

        return number

    def __definition_number(self, **kwargs) -> dict[str, any]:
        return {"type": "number"}

    def __validate_bool(self, boolean: str|bool) -> bool | None:
        if isinstance(boolean, bool):
            return boolean

        if boolean.lower() == "true" or "1":
            return True

        elif boolean.lower() == "false" or "0":
            return False

        return None

    def __definition_bool(self, **kwargs) -> dict[str, any]:
        return {"type": "boolean"}

    async def __validate_ship(self, name: str) -> str | None:
        ships = VehicleDataAccess().add_filter_by_is_spaceship(True).load()
        ship_names = []
        for ship in ships:
            ship_names.append(str(ship))

        closest_match = await self.__helper.get_llm().find_closest_match(name, ship_names)
        if closest_match:
            return closest_match

        return None

    def __definition_ship(self, **kwargs) -> dict[str, any]:
        return {"type": "string"}

    async def __validate_vehicle(self, name: str) -> str | None:
        vehicles = VehicleDataAccess().load()
        vehicle_names = []
        for vehicle in vehicles:
            vehicle_names.append(str(vehicle))

        closest_match = await self.__helper.get_llm().find_closest_match(name, vehicle_names)
        if closest_match:
            return closest_match

        return None

    def __definition_vehicle(self, **kwargs) -> dict[str, any]:
        return {"type": "string"}

    async def __validate_vehicle_role(self, name: str) -> str | None:
        try:
            from skills.uexcorp_beta.uexcorp.model.vehicle import Vehicle
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.model.vehicle import Vehicle

        closest_match = await self.__helper.get_llm().find_closest_match(name, list(Vehicle.VEHICLE_ROLES.keys()))
        if closest_match:
            return closest_match

        return None

    def __definition_vehicle_role(self, **kwargs) -> dict[str, any]:
        try:
            from skills.uexcorp_beta.uexcorp.model.vehicle import Vehicle
        except ModuleNotFoundError:
            from uexcorp_beta.uexcorp.model.vehicle import Vehicle

        return {"type": "string", "enum": list(Vehicle.VEHICLE_ROLES.keys())}

    async def __validate_star_system(self, name: str, available: bool = False) -> str | None:
        star_system_data_access = StarSystemDataAccess()
        if available:
            star_system_data_access = star_system_data_access.add_filter_by_is_available_live(True)

        star_systems = star_system_data_access.load()
        star_system_names = []
        for star_system in star_systems:
            star_system_names.append(str(star_system))

        closest_match = await self.__helper.get_llm().find_closest_match(name, star_system_names)
        if closest_match:
            return closest_match

        return None

    def __definition_star_system(self, available: bool = False) -> dict[str, any]:
        if not available:
            return {"type": "string"}

        star_systems = StarSystemDataAccess().add_filter_by_is_available_live(True).load()
        star_system_names = [str(star_system) for star_system in star_systems]
        return {"type": "string", "enum": star_system_names}

    async def __validate_commodity(self, name: str, for_trading: bool = False) -> str | None:
        commodity_data_access = CommodityDataAccess()
        if for_trading:
            commodity_data_access = commodity_data_access.add_filter_has_sell_price().add_filter_has_buy_price()
        commodities = commodity_data_access.load()
        commodity_names = []
        for commodity in commodities:
            commodity_names.append(str(commodity))

        closest_match = await self.__helper.get_llm().find_closest_match(name, commodity_names)
        if closest_match:
            return closest_match

        return None

    def __definition_commodity(self, **kwargs) -> dict[str, any]:
        return {"type": "string"}

    async def __validate_location(self, name: str, for_trading: bool = False) -> str | None:
        name_collection = []

        star_systems = StarSystemDataAccess().add_filter_by_is_available(True).load() # TODO change to "is_available_live" later
        for star_system in star_systems:
            name_collection.append(str(star_system))

            planets = PlanetDataAccess().add_filter_by_id_star_system(star_system.get_id()).add_filter_by_is_available_live(True).load()
            for planet in planets:
                name_collection.append(str(planet))

            moons = MoonDataAccess().add_filter_by_id_star_system(star_system.get_id()).add_filter_by_is_available_live(True).load()
            for moon in moons:
                name_collection.append(str(moon))

            space_station_data_access = SpaceStationDataAccess().add_filter_by_id_star_system(star_system.get_id()).add_filter_by_is_available_live(True)
            if for_trading:
                space_station_data_access = space_station_data_access.add_filter_by_has_trade_terminal(True)
            space_stations = space_station_data_access.load()
            for space_station in space_stations:
                name_collection.append(str(space_station))

            orbits = OrbitDataAccess().add_filter_by_id_star_system(star_system.get_id()).load()
            for orbit in orbits:
                name_collection.append(str(orbit))

            terminal_data_access = TerminalDataAccess().add_filter_by_id_star_system(star_system.get_id())
            if for_trading:
                terminal_data_access.add_filter_by_type("commodity")
            terminals = terminal_data_access.load()
            for terminal in terminals:
                name_collection.append(str(terminal))

            city_data_access = CityDataAccess().add_filter_by_id_star_system(star_system.get_id()).add_filter_by_is_available_live(True)
            if for_trading:
                city_data_access.add_filter_by_has_trade_terminal(True)
            cities = city_data_access.load()
            for city in cities:
                name_collection.append(str(city))

            poi_data_access = PoiDataAccess().add_filter_by_id_star_system(star_system.get_id()).add_filter_by_is_available_live(True)
            if for_trading:
                poi_data_access.add_filter_by_has_trade_terminal(True)
            pois = poi_data_access.load()
            for poi in pois:
                name_collection.append(str(poi))

            outpost_data_access = OutpostDataAccess().add_filter_by_id_star_system(star_system.get_id()).add_filter_by_is_available_live(True)
            if for_trading:
                outpost_data_access.add_filter_by_has_trade_terminal(True)
            outposts = outpost_data_access.load()
            for outpost in outposts:
                name_collection.append(str(outpost))

        closest_match = await self.__helper.get_llm().find_closest_match(name, name_collection)
        if closest_match:
            return closest_match

        return None

    def __definition_location(self, **kwargs) -> dict[str, any]:
        return {"type": "string"}

    async def __validate_company(self, name: str, is_item_manufacturer: bool|None = None, is_vehicle_manufacturer: bool|None = None) -> str | None:
        company_data_access = CompanyDataAccess()
        if is_item_manufacturer is not None:
            company_data_access = company_data_access.add_filter_by_is_item_manufacturer(is_item_manufacturer)
        if is_vehicle_manufacturer is not None:
            company_data_access = company_data_access.add_filter_by_is_vehicle_manufacturer(is_vehicle_manufacturer)
        companies = company_data_access.load()

        company_names = []
        for company in companies:
            company_names.append(str(company))

        closest_match = await self.__helper.get_llm().find_closest_match(name, company_names)
        if closest_match:
            return closest_match

        return None

    def __definition_company(self, **kwargs) -> dict[str, any]:
        return {"type": "string"}

    def __validate_enum(self, value: str, enum: list[str]) -> str | None:
        if value in enum:
            return value

        return None

    def __definition_enum(self, enum: list[str], **kwargs) -> dict[str, any]:
        return {"type": "string", "enum": enum}

    async def __validate_category(self, name: str, is_game_related: bool | None = None) -> str | None:
        category_data_access = CategoryDataAccess()
        if is_game_related is not None:
            category_data_access.add_filter_by_is_game_related(is_game_related)
        categories = category_data_access.load()

        category_names = []
        for category in categories:
            category_names.append(str(category))

        closest_match = await self.__helper.get_llm().find_closest_match(name, category_names)
        if closest_match:
            return closest_match

        return None

    def __definition_category(self, is_game_related: bool | None = None, **kwargs) -> dict[str, any]:
        category_data_access = CategoryDataAccess()
        if is_game_related is not None:
            category_data_access.add_filter_by_is_game_related(is_game_related)
        categories = category_data_access.load()

        category_names = []
        for category in categories:
            category_names.append(str(category))

        return {"type": "string", "enum": category_names}

    async def __validate_item(self, name: str) -> str | None:
        item_data_access = ItemDataAccess()
        items = item_data_access.load()

        item_names = []
        for item in items:
            item_names.append(str(item))

        closest_match = await self.__helper.get_llm().find_closest_match(name, item_names)

        if closest_match:
            return closest_match

        return None

    def __definition_item(self, **kwargs) -> dict[str, any]:
        return {"type": "string"}
