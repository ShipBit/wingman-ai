import json
import os
import traceback

from services.printr import Printr

from wingmen.star_citizen_services.model.delivery_mission import DeliveryMission, MissionPackage
from wingmen.star_citizen_services.function_manager import FunctionManager
from wingmen.star_citizen_services.functions.mission_services.delivery_mission_services.delivery_manager import PackageDeliveryPlanner, DeliveryMissionAction
from wingmen.star_citizen_services.functions.uex_v2.uex_api_module import UEXApi2
from wingmen.star_citizen_services.functions.mission_services.delivery_mission_services import delivery_mission_builder
from wingmen.star_citizen_services.overlay import StarCitizenOverlay
from wingmen.star_citizen_services.ai_context_enum import AIContext
from wingmen.star_citizen_services.location_name_matching import LocationNameMatching

from wingmen.star_citizen_services.helper import screenshots
from wingmen.star_citizen_services.helper.ocr import OCR


DEBUG = True
TEST = False
printr = Printr()


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class DeliveryMissionManager(FunctionManager):
    """  
        This is an example implementation structure that can be copy pasted for new managers.
    """
    MANAGER_CONTEXT = AIContext.CORA
    MANAGER_DESCRIPTION = "Manages delivery missions: capture missions, plan routes, and determine the next pickup/dropoff stop."
    MANAGER_CAPABILITIES = [
        "Read delivery missions via OCR",
        "Add, discard, and summarize missions",
        "Determine the next route step with pickup/dropoff logic",
    ]

    def __init__(self, config, secret_keeper):
        super().__init__(config, secret_keeper)
        # do further initialisation steps here

        self.missions: dict(int, DeliveryMission) = {}
        self.delivery_actions: list(DeliveryMissionAction) = []
        self.current_delivery_action_index: int = 0
        self.current_delivery_action_location_end_index = 0

        self.config = config
        self.mission_data_path = f'{self.config["data-root-directory"]}{self.config["box-mission-configs"]["mission-data-dir"]}'
        self.missions_file_path = f'{self.mission_data_path}/active-missions.json'
        self.delivery_route_file_path = f'{self.mission_data_path}/active-delivery-route.json'

        self.openai_api_key = secret_keeper.retrieve(
            requester="MissionService",
            key="openai",
            friendly_key_name="OpenAI API key",
            prompt_if_missing=False
        )

        self.uex_service = UEXApi2()

        self.overlay1 = StarCitizenOverlay()
        self.overlay2 = StarCitizenOverlay()
        self.delivery_manager = PackageDeliveryPlanner()
        
        with open(f'{self.mission_data_path}/templates/response_structure_delivery_mission.json', 'r', encoding="UTF-8") as file:
            file_content = file.read()

        # JSON-String direkt verwenden
        json_string = file_content   

        self.ocr = OCR(
            open_ai_model=f'{self.config["open-ai-vision-model"]}',
            openai_api_key=self.openai_api_key, 
            data_dir=self.mission_data_path,
            extraction_instructions=f"Give me the text within this image. Give me the response in a plain json object structured as defined in this example: {json_string}. Provide the json within markdown ```json ... ```.If you are unable to process the image, just return 'error' as response.",
            overlay=self.overlay1)
        
        # we always load from file, as we might restart wingmen.ai independently from star citizen
        # TODO need to check on start, if we want to discard this mission
        self.load_missions()
        self.load_delivery_route()

        self.mission_started = False
        self.current_delivery_location = None
      
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
        function_register[self.box_delivery_mission_management.__name__] = self.box_delivery_mission_management
        function_register[self.get_first_or_next_location_on_delivery_route.__name__] = self.get_first_or_next_location_on_delivery_route
    
    # @abstractmethod - overwritten
    def get_function_prompt(self) -> str:
        """  
            Here you can provide instructions to open ai on how to use this function. 
        """
        return (
            f"You are able to manage delivery missions the user has to fulfill. "
            "The following functions allow you to help the player in this task: "
            f"- {self.box_delivery_mission_management.__name__}: call it to add 1, remove 1 or delete all missions. "
            f"  This function will return all available and registered mission ids that you will need for further requests. "
            f"- {self.get_first_or_next_location_on_delivery_route.__name__}: get information about the next location the user should go. "
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
                    "name": self.box_delivery_mission_management.__name__,
                    "description": "Allows the player to add a new box mission, to delete a specific mission, to delete all missions or to get information about the next location he has to travel to",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "description": "The type of operation that the player wants to execute",
                                "enum": ["new_delivery_mission", "delete_or_discard_all_missions", "delete_or_discard_one_mission_with_id", None]
                            },
                            "mission_id": {
                                "type": "string",
                                "description": "The id of the mission, the player wants to delete",
                            },
                            "confirm_deletion": {
                                "type": "string",
                                "description": "User confirmed deletion",
                                "enum": ["confirmed", "notconfirmed", None]
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": self.get_first_or_next_location_on_delivery_route.__name__,
                    "description": (
                        "Identifies the next location where to pickup or drop boxes according to the calculated delivery route for the active delivery missions. "
                        "Always execute this function, if the user ask to get the next location. Do not call this function, if the user want's to have details about the current location."
                    ),
                }
            },
        ]

        return tools

    def cora_start_information(self):
        """  
            This method is called, when the AI context is started. 
            Here you can do further initialisation steps, if needed.
        """
        mission_count, package_count, revenue_sum, location_count, planetary_system_changes = self.get_missions_information()
        # 3 return new mission and active missions + instructions for ai
        if mission_count == 0:
            return "" # nothing to tell the user about.
        
        pick_up_count, dropoff_count = self.get_next_actions()

        if pick_up_count is None and dropoff_count is None:
            return {
                "delivery_mission_information": { 
                    "additional_instructions": "The user has completed all delivery missions. Remind him of his past achievement, reduced to the most important information. Any numbers in your response must be written out. Finally, ask him, if he would like to discard the information. ",
                    "missions_count": mission_count,
                    "all_mission_ids": self.get_mission_ids(),
                    "total_revenue": revenue_sum,
                    "total_packages_to_deliver": package_count,
                    "number_of_locations_to_visit": location_count,
                    "number_of_moons_or_planets_to_visit": planetary_system_changes
                }
            }

        return {
            "delivery_mission_information": {
                "additional_instructions": "The user has active missions. Do not provide any information, if there is no value or 0. Any numbers in your response must be written out. Keep a conversational tone, and provide only the important information. ",
                "missions_count": mission_count,
                "all_mission_ids": self.get_mission_ids(),
                "total_revenue": revenue_sum,
                "total_packages_to_deliver": package_count,
                "total_number_of_locations_to_visit": location_count,
                "total_number_of_moons_or_planets_to_visit": planetary_system_changes,
                "packages_still_to_get": pick_up_count,
                "packages_still_to_dropoff": dropoff_count,
                "next_location_to_visit": self.current_delivery_location.get("name")
            }
        }

    def box_delivery_mission_management(self, function_args):
        mission_id = function_args.get("mission_id", None)
        confirmed_deletion = function_args.get("confirm_deletion", None)
        function_type= function_args["type"]
        printr.print(f'-> Delivery Mission Management: {function_type}', tags="info")
        function_response = self.manage_missions(type=function_type, mission_id=mission_id, confirmed_deletion=confirmed_deletion)
        printr.print(f'-> Result: {json.dumps(function_response, indent=2)}', tags="info")

        return function_response
    
    def manage_missions(self, type="new", mission_id=None, confirmed_deletion=None):
        if type == "new_delivery_mission":
            return self.get_new_mission()
        if type == "delete_or_discard_all_missions":
            if not confirmed_deletion or not confirmed_deletion == "confirmed":
                return {"success": False, "instructions": "User has to confirm deletion of all missions"}
            return self.discard_all_missions()
        if type == "delete_or_discard_one_mission_with_id":
            if not confirmed_deletion or not confirmed_deletion == "confirmed":
                return {"success": False, "instructions": f"User has to confirm deletion of mission with id {mission_id}"}
            return self.discard_mission(mission_id)
        
    def get_next_actions(self, current_index=0):
        print_debug(f"get_next_actions start at {current_index}")
        if not self.delivery_actions or not self.missions:
            return None, None
        
        index = current_index
        start_index = None
        end_index = 0
        current_location = None
        pick_up_count = 0
        dropoff_count = 0
        
        while index < len(self.delivery_actions):
            action: DeliveryMissionAction = self.delivery_actions[index]
            if action.state == "DONE":
                self.mission_started = True
                print_debug(f"skipping index {index} as done: {action}")

            if action.state == "TODO":
                if start_index is None: # we find the first "TODO" action in the list, which is our start index for the next location
                    print_debug(f"found start at index: {index}")
                    start_index = index
                    current_location = self.delivery_actions[index].location_ref
                    self.mission_started = True

                if current_location and action.location_ref.get("code") != current_location.get("code"):
                    print_debug("changed location, finished")
                    break

                end_index = index

                if action.action == "pickup":
                    pick_up_count += 1
                else:
                    dropoff_count += 1

            index += 1

        self.current_delivery_action_index = start_index
        self.current_delivery_action_location_end_index = end_index
        self.current_delivery_location = current_location

        print_debug(f"identified next location: {self.current_delivery_location}, same location actions indexes: {self.current_delivery_action_index}->{self.current_delivery_action_location_end_index}")
        
        if start_index is None:  # we have reached the end of the delivery route
            return None, None
        
        return pick_up_count, dropoff_count
    
    def update_last_location(self):
        """Updates all actions between current_delivery_action_index and current_delivery_action_location_end_index to state 'DONE', saves and returns the next index or None, if the end has been reached"""
        if len(self.delivery_actions) == 0:
            return False, {
                "success": "False", 
                "instructions": "There are no delivery missions active"
            }
        
        if self.mission_started is False:
            print_debug("no actions done yet")
            return True, None
        
        index = self.current_delivery_action_index
        end_index = self.current_delivery_action_location_end_index

        while index < len(self.delivery_actions) and index <= end_index:
            print_debug(f"box action done index: {self.delivery_actions[index].index}")
            self.delivery_actions[index].state = "DONE"
            index += 1

        self.current_delivery_action_index = self.current_delivery_action_location_end_index
        if self.current_delivery_action_index >= len(self.delivery_actions):
            self.discard_all_missions()
            return False, {"success": "False", 
            "instructions": "The player has completed all delivery missions. No active missions available."}
                    
        self.save_delivery_route()
 
        return True, None
                   
    def get_missions_information(self):
        mission_count = 0
        package_count = 0
        revenue_sum = 0
        location_count = 0
        planetary_system_changes = 0
        locations = set()
        moons_and_planets = set()
        for mission in self.missions.values():
            mission: DeliveryMission
            print_debug(mission)
            mission_count += 1
            revenue_sum += mission.revenue
            package_count += len(mission.packages)

            for location_info in mission.mission_packages:
                location_info: MissionPackage

                locations.add(location_info.pickup_location_ref.get("code"))
                locations.add(location_info.drop_off_location_ref.get("code"))
                
                moon_pickup = str(location_info.pickup_location_ref.get("satellite"))
                planet_pickup = str(location_info.pickup_location_ref.get("planet"))

                moon_planet_pickup = moon_pickup + planet_pickup
                moons_and_planets.add(moon_planet_pickup)

                moon_dropoff = str(location_info.drop_off_location_ref.get("satellite"))
                planet_dropoff = str(location_info.drop_off_location_ref.get("planet"))

                moon_planet_dropoff = moon_dropoff + planet_dropoff
                moons_and_planets.add(moon_planet_dropoff)

        location_count = len(locations)
        planetary_system_changes = len(moons_and_planets)

        return mission_count, package_count, revenue_sum, location_count, planetary_system_changes

    def get_first_or_next_location_on_delivery_route(self, function_args):
        
        success, message = self.update_last_location()
        
        if success is False:
            return message
        
        pickup_count, dropoff_count = self.get_next_actions(self.current_delivery_action_index)

        print_debug(f"next action: {self.current_delivery_location} pickup #{pickup_count}, dropoff #{dropoff_count}")
        if pickup_count == 0 and dropoff_count == 0:
            # shouldn't happen
            print_debug("ERROR - no next location")
            return {"success": False, "message": "Error"}
        
        next_action: DeliveryMissionAction = self.delivery_actions[self.current_delivery_action_index]
        next_location = self.current_delivery_location
        moon_or_planet = ""
        if next_location.get("satellite"):
            moon_or_planet = self.uex_service.get_satellite_name(next_location.get("satellite"))
        else:
            moon_or_planet = self.uex_service.get_planet_name(next_location.get("planet"))

        index = self.current_delivery_action_index
        pickup_packages = []
        dropoff_packages = []
        while index < len(self.delivery_actions) and index <= self.current_delivery_action_location_end_index:
            action: DeliveryMissionAction = self.delivery_actions[index]
            if action.action == "pickup":
                pickup_packages.append(action.package_id)
            else: 
                dropoff_packages.append(action.package_id)
            
            index += 1

        self.overlay1.display_overlay_text(
            (
                f'Next location: {next_location.get("name")}  '
                f'on  {moon_or_planet}  '
                f'pickup:  {pickup_packages}  '
                f'dropoff:  {dropoff_packages}'
            ),
            vertical_position_ratio=10
        )
        
        response = {
            "success": True, 
            "instructions": "Provide the user with all provided information based on your calculation of the best delivery route considering risk, and least possible location-switches. Do not provide any information, if there is no value or 0.",
            "next_location": next_location.get("name"),
            "on_moon": self.uex_service.get_satellite_name(next_location.get("satellite")),
            "on_planet": self.uex_service.get_planet_name(next_location.get("planet")),
            "in_city": self.uex_service.get_city_name(next_location.get("city")),
            "possible_threads": next_action.danger,
            "number_of_packages_to_pickup": pickup_count,
            "number_of_packages_to_dropoff": dropoff_count,
            "sell_commodity": self.uex_service.get_commodity_name(next_action.sell_commodity_code),
            "buy_commodity": self.uex_service.get_commodity_name(next_action.buy_commodity_code)
        }
        printr.print(f'-> Next location: {json.dumps(response, indent=2)}', tags="info")

        return response
    
    def get_mission_ids(self):
        return [mission for mission in self.missions.keys()]
    
    def get_new_mission(self):

        image_path = screenshots.take_screenshot(self.mission_data_path, "delivery_missions", test=TEST)
        if not image_path:
            return {"success": False, "instructions": "Could not take screenshot. Explain the player, that you only take screenshots, if the active window is Star Citizen. "}
        cropped_image = screenshots.crop_screenshot(
            data_dir_path=self.mission_data_path, 
            screenshot=image_path, 
            areas_and_corners_and_cropstrat=[
                ("UPPER_LEFT", "LOWER_LEFT", "AREA"),
                ("LOWER_RIGHT", "LOWER_RIGHT", "AREA")],
            cash_key="delivery_missions")
        retrieved_json, success = self.ocr.get_screenshot_texts(cropped_image, "delivery_missions", test=TEST)
        if not success:
            return {"success": False, "error": retrieved_json, "instructions": "Explain the player the reason for the delivery mission not beeing able to be extracted. "}

        delivery_mission = delivery_mission_builder.build(retrieved_json)

        if not delivery_mission or len(delivery_mission.packages) == 0:
            return None

        LocationNameMatching.validate_location_names(delivery_mission, self.mission_data_path)

        print_debug(delivery_mission)

        self.overlay1.display_overlay_text(
            (
                f"Identified mission with a payout of {delivery_mission.revenue} aUEC and {len(delivery_mission.packages)} packages to deliver."
            ),
            vertical_position_ratio=10
        )

        self.missions[delivery_mission.id] = delivery_mission
        print_debug(f"new mission: {delivery_mission.to_json()}")
        
        self.calculate_delivery_route()
        
        mission_count, package_count, revenue_sum, location_count, planetary_system_changes = self.get_missions_information()

        self.overlay2.display_overlay_text(
            (
                f"Total missions: #{mission_count}  "
                f"for {revenue_sum} αUEC   "
                f"packages: {package_count}."
            ),
            vertical_position_ratio=8
        )

        # 3 return new mission and active missions + instructions for ai
        return {
            "success": "True", 
            "instructions": "Provide the user with all provided information based on your calculation of the best delivery route considering risk, and least possible location-switches. Do not provide any information, if there is no value or 0. Any numbers in your response must be written out. ",
            "missions_count": mission_count,
            "all_mission_ids": self.get_mission_ids(),
            "total_revenue": revenue_sum,
            "total_packages_to_deliver": package_count,
            "number_of_locations_to_visit": location_count,
            "number_of_moons_or_planets_to_visit": planetary_system_changes,
        }

    def calculate_delivery_route(self):
        self.delivery_actions = self.delivery_manager.calculate_delivery_route(self.missions)
         
        # CargoRoutePlanner.finde_routes_for_delivery_missions(ordered_delivery_locations, tradeports_data)
			
        # Save the missions to a JSON file
        self.save_missions()
        self.save_delivery_route()
        self.current_delivery_action_index = 0
       
    def discard_mission(self, mission_id):
        """Discard a specific mission by its ID."""

        try:
            mission_id = int(mission_id)
        except ValueError:
            return {
                "success": False, 
                "instructions": "The id of the mission provided is not a number. ",
            }
        if mission_id not in self.missions:
            return {
                "success": False, 
                "instructions": f"The id of the mission provided is not valid. Valid numbers: {self.get_mission_ids()} ",
            }
        
        self.missions.pop(mission_id, None)
        
        self.calculate_delivery_route()
        
        mission_count, package_count, revenue_sum, location_count, planetary_system_changes = self.get_missions_information()

        self.overlay1.display_overlay_text(
            f"Discarded Mission #{mission_id}   "
            f"Total missions: #{mission_count}  "
            f"for {revenue_sum} αUEC   "
            f"packages: {package_count}. ",
            vertical_position_ratio=10
        )
        
        return {
            "success": "True", 
            "instructions": "Provide the user with all provided information based on your calculation of the best delivery route considering risk, and least possible location-switches. Do not provide any information, if there is no value or 0. Any numbers in your response must be written out. ",
            "missions_count": mission_count,
            "all_mission_ids": self.get_mission_ids(),
            "total_revenue": revenue_sum,
            "total_packages_to_deliver": package_count,
            "number_of_locations_to_visit": location_count,
            "number_of_moons_or_planets_to_visit": planetary_system_changes,
        }

    def discard_all_missions(self):
        """Discard all missions."""
        number = len(self.missions)
        self.missions.clear()
        self.delivery_actions.clear()
        self.mission_started = False

        self.overlay1.display_overlay_text(
            "Discarded all mission, reject them ingame.",
            vertical_position_ratio=10
        )

        self.save_missions()
        self.save_delivery_route()
        self.current_delivery_action_index = 0
        self.current_delivery_action_location_end_index = 0

        return {"success": "True", 
                "instructions": "Provide only the following information: Acknowledge the deletion of the number of missions. Any numbers in your response must be written out. Do not provide any further information.",
                "delete_missions_count": number }

    def save_missions(self):
        """Save mission data to a file."""
        filename = self.missions_file_path
        with open(filename, 'w') as file:
            missions_data = {}
            for mission_id, mission in self.missions.items():
                mission_dict = mission.to_dict()
                
                # mission_dict = mission.__dict__.copy()
                mission_dict['packages'] = list(mission_dict['packages'])  # Convert set to list

                # Convert pickup and drop-off locations to a serializable format if needed
                # Depending on how they are stored, you might need similar conversion
                
                missions_data[mission_id] = mission_dict
            json.dump(missions_data, file, indent=3)

    def load_missions(self):
        """Load mission data from a file."""
        filename = self.missions_file_path
        try:
            if os.path.exists(filename):
                with open(filename, 'r') as file:
                    data = json.load(file)
                    for mid, mission_data in data.items():
                        print_debug(f"loading mission: {mission_data}")
                        mission = DeliveryMission()

                        # Grundlegende Attribute aktualisieren
                        mission.id = mission_data['id']
                        mission.revenue = mission_data['revenue']

                        # Sets und Listen rekonstruieren
                        mission.packages = set(mission_data['packages'])
                        
                        # Dictionaries für pickup und drop-off locations rekonstruieren
                        mission.pickup_locations = {int(k): v for k, v in mission_data['pickup_locations'].items()}
                        mission.drop_off_locations = {int(k): v for k, v in mission_data['drop_off_locations'].items()}

                        # MissionPackages für jede package_id erstellen
                        for package_id in mission.packages:
                            mission_package = MissionPackage()
                            mission_package.mission_id = mission.id
                            mission_package.package_id = int(package_id)
                            mission_package.pickup_location_ref = mission.pickup_locations.get(int(package_id))
                            mission_package.drop_off_location_ref = mission.drop_off_locations.get(int(package_id))
                            mission.mission_packages.append(mission_package)

                        self.missions[mission.id] = mission  
                        print_debug(f"loaded mission: {mission.to_json()}")
        except Exception as e:
            print(f"Error loading missions: {e}")
            traceback.print_exc()

    def save_delivery_route(self):
        """Save mission data to a file."""
        filename = self.delivery_route_file_path
        with open(filename, 'w') as file:
            delivery_route_data = []
            for delivery_action in self.delivery_actions:
                delivery_action: DeliveryMissionAction
                deliver_json = delivery_action.to_json()
                delivery_route_data.append(deliver_json)
                
            json.dump(delivery_route_data, file, indent=3)

    def load_delivery_route(self):
        """Load delivery route data from a file."""
        filename = self.delivery_route_file_path
        try:
            if os.path.exists(filename):
                with open(filename, 'r') as file:
                    data = json.load(file)
                    for index, action_json in enumerate(data):
                        action = DeliveryMissionAction.from_json(self.missions, action_json, index)                   
                        
                        if isinstance(action.mission_ref, int):
                            action.mission_ref = self.missions[action.mission_ref] # we stored only the id of the mission, so now we recover the reference                    
                        self.delivery_actions.append(action)
                    
                    # we need to reiterate to build the partner-relation
                    for action in self.delivery_actions:
                        me: DeliveryMissionAction = action
                        if isinstance(me.partner_action, int):  # we only need to set, if we haven't already replaced the index by the reference
                            partner: DeliveryMissionAction = self.delivery_actions[me.partner_action]  # we have the index currently saved, so we can access the partner directly

                            me.partner_action = partner
                            partner.partner_action = me
                    print_debug("loaded delivery route")
            else:
                self.delivery_actions = self.delivery_manager.calculate_delivery_route(self.missions)
                self.save_delivery_route()
                print_debug("loading failed: calculated delivery route")

        except Exception:
            traceback.print_exc()
    
    def __str__(self):
        """Return a string representation of all missions."""
        return "\n".join(str(mission) for mission in self.missions.values())
