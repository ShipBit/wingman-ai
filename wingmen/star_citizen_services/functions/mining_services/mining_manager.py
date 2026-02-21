import json
import re
import time

from services.printr import Printr

from wingmen.star_citizen_services.function_manager import FunctionManager
from wingmen.star_citizen_services.ai_context_enum import AIContext
from wingmen.star_citizen_services.overlay import StarCitizenOverlay
from wingmen.star_citizen_services.helper import screenshots, find_best_match, time_string_converter
from wingmen.star_citizen_services.helper.ocr import OCR

from wingmen.star_citizen_services.functions.mining_services.regolith_api import RegolithAPI
from wingmen.star_citizen_services.functions.mining_services.mining_validation_popup import MiningValidationPopup
from wingmen.star_citizen_services.functions.uex_v2.uex_api_module import UEXApi2
from wingmen.star_citizen_services.functions.uex_v2 import uex_api_module


DEBUG = False
TEST = False # Set to True for testing purposes, e.g. to use example screenshots without being in the game
REGOLITH_TEST = False
printr = Printr()

# Crop area coordinates for refinery work order screenshots
REFINERY_CROP_COORDS = ((180, 75), (1200, 1300))
# Add constant for rock scans
ROCK_SCAN_COORDS = ((1500, 400), (2300, 1200))

# Mapping of in-game station names to Regolith API refinery enum values
REFINERY_STATION_MAPPING = {
    "ARC-L1 Wide Forest Station": "ARCL1",
    "ARC-L2 Lively Pathway Station": "ARCL2",
    "ARC-L4 Faint Glen Station": "ARCL4",
    "CRU-L1 Ambitious Dream Station": "CRUL1",
    "HUR-L1 Green Glade Station": "HURL1",
    "HUR-L2 Faithful Dream Station": "HURL2",
    "MIC-L1 Shallow Frontier Station": "MICL1",
    "MIC-L2 Long Forest Station": "MICL2",
    "MIC-L5 Modern Icarus Station": "MICL5",
    "Pyro Gateway (Stanton)": "PYROG",
    "Nyx Gateway (Stanton)": "NYX_STANTG",
    "Terra Gateway (Stanton)": "TERRG",
    "Checkmate Station": "PYRO_CHECKMATE",
    "Orbituary": "PYRO_ORBITUARY",
    "Patch City": "MAGNG",
    "Ruin Station": "PYRO_RUIN",
    "Stanton Gateway (Pyro)": "PYRO_STANTG",
    "Levski": "NYX_LEVSKI",
}

def print_debug(to_print):
    if DEBUG:
        print(to_print)


