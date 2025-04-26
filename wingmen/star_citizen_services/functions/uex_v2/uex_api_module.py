import json
import os
import time
import requests
import random
import heapq

if __name__ != "__main__":
    from wingmen.star_citizen_services.helper import find_best_match


DEBUG = False
TEST = False
CALL_UEX_SR_ENDPOINT = True


def print_debug(to_print):
    if DEBUG:
        print(to_print)


if __name__ != "__main__":
    from services.printr import Printr

    printr = Printr()

# basic field names among all endpoints:
ID_FIELD_NAME = "id"
NAME_FIELD_NAME = "name"

# endpoint names
CATEGORY_VEHICLES = "vehicles"
CATEGORY_CITIES = "cities"
CATEGORY_COMMODITIES = "commodities"
CATEGORY_TERMINALS = "terminals"
CATEGORY_OUTPOSTS = "outposts"
CATEGORY_ORBITS = "orbits"
CATEGORY_MOONS = "moons"
CATEGORY_STATIONS = "space_stations"
CATEGORY_SYSTEMS = "star_systems"
CATEGORY_ITEMS = "items"
PRICES_COMMODITIES = "commodities_prices"
PRICES_VEHICLES = "vehicles_purchases_prices"
PRICES_ITEMS = "items_prices"
CATEGORY_REFINERY_METHODS = "refineries_methods"
TRADE_ROUTES_REPORTS = "commodities_routes"


ACTIVE_STAR_SYSTEMS = {
    "Stanton": 68,
    "Pyro": 64,
}

TRADE_ROUTE_PROMPT_INSTRUCTIONS = (
    "Tell the user how many alternatives you have identified. Provide him details about the best "
    "alternative only and ask him if he wants to know more about the other alternatives. "
    "Your response should be in narrative form that is suitable for a tts engine. "
    "It is important to provide the player with the information about the trade route, "
    "especially if he has to travel to another planetary body (orbit) or even a different star system. "
    "If the other alternatives have similar profit without system change, mention that to the player. "
    "Write out all numbers, especially prices. "
    "Example: instead of 24 write 'twentyfour'!"
)


