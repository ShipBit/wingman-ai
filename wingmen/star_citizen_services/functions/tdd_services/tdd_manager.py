import json

from services.printr import Printr

from wingmen.star_citizen_services.overlay import StarCitizenOverlay
from wingmen.star_citizen_services.functions.uex_v2.uex_api_module import UEXApi2
from wingmen.star_citizen_services.function_manager import FunctionManager
from wingmen.star_citizen_services.ai_context_enum import AIContext

DEBUG = False
# TEST = True

printr = Printr()


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class TddManager(FunctionManager):
    MANAGER_CONTEXT = AIContext.CORA
    MANAGER_DESCRIPTION = "Provides trading information about commodities and trade routes."
    MANAGER_CAPABILITIES = [
        "Find the best trade route from/between locations",
        "Find the best selling locations for commodities",
    ]

    def __init__(self, config, secret_keeper):
        super().__init__(config, secret_keeper)
        self.config = config  # the wingmen config
        self.uex_service: UEXApi2 = UEXApi2()
        self.overlay: StarCitizenOverlay = StarCitizenOverlay()

    # @abstractmethod
    def get_context_mapping(self) -> AIContext:
        return self.MANAGER_CONTEXT
    
    # @abstractmethod
    def register_functions(self, function_register):
        function_register[self.get_commodity_price.__name__] = self.get_commodity_price
        function_register[self.find_commodity_trade_locations.__name__] = self.find_commodity_trade_locations
        function_register[self.get_buyable_commodities_at_location.__name__] = self.get_buyable_commodities_at_location
        function_register[self.can_buy_commodity_at_location.__name__] = self.can_buy_commodity_at_location
        function_register[self.find_trade_routes.__name__] = self.find_trade_routes
        function_register[self.get_trade_information.__name__] = self.get_trade_information
        
    # @abstractmethod
    def get_function_tools(self):
        # tradeport_names = self.uex_service.get_category_names("tradeports")
        # planet_names = self.uex_service.get_category_names("planets")
        # satellite_names = self.uex_service.get_category_names("satellites")
        # commodity_names = self.uex_service.get_category_names("commodities")
        # cities_names = self.uex_service.get_category_names("cities")

        # combined_locations_names = planet_names + satellite_names + cities_names + tradeport_names

        tools = [
            {
                "type": "function",
                "function": {
                    "name": self.get_commodity_price.__name__,
                    "description": (
                        "Use for commodity price questions only. "
                        "'What does X cost?' means buy_average. "
                        "'How much do I get for X?' means sell_average. "
                        "Do not use for where-to-buy, where-to-sell, or route questions."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "commodity_name": {
                                "type": "string",
                                "description": "Commodity name or fragment exactly as the player said it. Do not replace unclear names with another known commodity."
                            },
                            "price_type": {
                                "type": "string",
                                "description": "Requested price direction.",
                                "enum": ["buy_average", "sell_average"]
                            },
                            "location_name": {
                                "type": "string",
                                "description": "Optional planet, moon, system, city, station, outpost, tradeport, or terminal."
                            }
                        },
                        "required": ["commodity_name", "price_type"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": self.find_commodity_trade_locations.__name__,
                    "description": (
                        "Use for questions asking where a commodity can be bought or sold. "
                        "Do not use for average price, route questions, 'what can I buy at location', "
                        "or yes/no questions like 'can I buy commodity at location'."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "commodity_name": {
                                "type": "string",
                                "description": "Commodity name or fragment exactly as the player said it. Do not replace unclear names with another known commodity."
                            },
                            "operation": {
                                "type": "string",
                                "description": "buy for where-can-I-buy, sell for where-can-I-sell.",
                                "enum": ["buy", "sell"]
                            },
                            "location_name": {
                                "type": "string",
                                "description": "Optional planet, moon, system, city, station, outpost, tradeport, or terminal restriction."
                            }
                        },
                        "required": ["commodity_name", "operation"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": self.get_buyable_commodities_at_location.__name__,
                    "description": (
                        "Use for questions asking what commodities can be bought at a location, "
                        "for example 'What can I buy at XYZ?' or 'Was kann ich bei XYZ kaufen?'. "
                        "Return commodity names only, no prices."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location_name": {
                                "type": "string",
                                "description": "Planet, moon, system, city, station, outpost, tradeport, or terminal exactly as the player said it."
                            }
                        },
                        "required": ["location_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": self.can_buy_commodity_at_location.__name__,
                    "description": (
                        "Use for yes/no questions asking whether a specific commodity can be bought at a specific location, "
                        "for example 'Can I buy ABC at XYZ?' or 'Kann ich an XYZ ABC kaufen?'. "
                        "Answer by speech only and mention the terminal where it can be bought. Do not include prices."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location_name": {
                                "type": "string",
                                "description": "Planet, moon, system, city, station, outpost, tradeport, or terminal exactly as the player said it."
                            },
                            "commodity_name": {
                                "type": "string",
                                "description": "Commodity name or fragment exactly as the player said it. Do not replace unclear names with another known commodity."
                            }
                        },
                        "required": ["location_name", "commodity_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": self.find_trade_routes.__name__,
                    "description": (
                        "Use for trade route questions, profit route questions, or 'how can I trade X'. "
                        "Do not use for plain price questions."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "commodity_name": {
                                "type": "string",
                                "description": "Optional commodity name or fragment exactly as the player said it for commodity-specific routes."
                            },
                            "location_name_from": {
                                "type": "string",
                                "description": "Optional route start location."
                            },
                            "location_name_to": {
                                "type": "string",
                                "description": "Optional route target location."
                            }
                        }
                    }
                }
            },
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

    @staticmethod
    def _optional_arg(function_args, key):
        value = function_args.get(key)
        if isinstance(value, str):
            value = value.strip()
        return value or None

    @staticmethod
    def _first_route(function_response):
        routes = function_response.get("trade_routes") or []
        if routes:
            return routes[0]

        community_routes = function_response.get("uex_community_trade_routes") or []
        if community_routes:
            return community_routes[0]

        return None

    @staticmethod
    def _route_commodity(route):
        return route.get("commodity") or route.get("commodity_name", "")

    @staticmethod
    def _route_origin_name(route):
        return route.get("buy_at_tradeport_name") or route.get("origin_terminal_name", "")

    @staticmethod
    def _route_destination_name(route):
        return route.get("sell_at_tradeport_name") or route.get("destination_terminal_name", "")

    @staticmethod
    def _route_origin_area(route):
        return (
            route.get("buy_moon")
            or route.get("buy_orbit")
            or route.get("buy_system")
            or route.get("origin_orbit_name")
            or route.get("origin_planet_name")
            or route.get("origin_star_system_name")
            or ""
        )

    @staticmethod
    def _route_destination_area(route):
        return (
            route.get("sell_moon")
            or route.get("sell_orbit")
            or route.get("sell_system")
            or route.get("destination_orbit_name")
            or route.get("destination_planet_name")
            or route.get("destination_star_system_name")
            or ""
        )

    @staticmethod
    def _route_buy_price(route):
        return route.get("buy_price") or route.get("price_origin", "")

    @staticmethod
    def _route_sell_price(route):
        return route.get("sell_price") or route.get("price_destination", "")

    def _finish_tdd_response(self, function_response, fallback_message=None):
        function_response["do_not_cache"] = True
        if not function_response.get("success", False):
            message = function_response.get("message", fallback_message or "No trade information found.")
            if not function_response.get("suppress_overlay"):
                self.overlay.display_overlay_text(message)
            print_debug(message)

        printr.print(f'-> Resultat: {json.dumps(function_response, indent=2)}', tags="info")
        return function_response

    @staticmethod
    def _format_commodity_overlay_list(commodity_names, names_per_line=3):
        lines = []
        for index in range(0, len(commodity_names), names_per_line):
            lines.append(", ".join(commodity_names[index:index + names_per_line]))
        return "\n".join(lines)

    def _add_price_summary(self, function_response, location_name=None):
        if not function_response.get("success"):
            return

        operation = function_response.get("operation")
        commodity = function_response.get("commodity")
        average_price = function_response.get("average_price")
        price_label = "buying" if operation == "buy" else "selling"
        location_suffix = f" at {location_name}" if location_name else ""

        function_response["summary_payload"] = {
            "result_type": "commodity_price",
            "commodity": commodity,
            "price_type": f"{operation}_average",
            "location": location_name,
            "average_price": average_price,
            "currency": "alpha you ee see",
            "minimum_price": function_response.get("minimum_price"),
            "maximum_price": function_response.get("maximum_price"),
            "price_count": function_response.get("price_count"),
            "spoken_instruction": (
                f"Answer with the average {price_label} price only. "
                "Name the currency as alpha you ee see. "
                "Write out all numbers in words and do not use decimal places. "
                "Do not mention routes or alternatives."
            )
        }
        self.overlay.display_overlay_text(
            f'{commodity}: average {price_label} price{location_suffix}: {average_price} aUEC.'
        )

    def _add_location_summary(self, function_response, operation, location_name=None):
        function_response.pop("uex_community_trade_routes", None)
        if not function_response.get("success"):
            return

        route = self._first_route(function_response)
        if not route:
            return

        commodity = self._route_commodity(route)
        if operation == "sell":
            terminal = route.get("sell_at_tradeport_name", "")
            area = self._route_destination_area(route)
            price = route.get("sell_price", "")
            action = "Sell"
            price_key = "sell_price"
        else:
            terminal = route.get("buy_at_tradeport_name", "")
            area = self._route_origin_area(route)
            price = route.get("buy_price", "")
            action = "Buy"
            price_key = "buy_price"

        function_response["result_type"] = "commodity_locations"
        function_response["operation"] = operation
        function_response["result_interpretation_instructions"] = (
            "Answer only where the commodity can be bought or sold. "
            "Mention the best option first. Do not describe trade routes."
        )
        function_response["summary_payload"] = {
            "result_type": "commodity_locations",
            "operation": operation,
            "commodity": commodity,
            "location_filter": location_name,
            "best_result": {
                "terminal": terminal,
                "area": area,
                "currency": "alpha you ee see",
                price_key: price
            },
            "number_of_alternatives": function_response.get("number_of_alternatives", 1),
            "spoken_instruction": (
                "Keep the answer to one short sentence. "
                "Name the currency as alpha you ee see. "
                "Write out all numbers in words."
            )
        }
        self.overlay.display_overlay_text(f'{action} {commodity} at {terminal} ({area}) for {price} aUEC.')

    def _add_route_summary(self, function_response):
        if not function_response.get("success"):
            return

        route = self._first_route(function_response)
        if not route:
            return

        function_response["summary_payload"] = {
            "result_type": "trade_route",
            "commodity": self._route_commodity(route),
            "buy": {
                "terminal": self._route_origin_name(route),
                "area": self._route_origin_area(route),
                "price": self._route_buy_price(route),
                "currency": "alpha you ee see"
            },
            "sell": {
                "terminal": self._route_destination_name(route),
                "area": self._route_destination_area(route),
                "price": self._route_sell_price(route),
                "currency": "alpha you ee see"
            },
            "profit": route.get("profit", ""),
            "profit_currency": "alpha you ee see",
            "number_of_alternatives": function_response.get("number_of_alternatives", 1),
            "spoken_instruction": (
                "Describe the best route only. Mention alternatives only as a count. "
                "Name the currency as alpha you ee see. "
                "Write out all numbers in words. "
                "Keep the answer concise."
            )
        }
        self.overlay.display_overlay_text(
            f'Buy {self._route_commodity(route)} at {self._route_origin_name(route)} '
            f'({self._route_origin_area(route)}). Sell at {self._route_destination_name(route)} '
            f'({self._route_destination_area(route)}). Profit: {route.get("profit", "")} aUEC.'
        )

    def _add_buyable_commodities_summary(self, function_response, location_name):
        if not function_response.get("success"):
            return

        commodity_names = function_response.get("commodity_names") or []
        function_response["summary_payload"] = {
            "result_type": "buyable_commodities_at_location",
            "location": function_response.get("location") or location_name,
            "commodity_names": commodity_names,
            "commodity_count": len(commodity_names),
            "spoken_instruction": (
                "Name only the buyable commodities. Do not mention prices. "
                "Keep the answer concise and comma-separated."
            )
        }

    def _add_can_buy_summary(self, function_response, commodity_name, location_name):
        route = self._first_route(function_response)
        can_buy = function_response.get("success", False) and bool(route)

        if can_buy:
            terminal = route.get("buy_at_tradeport_name", "")
            commodity = self._route_commodity(route) or commodity_name
            function_response["result_type"] = "can_buy_commodity_at_location"
            function_response["summary_payload"] = {
                "result_type": "can_buy_commodity_at_location",
                "can_buy": True,
                "commodity": commodity,
                "location": location_name,
                "terminal": terminal,
                "spoken_instruction": (
                    "Answer with one short spoken sentence. Say that the commodity can be bought there "
                    "and mention the terminal. Do not mention prices."
                )
            }
            return

        function_response["suppress_overlay"] = True
        function_response["summary_payload"] = {
            "result_type": "can_buy_commodity_at_location",
            "can_buy": False,
            "commodity": commodity_name,
            "location": location_name,
            "spoken_instruction": (
                "Answer with one short spoken sentence. Say that the commodity cannot be bought there, "
                "or that the location or commodity was not recognized if the tool result says so. "
                "Do not mention prices."
            )
        }

    def get_commodity_price(self, function_args):
        print_debug(f"commodity price request: {function_args}")
        printr.print(
            f'Executing function call {self.get_commodity_price.__name__} with args {function_args}',
            tags="info"
        )

        commodity_name = self._optional_arg(function_args, "commodity_name")
        price_type = self._optional_arg(function_args, "price_type")
        location_name = self._optional_arg(function_args, "location_name")

        if not commodity_name or price_type not in {"buy_average", "sell_average"}:
            return {
                "success": False,
                "message": "Could not identify the requested commodity price.",
                "do_not_cache": True
            }

        function_response = self.uex_service.find_commodity_price_information_code(
            commodity_name=commodity_name,
            price_type=price_type,
            location_name=location_name
        )
        self._add_price_summary(function_response, location_name)
        return self._finish_tdd_response(function_response, f"No price found for {commodity_name}.")

    def find_commodity_trade_locations(self, function_args):
        print_debug(f"commodity location request: {function_args}")
        printr.print(
            f'Executing function call {self.find_commodity_trade_locations.__name__} with args {function_args}',
            tags="info"
        )

        commodity_name = self._optional_arg(function_args, "commodity_name")
        operation = self._optional_arg(function_args, "operation") or "sell"
        location_name = self._optional_arg(function_args, "location_name")

        if not commodity_name or operation not in {"buy", "sell"}:
            return {
                "success": False,
                "message": "Could not identify the requested trade location.",
                "do_not_cache": True
            }

        if operation == "sell" and location_name:
            function_response = self.uex_service.find_best_sell_price_at_location_codes(
                commodity_name=commodity_name,
                location_name=location_name
            )
        elif operation == "sell":
            function_response = self.uex_service.find_best_selling_location_for_commodity_code(
                commodity_name=commodity_name
            )
        elif location_name:
            function_response = self.uex_service.find_best_buy_price_at_location_codes(
                commodity_name=commodity_name,
                location_name=location_name
            )
        else:
            function_response = self.uex_service.find_best_buying_location_for_commodity_code(
                commodity_name=commodity_name
            )

        self._add_location_summary(function_response, operation, location_name)
        return self._finish_tdd_response(function_response, f"No {operation} location found for {commodity_name}.")

    def get_buyable_commodities_at_location(self, function_args):
        print_debug(f"buyable commodities at location request: {function_args}")
        printr.print(
            f'Executing function call {self.get_buyable_commodities_at_location.__name__} with args {function_args}',
            tags="info"
        )

        location_name = self._optional_arg(function_args, "location_name")
        if not location_name:
            return {
                "success": False,
                "message": "Could not identify the requested location.",
                "do_not_cache": True
            }

        function_response = self.uex_service.find_buyable_commodities_at_location_code(location_name)
        commodity_names = function_response.get("commodity_names") or []
        if function_response.get("success") and len(commodity_names) <= 9:
            function_response["display_mode"] = "overlay"
            function_response["suppress_tts"] = True
            self.overlay.display_overlay_text(self._format_commodity_overlay_list(commodity_names))
        elif function_response.get("success"):
            function_response["display_mode"] = "speech"
            function_response["suppress_overlay"] = True
            self._add_buyable_commodities_summary(function_response, location_name)

        return self._finish_tdd_response(
            function_response,
            f"No buyable commodities found at {location_name}."
        )

    def can_buy_commodity_at_location(self, function_args):
        print_debug(f"can buy commodity at location request: {function_args}")
        printr.print(
            f'Executing function call {self.can_buy_commodity_at_location.__name__} with args {function_args}',
            tags="info"
        )

        location_name = self._optional_arg(function_args, "location_name")
        commodity_name = self._optional_arg(function_args, "commodity_name")
        if not location_name or not commodity_name:
            return {
                "success": False,
                "message": "Could not identify the requested commodity or location.",
                "do_not_cache": True,
                "suppress_overlay": True
            }

        function_response = self.uex_service.find_best_buy_price_at_location_codes(
            commodity_name=commodity_name,
            location_name=location_name
        )
        function_response["suppress_overlay"] = True
        self._add_can_buy_summary(function_response, commodity_name, location_name)
        return self._finish_tdd_response(
            function_response,
            f"No buying terminal found for {commodity_name} at {location_name}."
        )

    def find_trade_routes(self, function_args):
        print_debug(f"trade route request: {function_args}")
        printr.print(
            f'Executing function call {self.find_trade_routes.__name__} with args {function_args}',
            tags="info"
        )

        commodity_name = self._optional_arg(function_args, "commodity_name")
        location_from = self._optional_arg(function_args, "location_name_from")
        location_to = self._optional_arg(function_args, "location_name_to")

        if commodity_name:
            function_response = self.uex_service.find_best_trade_for_commodity_at_location_codes(
                commodity_name=commodity_name,
                location_name_from=location_from,
                location_name_to=location_to
            )
            fallback_message = f"No trade route found for {commodity_name}."
        elif location_from and location_to:
            function_response = self.uex_service.find_best_trade_between_locations_code(
                location_name_from=location_from,
                location_name_to=location_to
            )
            fallback_message = f"No trade route found from {location_from} to {location_to}."
        elif location_from:
            function_response = self.uex_service.find_best_trade_from_location_code(
                location_name_from=location_from
            )
            fallback_message = f"No trade route found from {location_from}."
        elif location_to:
            function_response = self.uex_service.find_best_trade_between_locations_code(
                location_name_from=location_to,
                location_name_to=location_to
            )
            fallback_message = f"No trade route found around {location_to}."
        else:
            return {
                "success": False,
                "message": "Could not identify the trade route request.",
                "do_not_cache": True
            }

        self._add_route_summary(function_response)
        return self._finish_tdd_response(function_response, fallback_message)

    def get_trade_information(self, function_args):
        print_debug(f"trade request: {function_args}")
        printr.print(f'Executing function call {self.get_trade_information.__name__} with args {function_args}', tags="info")

        location_from = self._optional_arg(function_args, "location_name_start_or_buy")
        location_to = self._optional_arg(function_args, "location_name_end_or_sell")
        commodity_name = self._optional_arg(function_args, "commodity_name")

        if commodity_name and location_to and not location_from:
            return self.find_commodity_trade_locations({
                "commodity_name": commodity_name,
                "operation": "sell",
                "location_name": location_to
            })

        if commodity_name and location_from and not location_to:
            return self.find_commodity_trade_locations({
                "commodity_name": commodity_name,
                "operation": "buy",
                "location_name": location_from
            })

        if commodity_name and not location_from and not location_to:
            return self.find_commodity_trade_locations({
                "commodity_name": commodity_name,
                "operation": "sell"
            })

        return self.find_trade_routes({
            "location_name_from": location_from,
            "location_name_to": location_to
        })
