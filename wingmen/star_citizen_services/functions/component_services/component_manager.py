import requests
import json

from services.printr import Printr
from wingmen.star_citizen_services.function_manager import FunctionManager
from wingmen.star_citizen_services.ai_context_enum import AIContext

DEBUG = True
printr = Printr()


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class ComponentManager(FunctionManager):
    """
    Manager for searching and retrieving ship component information from the Star Citizen Wiki API.
    Handles queries about coolers, power plants, quantum drives, and shields.
    """

    def __init__(self, config, secret_keeper):
        super().__init__(config, secret_keeper)
        self.api_base_url = "https://api.star-citizen.wiki/api/items"
        self.component_classifications = [
            "Ship.Cooler",
            "Ship.PowerPlant",
            "Ship.QuantumDrive",
            "Ship.Shield"
        ]
        self.valid_classes = [
            "Civilian",
            "Competition",
            "Industrial",
            "Military",
            "Stealth"
        ]

    def get_context_mapping(self) -> AIContext:
        return AIContext.CORA

    def register_functions(self, function_register):
        function_register[self.search_ship_component.__name__] = self.search_ship_component

    def get_function_prompt(self) -> str:
        return (
            f"Call the function {self.search_ship_component.__name__} when the user asks about components. Do not use the galactapedia function for components. This function is specifically designed to search for ship components "
            "like coolers, power plants, quantum drives, or shields. You can search by component name and optionally "
            "filter by size (1 to 12), grade (A to G), or class. "
            "IMPORTANT: The 'component_class' parameter refers to the component's quality/purpose class "
            "(Civilian, Competition, Industrial, Military, Stealth), NOT the component type (cooler, power plant, etc.). "
            "The component type (cooler, quantum drive, etc.) is automatically included in the search. "
            "Provide the information in a TTS-friendly format without mentioning technical details like URLs or API responses."
        )

    def get_function_tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": self.search_ship_component.__name__,
                    "description": "Searches for ship components (coolers, power plants, quantum drives, shields) by name with optional filters for size, grade, and quality class.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "component_name": {
                                "type": "string",
                                "description": "Name or partial name of the component to search for.",
                            },
                            "size": {
                                "type": "integer",
                                "description": "Optional size filter (1-12).",
                            },
                            "grade": {
                                "type": "string",
                                "description": "Optional grade filter (A-G).",
                            },
                            "component_class": {
                                "type": "string",
                                "description": "Optional quality/purpose class filter. Valid values: Civilian, Competition, Industrial, Military, Stealth. Do NOT use component types (cooler, power plant, etc.) here.",
                                "enum": ["Civilian", "Competition", "Industrial", "Military", "Stealth"]
                            },
                        },
                        "required": ["component_name"],
                    },
                },
            },
        ]

    def search_ship_component(self, function_args):
        """
        Searches for ship components using the Star Citizen Wiki API.
        Returns relevant component information including type, manufacturer, size, class, grade, and pricing.
        """
        component_name = function_args.get("component_name", "")
        size_filter = function_args.get("size", None)
        grade_filter = function_args.get("grade", None)
        class_filter = function_args.get("component_class", None)

        # Validate class filter - only use if it's a valid class value
        if class_filter and class_filter not in self.valid_classes:
            print_debug(
                f"Invalid class filter '{class_filter}' ignored. "
                f"Valid values: {', '.join(self.valid_classes)}"
            )
            printr.print(
                f"Invalid class filter '{class_filter}' ignored. "
                f"Valid classes are: {', '.join(self.valid_classes)}",
                tags="warning"
            )
            class_filter = None

        print_debug(
            f"{self.search_ship_component.__name__} called with component_name='{component_name}', "
            f"size={size_filter}, grade={grade_filter}, class={class_filter}"
        )
        printr.print(
            f"Executing function '{self.search_ship_component.__name__}' for component '{component_name}'.",
            tags="info"
        )

        # Build query parameters
        params = {
            "filter[classification]": ",".join(self.component_classifications),
            "filter[name]": component_name,
        }

        if size_filter:
            params["filter[size]"] = size_filter
        if grade_filter:
            params["filter[grade]"] = grade_filter
        if class_filter:
            params["filter[class]"] = class_filter

        with requests.Session() as session:
            session.headers.update({
                "accept": "application/json",
                "Content-Type": "application/json"
            })

            try:
                response = session.get(self.api_base_url, params=params, timeout=5)
                response.raise_for_status()
                data = response.json()

                results = data.get("data", [])

                if not results:
                    printr.print(f"No components found for '{component_name}'.", tags="info")
                    return {
                        "success": False,
                        "additional_instructions": (
                            f"No ship component found with the name '{component_name}'. "
                            "Please verify the component name or try a different search term. "
                            "Only ship components like coolers, power plants, quantum drives, and shields are searchable with this function."
                        ),
                    }

                # Extract relevant information
                components_info = []
                for item in results[:10]:  # Limit to first 10 results
                    component_info = {
                        "name": item.get("name"),
                        "type": item.get("type"),
                        "manufacturer": item.get("manufacturer_description"),
                        "size": item.get("size"),
                        "class": item.get("class"),
                        "grade": item.get("grade"),
                        "purchasable_ingame": len(item.get("shops", [])) > 0,
                        "price": None,
                        "price_location": None
                    }

                    # Get cheapest price if available
                    uex_prices = item.get("uex_prices", [])
                    if uex_prices:
                        # Find the cheapest price based on price_buy
                        cheapest = min(uex_prices, key=lambda x: x.get("price_buy", float('inf')))
                        component_info["price"] = cheapest.get("price_buy")
                        component_info["price_location"] = cheapest.get("terminal_name")

                    components_info.append(component_info)

                printr.print(
                    f"Found {len(results)} component(s): {json.dumps(components_info, indent=2)}",
                    tags="info"
                )

                # Check if there are too many results
                total_results = len(results)
                if total_results > 3:
                    filter_suggestions = []
                    if not size_filter:
                        filter_suggestions.append("size (1 to 12)")
                    if not grade_filter:
                        filter_suggestions.append("grade (A to G)")
                    if not class_filter:
                        filter_suggestions.append("class (Civilian, Competition, Industrial, Military, or Stealth)")

                    additional_info = ""
                    if filter_suggestions:
                        suggestions_text = ", ".join(filter_suggestions)
                        additional_info = (
                            f" The user can refine the search by specifying {suggestions_text}."
                        )

                    return {
                        "success": True,
                        "additional_instructions": (
                            f"Found {total_results} components matching '{component_name}'. "
                            f"Showing the first {min(total_results, 3)} results.{additional_info} "
                            "Provide a TTS-friendly summary of the most relevant components. "
                            "Mention name, manufacturer, type, size, class, and grade for each. "
                            "If purchasable in-game, mention the cheapest price in alphaUEC and where to buy it."
                        ),
                        "components": components_info,
                        "total_found": total_results,
                    }
                else:
                    return {
                        "success": True,
                        "additional_instructions": (
                            "Provide a TTS-friendly summary of the component information. "
                            "Mention name, manufacturer, type, size, class, and grade. "
                            "If purchasable in-game, mention the cheapest price in alphaUEC and where to buy it. "
                            "Speak naturally without mentioning technical details."
                        ),
                        "components": components_info,
                        "total_found": total_results,
                    }

            except requests.exceptions.RequestException as e:
                print_debug(f"{self.search_ship_component.__name__} exception: {str(e)}")
                printr.print(f"Error searching for component '{component_name}': {str(e)}", tags="error")
                return {
                    "success": False,
                    "additional_instructions": (
                        "The ship component database is currently unavailable. Please try again later."
                    ),
                    "error": str(e),
                }


if __name__ == "__main__":
    # Test the ComponentManager
    cm = ComponentManager({}, {})
    print("Testing ComponentManager...")
    result = cm.search_ship_component({"component_name": "FullStop"})
    print(json.dumps(result, indent=2))
