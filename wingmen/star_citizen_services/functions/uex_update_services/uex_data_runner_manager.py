import os
import json
import datetime

from openai import OpenAI

from services.secret_keeper import SecretKeeper
from services.printr import Printr

from wingmen.star_citizen_services.function_manager import FunctionManager
from wingmen.star_citizen_services.ai_context_enum import AIContext
from wingmen.star_citizen_services.helper import screenshots
from wingmen.star_citizen_services.helper.ocr import OCR

from wingmen.star_citizen_services.location_name_matching import LocationNameMatching
from wingmen.star_citizen_services.overlay import StarCitizenOverlay

from wingmen.star_citizen_services.functions.uex_update_services.data_validation_popup import OverlayPopup
from wingmen.star_citizen_services.functions.uex_update_services.commodity_price_validator import CommodityPriceValidator
from wingmen.star_citizen_services.functions.uex_v2.uex_api_module import UEXApi2


DEBUG = False
TEST = False


def print_debug(to_print):
    if DEBUG:
        print(to_print)


printr = Printr()


class UexDataRunnerManager(FunctionManager):
    
    def __init__(self, config, secret_keeper: SecretKeeper):
        super().__init__(config, secret_keeper)
        self.config = config
        self.data_dir_path = f'{self.config["data-root-directory"]}uex/kiosk_analyzer'
        self.openai_api_key = secret_keeper.retrieve(
            requester="UexDataRunnerManager",
            key="openai",
            friendly_key_name="OpenAI API key",
            prompt_if_missing=False
        )
        self.client: OpenAI = OpenAI(api_key=self.openai_api_key)

        self.best_template_index = 1
        
        self.function_name = "transmit_commodity_prices_for_tradeport"

        self.screenshots_path = f"{self.data_dir_path}/screenshots"

        self.uex2_api_key = secret_keeper.retrieve(
            requester="UexDataRunnerManager",
            key="uex2_api_key",
            friendly_key_name="UEX2 API key",
            prompt_if_missing=True
        )
        self.uex2_secret_key = secret_keeper.retrieve(
            requester="UexDataRunnerManager",
            key="uex2_secret_key",
            friendly_key_name="UEX2 secret user key",
            prompt_if_missing=True
        )
        self.uex2_service = UEXApi2.init(
            uex_api_key=self.uex2_api_key,
            user_secret_key=self.uex2_secret_key
        )
        self.overlay = StarCitizenOverlay()
        self.current_timestamp = None

        if not os.path.exists(self.screenshots_path):
            os.makedirs(self.screenshots_path)

        with open(f'{self.data_dir_path}/templates/response_structure_commodity_prices.prompt', 'r', encoding="UTF-8") as file:
            ocr_commodity_prices_prompt = file.read()

        # JSON-String direkt verwenden
        prompt = ocr_commodity_prices_prompt   

        self.commodity_prices_ocr = OCR(
            open_ai_model=f'{self.config["open-ai-vision-model"]}',
            openai_api_key=self.openai_api_key, 
            data_dir=self.data_dir_path,
            extraction_instructions=prompt,
            overlay=self.overlay)
        
    # @abstractmethod
    def get_context_mapping(self) -> AIContext:
        """  
            This method returns the context this manager is associated to
        """
        return AIContext.CORA
    
    # @abstractmethod
    def register_functions(self, function_register):
        function_register[self.transmit_commodity_prices_for_tradeport.__name__] = self.transmit_commodity_prices_for_tradeport
    
    # @abstractmethod
    def get_function_prompt(self):
        return (
            "If user asks to transmit commodity prices, call "
            f"'{self.transmit_commodity_prices_for_tradeport.__name__}' when player wants to transmit prices from trading terminal. "
            "Ask for missing terminal name or trading operation (buy/sell) if not provided. Only use explicitly provided information. Do not ask for confirmation, if all information is provided."
            "No context switch to TDD."
        )
    
    # @abstractmethod
    def get_function_tools(self):
        """ 
        Provides the openai function definition for this manager. 
        """
        tradeport_names = self.uex2_service.get_category_names(category="terminals", field_name="name")

        tools = [
            {
                "type": "function",
                "function": 
                {
                    "name": self.transmit_commodity_prices_for_tradeport.__name__,
                    "description": "Function to transmit commodity prices to the uex corp. Call this function on phrases like 'New prices for transmission'. Only fill values with user provided input.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "player_provided_terminal_name": {
                                "type": "string",
                                "description": "The terminal name provided by the user. Ask, if he didn't provide a terminal / tradeport name.",
                                "enum": tradeport_names
                            },
                            "terminal_type": {
                                "type": "string",
                                "description": "The type of terminal that the user is asking for. ",
                                "enum": ["commodity","item","commodity_raw","vehicle_buy","vehicle_rent","fuel","refinery_audit", None]
                            },
                            "operation": {
                                "type": "string",
                                "description": "What kind of prices the user want to transmit. 'buy' is for buyable commodities at the location, 'sell' are for sellable commodities.",
                                "enum": ["sell", "buy", None]
                            }
                        },
                    }
                }
            }
        ]

        # print_debug(json.dumps(tools, indent=2))
        return tools

    def transmit_commodity_prices_for_tradeport(self, function_args):
        printr.print(f'-> Command: Analysing commodity prices to be sent to uex corp. Doing screenshot analysis. Only commodity information and only if active window is star citizen for {function_args}.')
        self.overlay.display_overlay_text("Trying to submit all prices ...")
        print_debug(function_args)
        if not function_args.get("player_provided_terminal_name"):
            function_response = json.dumps({"success": False, "instruction": "Ask the player to provide the tradeport name for which he wants the prices to be transmitted"})
            return function_response, None

        terminal_type = function_args.get("terminal_type", "commodity")    
    
        tradeport = self.uex2_service.get_terminal(function_args["player_provided_terminal_name"], type=terminal_type, search_fields=["nickname", "name", "space_station_name", "outpost_name", "city_name"])

        if not tradeport:
            function_response = json.dumps({"success": False, "instruction": 'Could not identify the given tradeport name. Please repeat clearly the tradeport name.'})
            return function_response, None
               
        if "operation" not in function_args:
            self.overlay.display_overlay_text("Invalid command.")
            return {"success": False, "instructions": "The user did not provide enough information to process his request. He has to tell at what terminal he is standing and what trading operation he wants to analyse. It is important, that he selects the current location inventory and that he has activated the correct operations tab.", 
                    "error": "missing tradeport or trading operation. "
                    }, None
        
        function_response = self._get_data_from_screenshots(tradeport, function_args["operation"])
        
        printr.print(f'-> Result: {json.dumps(function_response)}', tags="info")

        return function_response

    def _get_data_from_screenshots(self, tradeport=None, asked_operation=None):
        validated_tradeport = tradeport
        operation = "buy"
        if asked_operation == "sell":
            operation = "sell"
        
        screenshot_path = screenshots.take_screenshot_ingame(self.data_dir_path, operation, test=TEST, operation=operation, tradeport=tradeport["code"])
        if screenshot_path is None:
            self.overlay.display_overlay_text("Could not take screenshot. ")
            return {"success": False, "instructions": "You where not able to analyse the data. You can provide error information, if he likes. ", 
                    "error": "Could not make screenshot. Maybe, during screenshot taking, the active window displayed was NOT Star Citizen. In that case, I don't make any screenshots! "
                    }, None
    
        location_name_crop = screenshots.crop_screenshot_coordinates(
            data_dir_path=f"{self.data_dir_path}/location_name_area",
            screenshot=screenshot_path,
            instructions=[
                {
                    "strategy": "AREA",
                    "coords": ((350, 330), (900, 385))
                }
            ],
            cash_key=f"uex_locationname_{validated_tradeport['code']}"
        )
                
        print_debug(f'location name: {validated_tradeport["nickname"]}')            
        self.overlay.display_overlay_text(f'Cora: Screenshot taken, selected tradeport: {validated_tradeport["nickname"]}')
        buy_result = self._analyse_prices_at_tradeport(screenshot_path, location_name_crop, validated_tradeport, operation)

        print_debug(buy_result)
        if "success" not in buy_result:
            return buy_result, "Ok"

        return buy_result
         
    def _analyse_prices_at_tradeport(self, screenshot_path, cropped_screenshot_location, validated_tradeport, operation):
        
        # commodity_area_crop = screenshots.crop_screenshot(f"{self.data_dir_path}/commodity_info_area", screenshot_path, [("UPPER_LEFT", "LOWER_LEFT", "HORIZONTAL"), ("UPPER_LEFT", "LOWER_LEFT", "VERTICAL")], ["BOTTOM", "RIGHT"])
        commodity_area_crop = screenshots.crop_screenshot_coordinates(
            data_dir_path=f"{self.data_dir_path}/commodity_info_area",
            screenshot=screenshot_path,
            instructions=[
                # aus uex_sell_STAHN_UPPER_LEFT_LOWER_LEFT => (x=1640,y=383) → HORIZONTAL: y
                { "strategy": "HORIZONTAL", "coords": [380] },
                # aus uex_sell_STAHN_UPPER_LEFT_LOWER_LEFT und
                #     uex_sell_STAHN_UPPER_RIGHT_LOWER_RIGHT ⇒ x1=1640, x2=2404 → VERTICAL zwischen diesen beiden x
                { "strategy": "VERTICAL",   "coords": [1640, 2400] },
            ],
            cash_key=f"uex_{operation}_{validated_tradeport['code']}",
            select_sides=["BOTTOM", "RIGHT"]
        )
        # commodity_area_crop = screenshots.crop_screenshot(f"{self.data_dir_path}/commodity_info_area", screenshot_path, [("UPPER_LEFT", "LOWER_LEFT", "AREA"), ("LOWER_RIGHT", "LOWER_RIGHT", "AREA")])
        prices_raw, success = self.commodity_prices_ocr.get_screenshot_texts(commodity_area_crop, "commodity_info_area", operation, operation=operation, tradeport=validated_tradeport['code'])
        
        if not success or not prices_raw.get("commodity_prices", False):
            self.overlay.display_overlay_text("Error retrieving commodity prices in screenshot.")
            return {"success": False, 
                    "instructions": "There was an error in retrieving the commodity prices from the screenshot. Provide information about the error, if the user asks for it. ", 
                    "message": prices_raw
                    }
        
        number_of_extracted_prices = len(prices_raw["commodity_prices"])

        print_debug(f"extracted {number_of_extracted_prices} price-informations from screenshot")

        terminal_prices = self.uex2_service.get_prices_of(price_category="commodities_prices", id_terminal=validated_tradeport["id"])
        screenshot_prices, validated_prices, invalid_prices, success = CommodityPriceValidator.validate_price_information(prices_raw.get("commodity_prices", []), terminal_prices, operation)

        if not success:
            self.overlay.display_overlay_text("Error: could not identify commodities. Check logs.")
            return {"success": False, 
                    "instructions": "You couldn't identify the commodities and prices. Instruct the user to analyse the log files.", 
                    }
        
        manually_confirmed_data, new_operation, new_terminal_id = OverlayPopup.show_data_validation_popup(terminal_prices, operation, screenshot_prices, commodity_area_crop, cropped_screenshot_location)
        
        if manually_confirmed_data == "aborted":
            return {
                "instructions": "Tell the user, that transmission has been aborted. "
            }
        print(f"user-validated {new_operation}@{new_terminal_id}: {json.dumps(manually_confirmed_data, indent=2)}")
        
        number_of_validated_prices = len(manually_confirmed_data)

        print_debug(f"{number_of_validated_prices} prices are valid")

        if number_of_validated_prices == 0:
            self.overlay.display_overlay_text("Prices or commodity names not recognized. Check logs.")
            return {"success": False, 
                    "instructions": "You have made errors in recognizing the correct prices on the terminal and all have been rejected.", 
                    "message": "Could not identify commodity names or prices are not within 40% of allowed tollerance to current prices"
                    }
        
        validated_tradeport = self.uex2_service.get_data("terminals").get(str(new_terminal_id))
        if not validated_tradeport:
            self.overlay.display_overlay_text(f"Error: No tradeport with id {new_terminal_id} found.")
            print(f"terminal with id {new_terminal_id} not found.")
            terminals = self.uex2_service.get_data("terminals")
            first_terminal = terminals[next(iter(terminals))]
            print(json.dumps(first_terminal, indent=2))
            return {"success": False, 
                    "instructions": "You couldn't identify the tradeport. Instruct the user to analyse the log files.", 
                    }
        operation = new_operation
        now = datetime.datetime.now()
        self.current_timestamp = now.strftime("%Y%m%d_%H%M%S_%f")

        # Write JSON data to a file
        json_file_name = f'{self.data_dir_path}/debug_data/verified_price_information_{operation}_{validated_tradeport["code"]}_{self.current_timestamp}.json'
        json_dir = os.path.dirname(json_file_name)
        if not os.path.exists(json_dir):
            os.makedirs(json_dir)
        with open(json_file_name, 'w') as file:
            json.dump(manually_confirmed_data, file, indent=4)
        
        self.overlay.display_overlay_text("Now transmitting to UEX.")
        response2, success2 = self.uex2_service.update_tradeport_prices(tradeport=validated_tradeport, commodity_update_infos=manually_confirmed_data, operation=operation)
        if not success2:
            self.overlay.display_overlay_text(f"Error UEX: no price information accepted.", display_duration=1500)
        
            # Write JSON data to a file
            json_file_name = f'{self.data_dir_path}/debug_data/uex2_rejected_price_information_{operation}_{validated_tradeport["code"]}_{self.current_timestamp}.json'
            with open(json_file_name, 'w') as file:
                json.dump(response2, file, indent=4)
            return {
                        "success": False,
                        "instructions": "Price information was not accepted by UEX. Provide information about the error, if the user asks for it. ",
                        "message": {
                            "tradeport": validated_tradeport["name"],
                            f"{operation}able_commodities_info": {
                                "result_information": response2["status"]
                            }
                        }
                    }
        
        self.overlay.display_overlay_text(f'UEX Corp: acknowledged the data transmittion. ', display_duration=1500)
        
        return "Ok"  # we don't want cora to repeat what we see on screen, if everything was fine
