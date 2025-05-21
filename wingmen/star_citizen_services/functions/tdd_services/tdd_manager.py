import json
import random

from services.printr import Printr

from wingmen.star_citizen_services.overlay import StarCitizenOverlay
from wingmen.star_citizen_services.functions.uex_v2.uex_api_module import UEXApi2
from wingmen.star_citizen_services.function_manager import FunctionManager
from wingmen.star_citizen_services.ai_context_enum import AIContext

from wingmen.star_citizen_services.helper import transform_numbers_in_words


DEBUG = False
# TEST = True

printr = Printr()


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class TddManager(FunctionManager):

    def __init__(self, config, secret_keeper):
        super().__init__(config, secret_keeper)
        self.config = config  # the wingmen config
        self.uex_service: UEXApi2 = UEXApi2()
        self.overlay: StarCitizenOverlay = StarCitizenOverlay()
        self.tdd_voice = self.config["openai"]["contexts"]["tdd_voice"]

    # @abstractmethod
    def get_context_mapping(self) -> AIContext:
        return AIContext.TDD
    
    # @abstractmethod
    def register_functions(self, function_register):
        function_register[self.get_trade_information_from_tdd_employee.__name__] = self.get_trade_information_from_tdd_employee
        function_register[self.switch_tdd_employee.__name__] = self.switch_tdd_employee
        
    # @abstractmethod
    def get_function_tools(self):
        # tradeport_names = self.uex_service.get_category_names("tradeports")
        # planet_names = self.uex_service.get_category_names("planets")
        # satellite_names = self.uex_service.get_category_names("satellites")
        # commodity_names = self.uex_service.get_category_names("commodities")
        # cities_names = self.uex_service.get_category_names("cities")

        # combined_locations_names = planet_names + satellite_names + cities_names + tradeport_names

        # commands = all defined keybinding label names
        tools = [
            {
                "type": "function",
                "function": 
                {
                    "name": self.get_trade_information_from_tdd_employee.__name__,
                    "description": (
                        "When asked for trading information,  "
                        "select the appropriate parameters to met the players request and make sure to follow the given instructions: "
                        "All locations can be planets, moons / satellites or a specific tradeport or even a terminal. "
                        "The player can ask for a specific location or a general area. "
                        "When he asks where he can sell something, use the location_name_end_or_sell parameter. "
                        "When he asks where he can buy something, use the location_name_start_or_buy parameter. "
                        "For any of the parameters, make sure to only use one of the allowed values. If there is none that matches, ask for clarification. "
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location_name_start_or_buy": {
                                "type": "string",
                                "description": "The location area, where the player wants buy a commodity or start a trade route from. Can be the name of a planet, a moon / satellite, system or a specific tradeport / terminal. Can be empty.",
                                # "enum": combined_locations_names
                            },
                            "location_name_end_or_sell": {
                                "type": "string",
                                "description": "The location area, where the player wants to sell a commodity or end a trade route. Can be the name of a planet, a moon / satellite, system or a specific tradeport / terminal. Can be empty.",
                                # "enum": combined_locations_names
                            },
                            "commodity_name": {
                                "type": "string",
                                "description": "One of the known commodities that the user wants to sell or buy. Can be empty.",
                                # "enum": commodity_names
                            },
                            "include_illegal_commodities": {
                                "type": "boolean",
                                "description": "Indicates if illegal or restricted commodities should be searched as well. Only True, if the user explicitely requests it."
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": 
                {
                    "name": self.switch_tdd_employee.__name__,
                    "description": "Whenever the player adresses a new Trading Division Departement, make this function call.",
                }
            }

        ]

        # print_debug(f"tools definition: {json.dumps(tools, indent=2)}")
        return tools

    # @abstractmethod
    def get_function_prompt(self):
        return (""
                # "When asked for trading information,  "
                # "select that appropriate parameters to met the players request and make sure to follow the given instructions: "
                # "All locations can be planets, moons / satellites or a specific tradeport or even a terminal. "
                # "The player can ask for a specific location or a general area. "
                # "When he asks where he can sell something, use the location_name_end_or_sell parameter. "
                # "When he asks where he can buy something, use the location_name_start_or_buy parameter. "
                # "For any of the parameters, make sure to only use one of the allowed values. If there is none that matches, ask for clarification. "
        )

    def get_trade_information_from_tdd_employee(self, function_args):
        print_debug(f"trade request: {function_args}")
        printr.print(f'Executing function call {self.get_trade_information_from_tdd_employee.__name__} with args {function_args}', tags="info")
        
        # Extract parameters
        location_from = function_args.get("location_name_start_or_buy")
        location_to = function_args.get("location_name_end_or_sell")
        commodity_name = function_args.get("commodity_name")
        not_found_message = ""
        
        # Determine which function to call based on provided parameters.
        if location_from and not location_to and not commodity_name:
            # Only location_from is provided -> find best trade route starting at location
            function_response = self.uex_service.find_best_trade_from_location_code(location_name_from=location_from)
            not_found_message = f"No trade found @'{location_from}'->."
        elif location_from and location_to:
            # Both locations provided -> find best trade route between locations
            function_response = self.uex_service.find_best_trade_between_locations_code(
                location_name_from=location_from,
                location_name_to=location_to)
            not_found_message = f"No trade found @'{location_from}'->{location_to}."
        elif commodity_name and location_to and not location_from:
            # Commodity and destination provided -> find tradeports at given location for commodity
            function_response = self.uex_service.find_best_sell_price_at_location_codes(location_name=location_to, commodity_name=commodity_name)
            not_found_message = f"No trade found @'{location_to}' for {commodity_name}."
        elif commodity_name and not location_from and not location_to:
            function_response = self.uex_service.find_best_selling_location_for_commodity_code(commodity_name=commodity_name)
            not_found_message = f"No trade found for {commodity_name}."
        elif location_to and not location_from and not commodity_name:
            # Only location_to provided -> find best trade routes around the location
            function_response = self.uex_service.find_best_trade_between_locations_code(location_name_from=location_to, location_name_to=location_to)
            not_found_message = f"No trade for destination '{location_to}'."
        else:
            # In case the provided parameters are insufficient or ambiguous, ask the player for clarification.
            return {"instructions": "Could not identify the trade request. Please provide more details."}
        
        # Process response
        success = function_response.get("success", False)
        if success and function_response.get("trade_routes"):
            trade_route = function_response["trade_routes"][0]
            # Safely retrieve keys with fallback values
            moon_or_planet_buy = trade_route.get("buy_moon", "") or trade_route.get("buy_orbit", "")
            moon_or_planet_sell = trade_route.get("sell_moon", "") or trade_route.get("sell_orbit", "")
            if commodity_name and moon_or_planet_sell and not moon_or_planet_buy:
                self.overlay.display_overlay_text(
                    f'Sell {trade_route["commodity"]} at {trade_route["sell_at_tradeport_name"]} ({moon_or_planet_sell}) for {trade_route["sell_price"]} aUEC.'
                )
                print_debug(f'Sell {trade_route["commodity"]} at {trade_route["sell_at_tradeport_name"]} ({moon_or_planet_sell}) for {trade_route["sell_price"]} aUEC.')
            else:
                self.overlay.display_overlay_text(
                    f'Buy {trade_route["commodity"]} at {trade_route["buy_at_tradeport_name"]} ({moon_or_planet_buy}). '
                    f'Sell at {trade_route["sell_at_tradeport_name"]} ({moon_or_planet_sell}). Profit: {trade_route["profit"]} aUEC.'
                )
                print_debug(f'Buy {trade_route["commodity"]} at {trade_route["buy_at_tradeport_name"]} ({moon_or_planet_buy}). '
                            f'Sell at {trade_route["sell_at_tradeport_name"]} ({moon_or_planet_sell}).')
        else:
            # If not successful, display the error message if available.
            message = function_response.get("message", not_found_message)
            self.overlay.display_overlay_text(message)
            print_debug(message)
            
        printr.print(f'-> Resultat: {json.dumps(function_response, indent=2)}', tags="info")
        transform_numbers_in_words.transform_numbers(function_response)
        return function_response

    def switch_tdd_employee(self, function_args):
        tdd_voices = set(self.config["openai"]["contexts"]["tdd_voices"].split(","))
        tdd_voices.remove(self.tdd_voice)
        self.tdd_voice = random.choice(list(tdd_voices))
        self.config["openai"]["contexts"]["tdd_voice"] = self.tdd_voice
        self.config["openai"]["tts_voice"] = self.tdd_voice
        printr.print("TDD Department changed", tags="info")
        return json.dumps(
            {"success": True, 
                "instructions": (
                    f"You are now a new Trade and Developmenent Employee. Please briefly introduce yourself giving you a first name in the star citizen universe. Your gender should match the voice you are using: {self.tdd_voice}. "
                    "Tell the player your position within the requested TDD-Departement and ask him how you can help. Example: 'Hello, my name is Lilia from the Hurston Trading Devision. I'm your trade operator, how can I help you?'"
                )
            }), None