class UEXApi2():

    _uex_instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._uex_instance:
            cls._uex_instance = super(UEXApi2, cls).__new__(cls)
        return cls._uex_instance

    def __init__(self):
        # Initialize your instance here, if not already initialized
        if not hasattr(self, 'is_initialized'):
            self.root_data_path = "star_citizen_data/uex2"
            
            self.base_url = "https://uexcorp.space/api/2.0/"
            self.session = requests.Session()
            self.session.headers.update({"Authorization": f"Bearer {self.api_key}"})
            self.session.headers.update({"secret_key": f"{self.user_secret_key}"})
            
            self.vehicles_max_age = 864010  # ~10 days
            self.cities_max_age = 864120  # ~10 days
            self.commodities_max_age = 864230  # ~10 days
            self.terminals_max_age = 864340  # ~10 days
            self.outposts_max_age = 864450  # ~10 days
            self.orbits_max_age = 864560  # ~10 days
            self.moons_max_age = 864670  # ~10 days
            self.systems_max_age = 2594010  # ~30 days
            self.items_max_age = 864780  # ~10 days
            self.vehicle_prices_max_age = 864090  # ~10 days (UEX refresh)(prices)
            self.commodities_prices_max_age = 1210  # ~20 min (UEX 1h refresh)(prices)
            self.commodities_routes_max_age = 1120  # ~20 min (UEX 1h refresh)(prices)
            self.item_prices_max_age = 7210  # ~2h (UEX refresh)(prices)
            self.refinery_methods_max_age = 864780  # ~10 days

            self.max_ages = {
                CATEGORY_VEHICLES: self.vehicles_max_age,
                CATEGORY_CITIES: self.cities_max_age,
                CATEGORY_COMMODITIES: self.commodities_max_age,
                CATEGORY_TERMINALS: self.terminals_max_age,
                CATEGORY_ORBITS: self.orbits_max_age,
                CATEGORY_MOONS: self.moons_max_age,
                CATEGORY_SYSTEMS: self.systems_max_age,
                CATEGORY_STATIONS: self.systems_max_age,
                CATEGORY_ITEMS: self.item_prices_max_age,
                CATEGORY_OUTPOSTS: self.outposts_max_age,
                PRICES_COMMODITIES: self.commodities_prices_max_age,
                PRICES_ITEMS: self.item_prices_max_age,
                PRICES_VEHICLES: self.item_prices_max_age,
                CATEGORY_REFINERY_METHODS: self.refinery_methods_max_age,
                TRADE_ROUTES_REPORTS: self.commodities_routes_max_age
            }

            self.inventory_state_mapping = {
                "OUT OF STOCK": 1, 
                "VERY LOW INVENTORY": 2, 
                "LOW INVENTORY": 3,
                "MEDIUM INVENTORY": 4,
                "HIGH INVENTORY": 5,
                "VERY HIGH INVENTORY": 6,
                "MAX INVENTORY": 7
            }

            self.code_mapping = {}
            self.name_mapping = {}
            self.data = {}

            print_debug("Initializing UexApi2 instance")
            self.is_initialized = True
        else:
            print_debug("UexApi2 instance already initialized")
    
    @classmethod
    def init(cls, uex_api_key: str, user_secret_key: str):
        cls.api_key = uex_api_key
        cls.user_secret_key = user_secret_key
        # get secret mappings stuff

        return cls()

    def get_api_endpoints_per_category(self, system_id, category=None):
        api_endpoints = {
            CATEGORY_VEHICLES: f"{CATEGORY_VEHICLES}/",
            CATEGORY_CITIES: f"{CATEGORY_CITIES}/id_star_system/{system_id}/",
            CATEGORY_COMMODITIES: f"{CATEGORY_COMMODITIES}/",
            CATEGORY_TERMINALS: f"{CATEGORY_TERMINALS}/id_star_system/{system_id}/",
            CATEGORY_ORBITS: f"{CATEGORY_ORBITS}/id_star_system/{system_id}/",
            CATEGORY_MOONS: f"{CATEGORY_MOONS}/id_star_system/{system_id}/",
            CATEGORY_SYSTEMS: f"{CATEGORY_SYSTEMS}/",
            CATEGORY_STATIONS: f"{CATEGORY_STATIONS}/id_star_system/{system_id}/",
            CATEGORY_ITEMS: f"{CATEGORY_ITEMS}",
            CATEGORY_OUTPOSTS: f"{CATEGORY_OUTPOSTS}/id_star_system/{system_id}/",
            PRICES_COMMODITIES: f"{PRICES_COMMODITIES}/",
            PRICES_ITEMS: f"{PRICES_ITEMS}/",  # filter applied later
            PRICES_VEHICLES: f"{PRICES_VEHICLES}/",  # filter applied later
            CATEGORY_REFINERY_METHODS: f"{CATEGORY_REFINERY_METHODS}/",
            TRADE_ROUTES_REPORTS: f"{TRADE_ROUTES_REPORTS}/"  # filter applied later
        }
        
        if category:
            return api_endpoints.get(category)
        
        return api_endpoints
    
    def _fetch_from_file_or_api(self, category, **additional_category_filters):
        file_age = self.max_ages[category]
        max_age_seconds = self.max_ages[category]

        file_path = f"{self.root_data_path}/{category}"
        for attribut, value in additional_category_filters.items():
            file_path += f"_{attribut}-{value}"
        
        file_path += ".json"

        file_data = None
        # Check if the file exists and is not too old
        if os.path.exists(file_path):
            file_age = time.time() - os.path.getmtime(file_path)

            with open(file_path, 'r', encoding="utf-8") as file:
                file_data = json.load(file)
                
        if file_age < max_age_seconds:
            # print_debug(f"Loading from file {name}")
            return file_data, file_age
        
        data = self._fetch_data_api(category, **additional_category_filters)
        if not data:
            # print_debug("Force loading from file")
            if not file_data:
                return None, None
            
            print_debug(f"no data from uex.api. Postponing file refresh: {file_path}")
            # we got an error from api, so we should extend the time before we retry the next time
            # therefore, we write back the data to file to update the file-date
            with open(file_path, 'w', encoding='utf-8') as file:
                json.dump(file_data, file, indent=3)
            return file_data, file_age
        else:
            # Make a map of the uexDB:
            uex_location_code_map = {loc.get(ID_FIELD_NAME): loc for loc in data}

            # save the call to the file system
            with open(file_path, 'w', encoding='utf-8') as file:
                json.dump(uex_location_code_map, file, indent=3)

            # print_debug(f"saved new api data to {file_path}")
            return uex_location_code_map, 0

    def _fetch_data(self):
        return self._refresh_data()

    def _refresh_data(self):
        """
        Fetch data from a file if it exists and is not too old, otherwise fetch from the API.
        :param category: if provided, will get data only for the given category, else all categories will be fetched and updated.
        :param additional_category_filters: only relevant, if the category is provided (usually a price category request that should be filtered to something)
        :return: Data either from the file or the API
        """
        categories = [CATEGORY_SYSTEMS, CATEGORY_CITIES, CATEGORY_COMMODITIES, CATEGORY_MOONS, CATEGORY_ORBITS, CATEGORY_OUTPOSTS, CATEGORY_TERMINALS, CATEGORY_STATIONS, CATEGORY_VEHICLES, CATEGORY_REFINERY_METHODS]
        
        for check_category in categories:
            if self._needs_refresh(check_category):
                data, age = self._fetch_from_file_or_api(check_category)
                self._write_code_mapping_to_file(
                    data=data,
                    category=check_category,
                    api_value_field=NAME_FIELD_NAME,
                    export_value_field_name=NAME_FIELD_NAME,
                    export_code_field_name=ID_FIELD_NAME
                )
                self.data[check_category] = {"data": data, "age": age}

        # # Kombinieren aller Daten in einem Dictionary
        # data = {
        #     CATEGORY_SHIPS: {"data": ship_data, "age": ship_age},
        #     CATEGORY_CITIES: {"data": cities_data, "age": cities_age},
        #     CATEGORY_COMMODITIES: {"data": commodities_data, "age": commoties_age},
        #     CATEGORY_TRADEPORTS: {"data": tradeports_data, "age": tradeports_age},
        #     CATEGORY_PLANETS: {"data": planets_data, "age": planets_age},
        #     CATEGORY_SATELLITES: {"data": satellites_data, "age": sattelites_age}
        # }

    def _needs_refresh(self, category, **additional_category_filters):
        if not category or not self.data or category not in self.data:
            return True
        
        category_key = category
        for attribute, value in additional_category_filters.items():
            category_key += f"_{attribute}-{value}"
        return self.data[category_key].get("age") is None or self.data[category_key].get("age") > self.max_ages[category]

    def _write_code_mapping_to_file(self, data, category, api_value_field, export_code_field_name, export_value_field_name):
        """
        Writes the code mapping for entities to a file from the given data.

        Args:
        - data (list of dicts): Data containing the key-value pairs to be written.
        - category (str): Category of the data, used for filename and internal mapping.
        - key_field (str): The field to be used as the key in the key-value pair.
        - value_field (str): The field to be used as the value in the key-value pair.
        """
        if not data:
            return

        if category not in self.code_mapping:
            self.code_mapping[category] = {}
            self.name_mapping[category] = {}

        # Erstellen eines Dictionarys zur Speicherung der JSON-Daten
        json_data = {}
        for _, category_entry in data.items():
            entry_code = category_entry.get("code", "")
            entry_name = category_entry.get(api_value_field, "")
            entry_id = category_entry.get(export_code_field_name, "")
            self.code_mapping[category][entry_id] = entry_name
            self.name_mapping[category][entry_name] = entry_id
            json_data[entry_name] = {
                export_code_field_name: entry_id,
                export_value_field_name: entry_name,
                "code": entry_code
            }

        # Schreiben des Dictionarys in eine Datei als JSON
        with open(f"{self.root_data_path}/{category}_mapping.json", 'w', encoding='utf-8') as file:
            json.dump(json_data, file, ensure_ascii=False, indent=4)
 
    def _fetch_data_api(self, category, **additional_category_filters):
        category_data = []
        system_relevant_categories = {
            CATEGORY_CITIES,
            CATEGORY_TERMINALS,
            CATEGORY_ORBITS,
            CATEGORY_MOONS,
            CATEGORY_OUTPOSTS,
        }

        # only one iteration, if category not dependent of star system    
        for system_code in ACTIVE_STAR_SYSTEMS.values():
            print_debug(f"Fetching data for system {system_code}")

            endpoint = self.get_api_endpoints_per_category(system_code, category)
            url = f"{self.base_url}{endpoint}"
            response = self.session.get(url, params=additional_category_filters, timeout=30)
            actual_url = response.request.url

            if response.status_code == 200:
                print_debug(f"Request: {actual_url}")
                print_debug(f'result: {json.dumps(response.json(), indent=2)[0:100]}...')
                if category in system_relevant_categories:
                    category_data.extend(response.json()["data"])
                else:
                    return response.json()["data"]
            else:
                sent_headers = response.request.headers
                print_debug(f"Error calling: {actual_url}")
                print_debug(f"Sent headers: {json.dumps(dict(sent_headers), indent=2)}")
                print_debug(f"Response Body: {json.dumps(response.json(), indent=2)}")
                return None  # if there is one error, we stop the whole process
        
        return category_data

    def _filter_available_commodities(self, commodities_data, include_restricted_illegal, isOnlySellable=False):
        """
        Filters commodities based on buyable, sellable, and legal status.

        Args:
        - commodities_data (dict): Contains the data of commodities.
        - include_restricted_illegal (bool): If True, includes commodities regardless of their legal status (restricted or illegal).
        - isOnlySellable (bool): If True, filters only for sellable commodities. If False, filters for commodities that are both buyable and sellable.

        Returns:
        - dict: A dictionary of filtered commodities. If isOnlySellable is True, returns commodities that are sellable. 
                Otherwise, returns commodities that are both buyable and sellable, depending on the include_restricted_illegal flag.
        """
        if (include_restricted_illegal):
            buyable = {
                c[ID_FIELD_NAME]: c
                for c in commodities_data.values()
                if c['is_buyable'] == 1 and c['price_buy'] > 0
            }
            sellable = {
                c[ID_FIELD_NAME]: c
                for c in commodities_data.values()
                if c['is_sellable'] == 1 and c['price_sell'] > 0
            }
        else:
            buyable = {
                c[ID_FIELD_NAME]: c
                for c in commodities_data.values()
                if c['is_buyable'] == 1 and c['price_buy'] > 0 and c['is_illegal'] != 1
            }
            sellable = {
                c[ID_FIELD_NAME]: c
                for c in commodities_data.values()
                if c['is_sellable'] == 1 and c['price_sell'] > 0 and c['is_illegal'] != 1
            }

        if isOnlySellable:
            return sellable

        # Intersection of buyable and sellable commodities
        buyable_and_sellable = {code: buyable[code] for code in buyable if code in sellable}
        return buyable_and_sellable
    
    def get_uex_trade_routes(self, **additional_category_filters):
        """
        Get trade routes from uex community data.
        Allowed filters are:
        // at least one of these inputs are required
        id_terminal_origin int(11)
        id_planet_origin int(11)
        id_orbit_origin int(11)
        id_commodity int(11)

        // optional inputs
        id_terminal_destination int(11)
        id_planet_destination int(11)
        id_orbit_destination int(11)
        id_faction_origin int(11)
        id_faction_destination int(11)
        investment int(11)
        """
        category_key = TRADE_ROUTES_REPORTS
        for attribute, value in additional_category_filters.items():
            category_key += f"_{attribute}-{value}"

        if self._needs_refresh(TRADE_ROUTES_REPORTS, **additional_category_filters):
            data, age = self._fetch_from_file_or_api(TRADE_ROUTES_REPORTS, **additional_category_filters)
            self.data[category_key] = {"data": data, "age": age}

        if not self.data.get(category_key) or not self.data[category_key].get("data"):
            return []
        data = list(self.data[category_key].get("data").values())
        print_debug(f"uex community trades: {json.dumps(data, indent=2)[0:100]}...")
        # Filter out entries with negative score or negative profit
        filtered_data = [
            entry for entry in data
            if entry["score"] >= 0 and entry["profit"] >= 0
        ]
        
        # Sort the remaining entries:
        # 1) by 'score' descending
        # 2) then by 'profit' descending
        filtered_data.sort(key=lambda x: (x["score"], x["profit"]), reverse=True)

        return filtered_data
    
    def get_prices_of(self, price_category=PRICES_COMMODITIES, **additional_category_filters):
        """
        Get prices of something for given filters

        :param price_category PRICES_COMMODITIES, PRICES_ITEMS or PRICES_VEHICLES
        :param additional_category_filters must contain at least one parameter:
            - the id of the terminal - id_terminal=id
            - the id of the commodity - id_commodity=id


        :return: A dictionary of filtered prices of the category type.
        """
        category_key = price_category
        for attribute, value in additional_category_filters.items():
            category_key += f"_{attribute}-{value}"

        if self._needs_refresh(price_category, **additional_category_filters):
            data, age = self._fetch_from_file_or_api(price_category, **additional_category_filters)
            self.data[category_key] = {"data": data, "age": age}

        return self.data[category_key].get("data")
    
    # ---------------------------------------------------------
    #   Hilfsfunktion: Param-Builder
    # ---------------------------------------------------------
    def _build_dynamic_param_dict(self, location_category: str, location_id: int, is_origin=True) -> dict:
        """
        Baut ein Dictionary { 'id_???_origin': location_id } bzw. { 'id_???_destination': location_id }
        abhängig von der Category (SYSTEMS, ORBITS, MOONS, CITIES, OUTPOSTS).
        
        Sonderfall Moons: Manchmal mappen wir 'id_moon' -> 'id_planet', 
        je nachdem wie Du es brauchst in Deinen Parametern.
        """
        # Mappings: Nur ein Basis-Map
        param_map = {
            CATEGORY_SYSTEMS: "id_star_system",
            CATEGORY_ORBITS:  "id_orbit",
            CATEGORY_MOONS:   "id_moon",
            CATEGORY_CITIES:  "id_city",
            CATEGORY_OUTPOSTS: "id_outpost",
            CATEGORY_TERMINALS: "id_terminal",
            CATEGORY_STATIONS: "id_space_station",
        }
        base = param_map.get(location_category)
        if not base:
            # unbekannte Category -> leeres dict
            return {}

        suffix = "origin" if is_origin else "destination"
        key = f"{base}_{suffix}"
        return {key: location_id}

    # ---------------------------------------------------------
    #   ÜBERARBEITET: _find_best_trade_from_location
    # ---------------------------------------------------------
    def _find_best_trade_from_location(self, location_id, location_category, include_restricted_illegal=False):
        """
        Find the best trading option starting from a given location.
        """

        # 1) Lade Terminal + Commodities
        terminal_data = [
            t for t in self.data[CATEGORY_TERMINALS].get("data").values()
            if t["type"] == "commodity"
        ]
        commodities_data = self.data[CATEGORY_COMMODITIES].get("data", {})

        # 2) Erzeuge ParamDict für UEX-Routen, z. B. {"id_orbit_origin": location_id} ...
        param_dict = {}
        # Sonderfall: MOONS => ID auf Planet mappen
        if location_category == CATEGORY_MOONS:
            moon = self.data[CATEGORY_MOONS]["data"].get(location_id)
            if moon:
                param_dict["id_planet_origin"] = moon["id_planet"]
        else:
            param_dict = self._build_dynamic_param_dict(location_category, location_id, is_origin=True)

        # 3) Bei Cities / Outposts: mehrere Terminals => wir sammeln Routen
        uex_trade_routes = []
        if location_category == CATEGORY_CITIES:
            city_terminals = [t["id"] for t in terminal_data if t["id_city"] == location_id]
            for term_id in city_terminals:
                dict_for_this_term = dict(param_dict)
                dict_for_this_term["id_terminal_origin"] = term_id
                routes = self.get_uex_trade_routes(**dict_for_this_term)
                uex_trade_routes.extend(routes)
        elif location_category == CATEGORY_OUTPOSTS:
            outpost_terminals = [t["id"] for t in terminal_data if t["id_outpost"] == location_id]
            for term_id in outpost_terminals:
                dict_for_this_term = dict(param_dict)
                dict_for_this_term["id_terminal_origin"] = term_id
                routes = self.get_uex_trade_routes(**dict_for_this_term)
                uex_trade_routes.extend(routes)
        else:
            # Normaler Fall: Systems, Orbits, oder Moons (bereits mapped)
            if param_dict:
                routes = self.get_uex_trade_routes(**param_dict)
                uex_trade_routes.extend(routes)

        # 4) Filter nach erlaubten Commodities
        allowed_commodities = self._filter_available_commodities(commodities_data, include_restricted_illegal)
        if uex_trade_routes:
            uex_trade_routes = [
                r for r in uex_trade_routes
                if r["id_commodity"] in allowed_commodities
            ]
            # Score sort / limit
            uex_trade_routes.sort(key=lambda x: x["score"], reverse=True)
            uex_trade_routes = uex_trade_routes[:5]
            # Umwandeln in "kleines" Dict
            uex_trade_routes = [self._transform_uex_trade_entry(r) for r in uex_trade_routes]

        # 5) Lokale Berechnung (wie gehabt)
        # Terminal, das dem Ort entspricht
        # Id-Feld (z. B. 'id_orbit') ermitteln:
        id_field_name = {
            CATEGORY_SYSTEMS: "id_star_system",
            CATEGORY_ORBITS: "id_orbit",
            CATEGORY_MOONS: "id_moon",
            CATEGORY_CITIES: "id_city",
            CATEGORY_OUTPOSTS: "id_outpost",
            CATEGORY_STATIONS: "id_space_station",
        }.get(location_category, "")

        # Start-Terminals = alle Commodity-Typ-Terminals, deren {id_field_name} = location_id
        start_location_terminals = [
            t for t in terminal_data
            if t.get(id_field_name) == location_id
        ]

        # Commodity-Preise
        commodity_prices = {}
        for c_id in allowed_commodities.keys():
            prices = self.get_prices_of(price_category=PRICES_COMMODITIES, id_commodity=c_id)
            if prices is None:
                print_debug(f"Skipping commodity with id {c_id} as no prices found.")
                continue
            commodity_prices[c_id] = list(prices.values())

        top_trades = []
        heapq.heapify(top_trades)
        trade_id = 0
        max_profit = 0

        # Kaufe an "start_location_terminals"
        for buy_terminal in start_location_terminals:
            buy_terminal_id = buy_terminal[ID_FIELD_NAME]

            buyable_commodities = [
                c_price for c_list in commodity_prices.values()
                for c_price in c_list
                if c_price["id_terminal"] == buy_terminal_id and c_price["price_buy"] > 0
            ]
            for terminal_buyable_commodity in buyable_commodities:
                cid = terminal_buyable_commodity["id_commodity"]
                buy_price = terminal_buyable_commodity["price_buy"]
                # Finde best sell
                best_sell_price = 0
                best_sell_term = None

                sells = [
                    c_price for c_list in commodity_prices.values()
                    for c_price in c_list
                    if c_price["id_commodity"] == cid and c_price["price_sell"] > 0
                ]
                for st in sells:
                    if st["price_sell"] > best_sell_price:
                        best_sell_price = st["price_sell"]
                        best_sell_term = st

                profit = best_sell_price - buy_price
                if profit > 0 and best_sell_term and profit > max_profit:
                    trade_info = self._create_trade_info(
                        terminal_buyable_commodity,
                        best_sell_term,
                        cid,
                        buy_price,
                        best_sell_price,
                        round(profit, 2)
                    )
                    heapq.heappush(top_trades, (-profit, trade_id, trade_info))
                    max_profit = profit
                    trade_id += 1

        if not top_trades:
            return {
                "success": False,
                "message": f"No trade route found starting at {location_id}."
            }

        best_trade_routes = []
        for _ in range(min(3, len(top_trades))):
            _, _, trade_info = heapq.heappop(top_trades)
            best_trade_routes.append(trade_info)

        return {
            "success": True,
            "result_interpretation_instructions": TRADE_ROUTE_PROMPT_INSTRUCTIONS,
            "trade_routes": best_trade_routes,
            "uex_community_trade_routes": uex_trade_routes,
            "number_of_alternatives": len(best_trade_routes) + len(uex_trade_routes)
        }

    # ---------------------------------------------------------
    #   ÜBERARBEITET: _find_best_trade_between_locations
    # ---------------------------------------------------------
    def _find_best_trade_between_locations(self, location_id1, location_category1, location_id2, location_category2, include_restricted_illegal=False):
        """
        Find the best trading option between two distinct locations.
        """

        # 1) Terminal + Commodities laden
        terminal_data = [
            t for t in self.data[CATEGORY_TERMINALS].get("data").values()
            if t["type"] == "commodity"
        ]
        commodities_data = self.data[CATEGORY_COMMODITIES].get("data", {})

        # ------------------------------------------------------
        #   Hilfsfunktion: Umbau "Moon => Planet" oder generisch
        # ------------------------------------------------------
        def _maybe_moon_to_planet(category, loc_id, is_origin=True):
            """
            Falls location_category == MOONS => wir nutzen id_planet_{origin,destination},
            sonst holen wir mit _build_dynamic_param_dict(...) das passende Key.
            """
            if category == CATEGORY_MOONS:
                moon = self.data[CATEGORY_MOONS]["data"].get(loc_id)
                if moon:
                    suffix = "origin" if is_origin else "destination"
                    return {f"id_planet_{suffix}": moon["id_planet"]}
                return {}
            return self._build_dynamic_param_dict(category, loc_id, is_origin=is_origin)

        # ------------------------------------------------------
        #   Hilfsfunktion: Erzeuge alle möglichen Param-Dicts 
        #   (City/Outpost kann mehrere Terminals haben)
        # ------------------------------------------------------
        def _build_params_list_for_location(loc_id, loc_cat, is_origin=True):
            """
            Gibt eine Liste von Param-Dicts zurück. 
            Example: Falls City => wir liefern eine Liste von N Parametern 
                    (je Terminal), 
                    sonst 1 Dicte.
            """
            base_param = _maybe_moon_to_planet(loc_cat, loc_id, is_origin=is_origin)

            all_commodity_terminals = [
                t for t in terminal_data if t["type"] == "commodity"
            ]

            if loc_cat == CATEGORY_CITIES:
                # City => mehrere Terminals
                city_terminals = [t["id"] for t in all_commodity_terminals if t.get("id_city") == loc_id]
                if not city_terminals:
                    return [base_param]
                params_list = []
                suffix = "origin" if is_origin else "destination"
                for term_id in city_terminals:
                    new_param = dict(base_param)
                    new_param[f"id_terminal_{suffix}"] = term_id
                    params_list.append(new_param)
                return params_list

            elif loc_cat == CATEGORY_OUTPOSTS:
                # Outpost => mehrere Terminals
                outpost_terminals = [t["id"] for t in all_commodity_terminals if t.get("id_outpost") == loc_id]
                if not outpost_terminals:
                    return [base_param]
                params_list = []
                suffix = "origin" if is_origin else "destination"
                for term_id in outpost_terminals:
                    new_param = dict(base_param)
                    new_param[f"id_terminal_{suffix}"] = term_id
                    params_list.append(new_param)
                return params_list

            else:
                # Systems / Orbits / Moons => nur 1 Dicte
                return [base_param]

        # ------------------------------------------------------
        # 2) UEX-Community-Routes einholen
        # ------------------------------------------------------
        params_for_origin = _build_params_list_for_location(location_id1, location_category1, is_origin=True)
        params_for_destination = _build_params_list_for_location(location_id2, location_category2, is_origin=False)

        uex_trade_routes = []
        for po in params_for_origin:
            for pd in params_for_destination:
                combined_params = {**po, **pd}  # z.B. {'id_planet_origin': X, 'id_terminal_destination': Y, ...}
                routes = self.get_uex_trade_routes(**combined_params)
                if routes:
                    uex_trade_routes.extend(routes)

        # Filter nur erlaubte Commodities 
        allowed_commodities = self._filter_available_commodities(commodities_data, include_restricted_illegal)
        if uex_trade_routes:
            uex_trade_routes = [
                r for r in uex_trade_routes
                if r["id_commodity"] in allowed_commodities
            ]
            # nach score sortieren
            uex_trade_routes.sort(key=lambda x: x["score"], reverse=True)
            # ggf. einkürzen (Top 5)
            uex_trade_routes = uex_trade_routes[:5]
            # transformieren
            uex_trade_routes = [self._transform_uex_trade_entry(r) for r in uex_trade_routes]

        # ------------------------------------------------------
        # 3) Lokale Preiskalkulation
        # ------------------------------------------------------
        #    - Terminal-IDs für Start + End
        #    - Commodity-Preise per 'get_prices_of'
        #    - Profit-Berechnung
        #    - Top 3 Heap
        # ------------------------------------------------------
        # Start-Terminals
        key_map = {
            CATEGORY_SYSTEMS:  "id_star_system",
            CATEGORY_ORBITS:   "id_orbit",
            CATEGORY_MOONS:    "id_moon",
            CATEGORY_CITIES:   "id_city",
            CATEGORY_OUTPOSTS: "id_outpost",
            CATEGORY_STATIONS: "id_space_station"
        }
        id_key1 = key_map.get(location_category1, "")
        id_key2 = key_map.get(location_category2, "")

        terminals_start = [
            t for t in terminal_data
            if t.get(id_key1) == location_id1
        ]
        target_terminal_ids = {
            t["id"] for t in terminal_data
            if t.get(id_key2) == location_id2
        }

        # Commodity-Preise laden
        commodity_prices = {}
        for c_id in allowed_commodities.keys():
            prices = self.get_prices_of(price_category=PRICES_COMMODITIES, id_commodity=c_id)
            if prices:
                commodity_prices[c_id] = list(prices.values())

        # Heap für Best Trades
        import heapq
        top_trades = []
        heapq.heapify(top_trades)
        trade_id = 0

        for buy_terminal in terminals_start:
            buy_terminal_id = buy_terminal["id"]
            buyable_commodities = [
                cp for cp_list in commodity_prices.values()
                for cp in cp_list
                if cp["id_terminal"] == buy_terminal_id and cp["price_buy"] > 0
            ]
            for c_buy in buyable_commodities:
                commodity_id = c_buy["id_commodity"]
                buy_price = c_buy["price_buy"]

                # an target-terminal-ids verkaufen
                sellable_commodities = [
                    cp for cp_list in commodity_prices.values()
                    for cp in cp_list
                    if cp["id_commodity"] == commodity_id
                    and cp["price_sell"] > 0
                    and cp["id_terminal"] in target_terminal_ids
                ]
                for c_sell in sellable_commodities:
                    profit = c_sell["price_sell"] - buy_price
                    if profit <= 0:
                        continue
                    trade_info = self._create_trade_info(
                        c_buy,
                        c_sell,
                        commodity_id,
                        buy_price,
                        c_sell["price_sell"],
                        round(profit, 2)
                    )
                    heapq.heappush(top_trades, (-profit, trade_id, trade_info))
                    trade_id += 1

        if not top_trades:
            return {
                "success": False,
                "message": f"No trade route found between {location_id1} and {location_id2}."
            }

        best_trade_routes = []
        for _ in range(min(3, len(top_trades))):
            _, _, route = heapq.heappop(top_trades)
            best_trade_routes.append(route)

        return {
            "success": True,
            "result_interpretation_instructions": TRADE_ROUTE_PROMPT_INSTRUCTIONS,
            "trade_routes": best_trade_routes,
            "uex_community_trade_routes": uex_trade_routes,
            "number_of_alternatives": len(best_trade_routes) + len(uex_trade_routes)
        }

    # ---------------------------------------------------------
    #   ÜBERARBEITET: _find_best_trade_for_commodity
    #   -> param usage
    # ---------------------------------------------------------
    def _find_best_trade_for_commodity(self, commodity_id, include_restricted_illegal=False):
        """
        Find the best trade route for a specific commodity.
        """

        # 1) Lade Terminal-Daten (Commodity‑Terminals) und Commodity‑Daten:
        terminal_data = [
            t for t in self.data[CATEGORY_TERMINALS].get("data").values()
            if t["type"] == "commodity"
        ]
        commodities_data = self.data[CATEGORY_COMMODITIES].get("data", {})
        no_route = {"success": False, "message": f"No trade route found for commodity {commodity_id}."}

        # 2) Prüfe, ob die Commodity überhaupt "zulässig" (nicht illegal) ist:
        allowed_commodities = self._filter_available_commodities(
            commodities_data,
            include_restricted_illegal,
            isOnlySellable=False  # Du möchtest auch buyable => False
        )
        if commodity_id not in allowed_commodities:
            return no_route

        # 3) UEX-Community-Routen für diese Commodity laden
        #    => param: { "id_commodity": commodity_id } 
        uex_routes_raw = self.get_uex_trade_routes(id_commodity=commodity_id)
        #   => ggf. Sortieren & Begrenzen
        uex_community_trade_routes = []
        if uex_routes_raw:
            # Filter, falls Du bestimmte Restriktionen hast oder Score >= 0,
            # da get_uex_trade_routes i.d.R. schon filtert:
            # z.B. "Profit >= 0, Score >= 0" (passiert meist in get_uex_trade_routes)
            # Sortiere nach Score, nimm Top 5
            uex_routes_raw.sort(key=lambda x: x["score"], reverse=True)
            uex_routes_raw = uex_routes_raw[:5]
            # Transformiere in Dein kompakteres Schema
            uex_community_trade_routes = [
                self._transform_uex_trade_entry(r) for r in uex_routes_raw
            ]

        # 4) Lokale Prices besorgen:
        prices_data = self.get_prices_of(price_category=PRICES_COMMODITIES, id_commodity=commodity_id)
        if not prices_data:
            # => Kein lokaler Eintrag
            return no_route

        # Umwandeln in dict {id_terminal: info}
        prices_dict = {item["id_terminal"]: item for item in prices_data.values()}

        # 5) Heap-Logik für bestes Buy‑Sell
        import heapq
        top_trades = []
        heapq.heapify(top_trades)
        trade_id = 0

        # BUY -> SELL
        for t_buy in terminal_data:
            buy_price_info = prices_dict.get(t_buy["id"])
            if not buy_price_info or buy_price_info["price_buy"] <= 0:
                continue
            buy_price = buy_price_info["price_buy"]

            for t_sell in terminal_data:
                sell_price_info = prices_dict.get(t_sell["id"])
                if not sell_price_info or sell_price_info["price_sell"] <= 0:
                    continue
                sell_price = sell_price_info["price_sell"]

                # Profitberechnung
                profit = sell_price - buy_price
                if profit <= 0:
                    continue

                # Baue 'trade_info' 
                trade_info = self._create_trade_info(
                    buy_price_info,
                    sell_price_info,
                    commodity_id,
                    buy_price,
                    sell_price,
                    round(profit, 2)
                )
                # Negative Profit in den Heap, damit "höchstes" = bestes
                heapq.heappush(top_trades, (-profit, trade_id, trade_info))
                trade_id += 1

        # 6) Falls KEIN lokaler Trade möglich => check "no_route"
        if not top_trades and not uex_community_trade_routes:
            return no_route
        elif not top_trades:
            # Nur UEX-Community-Einträge
            return {
                "success": True,
                "result_interpretation_instructions": TRADE_ROUTE_PROMPT_INSTRUCTIONS,
                "trade_routes": [],  # keine local trades
                "uex_community_trade_routes": uex_community_trade_routes,
                "number_of_alternatives": len(uex_community_trade_routes)
            }

        # 7) Top 3 lokale Routen
        best_trade_routes = []
        for _ in range(min(3, len(top_trades))):
            _, _, info = heapq.heappop(top_trades)
            best_trade_routes.append(info)

        # 8) Zusammenfügen von local + UEX
        return {
            "success": True,
            "result_interpretation_instructions": TRADE_ROUTE_PROMPT_INSTRUCTIONS,
            "trade_routes": best_trade_routes,               # Lokale Top 3
            "uex_community_trade_routes": uex_community_trade_routes,  # UEX Top 5
            "number_of_alternatives": len(best_trade_routes) + len(uex_community_trade_routes)
        }
  
    # ---------------------------------------------------------
    #   ÜBERARBEITET: _find_best_selling_location_for_commodity
    # ---------------------------------------------------------
    def _find_best_selling_location_for_commodity(self, commodity_id, include_restricted_illegal=False):
        """
        Find the best location to sell a commodity.
        """
        commodities_data = self.data[CATEGORY_COMMODITIES].get("data", {})
        no_route = {"success": False, "message": f"No selling location found for commodity {commodity_id}."}

        allowed_commodities = self._filter_available_commodities(commodities_data, include_restricted_illegal, isOnlySellable=True)
        if commodity_id not in allowed_commodities:
            no_route["message"] = f"Commodity {commodity_id} is not sellable."
            return no_route

        # community routes:
        routes = self.get_uex_trade_routes(id_commodity=commodity_id)
        if routes:
            # transform etc.
            routes = [self._transform_uex_trade_entry(r) for r in routes[:5]]

        prices = self.get_prices_of(price_category=PRICES_COMMODITIES, id_commodity=commodity_id)
        if not prices:
            return no_route
        
        top_trades = []
        trade_id = 0
        max_sell_price = 0

        for term_price in prices.values():
            sp = term_price["price_sell"]
            if sp > max_sell_price or len(top_trades) < 3:
                info = self._build_trade_selling_info(commodity_id, term_price, round(sp, 2))
                heapq.heappush(top_trades, (-sp, trade_id, info))
                trade_id += 1
                max_sell_price = sp

        if not top_trades:
            return no_route

        best_routes = []
        for _ in range(min(3, len(top_trades))):
            _, _, info = heapq.heappop(top_trades)
            best_routes.append(info)

        return {
            "success": True,
            "result_interpretation_instructions": TRADE_ROUTE_PROMPT_INSTRUCTIONS,
            "trade_routes": best_routes,
            "uex_community_trade_routes": routes if routes else [],
            "number_of_alternatives": len(best_routes) + (len(routes) if routes else 0)
        }

    # ---------------------------------------------------------
    #   ÜBERARBEITET: _find_best_sell_price_at_location
    # ---------------------------------------------------------
    def _find_best_sell_price_at_location(self, commodity_id, location_id, location_category):
        """
        Find best local selling price for a commodity at a specific location.
        """
        no_route = {"success": False, "message": f"No available tradeport found for commodity {commodity_id} at location {location_id}."}
        terminal_data = [
            t for t in self.data[CATEGORY_TERMINALS].get("data").values()
            if t["type"] == "commodity"
        ]
        commodities_data = self.data[CATEGORY_COMMODITIES].get("data", {})

        allowedCommodities = self._filter_available_commodities(commodities_data, include_restricted_illegal=True, isOnlySellable=True)
        if commodity_id not in allowedCommodities:
            return no_route

        # UEX community routes – dynamischer Param-Builder
        # falls MOON => map to planet ...
        param_dict = {}
        if location_category == CATEGORY_MOONS:
            moon = self.data[CATEGORY_MOONS]["data"].get(location_id)
            if moon:
                param_dict["id_planet_destination"] = moon["id_planet"]
        else:
            param_dict = self._build_dynamic_param_dict(location_category, location_id, is_origin=False)
        param_dict["id_commodity"] = commodity_id

        uex_routes = []
        # CITIES => mehrere Terminals
        if location_category == CATEGORY_CITIES:
            city_terms = [t["id"] for t in terminal_data if t["id_city"] == location_id]
            for tid in city_terms:
                d = dict(param_dict)
                d["id_terminal_destination"] = tid
                tmp = self.get_uex_trade_routes(**d)
                uex_routes.extend(tmp)
        elif location_category == CATEGORY_OUTPOSTS:
            outpost_terms = [t["id"] for t in terminal_data if t["id_outpost"] == location_id]
            for tid in outpost_terms:
                d = dict(param_dict)
                d["id_terminal_destination"] = tid
                tmp = self.get_uex_trade_routes(**d)
                uex_routes.extend(tmp)
        else:
            # normal
            routes = self.get_uex_trade_routes(**param_dict)
            uex_routes.extend(routes)

        if uex_routes:
            uex_routes.sort(key=lambda x: x["score"], reverse=True)
            uex_routes = uex_routes[:5]
            uex_routes = [self._transform_uex_trade_entry(r) for r in uex_routes]

        # Lokaler Teil
        id_field_name = {
            CATEGORY_SYSTEMS: "id_star_system",
            CATEGORY_ORBITS: "id_orbit",
            CATEGORY_MOONS:  "id_moon",
            CATEGORY_CITIES: "id_city",
            CATEGORY_OUTPOSTS: "id_outpost",
            CATEGORY_STATIONS: "id_space_station"
        }.get(location_category, "")

        tradeports = [
            t for t in terminal_data
            if t.get(id_field_name) == location_id
        ]

        prices = self.get_prices_of(price_category=PRICES_COMMODITIES, id_commodity=commodity_id)
        if not prices:
            return no_route
        prices = {p["id_terminal"]: p for p in prices.values()}

        top_trades = []
        max_sell_price = 0
        trade_id = 0

        for trp in tradeports:
            pinfo = prices.get(trp["id"])
            if pinfo is None:
                continue
            sp = pinfo["price_sell"]
            if sp > max_sell_price or len(top_trades) < 3:
                info = self._build_trade_selling_info(commodity_id, pinfo, round(sp, 2))
                heapq.heappush(top_trades, (-sp, trade_id, info))
                trade_id += 1
                max_sell_price = sp

        if not top_trades:
            return no_route

        best_trades = []
        for _ in range(min(3, len(top_trades))):
            _, _, info = heapq.heappop(top_trades)
            best_trades.append(info)

        return {
            "success": True,
            "result_interpretation_instructions": TRADE_ROUTE_PROMPT_INSTRUCTIONS,
            "trade_routes": best_trades,
            "uex_community_trade_routes": uex_routes,
            "number_of_alternatives": len(best_trades) + len(uex_routes)
        }

    # ---------------------------------------------------------
    #   UNVERÄNDERT: Hilfsfunktionen create_trade_info, transform_uex_trade_entry
    #                plus Deine find_best_*_code-Methoden
    # ---------------------------------------------------------
    def _create_trade_info(self, buy_terminal, sell_terminal, commodity_code, buy_price, sell_price, profit):
        return {
            "commodity": self.code_mapping.get(CATEGORY_COMMODITIES, {}).get(commodity_code, ''),
            "buy_at_tradeport_name": buy_terminal.get("terminal_name", ''),
            "buy_moon": buy_terminal.get("moon_name", ''),
            "buy_orbit": buy_terminal.get("orbit_name", ''),
            "buy_system": buy_terminal.get("star_system_name", ''),
            "sell_at_tradeport_name": sell_terminal.get("terminal_name", ''),
            "sell_moon": sell_terminal.get("moon_name", ''),
            "sell_orbit": sell_terminal.get("orbit_name", ''),
            "sell_system": sell_terminal.get("star_system_name", ''),
            "buy_price": buy_price,
            "sell_price": sell_price,
            "profit": profit
        }

    def _transform_uex_trade_entry(self, entry):
        """Transform a full trade entry dict to a trimmed-down dict with a computed profit."""
        computed_profit = entry["price_destination"] - entry["price_origin"]
        return {
            "price_origin": entry["price_origin"],
            "price_destination": entry["price_destination"],
            "profit": computed_profit,
            "scu_reachable": entry["scu_reachable"],
            "distance": entry["distance"],
            "score": entry["score"],
            "container_sizes_origin": entry["container_sizes_origin"],
            "container_sizes_destination": entry["container_sizes_destination"],
            "commodity_name": entry["commodity_name"],
            "origin_star_system_name": entry["origin_star_system_name"],
            "origin_planet_name": entry["origin_planet_name"],
            "origin_orbit_name": entry["origin_orbit_name"],
            "origin_terminal_name": entry["origin_terminal_name"],
            "destination_star_system_name": entry["destination_star_system_name"],
            "destination_planet_name": entry["destination_planet_name"],
            "destination_orbit_name": entry["destination_orbit_name"],
            "destination_terminal_name": entry["destination_terminal_name"],
        }

    def _build_trade_selling_info(self, commodity_code, best_sell, max_sell_price):
        return {
            "commodity": best_sell.get("commodity_name", ''),
            "sell_at_tradeport_name": best_sell.get("terminal_name", ''),
            "sell_moon": best_sell.get("moon_name", ''),
            "sell_orbit": best_sell.get("orbit_name", ''),
            "sell_system": best_sell.get("star_system_name", ''),
            "sell_price": max_sell_price
        }

    # ---------------------------------------------------------
    #   Deine "find_best_trade_between_locations_code" & Co.
    #   => rufen intern _find_best_trade_between_locations auf
    # ---------------------------------------------------------
    def find_best_trade_between_locations_code(self, location_name_from, location_name_to):
        if __name__ != "__main__":
            printr.print(text=f"Suche beste Handelsoption für die Reise {location_name_from} -> {location_name_to}", tags="info")
        category_from, location_from = self.get_location(location_name_from)
        category_to, location_to = self.get_location(location_name_to)
        
        if not location_from: 
            return {"success": False, "message": f"Start location not recognised: {location_name_from}"}
        if not location_to:
            return {"success": False, "message": f"Target location not recognised: {location_name_to}"}

        return self._find_best_trade_between_locations(
            location_from[ID_FIELD_NAME],
            category_from,
            location_to[ID_FIELD_NAME],
            category_to
        )

    def find_best_trade_from_location_code(self, location_name_from):
        if __name__ != "__main__":
            printr.print(text=f"Search best trade option from {location_name_from}", tags="info")
        category, location_from = self.get_location(location_name_from)
        
        if not location_from: 
            return {
                "success": False,
                "message": f"Start location not recognised: {location_name_from}"
            }
        
        return self._find_best_trade_from_location(location_from[ID_FIELD_NAME], category)

    def find_best_trade_for_commodity_code(self, commodity_name):
        if __name__ != "__main__":
            printr.print(text=f"Suche beste Route für {commodity_name}", tags="info")
        commodity = self.get_commodity(commodity_name)
        if not commodity:
            return {
                "success": False,
                "result_interpretation_instructions": "Ask the player for the commodity that he wants to trade."
            }
        return self._find_best_trade_for_commodity(commodity[ID_FIELD_NAME])
    
    def find_best_selling_location_for_commodity_code(self, commodity_name):
        if __name__ != "__main__":
            printr.print(text=f"Suche beste Verkaufsort für {commodity_name}", tags="info")
        commodity = self.get_commodity(commodity_name)
        if not commodity:
            return {
                "success": False,
                "result_interpretation_instructions": "Ask the player the commodity that he wants to sell."
            }
        print_debug(f"Commodity found for '{commodity_name}: {commodity['name']}")
        return self._find_best_selling_location_for_commodity(commodity[ID_FIELD_NAME], include_restricted_illegal=True)
    
    def find_best_sell_price_at_location_codes(self, commodity_name, location_name):
        if __name__ != "__main__":
            printr.print(text=f"Suche beste Verkaufsoption für {commodity_name} bei {location_name}", tags="info")
        
        category, location_to = self.get_location(location_name)
        commodity = self.get_commodity(commodity_name)
        
        if not location_to:
            return {
                "success": False,
                "result_interpretation_instructions": f"The location {location_name} could not be found. User should try again speaking clearly. "
            }
        if not commodity:
            return {
                "success": False,
                "result_interpretation_instructions": f"The commodity {commodity_name} could not be identified. Ask the user to repeat the name clearly. "
            }
    
        return self._find_best_sell_price_at_location(
            commodity_id=commodity[ID_FIELD_NAME],
            location_id=location_to[ID_FIELD_NAME],
            location_category=category
        )

    # ---------------------------------------------------------
    #   UNVERÄNDERT:  Hilfsfunktionen get_location, get_commodity ...
    # ---------------------------------------------------------
    def get_commodity_name(self, commodity_id):
        self._refresh_data()
        if commodity_id in self.code_mapping.get(CATEGORY_COMMODITIES):
            return self.code_mapping.get(CATEGORY_COMMODITIES).get(commodity_id)
        
        return commodity_id
    
    def get_satellite_name(self, moon_id):
        self._refresh_data()
    
        if moon_id in self.code_mapping.get(CATEGORY_MOONS):
            return self.code_mapping.get(CATEGORY_MOONS).get(moon_id)
        
        return moon_id
    
    def get_planet_name(self, planet_id):
        self._refresh_data()
    
        if planet_id in self.code_mapping.get(CATEGORY_ORBITS):
            return self.code_mapping.get(CATEGORY_ORBITS).get(planet_id)
        
        return planet_id
    
    def get_city_name(self, city_id):
        self._refresh_data()
    
        if city_id in self.code_mapping.get(CATEGORY_CITIES):
            return self.code_mapping.get(CATEGORY_CITIES).get(city_id)
        
        return city_id
    
    def get_tradeport_name(self, terminal_id):
        self._refresh_data()
    
        if terminal_id in self.code_mapping.get(CATEGORY_TERMINALS):
            return self.code_mapping.get(CATEGORY_TERMINALS).get(terminal_id)
        
        return terminal_id

    def get_tradeports(self):
        self._refresh_data()
        category = CATEGORY_TERMINALS
        return self.data[category].get("data", [])
    
    def get_refineries(self):
        self._refresh_data()
        category = CATEGORY_TERMINALS
        data, age = self._fetch_from_file_or_api(category, type="refinery")
        return data 
    
    def get_terminal(self, tradeport_mapping_name, type="commodity", search_fields=["name"], cutoff=80):
        
        self._refresh_data()
        filtered_data = [item for item in self.data[CATEGORY_TERMINALS].get('data', {}).values() if str(item.get("type", "")) == type]
        terminal_mapping, success = find_best_match.find_best_match(tradeport_mapping_name, filtered_data, attributes=search_fields, score_cutoff=cutoff)
        if not success:
            return None
        
        return terminal_mapping["root_object"]
    
    def get_location(self, location_mapping_name):
        self._refresh_data()
        location_categories = [CATEGORY_SYSTEMS, CATEGORY_ORBITS, CATEGORY_MOONS, CATEGORY_CITIES, CATEGORY_OUTPOSTS, CATEGORY_STATIONS, CATEGORY_TERMINALS]
        
        for category in location_categories:
            location_mapping, success = find_best_match.find_best_match(
                location_mapping_name,
                self.data[category].get('data', {}),
                attributes=["name"]
            )
            if not success:
                continue

            location = location_mapping["root_object"]
            print_debug(f"found location '{location_mapping_name}' in category '{category}':\n {json.dumps(location_mapping, indent=2)}")
            return category, location
        
        return None, None
    
    def get_commodity(self, commodity_mapping_name):
        self._refresh_data()
        commodity_mapping, success = find_best_match.find_best_match(
            commodity_mapping_name,
            self.data[CATEGORY_COMMODITIES].get('data', {}),
            attributes=["name"]
        )
        if not success:
            return None
        
        commodity = commodity_mapping["root_object"]
        print_debug(f"found matching commodity for '{commodity_mapping_name}':\n {json.dumps(commodity, indent=2)}")
        return commodity

    def get_commodity_for_tradeport(self, commodity_mapping_name, tradeport):
        self._refresh_data()
        commodity_id = self.name_mapping[CATEGORY_COMMODITIES].get(commodity_mapping_name, None)
        # print_debug(f'uex: {commodity_mapping_name}-> {code} @ {tradeport["name_short"]}')
        if not commodity_id:
            return None
        
        commodity_prices = self.get_prices_of(price_category=PRICES_COMMODITIES, id_commodity=commodity_id, id_tradeport=tradeport[ID_FIELD_NAME])

        return commodity_prices[commodity_id] if commodity_prices else None
        
    def get_data(self, category):
        self._refresh_data()
        return self.data[category].get("data", [])
        
    def get_category_names(self, category: str, field_name: str = "name", filter: tuple[str, str] = None) -> list[str]:
        """
        Fetch names from a given category filtered by the provided attribute-value tuple.
        
        :param category: The category to fetch from, e.g., "terminals" or "planets".
        :param field_name: The field name to fetch, e.g., "name" or "nickname".
        :param filter: A tuple containing the filter attribute and filter value, e.g., ("is_available", "1").
        :return: A list of names (or other properties) from the filtered items.
        """
        self._refresh_data()
        
        if filter is None:
            return list(self.name_mapping[category].keys())
        
        category_data = self.data[category].get("data")

        filter_attribute, filter_value = filter
        # Filter the data based on the provided attribute and value
        filtered_data = [item for item in category_data.values() if str(item.get(filter_attribute, "")) == filter_value]

        # Assuming 'name' is a key in the dictionary that holds the name of the entity
        names = [item[field_name] for item in filtered_data]
        return names
        
    def update_tradeport_prices(self, tradeport, commodity_update_infos, operation):
        self._refresh_data()
        url = f"{self.base_url}data_submit/"
        
        if not ("code" in tradeport):
            return "missing code, rejected", False
        
        terminal_id = self.name_mapping[CATEGORY_TERMINALS][tradeport["name"]] if tradeport["name"] in self.name_mapping[CATEGORY_TERMINALS] else None        
        prices = []
        for commodity_info in commodity_update_infos:
            # {
            #     "commodity_name": "Medical Supplies",
            #     "available_SCU_quantity": 0,
            #     "inventory_state": "OUT OF STOCK",
            #     "price_per_unit": 1.92499995,
            #     "multiplier": "K",
            #     "currency": "\u00a2",
            #     "code": "MEDS",
            #     "uex_price": 1924.99995,
            #     "validation_result": "all plausible",
            #     "transmit": true
            # }
            if commodity_info["transmit"] is False:
                continue

            if commodity_info["commodity_name"] not in self.name_mapping[CATEGORY_COMMODITIES]:
                print_debug(f'unknown commodity id for {commodity_info["commodity_name"]}. Skipping update.')
                continue
            
            if "uex_price" not in commodity_info:
                print_debug(f'no valid price for {commodity_info["commodity_name"]}. Skipping update.')
                continue
            
            prices.append(
                {
                    "id_commodity": self.name_mapping[CATEGORY_COMMODITIES][commodity_info["commodity_name"]],
                    f"price_{operation}": commodity_info["uex_price"],
                    f"scu_{operation}": commodity_info["available_SCU_quantity"],
                    f"status_{operation}": self.inventory_state_mapping[commodity_info["inventory_state"]]
                }
            )
  
        update_data = {
            "id_terminal": terminal_id,
            "type": "commodity",
            "prices": prices
        }
        
        if not CALL_UEX_SR_ENDPOINT:
            possible_strings = ["2423", "1234", "5678", "53249", "5294"]
            possible_bools = [True, True, True, False]
            return random.choice(possible_strings), random.choice(possible_bools)

        if not TEST:
            update_data["is_production"] = "1"

        response = self.session.post(url, data=json.dumps(update_data), timeout=360)
        if response.status_code == 200:
            print_debug(f"UEX2 prices where accepted: {json.dumps(response.json(), indent=2)}")    
            return response.json(), True  # report id received
        
        print_debug(f"Fehler beim Abrufen von Daten von {url} mit params {json.dumps(update_data, indent=2)}: with response: {json.dumps(response.json(), indent=2)}")
        return response.json(), False  # error reason

    def add_refinery_job(self, work_order):
        url = f"{self.base_url}user_refineries_jobs_add/"

        if not CALL_UEX_SR_ENDPOINT:
            possible_strings = ["2423", "1234", "5678", "53249", "5294"]
            possible_bools = [True, True, True, False]
            return random.choice(possible_strings), random.choice(possible_bools)

        if not TEST:
            work_order["is_production"] = "1"

        response = self.session.post(url, data=json.dumps(work_order), timeout=360)
        if response.status_code == 200:
            print_debug(f"UEX refinery job added: {json.dumps(response.json(), indent=2)}")    
            return response.json(), True  # report id received
        
        print_debug(f"Error retrieving data from {url} mit params {json.dumps(work_order, indent=2)}: with response: {json.dumps(response.json(), indent=2)}")
        return response.json(), False  # error reason
    
    def get_refinery_jobs(self):
        url = f"{self.base_url}user_refineries_jobs/"

        response = self.session.get(url, timeout=360)
        if response.status_code == 200:
            print_debug(f"UEX refinery jobs retrieved: {json.dumps(response.json(), indent=2)}")    
            return response.json()["data"], True  # report id received
        
        print_debug(f"Error retrieving data from {url}: with response: {json.dumps(response.json(), indent=2)}")
        return response.json(), False  # error reason
    
    def delete_refinery_job(self, job_id):
        print_debug(f"UEX refinery job deleting: '{job_id}'")   
        url = f"{self.base_url}user_refineries_jobs_remove/id/{job_id}/is_production/1/"

        response = self.session.delete(url, timeout=360)
        if response.status_code == 200:
            print_debug(f"UEX refinery jobs deleted: {json.dumps(response.json(), indent=2)}")    
            return response.json()["data"], True  # report id received
        
        print_debug(f"Error deleting job from {url}: with response: {json.dumps(response.json(), indent=2)}")
        return response.json(), False  # error reason