class MiningManager(FunctionManager):
    """  
        This is an example implementation structure that can be copy pasted for new managers.
    """
    MANAGER_CONTEXT = AIContext.CORA
    MANAGER_DESCRIPTION = "Supports mining and salvage sessions, including Regolith session control, refinery work orders, and scan capture."
    MANAGER_CAPABILITIES = [
        "Create and manage mining/salvage sessions",
        "Capture and store refinery work orders via OCR",
        "Document rock scans and cluster information",
        "Look up cluster details by signature value",
    ]

    def __init__(self, config, secret_keeper):
        super().__init__(config, secret_keeper)
        # do further initialisation steps here

        self.config = config
        self.mining_data_path = f'{self.config["data-root-directory"]}/mining-data'
        self.mining_file_path = f'{self.mining_data_path}/active-refinery-jobs.json'

        self.uex2_api_key = secret_keeper.retrieve(
            requester="MiningManager",
            key="uex2_api_key",
            friendly_key_name="UEX2 API key",
            prompt_if_missing=False
        )
        self.uex2_secret_key = secret_keeper.retrieve(
            requester="MiningManager",
            key="uex2_secret_key",
            friendly_key_name="UEX2 secret user key",
            prompt_if_missing=False
        )
        self.uex2_service = UEXApi2.init(
            uex_api_key=self.uex2_api_key,
            user_secret_key=self.uex2_secret_key
        )
        regolith_api_key = secret_keeper.retrieve(
            requester="MiningManager",
            key="regolith_secret_key",
            friendly_key_name="Regolith secret api key",
            prompt_if_missing=True
        ) if not REGOLITH_TEST else secret_keeper.retrieve(
            requester="MiningManager",
            key="regolith_secret_key_test",
            friendly_key_name="Regolith secret api key for test",
            prompt_if_missing=True
        )
        self.regolith = RegolithAPI(config=config, x_api_key=regolith_api_key)

        self.overlay = StarCitizenOverlay()

        self.refineries = self.uex2_service.get_refineries()
        self.refinery_methods = self.uex2_service.get_data(uex_api_module.CATEGORY_REFINERY_METHODS)
        commodities = self.uex2_service.get_data(uex_api_module.CATEGORY_COMMODITIES)
        self.ores = {key: value for key, value in commodities.items() if value.get('is_raw') == 1}

        self.refinery_names = [details["space_station_name"] for details in self.refineries.values() if "space_station_name" in details]
        self.refinery_jobs = []
            
        with open(f'{self.mining_data_path}/examples/response_structure_refinery.json', 'r', encoding="UTF-8") as file:
            file_content = file.read()

        # JSON-String direkt verwenden
        json_string = file_content   

        self.ocr = OCR(
            data_dir=self.mining_data_path,
            config=self.config,
            secret_keeper=secret_keeper,
            requester_name="MiningManager",
            extraction_instructions=(
                f"Extract the refinery work order data from this image exactly as shown. "
                f"Return a plain JSON object matching this structure: {json_string}. "
                "Instructions: "
                "- Extract 'station_name' exactly as shown (e.g., 'HUR-L1 Green Glade Station'). "
                "- Extract 'processing_selection_method' exactly as shown (e.g., 'Dinyx Solventation'). "
                "- Extract 'total_cost' as a number without commas. "
                "- Extract 'processing_time' exactly as shown (e.g., '5h 59m' or '1d 5h 24m'). "
                "- For 'selected_materials', only include items where yield > 0. "
                "- Extract 'commodity_name' exactly as shown (e.g., 'Iron (Ore)', 'Taranite (Raw)'). "
                "- Extract both 'quantity' and 'yield' as numbers. "
                "Provide the json within markdown ```json ... ```. "
                "If you are unable to process the image, just return 'error' as response."
            ),
            overlay=self.overlay)

        with open(f'{self.mining_data_path}/examples/response_structure_rock_scan.json', 'r', encoding="UTF-8") as file:
            rock_scan_json = file.read()

        self.rock_scan_ocr = OCR(
            data_dir=self.mining_data_path,
            config=self.config,
            secret_keeper=secret_keeper,
            requester_name="MiningManager",
            extraction_instructions=(
                "Extract the rock scan data from this image. "
                f"Return a plain json object that matches the format of this example exactly: {rock_scan_json}. "
                "The 'percent' values must be decimals between 0 and 1 (not 0-100). "
                "Provide the json within markdown ```json ... ```. "
                "If you are unable to process the image, just return 'error' as response."
            ),
            overlay=self.overlay,
        )

        # # we always load from file, as we might restart wingmen.ai indipendently from star citizen
        # # TODO need to check on start, if we want to discard this mission
        # self.load_missions()
        # self.load_delivery_route()

        # self.mission_started = False
        # self.current_delivery_location = None
      
    # @abstractmethod - overwritten
    def get_context_mapping(self) -> AIContext:
        """  
            This method returns the context this manager is associated to. This means, that this function will only be callable if the current context matches the defined context here.
        """
        return AIContext.CORA    
    
    # @abstractmethod - overwritten
    def register_functions(self, function_register):
        """  
            You register method(s) that can be called by openAI.
        """
        function_register[self.refinery_job_work_order_management.__name__] = self.refinery_job_work_order_management
        function_register[self.mining_or_salvage_session_management.__name__] = self.mining_or_salvage_session_management
        function_register[self.add_rock_scan_or_deposit_cluster_information.__name__] = self.add_rock_scan_or_deposit_cluster_information
        function_register[self.signature_based_cluster_info.__name__] = self.signature_based_cluster_info
    
    # @abstractmethod - overwritten
    def get_function_prompt(self) -> str:      
        """  
            Here you can provide instructions to open ai on how to use this function. 
        """
        return (
            f"You are able to manage mining or salvaging sessions and corresponding refinery work orders. "
            f"The following functions allow you to help the player in this task. For each of them, don't make assumptions on the value and set to None if the user hasn't provided information about it. "
            f"- {self.refinery_job_work_order_management.__name__}: call it to add 1, remove 1 or retrieve all refinery work orders / jobs of the active refinery session. This function does not require any further information from the user. "
            f"- {self.mining_or_salvage_session_management.__name__}: call it to create a new mining / salvage session, or to open the current session in the browser. "
            f"- {self.add_rock_scan_or_deposit_cluster_information.__name__}: call this, when the player has found a new deposit cluster or wants to save it, or if he wants to save a scan result of a rock."
            "If the user provided all information required, do not ask for confirmation about the action to be taken. Do not make assumptions on the values and ask for clarification if not clear. "
        )
    
    # @abstractmethod - overwritten
    def get_function_tools(self) -> list[dict]:      
        """  
            This is the function definition for OpenAI, provided as a list of tool definitions:
            Location names (planet, moons, cities, tradeports / outposts) are given in the system context, 
            so no need to make reference to it here.
        """       
        tools = [
            {
                "type": "function",
                "function": {
                    "name": self.refinery_job_work_order_management.__name__,
                    "description": "Allows the player to add or remove a refinery work order / jobs to the active session, or to retrieve all active work order.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "description": "The type of operation that the player wants to execute",
                                "enum": ["add_work_order", "get_all_work_orders"]
                            }
                        },
                        "required": ["type"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": self.mining_or_salvage_session_management.__name__,
                    "description": "Allows the player to create, remove or get a session for ship mining, vehicle mining or salvaging at Regolith.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "description": "The type of operation that the player wants to execute. Default: new_session",
                                "enum": ["new_session", "open_session_in_browser"]
                            },
                            "name": {
                                "type": "string",
                                "description": "Only relevant for new sessions: The name the session should get. Do not make assumptions on the value. "
                            },
                            "activity": {
                                "type": "string",
                                "description": "Only relevant for new sessions: The activity of this session.  Do not make assumptions on the value. ",
                                "enum": self.regolith.get_activity_names()
                            },
                            "refinery": {
                                "type": "string",
                                "description": "Only relevant for new sessions: The refinery where the ores will be processed. Is mandatory. Do not make assumptions on the value. ",
                                "enum": self.regolith.get_refinery_names()
                            },
                            "gravityWell": {
                                "type": "string",
                                "description": "Only relevant for new sessions: The planet, moon or asteroid field where the mining or salvaging takes place. Do not make assumptions on the value. ",
                                "enum": self.regolith.get_gravity_wells() + [None]
                            },
                            "scouting_start_location": {
                                "type": "string",
                                "description": "Only relevant for new sessions: At what starting POI does the scouting begins. Do not make assumptions on the value. It should be a name of an outpost, station, planet or gravityWell location. "
                            },
                            "scouting_direction": {
                                "type": "string",
                                "description": "Only relevant for new sessions: In which scouting_direction does the scouting mainly focussing. Is either a POI name or a compass scouting_direction. Do not make assumptions on the value. "
                            }
                        },
                        "required": ["type"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": self.add_rock_scan_or_deposit_cluster_information.__name__,
                    "description": "Allows the player to add/save information about found mining deposit clusters and rock scan results.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "description": "The type of operation that the player wants to execute",
                                "enum": ["save_scan_result", "add_new_cluster"]
                            },
                            "cluster_count": {
                                "type": "integer",
                                "description": "Is only necessary for type 'add_new_cluster'. The number of rocks in the cluster. Do not ask for this value if type is 'save_scan_result'. Optional "
                            },
                            "cluster_type": {
                                "type": "string",
                                "description": "Is only necessary for type 'add_new_cluster'. The deposit / rock types within this cluster. Do not ask for this value if type is 'save_scan_result'. Optional ",
                                "enum": self.regolith.get_cluster_types() + [None]
                            }
                            
                        },
                        "required": ["type"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": self.signature_based_cluster_info.__name__,
                    "description": "Call this function to lookup rock cluster information based on a signature scan value.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "scan_value": {
                                "type": "integer",
                                "description": "Signature scan value to lookup cluster info."
                            }
                        }
                        # scan_value is optional
                    }
                }
            }
        ]

        return tools

    # overwritten
    def after_init(self):
        # self.scheduler.start()

        # self.refinery_jobs, success = self.uex2_service.get_refinery_jobs()
        # if success:
        #     self.activate_refinery_job_monitoring(self.refinery_jobs)

        self.regolith.initialize_all_names()
        # load mining knowledge for signature lookup
        with open(f'{self.mining_data_path}/mining_knowledge.json', 'r', encoding='UTF-8') as f:
            self.mining_knowledge = json.load(f)

    # overwritten
    def cora_start_information(self):
        """  
            This method can be implemented to retrieve information from the manager, that Cora should provide to the user on startup.
        """
        result = self.regolith.get_active_work_orders()
        if result and not result["success"]:
            return ""  # we don't tell the user that errors occured
        
        return result

    def mining_or_salvage_session_management(self, function_args):
        printr.print(f"Executing function '{self.mining_or_salvage_session_management.__name__}'.", tags="info")

        function_type = function_args["type"]
        printr.print(f'-> Work Session Management: {function_type} with args: \n{json.dumps(function_args, indent=2)}', tags="info")
        function_response = self.manage_work_session(type=function_type, function_args=function_args)
        printr.print(f'-> Result: {json.dumps(function_response, indent=2)}', tags="info")
        self.overlay.display_overlay_text("DONE", vertical_position_ratio=3, display_duration=5000)
        function_response["do_not_cache"] = True  # we don't want session management commands to be cached, as they are usually one-time commands that change frequently
        return function_response

    def manage_work_session(self, type, function_args):
        if type == "new_session":
            return self.create_session(function_args)
        
        if type == "open_session_in_browser":
            success = self.regolith.open_session_in_browser()
            if not success:
                return {"success": False, "message": f"I couldn't open the browser{' as there is no active session. ' if self.regolith.active_session_id is None else '. '}"}
            return {"success": True, "message": "You should see the browser now. "}
        
        return {"success": False, "message": "I couldn't identify the action to be taken. Please repeat. "}
        
    def create_session(self, function_args):
        name = function_args.get("name", None)
        activity = function_args.get("activity", None)
        refinery = function_args.get("refinery", None)
        gravityWell = function_args.get("gravityWell", None)
        scouting_start_location = function_args.get("scouting_start_location", None)
        scouting_direction = function_args.get("scouting_direction", None)

        if activity is None: 
            return {"success": False, "message": f"Please provide the activity you want the session to track. One of: {self.regolith.get_activity_names()}"}
                
        if activity == "SHIP_MINING" and refinery is None or gravityWell is None:
            return {"success": False, "message": f"Please provide the {'refinery name' if refinery is None else ''} {'and ' if refinery is None and gravityWell is None else ''} {'gravity well' if gravityWell is None else ''} to create a mining session. "}
        
        session_id = self.regolith.create_mining_session(name, activity, refinery, gravityWell, scouting_start_location, scouting_direction)
        if session_id is not None:
            return {"success": True, "message": "Session created. ", "do_not_cache": True}
        
        return {"success": False, "message": "Session was not created."}

    def refinery_job_work_order_management(self, function_args):
        printr.print(f"Executing function '{self.refinery_job_work_order_management.__name__}'.", tags="info")
        work_order_index = function_args.get("work_order_index", None)
        function_type = function_args["type"]
        printr.print(f'-> Refinery Management: {function_type}', tags="info")
        function_response = self.manage_work_order(type=function_type, work_order_index=work_order_index)
        function_response["do_not_cache"] = True  # we don't want work order management commands to be cached, as they are usually one-time commands that change frequently
        printr.print(f'-> Result: {json.dumps(function_response, indent=2)}', tags="info")
        return function_response
    
    def add_rock_scan_or_deposit_cluster_information(self, function_args):
        printr.print(f"Executing function '{self.add_rock_scan_or_deposit_cluster_information.__name__}'. with args {json.dumps(function_args, indent=2)}", tags="info")
        function_type = function_args["type"]
        
        if not function_type or function_type == "save_scan_result":
            image_path = screenshots.take_screenshot_ingame(self.mining_data_path, "scans", test=TEST)
            if not image_path:
                self.overlay.display_overlay_text("Cora: Error", vertical_position_ratio=3, display_duration=5000)
                function_response = {
                    "success": False,
                    "response_instructions": "Tell the player the screenshot could not be taken.",
                    "message": "Could not take screenshot. Explain the player, that you only take screenshots, if the active window is Star Citizen. ",
                    "do_not_cache": True,
                }
                printr.print(f'-> Result: {json.dumps(function_response, indent=2)}', tags="info")
                return function_response
            self.overlay.display_overlay_text("Screenshot taken", vertical_position_ratio=3, display_duration=5000)
            
            area_image = screenshots.crop_screenshot_coordinates(
                data_dir_path=f"{self.mining_data_path}/templates/scans",
                screenshot=image_path,
                instructions=[{'strategy': 'AREA', 'coords': ROCK_SCAN_COORDS}],
                cash_key="rock_scan"
            )
            cropped_image = screenshots.crop_screenshot(
                data_dir_path=f"{self.mining_data_path}/templates/scans",
                screenshot=area_image,
                areas_and_corners_and_cropstrat=[("UPPER_LEFT", "UPPER_LEFT", "AREA"), ("LOWER_RIGHT", "LOWER_RIGHT", "AREA")]
            )
            scan_result, success = self.rock_scan_ocr.get_screenshot_texts(
                cropped_image,
                "scans",
                test=TEST,
            )

            if not success or not isinstance(scan_result, dict):
                self.overlay.display_overlay_text("Cora: Error", vertical_position_ratio=3, display_duration=5000)
                function_response = {
                    "success": False,
                    "response_instructions": "Tell the player the scan data could not be read.",
                    "message": "Couldn't read scan data. Reposition or try have a darker background. ",
                    "do_not_cache": True,
                }
                printr.print(f'-> Result: {json.dumps(function_response, indent=2)}', tags="info")
                return function_response

            if "captureShipRockScan" not in scan_result:
                scan_result = {"captureShipRockScan": scan_result}

            scan_payload = scan_result.get("captureShipRockScan", {})
            if not isinstance(scan_payload, dict) or not scan_payload.get("ores"):
                self.overlay.display_overlay_text("Cora: Error", vertical_position_ratio=3, display_duration=5000)
                function_response = {
                    "success": False,
                    "response_instructions": "Tell the player the scan data could not be read.",
                    "message": "Couldn't read scan data. Reposition or try have a darker background. ",
                    "do_not_cache": True,
                }
                printr.print(f'-> Result: {json.dumps(function_response, indent=2)}', tags="info")
                return function_response

            def _coerce_float(value):
                if isinstance(value, (int, float)):
                    return float(value)
                if isinstance(value, str):
                    cleaned = value.strip().replace("%", "").replace(",", ".")
                    try:
                        return float(cleaned)
                    except ValueError:
                        return None
                return None

            for key in ("mass", "inst", "res"):
                if key in scan_payload:
                    coerced = _coerce_float(scan_payload.get(key))
                    if coerced is not None:
                        scan_payload[key] = coerced

            for ore in scan_payload.get("ores", []):
                percent_value = _coerce_float(ore.get("percent"))
                if percent_value is None:
                    continue
                if percent_value > 1:
                    percent_value = percent_value / 100
                ore["percent"] = percent_value

            scan_result["captureShipRockScan"] = scan_payload
           
            # Übergabe des gecroppten Bildes an das Validation Popup für Rock Scans
            scan_result, operation = MiningValidationPopup.show_popup(
                scan_result,
                anchor_coords=ROCK_SCAN_COORDS[0],
                title="Scan-Validierung",
                align="right",
                crop_image=cropped_image,
                config_dir=self.mining_data_path,
                validation_context={
                    "rock_types": self.regolith.get_cluster_types(),
                    "ship_ores": self.regolith.get_ship_ore_names(),
                },
            )
            if operation == "aborted":
                self.overlay.display_overlay_text("Transmission aborted", vertical_position_ratio=3, display_duration=3000)
                function_response = {
                    "success": False,
                    "response_instructions": "Tell the player the scan transmission was aborted.",
                    "message": "Scan transmission aborted.",
                    "do_not_cache": True,
                }
                printr.print(f'-> Result: {json.dumps(function_response, indent=2)}', tags="info")
                return function_response

            session_id = self.regolith.get_or_create_mining_session(name="Ship", activity="SHIP_MINING", refinery=None)
            cluster = self.regolith.get_or_create_scouting_cluster(session_id)
            function_response = self.regolith.add_ship_cluster_scan_results(session_id, cluster, scan_result["captureShipRockScan"])
            if function_response is None or function_response.get("success", False) is False:
                self.overlay.display_overlay_text("Cora: Error", vertical_position_ratio=3, display_duration=5000)
                if isinstance(function_response, dict):
                    function_response.setdefault(
                        "response_instructions",
                        "Tell the player the scan could not be saved.",
                    )
                    function_response.setdefault("do_not_cache", True)
            else:
                if function_response.get("warnings"):
                    self.overlay.display_overlay_text(
                        f"Cora: warning {function_response['total_scans']}",
                        vertical_position_ratio=3,
                        display_duration=5000,
                    )
                else:
                    self.overlay.display_overlay_text(
                        f"Cora: saved {function_response['total_scans']}",
                        vertical_position_ratio=3,
                        display_duration=5000,
                    )
                function_response["do_not_cache"] = True
                
        elif function_type == "add_new_cluster":
            cluster_count = function_args.get("cluster_count", 0)
            cluster_type = function_args.get("cluster_type", None)
            session_id = self.regolith.get_or_create_mining_session(name="Ship", activity="SHIP_MINING", refinery=None)
            scout_finding_id = self.regolith.create_scouting_cluster(session_id, cluster_count, cluster_type)
            if scout_finding_id is None:
                self.overlay.display_overlay_text("Cora: Error", vertical_position_ratio=3, display_duration=5000)
                return {"success": False, "message": "Couldn't create a new cluster."}
            function_response = {"success": True, "instructions": f"Saved {cluster_count}x{cluster_type}'.", "do_not_cache": True}
            self.overlay.display_overlay_text("Cora: Saved", vertical_position_ratio=3, display_duration=5000)
       
        printr.print(f'-> Result: {json.dumps(function_response, indent=2)}', tags="info")

        return function_response

    def manage_work_order(self, type="new", work_order_index=None):
        if type == "add_work_order":
            image_path = screenshots.take_screenshot_ingame(self.mining_data_path, "workorder", "images", test=TEST)
            if not image_path:
                self.overlay.display_overlay_text("Cora: Error", vertical_position_ratio=3, display_duration=5000)
                return {"success": False, "instructions": "Could not take screenshot. Explain the player, that you only take screenshots, if the active window is Star Citizen. "}
            
            self.overlay.display_overlay_text("Screenshot taken", vertical_position_ratio=3, display_duration=5000)

            area_image = screenshots.crop_screenshot_coordinates(
                data_dir_path=f"{self.mining_data_path}/templates/refineries",
                screenshot=image_path,
                instructions=[{'strategy': 'AREA', 'coords': REFINERY_CROP_COORDS}],
                cash_key="workorder"
            )

            scan_result, success = self.ocr.get_screenshot_texts(
                area_image,
                "refineries",
                test=TEST,
            )

            if not success or not isinstance(scan_result, dict):
                self.overlay.display_overlay_text("Cora: Error", vertical_position_ratio=3, display_duration=5000)
                function_response = {
                    "success": False,
                    "response_instructions": "Tell the player the refinery order data could not be read.",
                    "message": "Couldn't read refinery order data. Reposition or try again.",
                    "do_not_cache": True,
                }
                printr.print(f'-> Result: {json.dumps(function_response, indent=2)}', tags="info")
                return function_response
            
            # Validate the work_order structure
            work_order_data = scan_result.get("work_order", {})
            if not isinstance(work_order_data, dict) or not work_order_data.get("selected_materials"):
                self.overlay.display_overlay_text("Cora: Error", vertical_position_ratio=3, display_duration=5000)
                function_response = {
                    "success": False,
                    "response_instructions": "Tell the player the refinery order data could not be read.",
                    "message": "Couldn't read refinery order data. Reposition or try again.",
                    "do_not_cache": True,
                }
                printr.print(f'-> Result: {json.dumps(function_response, indent=2)}', tags="info")
                return function_response
            
            # Show validation popup
            anchor_coords = (REFINERY_CROP_COORDS[1][0], REFINERY_CROP_COORDS[0][1])
            scan_result, operation = MiningValidationPopup.show_popup(
                scan_result,
                anchor_coords=anchor_coords,
                config_dir=self.mining_data_path,
            )
            if operation == "aborted":
                self.overlay.display_overlay_text("Transmission aborted", vertical_position_ratio=3, display_duration=3000)
                return {
                    "success": False,
                    "message": "Work order transmission aborted.",
                    "do_not_cache": True,
                }
            
            function_response = self.add_work_order_from_screenshot_scan(scan_result)
            function_response["do_not_cache"] = True

            self.overlay.display_overlay_text(f"Cora: {'Success' if function_response.get('success', False) else 'Error'}", vertical_position_ratio=3, display_duration=5000)
            return function_response
        
        elif type == "add_work_order_uex":
            pass
        if type == "get_all_work_orders":
            return self.regolith.get_active_work_orders()

        return {"success": False, "message": "I couldn't identify the action to be taken. Please repeat. "}
    
    def add_work_order_from_screenshot_scan(self, scan_result):
        """
        Process work order from OCR scan with screenshot structure (work_order format).
        Maps screenshot data to Regolith API structure.
        """
        print_debug("\n ===== ADDING WORK ORDER FROM SCREENSHOT SCAN ======")
        
        current_time = int(time.time() * 1000)
        work_order = scan_result["work_order"]
        
        # Map station name to refinery enum using fixed mapping
        station_name = work_order["station_name"]
        
        # Try exact match first
        refinery_name = REFINERY_STATION_MAPPING.get(station_name)
        
        if refinery_name is None:
            # Fallback to fuzzy matching if exact match fails
            station_match, success = find_best_match.find_best_match(
                station_name, 
                list(REFINERY_STATION_MAPPING.keys()), 
                score_cutoff=70
            )
            if success:
                refinery_name = REFINERY_STATION_MAPPING[station_match["matched_value"]]
                print_debug(f'Fuzzy matched station "{station_match["matched_value"]}" from "{station_name}" (confidence: {station_match["score"]})')
            else:
                return {
                    "success": False,
                    "message": f"Could not identify refinery from station name: {station_name}. Available stations: {', '.join(REFINERY_STATION_MAPPING.keys())}",
                    "do_not_cache": True
                }
        else:
            print_debug(f'Exact matched station "{station_name}" to refinery enum: {refinery_name}')
        
        # Map processing method to method enum
        method_display = work_order["processing_selection_method"]
        method_match, success = find_best_match.find_best_match(
            method_display, 
            self.regolith.get_refinery_method_names(), 
            score_cutoff=60
        )
        if not success:
            return {
                "success": False,
                "message": f"Could not identify processing method: {method_display}",
                "do_not_cache": True
            }
        method_name = method_match["matched_value"]
        print_debug(f'Matched method "{method_name}" from "{method_display}" (confidence: {method_match["score"]})')
        
        # Convert processing time to seconds
        processing_time_str = work_order["processing_time"]
        processing_duration_s = time_string_converter.convert_to_seconds(processing_time_str)
        print_debug(f'Converted processing time "{processing_time_str}" to {processing_duration_s} seconds')
        
        # Create or get session
        session_id = self.regolith.get_or_create_mining_session(
            name="Ship", 
            activity="SHIP_MINING", 
            refinery=refinery_name
        )
        if session_id is None:
            print_debug("Couldn't get or create session.")
            return {"success": False, "message": "Couldn't get or create session."}
        
        # Map selected materials to shipOres
        shipOres = []
        ship_ore_names = self.regolith.get_ship_ore_names()
        
        for material in work_order["selected_materials"]:
            # Skip materials with yield = 0
            if material["yield"] <= 0:
                continue
            
            # Clean commodity name: remove suffixes like "(Ore)", "(Raw)", etc.
            commodity_name = material["commodity_name"]
            # Remove parenthetical suffixes and trim
            cleaned_name = re.sub(r'\s*\([^)]*\)\s*$', '', commodity_name).strip()
            
            ore_match, success = find_best_match.find_best_match(
                cleaned_name, 
                ship_ore_names, 
                score_cutoff=60
            )
            if not success:
                print_debug(f'Warning: Could not match ore "{commodity_name}" (cleaned: "{cleaned_name}"), skipping')
                continue
            
            ore_name = ore_match["matched_value"]
            print_debug(f'Matched ore "{ore_name}" from "{commodity_name}" (cleaned: "{cleaned_name}", confidence: {ore_match["score"]})')
            
            # Calculate amount using yield
            amt = self.regolith.ore_amt_calc(
                material["yield"], 
                ore_name, 
                refinery_name, 
                method_name
            )
            
            shipOres.append({
                "amt": amt,
                "ore": ore_name
            })
        
        if not shipOres:
            return {
                "success": False, 
                "message": "No valid ores found in the work order.",
                "do_not_cache": True
            }
        
        # Build work order mutation variables
        variables = {
            "sessionId": session_id,
            "shipOres": shipOres,
            "workOrder": {
                "expenses": [
                    {
                        "name": "Refinery Fee",
                        "amount": work_order["total_cost"],
                        "ownerScName": self.regolith.retrieve_user_info(),
                    }
                ],
                "includeTransferFee": True,
                "isRefined": True,
                "isSold": False,
                "method": method_name,
                "note": "Work order created by Cora - Your Star Citizen AI-companion",
                "processStartTime": current_time,
                "processDurationS": processing_duration_s,
                "refinery": refinery_name,
                "shareRefinedValue": True,
            },
            "shares": [
                {
                    "payeeScName": self.regolith.sc_name,
                    "share": 1,
                    "shareType": "SHARE",
                    "state": True
                }
            ]
        }

        return self.regolith.create_work_order(work_order_details=variables)
    
    def add_work_order_from_scan(self, scan_result):
        """Process work order directly from OCR scan with captureRefineryOrder structure"""
        print_debug("\n ===== ADDING WORK ORDER FROM SCAN ======")
        
        current_time = int(time.time() * 1000)
        refinery_data = scan_result["captureRefineryOrder"]
        
        # Validate and normalize refinery name
        refinery_name = refinery_data["refinery"]
        refinery_match, success = find_best_match.find_best_match(
            refinery_name, 
            self.regolith.get_refinery_names(), 
            score_cutoff=70
        )
        if success:
            refinery_name = refinery_match["matched_value"]
            print_debug(f'Matched refinery "{refinery_name}" (confidence: {refinery_match["score"]})')
        else:
            print_debug(f'Warning: Could not match refinery "{refinery_name}", using as-is')
        
        # Validate and normalize method name
        method_name = refinery_data["method"]
        method_match, success = find_best_match.find_best_match(
            method_name, 
            self.regolith.get_refinery_method_names(), 
            score_cutoff=70
        )
        if success:
            method_name = method_match["matched_value"]
            print_debug(f'Matched method "{method_name}" (confidence: {method_match["score"]})')
        else:
            print_debug(f'Warning: Could not match method "{method_name}", using as-is')
        
        # Create or get session
        session_id = self.regolith.get_or_create_mining_session(
            name="Ship", 
            activity="SHIP_MINING", 
            refinery=refinery_name
        )
        if session_id is None:
            print_debug("Couldn't get or create session.")
            return {"success": False, "message": "Couldn't get or create session."}
        
        # Prepare shipOres with validated ore names and calculated amounts
        shipOres = []
        ship_ore_names = self.regolith.get_ship_ore_names()
        for ore_data in refinery_data["shipOres"]:
            ore_name = ore_data["ore"]
            
            # Validate and normalize ore name
            ore_match, success = find_best_match.find_best_match(
                ore_name, 
                ship_ore_names, 
                score_cutoff=70
            )
            if success:
                ore_name = ore_match["matched_value"]
                print_debug(f'Matched ore "{ore_name}" (confidence: {ore_match["score"]})')
            else:
                print_debug(f'Warning: Could not match ore "{ore_name}", skipping')
                continue
            
            amt = self.regolith.ore_amt_calc(
                ore_data["yield"], 
                ore_name, 
                refinery_name, 
                method_name
            )
            shipOres.append({
                "amt": amt,
                "ore": ore_name
            })
        
        if not shipOres:
            return {
                "success": False, 
                "message": "No valid ores found in the work order.",
                "do_not_cache": True
            }
        
        # Build work order mutation variables
        variables = {
            "sessionId": session_id,
            "shipOres": shipOres,
            "workOrder": {
                "expenses": [
                    {
                        "name": refinery_data["expenses"][0]["name"],
                        "amount": refinery_data["expenses"][0]["amount"],
                        "ownerScName": self.regolith.retrieve_user_info(),
                    }
                ],
                "includeTransferFee": True,
                "isRefined": True,
                "isSold": False,
                "method": method_name,
                "note": "Work order created by Cora - Your Star Citizen AI-companion",
                "processStartTime": current_time,
                "processDurationS": refinery_data["processDurationS"],
                "refinery": refinery_name,
                "shareRefinedValue": True,
            },
            "shares": [
                {
                    "payeeScName": self.regolith.sc_name,
                    "share": 1,
                    "shareType": "SHARE",
                    "state": True
                }
            ]
        }

        return self.regolith.create_work_order(work_order_details=variables)
    
    def add_work_order_regolith(self, work_order):
        print_debug("\n ===== ADDING REGOLITH WORK ORDER ======")
        
        # Retrieve user info to ensure sc_name is available
        self.regolith.retrieve_user_info()
        
        station = work_order["work_order"]["station_name"]
        refinery, success = find_best_match.find_best_match(station, self.regolith.get_refinery_names(), score_cutoff=0)
        if not success:
            print_debug(f"Couldn't identify refinery from '{station}'.")
            return f"Couldn't identify refinery from '{station}'."
        print_debug(f'matched refinery "{refinery["matched_value"]}" with confidence {refinery["score"]}')
        
        method = work_order["work_order"]["processing_selection_method"]
        refinery_method, success = find_best_match.find_best_match(
            method, 
            self.regolith.get_refinery_method_names(), score_cutoff=80)
        if not success:
            print_debug(f"Couldn't identify refinery method from '{method}'.")
            return f"Couldn't identify refinery method from '{method}'."
        print_debug(f'matched refinery method "{refinery_method["matched_value"]}" with confidence {refinery_method["score"]}')

        current_time = int(time.time() * 1000)
        session_id = self.regolith.get_or_create_mining_session(name="Ship", activity="SHIP_MINING", refinery=refinery["matched_value"])
        processing_time_s = time_string_converter.convert_to_seconds(work_order["work_order"]["processing_time"])
        if session_id is None:
            print_debug(f"Couldn't get or create session.")
            return {"success": False, "message": "Couldn't get or create session."}
        variables = {
            "sessionId": session_id,
            "workOrder": {
                "expenses": [
                    {
                        "amount": work_order["work_order"]["total_cost"],
                        "name": "Refinery Fee",
                        "ownerScName": self.regolith.retrieve_user_info(),
                    }
                ],
                "includeTransferFee": True,
                "isRefined": True,
                "isSold": False,
                "method": refinery_method["matched_value"],
                "note": "Work order created by Cora - Your Star Citizen ai-compagnion",
                "processDurationS": processing_time_s, 
                "processStartTime": current_time,
                # "processEndTime": (current_time + (processing_time_s * 1000)), not supported, will be returned
                "refinery": refinery["matched_value"],
                "shareRefinedValue": True,
            },
            "shares": [
                {
                    "payeeScName": self.regolith.sc_name,
                    "share": 1,
                    "shareType": "SHARE",
                    "state": True
                }
            ]
        }
        materials = []
        for material in work_order["work_order"]["selected_materials"]:
            if material["yield"] <= 0:
                continue  # material hasn't been selected to be refined
            ore_name = material["commodity_name"]
            ore, success = find_best_match.find_best_match(ore_name, self.regolith.get_ship_ore_names(), score_cutoff=0)
            if not success:
                print_debug(f"couldn't identify ore '{ore_name}'")
                continue
            print_debug(f'matched ore "{ore["matched_value"]}" with confidence {ore["score"]}')
            
            item = {
                # "yield": material["yield"], not supported, is only returned
                "amt": material["quantity"],  
                "ore": ore["matched_value"]  
            }
            materials.append(item)

        variables["shipOres"] = materials

        return self.regolith.create_work_order(work_order_details=variables)
    
    def add_scan_result_regolith(self, scan_result):
        print_debug("\n ===== ADDING REGOLITH SCAN Result ======")
    
        session_id = self.regolith.get_or_create_mining_session(name="Ship", activity="SHIP_MINING", refinery=None)
        if session_id is None:
            print_debug(f"Couldn't get or create session.")
            return {"success": False, "message": "Couldn't get or create session."}
        variables = {
            "sessionId": session_id,
            "scoutingFind": {
                "state": "DISCOVERED",
                "clusterCount": 1
            },
        }
        materials = []
        for material in work_order["work_order"]["selected_materials"]:
            if material["yield"] <= 0:
                continue  # material hasn't been selected to be refined
            ore_name = material["commodity_name"]
            ore, success = find_best_match.find_best_match(ore_name, self.regolith.get_ship_ore_names(), score_cutoff=0)
            if not success:
                print_debug(f"couldn't identify ore '{ore_name}'")
                continue
            print_debug(f'matched ore "{ore["matched_value"]}" with confidence {ore["score"]}')
            
            item = {
                # "yield": material["yield"], not supported, is only returned
                "amt": material["quantity"],  
                "ore": ore["matched_value"]  
            }
            materials.append(item)

        variables["shipOres"] = materials

        return self.regolith.create_work_order(work_order_details=variables)
    
    def add_work_order_uex(self, work_order):
        print_debug("\n ===== ADDING UEX WORK ORDER ======")
        station = work_order["work_order"]["station_name"]
        refinery, success = find_best_match.find_best_match(station, self.refineries, attributes=["space_station_name"])
        if not success:
            return f"Couldn't identify refinery from '{station}'."
        print_debug(f'matched refinery "{refinery["matched_value"]}" with confidence {refinery["score"]}')
        
        method = work_order["work_order"]["processing_selection_method"]
        refinery_method, success = find_best_match.find_best_match(
            method, 
            self.refinery_methods, 
            attributes=["name"])
        if not success:
            return f"Couldn't identify refinery method from '{method}'."

        uex_refinery_order = {
            "id_terminal": refinery["root_object"]["id"],
            "id_refinery_method": refinery_method["root_object"]["id"],
            "cost": work_order["work_order"]["total_cost"],
            "time_minutes": time_string_converter.convert_to_minutes(work_order["work_order"]["processing_time"]),
            "refinery_capacity": work_order["work_order"]["current_capacity"]
        }

        materials = []
        for material in work_order["work_order"]["selected_materials"]:
            if material["yield"] <= 0:
                continue  # material hasn't been selected to be refined
            ore_name = material["commodity_name"]
            ore, success = find_best_match.find_best_match(ore_name, self.ores, attributes=["name"])
            if not success:
                print_debug(f"couldn't identify ore '{ore_name}'")
                continue
            item = {
                "yield": material["yield"],
                "quantity": material["quantity"],
                "id_commodity": ore["root_object"]["id"]
            }
            materials.append(item)

        uex_refinery_order["items"] = materials

        return self.uex2_service.add_refinery_job(uex_refinery_order)

    def activate_refinery_job_monitoring(self, refinery_jobs):
        pass
        # self.scheduler.remove_all_jobs()
        
        # if len(refinery_jobs) <= 0:
        #     print_debug("No refinery jobs to activate")
        #     return
        
        # current_time = int(time.time())
        # # Filter for active jobs
        # self.active_jobs = [job for job in refinery_jobs if job["date_expiration"] - current_time > 0]

        # # processed jobs
        # self.processed_jobs = [job for job in refinery_jobs if job["date_expiration"] - current_time <= 0]

        # for job in self.active_jobs:
        #     # Schedule the action to be executed once the job expires
        #     self.scheduler.add_job(self.execute_action, 'date', run_date=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(job["date_expiration"])), args=[job])
        
    def execute_action(self, job):
        print(f"Executing action for job {job['id']}")

        self.overlay.display_overlay_text(f"Refinery job {job['id']} finished @{job['terminal_name']}.", display_duration=10000)

    def signature_based_cluster_info(self, function_args):
        """Lookup rock cluster info by signature scan value."""
        scan_value = function_args.get("scan_value")
        # build signature->(cluster_size, type) map for multiples 1..15, skip non-list entries
        sigs = self.mining_knowledge.get("rock_signitures", {})
        lookup = {}
        for _, area in sigs.items():
            if not isinstance(area, list):
                continue
            for rock in area:
                base = rock.get("Signature_Value")
                name = rock.get("RockType", "").lower()
                if not isinstance(base, int):
                    continue
                for size in range(1, 25):
                    lookup[base * size] = {"cluster_size": size, "type": name}
        if scan_value is None:
            return {"success": False, "message": "Please provide a scan_value to lookup."}
        info = lookup.get(scan_value)
        if not info:
            return {"success": False, "message": f"No cluster info for signature {scan_value} available."}
        return {
            "success": True,
            "cluster_size": info["cluster_size"],
            "type": info["type"],
            "message": f"Signature {scan_value} corresponds to a cluster of {info['cluster_size']} {info['type'].capitalize()} rocks.",
            "do_not_cache": True
        }