if __name__ == "__main__":
    api = UEXApi2.init(uex_api_key="****", user_secret_key="****")
    import sys
    sys.path.append(os.path.abspath(r'D:\Dokumente\dev\python-projects\wigman-ai\wingman-ai'))
    from wingmen.star_citizen_services.helper import find_best_match

    # print("========= TEST start Hurston ========")
    # result = api.find_best_trade_from_location_code(location_name_from="Hurston")
    # print("RESULT:")
    # print(json.dumps(result, indent=2))

    # print("========= TEST start HDMS-Lathan ========")
    # result = api.find_best_trade_from_location_code(location_name_from="HDMS-Lathan")
    # print("RESULT:")
    # print(json.dumps(result, indent=2))

    # print("========= TEST start Arccorp ========")
    # result = api.find_best_trade_from_location_code(location_name_from="ArcCorp")
    # print("RESULT:")
    # print(json.dumps(result, indent=2))

    # print("========= TEST Arccorp -> Hurston ========")
    # result = api.find_best_trade_between_locations_code(location_name_from="ArcCorp", location_name_to="Hurston")
    # print("RESULT:")
    # print(json.dumps(result, indent=2))

    # print("========= TEST Hurston -> Arccorp ========")
    # result = api.find_best_trade_between_locations_code(location_name_from="hurton", location_name_to="Arccorp")
    # print("RESULT:")
    # print(json.dumps(result, indent=2))

    # print("========= TEST Medical Supplies -> Hurston ========")
    # result = api.find_best_sell_price_at_location_codes(commodity_name="Medical Supplies", location_name="Hurston")
    # print("RESULT:")
    # print(json.dumps(result, indent=2))

    # print("========= TEST where sell Laranite? ========")
    # result = api.find_best_selling_location_for_commodity_code(commodity_name="Laranite")
    # print("RESULT:")
    # print(json.dumps(result, indent=2))

    # print("========= TEST best trade for Medical Supplies? ========")
    # result = api.find_best_trade_for_commodity_code(commodity_name="Medical Supplies")
    # print("RESULT:")
    # print(json.dumps(result, indent=2))