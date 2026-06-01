import base64
import json
import os
import queue
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pyautogui
import pygetwindow
import pytesseract
from pynput import keyboard

from services.printr import Printr

from wingmen.star_citizen_services.function_manager import FunctionManager
from wingmen.star_citizen_services.ai_context_enum import AIContext
from wingmen.star_citizen_services.overlay import StarCitizenOverlay
from wingmen.star_citizen_services.helper import screenshots
from wingmen.star_citizen_services.helper.ocr import OCR

from wingmen.star_citizen_services.functions.mining_services.mining_validation_popup import MiningValidationPopup


TEST = False # Set to True for testing purposes, e.g. to use example screenshots without being in the game
printr = Printr()

# Crop area coordinates for refinery work order screenshots
REFINERY_CROP_COORDS = ((180, 75), (1200, 1300))

SIGNATURE_OBSERVER_DEFAULTS = {
    "enabled": True,
    "debug_mode": False,
    "debug_log_interval_seconds": 2.0,
    "interval_seconds": 0.25,
    "focus_activation_grace_seconds": 1.0,
    "activation_duration_seconds": 30,
    "recognition_extension_seconds": 30,
    "stable_reads": 2,
    "stable_single_tick_support": 3,
    "stable_miss_tolerance": 2,
    "unknown_clear_reads": 3,
    "display_duration_ms": 5000,
    "display_cooldown_seconds": 3.0,
    "overlay_offset_pixels": 2,
    "overlay_text_offset_x_pixels": 130,
    "overlay_text_offset_y_pixels": 8,
    "debug_rectangle_auto_clear_ms": 120,
    "debug_overlay_pre_capture_clear_wait_ms": 50,
    "vision_signature_fallback_enabled": True,
    "vision_signature_model": None,
    "vision_signature_min_interval_seconds": 5.0,
    "vision_signature_queue_size": 1,
    "vision_signature_single_inflight": True,
    "vision_signature_near_duplicate_enabled": True,
    "vision_signature_near_duplicate_cooldown_seconds": 30.0,
    "vision_signature_near_duplicate_max_mean_delta": 18.0,
    "vision_signature_near_duplicate_history_size": 8,
    "vision_signature_error_backoff_seconds": 30.0,
    "vision_signature_inflight_timeout_seconds": 60.0,
    "log_signature_vision_events": True,
    "signature_vision_event_log_interval_seconds": 2.0,
    "vision_signature_sample_known_reads": False,
    "vision_signature_accept_single_result": True,
    "vision_signature_reject_overlay_artifacts": True,
    "vision_signature_save_crops": True,
    "vision_signature_training_dir": "debug_data/signature_training",
    "vision_signature_max_output_tokens": 512,
    "local_signature_ocr_enabled": False,
    "save_number_crops": False,
    "overwrite_number_crop": True,
    "log_observed_clusters": True,
    "minimum_signature_digits": 4,
    "ocr_number_region_left_ratio": 0.35,
    "use_signature_icon_template": True,
    "signature_icon_template_path": "templates/scans/scan_signature_icon.png",
    "signature_icon_match_threshold": 0.70,
    "signature_icon_scales": [0.85, 1.0, 1.15],
    "signature_icon_tracking_enabled": True,
    "signature_icon_tracking_interval_seconds": 0.25,
    "signature_icon_tracking_search_padding_pixels": 48,
    "signature_icon_tracking_miss_tolerance": 4,
    "signature_number_crop_left_padding": 2,
    "signature_number_crop_width": 120,
    "signature_number_crop_min_width": 80,
    "signature_number_crop_right_padding": 36,
    "signature_number_crop_vertical_padding": 8,
    "debug_log_ocr_candidates": True,
    "debug_log_ocr_timing": True,
    "ocr_psm_modes": [7, 8, 13],
    "ocr_variant_names": ["gray", "light_text", "light_text_closed", "light_text_thick", "otsu", "adaptive"],
    "ocr_tesseract_timeout_seconds": 2.0,
    "ocr_fuzzy_reference_match": True,
    "ocr_fuzzy_max_distance": 1,
    "ocr_fuzzy_max_weighted_distance": 0.5,
    "ocr_fuzzy_max_numeric_delta": 100,
    "ocr_fuzzy_require_same_length": True,
    "ocr_fuzzy_allow_missing_leading_one": True,
    "save_ocr_debug_variants": True,
    "status_dot_size": 10,
    "status_dot_offset_pixels": 16,
    "status_dot_blink_ms": 450,
    "status_dot_hold_ms": 900,
    "dynamic_watch_area": {
        "enabled": True,
        "refresh_seconds": 10.0,
        "missing_icon_refresh_after": 2,
        "anchor_templates_glob": "templates/scans/scan_area_*.jpg",
        "anchor_match_threshold": 0.70,
        "anchor_scales": [0.90, 1.0, 1.10],
        "anchor_search_area": {
            "coords": [[850, 500], [1300, 950]],
        },
        "signature_area_offset": {
            "x": 250,
            "y": -250,
            "width": 300,
            "height": 210,
        },
        "use_last_on_miss": True,
    },
    "watch_area": {
        "coords": None,
        "center_x_ratio": 0.5,
        "center_y_ratio": 0.27,
        "width_ratio": 0.24,
        "height_ratio": 0.12,
    },
}

SIGNATURE_MATCH_PRIORITY = {
    "ROC Mineable": 0,
    "FPS Mineable": 1,
    "Salvage": 2,
}

class MiningManager(FunctionManager):
    """  
        This is an example implementation structure that can be copy pasted for new managers.
    """
    MANAGER_CONTEXT = AIContext.CORA
    MANAGER_DESCRIPTION = "Supports local refinery work order capture, retrieval, and mining signature lookup."
    MANAGER_CAPABILITIES = [
        "Capture refinery work orders via OCR",
        "Store active refinery work orders locally",
        "Retrieve or remove locally stored active refinery work orders",
        "Look up likely mining resources by radar signature",
        "Watch the mining signature HUD with template matching and Vision AI while active",
    ]

    def __init__(self, config, secret_keeper):
        super().__init__(config, secret_keeper)
        # do further initialisation steps here

        self.config = config
        self.mining_data_path = f'{self.config["data-root-directory"]}/mining-data'
        self.mining_file_path = f'{self.mining_data_path}/active-refinery-jobs.json'
        self.signature_reference_path = f'{self.mining_data_path}/signature_reference.json'
        self.signature_observer_config = self._get_signature_observer_config()
        self.signature_observer_stop_event = None
        self.signature_observer_thread = None
        self.signature_tab_listener = None
        self.signature_observer_lock = threading.RLock()
        self.signature_observer_active_until = 0.0
        self.signature_alt_modifier_down = False
        self.signature_last_non_star_citizen_focus_time = 0.0
        self.last_signature_value = None
        self.last_signature_display_time = 0.0
        self.signature_overlay_visible = False
        self.signature_candidate_value = None
        self.signature_candidate_reads = 0
        self.signature_candidate_misses = 0
        self.signature_unknown_reads = 0
        self.signature_last_ocr_value_support = {}
        self.signature_icon_template = None
        self.signature_icon_template_loaded = False
        self.signature_last_number_crop_rect = None
        self.signature_last_watch_area_rect = None
        self.signature_last_icon_match_rect = None
        self.signature_icon_tracking_misses = 0
        self.signature_icon_miss_count = 0
        self.signature_dynamic_anchor_templates = None
        self.signature_dynamic_watch_area_rect = None
        self.signature_dynamic_watch_area_updated_at = 0.0
        self.signature_vision_ocr = None
        self.signature_vision_queue = None
        self.signature_vision_stop_event = None
        self.signature_vision_worker_thread = None
        self.signature_vision_cache = {}
        self.signature_vision_queued_hashes = set()
        self.signature_vision_queued_at_by_hash = {}
        self.signature_vision_last_request_at = 0.0
        self.signature_vision_backoff_until = 0.0
        self.signature_vision_recent_crops = []
        self.signature_last_value_source = None
        self.signature_last_vision_skip_reason = None
        self.signature_ocr_unavailable_reported = False
        self.signature_debug_last_by_key = {}
        self.signature_vision_event_last_by_key = {}

        self.overlay = StarCitizenOverlay()
            
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
        function_register[self.mining_signature_lookup.__name__] = self.mining_signature_lookup
    
    # @abstractmethod - overwritten
    def get_function_prompt(self) -> str:      
        """  
            Here you can provide instructions to open ai on how to use this function. 
        """
        return (
            f"You are able to help with locally stored refinery work orders and mining radar signature lookups. "
            f"The following functions allow you to help the player in this task. For each of them, don't make assumptions on the value and set to None if the user hasn't provided information about it. "
            f"- {self.refinery_job_work_order_management.__name__}: call it to add, retrieve, or remove locally stored active refinery work orders. "
            f"- {self.mining_signature_lookup.__name__}: call it when the player asks which mining resource matches a radar signature value. "
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
                    "description": "Allows the player to add, retrieve, or remove locally stored active refinery work orders.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "description": "The type of operation that the player wants to execute",
                                "enum": ["add_work_order", "get_all_work_orders", "remove_work_order"]
                            },
                            "work_order_id": {
                                "type": "string",
                                "description": "Only relevant for remove_work_order: The id of the locally stored work order to remove."
                            },
                            "work_order_index": {
                                "type": "integer",
                                "description": "Only relevant for remove_work_order if no work_order_id is provided: zero-based index of the work order to remove."
                            }
                        },
                        "required": ["type"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": self.mining_signature_lookup.__name__,
                    "description": "Looks up likely mining resources and resource counts for a radar signature value.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "signature_value": {
                                "type": "integer",
                                "description": "The radar signature value to look up."
                            }
                        },
                        "required": ["signature_value"]
                    }
                }
            }
        ]

        return tools

    # overwritten
    def after_init(self):
        self._ensure_work_order_file()

    def on_manager_enabled(self, source: str = "manual"):
        if self.signature_observer_config.get("enabled", True):
            self.start_signature_observer()

    def on_manager_disabled(self, source: str = "manual"):
        self.stop_signature_observer()

    # overwritten
    def cora_start_information(self):
        """  
            This method can be implemented to retrieve information from the manager, that Cora should provide to the user on startup.
        """
        return ""

    def refinery_job_work_order_management(self, function_args):
        printr.print(f"Executing function '{self.refinery_job_work_order_management.__name__}'.", tags="info")
        work_order_index = function_args.get("work_order_index", None)
        work_order_id = function_args.get("work_order_id", None)
        function_type = function_args["type"]
        printr.print(f'-> Refinery Management: {function_type}', tags="info")
        function_response = self.manage_work_order(
            type=function_type,
            work_order_index=work_order_index,
            work_order_id=work_order_id,
        )
        function_response["do_not_cache"] = True  # we don't want work order management commands to be cached, as they are usually one-time commands that change frequently
        printr.print(f'-> Result: {json.dumps(function_response, indent=2)}', tags="info")
        return function_response
    
    def manage_work_order(self, type="new", work_order_index=None, work_order_id=None):
        if type == "add_work_order":
            image_path = screenshots.take_screenshot_ingame(self.mining_data_path, "workorder", "images", test=TEST)
            if not image_path:
                self.overlay.display_overlay_text("Cora: Error", vertical_position_ratio=3, display_duration=5000)
                return {
                    "success": False,
                    "message": "Could not take a screenshot because Star Citizen is not the active window.",
                    "instructions": "Tell the player that no refinery work order was created because screenshots can only be taken while Star Citizen is the active window.",
                }
            
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
                self.overlay.display_overlay_text("Save aborted", vertical_position_ratio=3, display_duration=3000)
                return {
                    "success": False,
                    "message": "Work order save aborted.",
                    "do_not_cache": True,
                }
            
            function_response = self.add_work_order_local(scan_result)
            function_response["do_not_cache"] = True

            self.overlay.display_overlay_text(f"Cora: {'Success' if function_response.get('success', False) else 'Error'}", vertical_position_ratio=3, display_duration=5000)
            return function_response
        
        if type == "get_all_work_orders":
            work_orders = self.load_active_work_orders()
            return {
                "success": True,
                "message": f"{len(work_orders)} active refinery work order(s) retrieved.",
                "work_orders": work_orders,
            }

        if type == "remove_work_order":
            return self.remove_work_order_local(work_order_id=work_order_id, work_order_index=work_order_index)

        return {"success": False, "message": "I couldn't identify the action to be taken. Please repeat. "}

    def _ensure_work_order_file(self):
        work_order_path = Path(self.mining_file_path)
        work_order_path.parent.mkdir(parents=True, exist_ok=True)
        if not work_order_path.exists():
            self.save_active_work_orders([])

    def load_active_work_orders(self):
        self._ensure_work_order_file()
        with open(self.mining_file_path, 'r', encoding='UTF-8') as file:
            try:
                file_content = json.load(file)
            except json.JSONDecodeError:
                return []

        if isinstance(file_content, list):
            return file_content
        if isinstance(file_content, dict):
            work_orders = file_content.get("active_work_orders", [])
            return work_orders if isinstance(work_orders, list) else []
        return []

    def save_active_work_orders(self, work_orders):
        work_order_path = Path(self.mining_file_path)
        work_order_path.parent.mkdir(parents=True, exist_ok=True)
        with open(work_order_path, 'w', encoding='UTF-8') as file:
            json.dump({"active_work_orders": work_orders}, file, indent=2, ensure_ascii=False)

    def add_work_order_local(self, scan_result):
        work_order = scan_result.get("work_order")
        if not isinstance(work_order, dict):
            return {
                "success": False,
                "message": "No valid work order data found.",
            }

        selected_materials = work_order.get("selected_materials")
        if not isinstance(selected_materials, list) or not selected_materials:
            return {
                "success": False,
                "message": "No selected materials found in the work order.",
            }

        active_work_orders = self.load_active_work_orders()
        work_order_entry = {
            "id": str(uuid.uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
            "work_order": work_order,
        }
        active_work_orders.append(work_order_entry)
        self.save_active_work_orders(active_work_orders)

        return {
            "success": True,
            "message": "Refinery work order saved locally.",
            "work_order": work_order_entry,
            "total_active_work_orders": len(active_work_orders),
        }

    def remove_work_order_local(self, work_order_id=None, work_order_index=None):
        active_work_orders = self.load_active_work_orders()
        if not active_work_orders:
            return {
                "success": False,
                "message": "There are no active refinery work orders to remove.",
            }

        remove_index = None
        if work_order_id:
            remove_index = next(
                (index for index, item in enumerate(active_work_orders) if item.get("id") == work_order_id),
                None,
            )
        elif work_order_index is not None:
            try:
                remove_index = int(work_order_index)
            except (TypeError, ValueError):
                remove_index = None

        if remove_index is None or remove_index < 0 or remove_index >= len(active_work_orders):
            return {
                "success": False,
                "message": "Could not identify the refinery work order to remove.",
            }

        removed_work_order = active_work_orders.pop(remove_index)
        self.save_active_work_orders(active_work_orders)
        return {
            "success": True,
            "message": "Refinery work order removed.",
            "removed_work_order": removed_work_order,
            "total_active_work_orders": len(active_work_orders),
        }

    def mining_signature_lookup(self, function_args):
        printr.print(f"Executing function '{self.mining_signature_lookup.__name__}'.", tags="info")
        signature_value = function_args.get("signature_value", function_args.get("scan_value"))
        try:
            signature_value = int(signature_value)
        except (TypeError, ValueError):
            return {
                "success": False,
                "message": "Please provide a valid numeric radar signature value.",
                "do_not_cache": True,
            }

        reference_entries = self.load_signature_reference()
        exact_matches = self.find_signature_matches(signature_value, reference_entries)
        if exact_matches:
            preferred_matches = self.get_preferred_signature_matches(exact_matches)
            match_descriptions = [
                self.format_signature_match_description(match)
                for match in preferred_matches
            ]
            return {
                "success": True,
                "signature_value": signature_value,
                "matches": exact_matches,
                "message": f"Signature {signature_value} matches: {', '.join(match_descriptions)}.",
                "do_not_cache": True,
            }

        max_known_signature = self.get_max_known_signature_value(reference_entries)
        if max_known_signature and signature_value > max_known_signature:
            return {
                "success": False,
                "signature_value": signature_value,
                "matches": [],
                "max_known_signature": max_known_signature,
                "message": f"Signature {signature_value} exceeds the highest known signature value ({max_known_signature}).",
                "do_not_cache": True,
            }

        nearest_matches = self.find_nearest_signature_matches(signature_value, reference_entries)
        return {
            "success": False,
            "signature_value": signature_value,
            "matches": [],
            "nearest_matches": nearest_matches,
            "message": f"No exact mining resource signature match found for {signature_value}.",
            "do_not_cache": True,
        }

    def load_signature_reference(self):
        try:
            with open(self.signature_reference_path, 'r', encoding='UTF-8') as file:
                reference = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        entries = reference.get("entries", [])
        return entries if isinstance(entries, list) else []

    def find_signature_matches(self, signature_value, reference_entries):
        matches = [
            match
            for match in self.iter_signature_reference_values(reference_entries)
            if match["signature_value"] == signature_value
        ]
        return self.sort_signature_matches(matches)

    def find_fuzzy_signature_match(self, signature_value, reference_entries):
        if not self.signature_observer_config.get("ocr_fuzzy_reference_match", True):
            return None
        if not isinstance(signature_value, int):
            return None

        value_text = str(signature_value)
        max_distance = int(self.signature_observer_config.get("ocr_fuzzy_max_distance", 1))
        max_weighted_distance = float(self.signature_observer_config.get("ocr_fuzzy_max_weighted_distance", 0.5))
        max_numeric_delta = int(self.signature_observer_config.get("ocr_fuzzy_max_numeric_delta", 100))
        require_same_length = bool(self.signature_observer_config.get("ocr_fuzzy_require_same_length", True))

        candidates = []
        for match in self.iter_signature_reference_values(reference_entries):
            reference_value = match["signature_value"]
            reference_text = str(reference_value)
            if require_same_length and len(reference_text) != len(value_text):
                continue

            distance = self._levenshtein_distance(value_text, reference_text)
            weighted_distance = self._weighted_digit_levenshtein_distance(value_text, reference_text)
            delta = abs(reference_value - signature_value)
            if distance <= max_distance and weighted_distance <= max_weighted_distance and delta <= max_numeric_delta:
                candidates.append({
                    **match,
                    "ocr_fuzzy_distance": distance,
                    "ocr_fuzzy_weighted_distance": weighted_distance,
                    "ocr_fuzzy_delta": delta,
                })

        if not candidates:
            return None

        candidates = sorted(
            candidates,
            key=lambda item: (
                item["ocr_fuzzy_weighted_distance"],
                item["ocr_fuzzy_distance"],
                item["ocr_fuzzy_delta"],
                self.get_signature_match_priority(item),
                self.get_signature_match_specificity_priority(item),
                item["signature_value"],
            ),
        )
        best_match = candidates[0]
        if len(candidates) > 1:
            second_match = candidates[1]
            if (
                second_match["ocr_fuzzy_weighted_distance"] == best_match["ocr_fuzzy_weighted_distance"]
                and second_match["ocr_fuzzy_distance"] == best_match["ocr_fuzzy_distance"]
                and second_match["ocr_fuzzy_delta"] == best_match["ocr_fuzzy_delta"]
                and second_match["signature_value"] != best_match["signature_value"]
            ):
                return None

        return best_match

    def _weighted_digit_levenshtein_distance(self, left, right):
        if left == right:
            return 0.0
        if not left:
            return float(len(right))
        if not right:
            return float(len(left))

        previous_row = [float(index) for index in range(len(right) + 1)]
        for left_index, left_char in enumerate(left, start=1):
            current_row = [float(left_index)]
            for right_index, right_char in enumerate(right, start=1):
                insertion_cost = current_row[right_index - 1] + 1.0
                deletion_cost = previous_row[right_index] + 1.0
                substitution_cost = previous_row[right_index - 1] + self._digit_substitution_cost(left_char, right_char)
                current_row.append(min(insertion_cost, deletion_cost, substitution_cost))
            previous_row = current_row
        return previous_row[-1]

    def _digit_substitution_cost(self, left, right):
        if left == right:
            return 0.0

        common_ocr_confusions = {
            frozenset(("6", "8")): 0.2,
            frozenset(("0", "8")): 0.35,
            frozenset(("0", "9")): 0.45,
            frozenset(("1", "7")): 0.45,
            frozenset(("3", "8")): 0.55,
            frozenset(("5", "6")): 0.75,
        }
        return common_ocr_confusions.get(frozenset((left, right)), 1.0)

    def _levenshtein_distance(self, left, right):
        if left == right:
            return 0
        if not left:
            return len(right)
        if not right:
            return len(left)

        previous_row = list(range(len(right) + 1))
        for left_index, left_char in enumerate(left, start=1):
            current_row = [left_index]
            for right_index, right_char in enumerate(right, start=1):
                insertion_cost = current_row[right_index - 1] + 1
                deletion_cost = previous_row[right_index] + 1
                substitution_cost = previous_row[right_index - 1] + (left_char != right_char)
                current_row.append(min(insertion_cost, deletion_cost, substitution_cost))
            previous_row = current_row
        return previous_row[-1]

    def get_max_known_signature_value(self, reference_entries):
        signature_values = [
            match["signature_value"]
            for match in self.iter_signature_reference_values(reference_entries)
        ]
        return max(signature_values) if signature_values else None

    def is_above_max_known_signature(self, signature_value, reference_entries=None):
        if not isinstance(signature_value, int):
            return False
        reference_entries = reference_entries if reference_entries is not None else self.load_signature_reference()
        max_known_signature = self.get_max_known_signature_value(reference_entries)
        return bool(max_known_signature and signature_value > max_known_signature)

    def get_preferred_signature_matches(self, matches):
        specific_matches = [match for match in matches if match.get("specific_cluster_size")]
        return specific_matches if specific_matches else matches

    def find_nearest_signature_matches(self, signature_value, reference_entries, limit=5):
        candidates = []
        for match in self.iter_signature_reference_values(reference_entries):
            candidates.append({
                **match,
                "delta": abs(match["signature_value"] - signature_value),
            })
        return sorted(
            candidates,
            key=lambda item: (
                item["delta"],
                self.get_signature_match_priority(item),
                self.get_signature_match_specificity_priority(item),
                item["signature_value"],
            ),
        )[:limit]

    def sort_signature_matches(self, matches):
        return sorted(
            matches,
            key=lambda item: (
                self.get_signature_match_priority(item),
                self.get_signature_match_specificity_priority(item),
                item["signature_value"],
                item["resource"],
            ),
        )

    def get_signature_match_priority(self, match):
        category = match.get("category")
        if category in SIGNATURE_MATCH_PRIORITY:
            return SIGNATURE_MATCH_PRIORITY[category]
        resource = match.get("resource")
        if resource in SIGNATURE_MATCH_PRIORITY:
            return SIGNATURE_MATCH_PRIORITY[resource]
        return 10

    def get_signature_match_specificity_priority(self, match):
        return 0 if match.get("specific_cluster_size") else 1

    def iter_signature_reference_values(self, reference_entries):
        for entry in reference_entries:
            resource = entry.get("resource")
            base_signature = entry.get("base_signature")
            max_count = entry.get("max_count")
            if not resource or not isinstance(base_signature, int) or not isinstance(max_count, int):
                continue

            cluster_sizes = self._get_signature_reference_cluster_sizes(entry, max_count)
            counts = cluster_sizes if cluster_sizes else range(1, max_count + 1)
            for count in counts:
                yield {
                    "resource": resource,
                    "category": entry.get("category", "Mining Resource"),
                    "count": count,
                    "cluster_size": count,
                    "specific_cluster_size": bool(cluster_sizes),
                    "base_signature": base_signature,
                    "signature_value": base_signature * count,
                }

    def _get_signature_reference_cluster_sizes(self, entry, max_count):
        cluster_sizes = entry.get("cluster_sizes")
        if not isinstance(cluster_sizes, list):
            return []

        normalized_cluster_sizes = []
        for cluster_size in cluster_sizes:
            try:
                cluster_size = int(cluster_size)
            except (TypeError, ValueError):
                continue
            if 1 <= cluster_size <= max_count:
                normalized_cluster_sizes.append(cluster_size)
        return sorted(set(normalized_cluster_sizes))

    def format_signature_match_description(self, match):
        cluster_size = match.get("cluster_size", match.get("count"))
        if match.get("specific_cluster_size"):
            return f"{match['resource']} cluster {cluster_size} ({match['category']})"
        return f"{match['resource']} x{match['count']} ({match['category']})"

    def _get_signature_observer_config(self):
        manager_config = self.config.get("features", {}).get(self.__class__.__name__, {})
        observer_config = {}
        if isinstance(manager_config, dict):
            observer_config = manager_config.get("signature_observer", {}) or {}

        merged = {**SIGNATURE_OBSERVER_DEFAULTS, **observer_config}
        merged["watch_area"] = {
            **SIGNATURE_OBSERVER_DEFAULTS["watch_area"],
            **(observer_config.get("watch_area", {}) if isinstance(observer_config, dict) else {}),
        }
        merged["dynamic_watch_area"] = {
            **SIGNATURE_OBSERVER_DEFAULTS["dynamic_watch_area"],
            **(observer_config.get("dynamic_watch_area", {}) if isinstance(observer_config, dict) else {}),
        }
        merged["dynamic_watch_area"]["anchor_search_area"] = {
            **SIGNATURE_OBSERVER_DEFAULTS["dynamic_watch_area"]["anchor_search_area"],
            **(
                observer_config.get("dynamic_watch_area", {}).get("anchor_search_area", {})
                if isinstance(observer_config, dict)
                and isinstance(observer_config.get("dynamic_watch_area", {}), dict)
                else {}
            ),
        }
        merged["dynamic_watch_area"]["signature_area_offset"] = {
            **SIGNATURE_OBSERVER_DEFAULTS["dynamic_watch_area"]["signature_area_offset"],
            **(
                observer_config.get("dynamic_watch_area", {}).get("signature_area_offset", {})
                if isinstance(observer_config, dict)
                and isinstance(observer_config.get("dynamic_watch_area", {}), dict)
                else {}
            ),
        }
        return merged

    def start_signature_observer(self):
        with self.signature_observer_lock:
            if self.signature_observer_thread and self.signature_observer_thread.is_alive():
                return

            self.signature_observer_stop_event = threading.Event()
            self.signature_observer_active_until = 0.0
            self._start_signature_vision_worker()
            self.signature_tab_listener = keyboard.Listener(
                on_press=self._on_signature_observer_key_press,
                on_release=self._on_signature_observer_key_release,
            )
            self.signature_tab_listener.daemon = True
            self.signature_tab_listener.start()
            self.signature_observer_thread = threading.Thread(
                target=self._signature_observer_loop,
                args=(self.signature_observer_stop_event,),
                daemon=True,
                name="MiningSignatureObserver",
            )
            self.signature_observer_thread.start()
            printr.print("Mining signature observer started.", tags="info")
            self._signature_debug(
                "listener started; press Tab in Star Citizen to enable OCR analysis window"
            )

    def stop_signature_observer(self):
        with self.signature_observer_lock:
            stop_event = self.signature_observer_stop_event
            thread = self.signature_observer_thread
            tab_listener = self.signature_tab_listener
            self.signature_observer_stop_event = None
            self.signature_observer_thread = None
            self.signature_tab_listener = None
            self.signature_observer_active_until = 0.0

        if stop_event:
            stop_event.set()
        self._stop_signature_vision_worker()
        if tab_listener:
            tab_listener.stop()
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        self._clear_signature_overlay()
        self._clear_signature_debug_scan_area()
        self._clear_signature_status_dot()
        printr.print("Mining signature observer stopped.", tags="info")

    def _on_signature_observer_key_press(self, key):
        if self._is_signature_alt_key(key):
            self.signature_alt_modifier_down = True
            return

        if key != keyboard.Key.tab:
            return

        now = time.time()
        if self.signature_alt_modifier_down:
            self._signature_debug("Tab ignored because Alt is held")
            return

        if not self._is_star_citizen_window_active():
            self.signature_last_non_star_citizen_focus_time = now
            was_active = self._deactivate_signature_analysis(reset_state=True)
            if was_active:
                self._signature_debug("analysis stopped: Star Citizen lost focus")
            self._signature_debug("Tab ignored because Star Citizen is not the active window")
            return

        focus_grace_seconds = float(self.signature_observer_config.get("focus_activation_grace_seconds", 1.0))
        if now - self.signature_last_non_star_citizen_focus_time < max(0.0, focus_grace_seconds):
            self._signature_debug(
                "Tab ignored because Star Citizen focus was just restored; press Tab again to ping",
                throttle_key="tab_focus_grace",
                interval_seconds=0.25,
            )
            return

        duration_seconds = float(self.signature_observer_config.get("activation_duration_seconds", 120))
        self._activate_signature_analysis_window(duration_seconds)
        self._show_signature_debug_scan_area()
        self._show_signature_status_dot("white")
        printr.print(f"Mining signature OCR active for {int(duration_seconds)} seconds.", tags="info")
        self._signature_debug(
            f"Tab detected; OCR analysis active for {int(duration_seconds)}s"
        )

    def _on_signature_observer_key_release(self, key):
        if self._is_signature_alt_key(key):
            self.signature_alt_modifier_down = False

    def _is_signature_alt_key(self, key):
        return key in {
            keyboard.Key.alt,
            keyboard.Key.alt_l,
            keyboard.Key.alt_r,
            getattr(keyboard.Key, "alt_gr", None),
        }

    def _signature_observer_loop(self, stop_event):
        interval_seconds = float(self.signature_observer_config.get("interval_seconds", 0.75))
        tracking_enabled = bool(self.signature_observer_config.get("signature_icon_tracking_enabled", True))
        tracking_interval_seconds = float(
            self.signature_observer_config.get("signature_icon_tracking_interval_seconds", 0.25)
        )
        tracking_interval_seconds = max(0.05, tracking_interval_seconds)
        next_analysis_at = 0.0
        while not stop_event.is_set():
            active = False
            try:
                active = self._should_analyze_signature_hud()
                if active:
                    now = time.time()
                    if now >= next_analysis_at:
                        self._signature_debug("analysis tick", throttle_key="analysis_tick")
                        self._run_signature_analysis_tick()
                        next_analysis_at = time.time() + max(0.1, interval_seconds)
                    elif tracking_enabled and self.signature_last_icon_match_rect:
                        self._refresh_signature_icon_tracking()
                else:
                    next_analysis_at = 0.0
            except pytesseract.TesseractNotFoundError:
                if not self.signature_ocr_unavailable_reported:
                    self.signature_ocr_unavailable_reported = True
                    printr.print_warn("Tesseract OCR is not installed or not available in PATH.")
                    self.overlay.display_overlay_text(
                        "Cora: Local OCR unavailable",
                        vertical_position_ratio=4,
                        display_duration=5000,
                    )
            except Exception as e:
                printr.print_warn(f"Mining signature observer failed: {e}")
                self._signature_debug(f"exception: {e}")

            wait_seconds = tracking_interval_seconds if active and tracking_enabled else max(0.1, interval_seconds)
            stop_event.wait(timeout=max(0.05, wait_seconds))

    def _run_signature_analysis_tick(self):
        signature_capture = self._capture_signature_watch_area()
        signature_value, number_crop = self._read_signature_value(signature_capture)
        if signature_value is not None:
            if not self._is_signature_analysis_active():
                self._signature_debug(
                    "discarding signature result because analysis window expired",
                    throttle_key="expired_result",
                )
                return
            self._signature_debug(f"read signature value {signature_value}")
            signature_status = self._get_observed_signature_status(signature_value)
            if signature_status == "known":
                self.signature_unknown_reads = 0
                extension_seconds = self._extend_signature_analysis_after_value()
                if extension_seconds:
                    self._signature_debug(
                        f"signature recognized; OCR analysis refreshed for {int(extension_seconds)}s",
                        throttle_key="recognition_extension",
                    )
                self._handle_observed_signature(signature_value, number_crop)
            else:
                self._show_signature_status_dot(
                    "red",
                    symbol="C" if self.signature_last_value_source == "cache" else None,
                )
                self._handle_unknown_signature_value(signature_value, number_crop, signature_status)
            return

        if (
            number_crop is not None
            and not self.signature_observer_config.get("local_signature_ocr_enabled", False)
            and self.signature_observer_config.get("vision_signature_fallback_enabled", True)
        ):
            now = time.time()
            if now < self.signature_vision_backoff_until:
                self._show_signature_status_dot(
                    "red",
                    symbol="!",
                    hold_ms_override=int((self.signature_vision_backoff_until - now) * 1000),
                    use_cached_rect=True,
                )
            elif self.signature_last_vision_skip_reason == "overlay_artifact":
                self._show_signature_status_dot("red", symbol="!", use_cached_rect=True)
            else:
                self._show_signature_status_dot("yellow")
                self._signature_debug(
                    "waiting for Vision AI signature result",
                    throttle_key="vision_pending",
                    interval_seconds=0.5,
                )
            return

        self._show_signature_status_dot("white")
        self.signature_unknown_reads = 0
        self._handle_signature_miss()
        if number_crop is None:
            self._signature_debug("no signature value detected in watch area", throttle_key="no_value")
        else:
            self._signature_debug("discarding implausible OCR value", throttle_key="discard_implausible_signature")

    def _should_analyze_signature_hud(self):
        if not self._is_star_citizen_window_active():
            self.signature_last_non_star_citizen_focus_time = time.time()
            was_active = self._deactivate_signature_analysis(reset_state=True)
            if was_active:
                self._signature_debug("analysis stopped: Star Citizen lost focus")
            return False
        with self.signature_observer_lock:
            active = time.time() < self.signature_observer_active_until
        if not active:
            self._signature_debug("analysis inactive: waiting for Tab ping", throttle_key="waiting_for_tab")
            self._clear_signature_overlay()
            self._clear_signature_debug_scan_area()
            self._clear_signature_status_dot()
        return active

    def _is_signature_analysis_active(self):
        if not self._is_star_citizen_window_active():
            return False
        with self.signature_observer_lock:
            return time.time() < self.signature_observer_active_until

    def _activate_signature_analysis_window(self, duration_seconds):
        with self.signature_observer_lock:
            self.signature_observer_active_until = time.time() + max(1.0, duration_seconds)
            self.signature_candidate_value = None
            self.signature_candidate_reads = 0
            self.signature_candidate_misses = 0
            self.signature_unknown_reads = 0
            self.signature_last_icon_match_rect = None
            self.signature_icon_tracking_misses = 0

    def _deactivate_signature_analysis(self, reset_state=True):
        with self.signature_observer_lock:
            was_active = time.time() < self.signature_observer_active_until
            self.signature_observer_active_until = 0.0
            if reset_state:
                self.signature_candidate_value = None
                self.signature_candidate_reads = 0
                self.signature_candidate_misses = 0
                self.signature_unknown_reads = 0
                self.signature_last_icon_match_rect = None
                self.signature_icon_tracking_misses = 0

        self._clear_signature_overlay()
        self._clear_signature_debug_scan_area()
        self._clear_signature_status_dot()
        return was_active

    def _extend_signature_analysis_after_value(self):
        extension_seconds = float(self.signature_observer_config.get("recognition_extension_seconds", 30))
        if extension_seconds <= 0:
            return None

        with self.signature_observer_lock:
            self.signature_observer_active_until = time.time() + max(1.0, extension_seconds)
            return extension_seconds

    def _signature_debug(self, message, throttle_key=None, interval_seconds=None):
        if not self.signature_observer_config.get("debug_mode", False):
            return

        if throttle_key:
            interval = float(
                interval_seconds
                if interval_seconds is not None
                else self.signature_observer_config.get("debug_log_interval_seconds", 2.0)
            )
            now = time.time()
            last_log_time = self.signature_debug_last_by_key.get(throttle_key, 0.0)
            if now - last_log_time < interval:
                return
            self.signature_debug_last_by_key[throttle_key] = now

        printr.print(f"Mining signature debug: {message}", tags="info")

    def _is_star_citizen_window_active(self):
        try:
            active_window = pygetwindow.getActiveWindow()
            return bool(active_window and "Star Citizen" in (active_window.title or ""))
        except Exception:
            return False

    def _capture_signature_watch_area(self):
        active_window = pygetwindow.getActiveWindow()
        if not active_window:
            return None

        watch_area = self.signature_observer_config.get("watch_area", {})
        relative_rect = self._resolve_signature_watch_area_rect(active_window, watch_area)
        if not relative_rect:
            self.signature_last_watch_area_rect = None
            return None

        rel_x, rel_y, width, height = relative_rect
        self.signature_last_watch_area_rect = relative_rect
        x = active_window.left + rel_x
        y = active_window.top + rel_y
        if width <= 0 or height <= 0:
            self._signature_debug(f"invalid watch area: {relative_rect}", throttle_key="invalid_area")
            return None

        self._signature_debug(
            f"capturing window for watch area relative=({rel_x}, {rel_y}, {width}, {height}) "
            f"screen=({x}, {y}, {width}, {height})",
            throttle_key="capture_area",
        )
        if self.signature_observer_config.get("debug_mode", False):
            self._clear_signature_debug_scan_area()
            clear_wait_ms = int(
                self.signature_observer_config.get("debug_overlay_pre_capture_clear_wait_ms", 50)
            )
            if clear_wait_ms > 0:
                time.sleep(clear_wait_ms / 1000.0)

        screenshot_pil = pyautogui.screenshot(
            region=(active_window.left, active_window.top, active_window.width, active_window.height)
        )
        window_image = cv2.cvtColor(np.array(screenshot_pil), cv2.COLOR_RGB2BGR)
        watch_image = window_image[rel_y:rel_y + height, rel_x:rel_x + width]
        if self.signature_observer_config.get("debug_mode", False):
            self._show_signature_debug_scan_area(active_window=active_window, relative_rect=relative_rect)
        return {
            "window_image": window_image,
            "watch_image": watch_image,
            "watch_rect": relative_rect,
        }

    def _show_signature_debug_scan_area(self, active_window=None, relative_rect=None):
        if not self.signature_observer_config.get("debug_mode", False):
            self._clear_signature_debug_scan_area()
            return

        try:
            if active_window is None:
                active_window = pygetwindow.getActiveWindow()
            if not active_window:
                return

            if relative_rect is None:
                watch_area = self.signature_observer_config.get("watch_area", {})
                relative_rect = self._resolve_signature_watch_area_rect(active_window, watch_area)
            if not relative_rect:
                return

            rel_x, rel_y, width, height = self._get_signature_debug_rect(relative_rect)
            self.overlay.display_debug_rectangle(
                active_window.left + rel_x,
                active_window.top + rel_y,
                width,
                height,
                color="red",
                auto_clear_ms=int(self.signature_observer_config.get("debug_rectangle_auto_clear_ms", 120)),
            )
        except Exception as e:
            self._signature_debug(f"could not show debug scan area: {e}", throttle_key="debug_scan_area_failed")

    def _clear_signature_debug_scan_area(self):
        self.overlay.clear_debug_rectangle()

    def _refresh_signature_icon_tracking(self):
        if not self.signature_last_icon_match_rect:
            return False

        active_window = pygetwindow.getActiveWindow()
        if not active_window:
            return False

        search_rect = self._resolve_signature_icon_tracking_rect(active_window)
        if not search_rect:
            return False

        rel_x, rel_y, width, height = search_rect
        try:
            screenshot_pil = pyautogui.screenshot(
                region=(
                    active_window.left + rel_x,
                    active_window.top + rel_y,
                    width,
                    height,
                )
            )
            search_image = cv2.cvtColor(np.array(screenshot_pil), cv2.COLOR_RGB2BGR)
        except Exception as e:
            self._signature_debug(f"signature icon tracking screenshot failed: {e}", throttle_key="icon_tracking_capture_failed")
            return False

        icon_match = self._find_signature_icon_match(search_image)
        if not icon_match:
            self.signature_icon_tracking_misses += 1
            miss_tolerance = int(self.signature_observer_config.get("signature_icon_tracking_miss_tolerance", 4))
            if self.signature_icon_tracking_misses > max(0, miss_tolerance):
                self._signature_debug(
                    "signature icon tracking missed repeatedly; waiting for next full scan",
                    throttle_key="icon_tracking_miss",
                    interval_seconds=0.5,
                )
            return False

        self.signature_icon_tracking_misses = 0
        self._set_signature_icon_match_rect(
            rel_x + int(icon_match["x"]),
            rel_y + int(icon_match["y"]),
            int(icon_match["width"]),
            int(icon_match["height"]),
        )
        self._signature_debug(
            f"signature icon tracked pos=({self.signature_last_icon_match_rect[0]},{self.signature_last_icon_match_rect[1]}) "
            f"score={icon_match['score']:.2f}",
            throttle_key="icon_tracking_match",
            interval_seconds=0.5,
        )
        self._refresh_signature_overlay_text_position()
        return True

    def _resolve_signature_icon_tracking_rect(self, active_window):
        icon_rect = self.signature_last_icon_match_rect
        if not icon_rect:
            return None

        icon_x, icon_y, icon_width, icon_height = icon_rect
        padding = int(self.signature_observer_config.get("signature_icon_tracking_search_padding_pixels", 48))
        padding = max(0, padding)
        x = icon_x - padding
        y = icon_y - padding
        width = icon_width + padding * 2
        height = icon_height + padding * 2
        return self._clamp_relative_rect(active_window, (x, y, width, height))

    def _get_signature_debug_rect(self, watch_relative_rect):
        number_crop_rect = self.signature_last_number_crop_rect
        if not number_crop_rect:
            return watch_relative_rect

        watch_x, watch_y, _, _ = watch_relative_rect
        crop_x, crop_y, crop_width, crop_height = number_crop_rect
        return (
            watch_x + crop_x,
            watch_y + crop_y,
            crop_width,
            crop_height,
        )

    def _show_signature_status_dot(self, color, symbol=None, hold_ms_override=None, use_cached_rect=False):
        try:
            active_window = pygetwindow.getActiveWindow()
            if not active_window:
                return

            relative_rect = self.signature_last_watch_area_rect if use_cached_rect else None
            if not relative_rect:
                watch_area = self.signature_observer_config.get("watch_area", {})
                relative_rect = self._resolve_signature_watch_area_rect(active_window, watch_area)
            if not relative_rect:
                return

            size = int(self.signature_observer_config.get("status_dot_size", 10))
            blink_ms = int(self.signature_observer_config.get("status_dot_blink_ms", 450))
            hold_ms = int(self.signature_observer_config.get("status_dot_hold_ms", 900))
            if hold_ms_override is not None:
                hold_ms = int(hold_ms_override)
            x_center, y_center = self._get_signature_status_dot_position(
                active_window,
                relative_rect,
                size,
            )
            self.overlay.display_blinking_status_dot(
                x_center=x_center,
                y_center=y_center,
                color=color,
                size=size,
                blink_ms=blink_ms,
                hold_ms=hold_ms if color != "white" else None,
                reset_to_color="white" if color != "white" else None,
                symbol=symbol,
            )
        except Exception as e:
            self._signature_debug(f"could not show signature status dot: {e}", throttle_key="status_dot_failed")

    def _clear_signature_status_dot(self):
        self.overlay.clear_blinking_status_dot()

    def _get_signature_status_dot_position(self, active_window, relative_rect, size=None):
        rel_x, rel_y, width, height = relative_rect
        offset = int(self.signature_observer_config.get("status_dot_offset_pixels", 16))
        dot_size = int(size if size is not None else self.signature_observer_config.get("status_dot_size", 10))
        icon_rect = self.signature_last_icon_match_rect
        if icon_rect:
            icon_x, icon_y, _, icon_height = icon_rect
            x_center = active_window.left + icon_x - offset
            y_center = active_window.top + icon_y + icon_height // 2
        else:
            x_center = active_window.left + rel_x + width // 2
            y_center = active_window.top + rel_y + height // 2
        return max(active_window.left + dot_size, x_center), y_center

    def _resolve_signature_watch_area_rect(self, active_window, watch_area):
        dynamic_rect = self._resolve_dynamic_signature_watch_area_rect(active_window)
        if dynamic_rect:
            return dynamic_rect

        coords = watch_area.get("coords")
        if coords:
            try:
                (x1, y1), (x2, y2) = coords
                x_min, x_max = sorted((int(x1), int(x2)))
                y_min, y_max = sorted((int(y1), int(y2)))
                x_min = max(0, min(active_window.width - 1, x_min))
                y_min = max(0, min(active_window.height - 1, y_min))
                x_max = max(0, min(active_window.width, x_max))
                y_max = max(0, min(active_window.height, y_max))
                rect = (x_min, y_min, x_max - x_min, y_max - y_min)
                self._signature_debug(f"using configured watch_area.coords={coords} resolved={rect}", throttle_key="coords")
                return rect
            except (TypeError, ValueError):
                printr.print_warn(f"Invalid MiningManager signature_observer.watch_area.coords: {coords}")
                return None

        width = max(1, int(active_window.width * float(watch_area.get("width_ratio", 0.24))))
        height = max(1, int(active_window.height * float(watch_area.get("height_ratio", 0.12))))
        center_x = int(active_window.width * float(watch_area.get("center_x_ratio", 0.5)))
        center_y = int(active_window.height * float(watch_area.get("center_y_ratio", 0.27)))
        x = max(0, center_x - width // 2)
        y = max(0, center_y - height // 2)
        width = min(width, active_window.width - x)
        height = min(height, active_window.height - y)
        rect = (x, y, width, height)
        self._signature_debug(f"using ratio watch area resolved={rect}", throttle_key="ratio_area")
        return rect

    def _resolve_dynamic_signature_watch_area_rect(self, active_window):
        dynamic_config = self.signature_observer_config.get("dynamic_watch_area", {})
        if not isinstance(dynamic_config, dict) or not dynamic_config.get("enabled", False):
            return None

        now = time.time()
        refresh_seconds = float(dynamic_config.get("refresh_seconds", 10.0))
        missing_icon_refresh_after = int(dynamic_config.get("missing_icon_refresh_after", 2))
        refresh_interval = max(0.1, refresh_seconds)
        has_dynamic_rect = self.signature_dynamic_watch_area_rect is not None
        needs_refresh = (
            self.signature_dynamic_watch_area_updated_at <= 0.0
            or now - self.signature_dynamic_watch_area_updated_at >= refresh_interval
            or (
                has_dynamic_rect
                and self.signature_icon_miss_count >= max(1, missing_icon_refresh_after)
            )
        )

        if not needs_refresh:
            if self.signature_dynamic_watch_area_rect:
                self._signature_debug(
                    f"using cached dynamic watch area resolved={self.signature_dynamic_watch_area_rect}",
                    throttle_key="dynamic_watch_cached",
                )
                return self.signature_dynamic_watch_area_rect
            return None

        anchor_match = self._find_dynamic_watch_area_anchor(active_window, dynamic_config)
        self.signature_dynamic_watch_area_updated_at = now
        if anchor_match:
            dynamic_rect = self._build_dynamic_signature_watch_area_rect(active_window, dynamic_config, anchor_match)
            if dynamic_rect:
                self.signature_dynamic_watch_area_rect = dynamic_rect
                self.signature_icon_miss_count = 0
                self._signature_debug(
                    f"dynamic watch area resolved={dynamic_rect} from template={anchor_match['template_name']} score={anchor_match['score']:.2f}"
                )
                return dynamic_rect

        if dynamic_config.get("use_last_on_miss", True) and self.signature_dynamic_watch_area_rect:
            self.signature_icon_miss_count = 0
            self._signature_debug(
                f"dynamic watch anchor not found; using last area={self.signature_dynamic_watch_area_rect}",
                throttle_key="dynamic_watch_anchor_miss",
            )
            return self.signature_dynamic_watch_area_rect

        self._signature_debug("dynamic watch anchor not found; falling back to configured watch_area", throttle_key="dynamic_watch_fallback")
        return None

    def _find_dynamic_watch_area_anchor(self, active_window, dynamic_config):
        search_area = dynamic_config.get("anchor_search_area", {})
        search_rect = self._resolve_rect_config(active_window, search_area)
        if not search_rect:
            return None

        rel_x, rel_y, width, height = search_rect
        if width <= 0 or height <= 0:
            return None

        screenshot_pil = pyautogui.screenshot(
            region=(
                active_window.left + rel_x,
                active_window.top + rel_y,
                width,
                height,
            )
        )
        search_image = cv2.cvtColor(np.array(screenshot_pil), cv2.COLOR_RGB2BGR)
        search_gray = cv2.cvtColor(search_image, cv2.COLOR_BGR2GRAY)
        templates = self._load_dynamic_watch_anchor_templates(dynamic_config)
        if not templates:
            return None

        scales = dynamic_config.get("anchor_scales", [1.0])
        if not isinstance(scales, list):
            scales = [1.0]

        best_match = None
        for template in templates:
            template_gray = template["gray"]
            for scale in scales:
                try:
                    scale = float(scale)
                except (TypeError, ValueError):
                    continue
                if scale <= 0:
                    continue

                scaled_width = max(4, int(template_gray.shape[1] * scale))
                scaled_height = max(4, int(template_gray.shape[0] * scale))
                if scaled_width > search_gray.shape[1] or scaled_height > search_gray.shape[0]:
                    continue

                scaled_template = cv2.resize(
                    template_gray,
                    (scaled_width, scaled_height),
                    interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC,
                )
                match_result = cv2.matchTemplate(search_gray, scaled_template, cv2.TM_CCOEFF_NORMED)
                _, max_value, _, max_location = cv2.minMaxLoc(match_result)
                if best_match is None or max_value > best_match["score"]:
                    best_match = {
                        "score": float(max_value),
                        "x": rel_x + int(max_location[0]),
                        "y": rel_y + int(max_location[1]),
                        "width": scaled_width,
                        "height": scaled_height,
                        "scale": scale,
                        "template_name": template["name"],
                    }

        threshold = float(dynamic_config.get("anchor_match_threshold", 0.70))
        if not best_match or best_match["score"] < threshold:
            if best_match:
                self._signature_debug(
                    f"dynamic watch anchor below threshold template={best_match['template_name']} score={best_match['score']:.2f} threshold={threshold:.2f}",
                    throttle_key="dynamic_watch_low_score",
                    interval_seconds=1.0,
                )
            return None

        self._signature_debug(
            f"dynamic watch anchor matched template={best_match['template_name']} score={best_match['score']:.2f} pos=({best_match['x']},{best_match['y']}) scale={best_match['scale']:.2f}",
            throttle_key="dynamic_watch_anchor",
            interval_seconds=1.0,
        )
        return best_match

    def _load_dynamic_watch_anchor_templates(self, dynamic_config):
        if self.signature_dynamic_anchor_templates is not None:
            return self.signature_dynamic_anchor_templates

        configured_glob = str(dynamic_config.get("anchor_templates_glob", "templates/scans/scan_area_*.jpg"))
        if os.path.isabs(configured_glob):
            template_paths = sorted(Path(configured_glob).parent.glob(Path(configured_glob).name))
        else:
            template_paths = sorted(Path(self.mining_data_path).glob(configured_glob))

        templates = []
        for template_path in template_paths:
            image = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
            if image is None:
                continue
            templates.append({
                "name": template_path.name,
                "gray": cv2.cvtColor(image, cv2.COLOR_BGR2GRAY),
            })

        self.signature_dynamic_anchor_templates = templates
        self._signature_debug(f"loaded {len(templates)} dynamic watch anchor templates", throttle_key="dynamic_watch_templates")
        return templates

    def _build_dynamic_signature_watch_area_rect(self, active_window, dynamic_config, anchor_match):
        offset = dynamic_config.get("signature_area_offset", {})
        x = int(anchor_match["x"] + int(offset.get("x", 250)))
        y = int(anchor_match["y"] + int(offset.get("y", -250)))
        width = int(offset.get("width", 300))
        height = int(offset.get("height", 210))
        return self._clamp_relative_rect(active_window, (x, y, width, height))

    def _resolve_rect_config(self, active_window, rect_config):
        coords = rect_config.get("coords") if isinstance(rect_config, dict) else None
        if coords:
            try:
                (x1, y1), (x2, y2) = coords
                x_min, x_max = sorted((int(x1), int(x2)))
                y_min, y_max = sorted((int(y1), int(y2)))
                return self._clamp_relative_rect(active_window, (x_min, y_min, x_max - x_min, y_max - y_min))
            except (TypeError, ValueError):
                return None

        if not isinstance(rect_config, dict):
            return None
        x = int(active_window.width * float(rect_config.get("x_ratio", 0.0)))
        y = int(active_window.height * float(rect_config.get("y_ratio", 0.0)))
        width = int(active_window.width * float(rect_config.get("width_ratio", 1.0)))
        height = int(active_window.height * float(rect_config.get("height_ratio", 1.0)))
        return self._clamp_relative_rect(active_window, (x, y, width, height))

    def _clamp_relative_rect(self, active_window, rect):
        x, y, width, height = rect
        if width <= 0 or height <= 0:
            return None
        x = max(0, min(active_window.width - 1, int(x)))
        y = max(0, min(active_window.height - 1, int(y)))
        width = max(1, min(int(width), active_window.width - x))
        height = max(1, min(int(height), active_window.height - y))
        return (x, y, width, height)

    def _read_signature_value(self, signature_capture):
        self.signature_last_value_source = None
        self.signature_last_vision_skip_reason = None
        if not signature_capture:
            return None, None

        if isinstance(signature_capture, dict):
            watch_image = signature_capture.get("watch_image")
            source_image = signature_capture.get("window_image")
            watch_rect = signature_capture.get("watch_rect") or self.signature_last_watch_area_rect
            source_offset = (watch_rect[0], watch_rect[1]) if watch_rect else (0, 0)
        else:
            watch_image = signature_capture
            source_image = None
            source_offset = (0, 0)

        if watch_image is None:
            return None, None

        number_crop, number_crop_rect = self._prepare_signature_ocr_crop(
            watch_image,
            source_image=source_image,
            source_offset=source_offset,
        )
        self.signature_last_number_crop_rect = number_crop_rect
        if number_crop is None:
            self.signature_icon_miss_count += 1
            if number_crop_rect:
                self._signature_debug(
                    f"signature number crop unavailable rect={number_crop_rect}",
                    throttle_key="signature_number_crop_unavailable",
                    interval_seconds=0.5,
                )
            else:
                self._signature_debug("signature icon not found in watch area", throttle_key="signature_icon_not_found")
            return None, None
        self.signature_icon_miss_count = 0
        cached_vision_value = self._get_cached_signature_vision_value(number_crop)
        if cached_vision_value is not None:
            return cached_vision_value, number_crop

        if not self.signature_observer_config.get("local_signature_ocr_enabled", False):
            queued_vision_value = self._queue_signature_vision_analysis(number_crop, reason="vision_only")
            if queued_vision_value is not None:
                return queued_vision_value, number_crop
            now = time.time()
            if now < self.signature_vision_backoff_until:
                self._show_signature_status_dot(
                    "red",
                    symbol="!",
                    hold_ms_override=int((self.signature_vision_backoff_until - now) * 1000),
                    use_cached_rect=True,
                )
            elif self.signature_last_vision_skip_reason == "overlay_artifact":
                self._show_signature_status_dot("red", symbol="!", use_cached_rect=True)
                self._signature_debug(
                    "Vision AI skipped because the signature crop contains overlay/debug pixels",
                    throttle_key="vision_overlay_artifact_status",
                    interval_seconds=0.5,
                )
            else:
                self._show_signature_status_dot("yellow")
                self._signature_debug(
                    "local signature OCR disabled; waiting for Vision AI result",
                    throttle_key="local_ocr_disabled",
                    interval_seconds=0.5,
                )
            return None, number_crop

        raw_signature_value = self._ocr_signature_number(number_crop)
        if raw_signature_value is None:
            self._signature_debug("OCR returned no digits", throttle_key="ocr_no_digits")
            self._queue_signature_vision_analysis(number_crop, reason="local_no_digits")
            return cached_vision_value, number_crop

        minimum_digits = int(self.signature_observer_config.get("minimum_signature_digits", 4))
        if len(str(raw_signature_value)) < max(1, minimum_digits):
            self._signature_debug(
                f"OCR read {raw_signature_value}, but it is shorter than {minimum_digits} digits",
                throttle_key="short_ocr_signature",
            )
            self._queue_signature_vision_analysis(number_crop, local_value=raw_signature_value, reason="local_short")
            return cached_vision_value, number_crop

        signature_value = self._correct_signature_ocr_value(raw_signature_value)
        signature_status = self._get_observed_signature_status(signature_value)
        if signature_status != "known":
            self._queue_signature_vision_analysis(number_crop, local_value=signature_value, reason=f"local_{signature_status}")
            if cached_vision_value is not None:
                return cached_vision_value, number_crop
        elif self.signature_observer_config.get("vision_signature_sample_known_reads", False):
            self._queue_signature_vision_analysis(number_crop, local_value=signature_value, reason="local_known_sample")
        self.signature_last_value_source = "local"
        return signature_value, number_crop

    def _start_signature_vision_worker(self):
        if not self.signature_observer_config.get("vision_signature_fallback_enabled", True):
            return
        if self.signature_vision_worker_thread and self.signature_vision_worker_thread.is_alive():
            return

        queue_size = int(self.signature_observer_config.get("vision_signature_queue_size", 1))
        self.signature_vision_queue = queue.Queue(maxsize=max(1, queue_size))
        self.signature_vision_stop_event = threading.Event()
        self.signature_vision_worker_thread = threading.Thread(
            target=self._signature_vision_worker_loop,
            args=(self.signature_vision_stop_event,),
            daemon=True,
            name="MiningSignatureVisionWorker",
        )
        self.signature_vision_worker_thread.start()
        self._signature_debug("signature vision fallback worker started", throttle_key="vision_worker_started")

    def _stop_signature_vision_worker(self):
        stop_event = self.signature_vision_stop_event
        thread = self.signature_vision_worker_thread
        if stop_event:
            stop_event.set()
        if thread and thread.is_alive():
            thread.join(timeout=1.0)
        self.signature_vision_queue = None
        self.signature_vision_stop_event = None
        self.signature_vision_worker_thread = None
        self.signature_vision_queued_hashes.clear()
        self.signature_vision_queued_at_by_hash.clear()
        self.signature_vision_recent_crops.clear()

    def _signature_vision_worker_loop(self, stop_event):
        while not stop_event.is_set():
            active_queue = self.signature_vision_queue
            if active_queue is None:
                stop_event.wait(timeout=0.25)
                continue

            try:
                job = active_queue.get(timeout=0.25)
            except queue.Empty:
                continue

            try:
                result = self._analyze_signature_crop_with_vision(job)
                with self.signature_observer_lock:
                    if result.get("transient_error"):
                        self._apply_signature_vision_backoff(result)
                    else:
                        self.signature_vision_cache[job["image_hash"]] = result
                    self.signature_vision_queued_hashes.discard(job["image_hash"])
                    self.signature_vision_queued_at_by_hash.pop(job["image_hash"], None)
                self._write_signature_vision_training_sample(job, result)
                self._handle_signature_vision_result(job, result)
            except Exception as e:
                with self.signature_observer_lock:
                    self.signature_vision_queued_hashes.discard(job.get("image_hash"))
                    self.signature_vision_queued_at_by_hash.pop(job.get("image_hash"), None)
                self._signature_debug(f"signature vision worker failed: {e}", throttle_key="vision_worker_failed")
                self._write_signature_vision_event(
                    "worker_exception",
                    image_hash=job.get("image_hash"),
                    error=str(e),
                )
            finally:
                try:
                    active_queue.task_done()
                except ValueError:
                    pass

    def _queue_signature_vision_analysis(self, number_crop, local_value=None, reason="local_uncertain"):
        if not self.signature_observer_config.get("vision_signature_fallback_enabled", True):
            self.signature_last_vision_skip_reason = "disabled"
            self._write_signature_vision_event("disabled", reason=reason)
            return None
        if number_crop is None or number_crop.size == 0:
            self.signature_last_vision_skip_reason = "empty_crop"
            self._write_signature_vision_event("empty_crop", reason=reason)
            return None

        image_hash = self._signature_crop_hash(number_crop)
        cached_value = self._get_cached_signature_vision_value(number_crop, image_hash=image_hash)
        if cached_value is not None:
            self._write_signature_vision_event(
                "cache_hit",
                image_hash=image_hash,
                reason=reason,
                signature_value=cached_value,
            )
            return cached_value
        if image_hash in self.signature_vision_cache:
            self.signature_last_vision_skip_reason = "cached_no_value"
            self._signature_debug(
                f"skipping cached no-value signature vision crop hash={image_hash[:12]}",
                throttle_key="vision_cached_no_value",
                interval_seconds=0.5,
            )
            self._write_signature_vision_event(
                "cached_no_value",
                image_hash=image_hash,
                reason=reason,
                crop_shape=self._get_signature_crop_shape(number_crop),
            )
            return None
        now = time.time()
        if now < self.signature_vision_backoff_until:
            self.signature_last_vision_skip_reason = "error_backoff"
            remaining_seconds = self.signature_vision_backoff_until - now
            self._show_signature_status_dot(
                "red",
                symbol="!",
                hold_ms_override=int(remaining_seconds * 1000),
                use_cached_rect=True,
            )
            self._signature_debug(
                f"skipping signature vision crop during error backoff "
                f"{remaining_seconds:.1f}s remaining",
                throttle_key="vision_error_backoff",
                interval_seconds=0.5,
            )
            self._write_signature_vision_event(
                "error_backoff",
                image_hash=image_hash,
                reason=reason,
                remaining_seconds=round(remaining_seconds, 2),
                crop_shape=self._get_signature_crop_shape(number_crop),
            )
            return None

        similar_crop = self._get_recent_similar_signature_vision_crop(number_crop, image_hash, now)
        if similar_crop:
            cached_result = self.signature_vision_cache.get(similar_crop["image_hash"])
            if cached_result and cached_result.get("signature_value") is not None:
                signature_value = cached_result["signature_value"]
                corrected_value = self._correct_signature_ocr_value(signature_value)
                self.signature_last_value_source = "cache"
                self._signature_debug(
                    f"using similar cached vision signature {signature_value}"
                    + (f" corrected={corrected_value}" if corrected_value != signature_value else "")
                    + f" delta={similar_crop['mean_delta']:.1f}",
                    throttle_key="vision_similar_cache_hit",
                    interval_seconds=0.5,
                )
                self._write_signature_vision_event(
                    "similar_cache_hit",
                    image_hash=image_hash,
                    similar_image_hash=similar_crop.get("image_hash"),
                    reason=reason,
                    signature_value=corrected_value,
                    mean_delta=round(float(similar_crop.get("mean_delta", 0.0)), 2),
                )
                return corrected_value
            self._signature_debug(
                f"skipping similar signature vision crop delta={similar_crop['mean_delta']:.1f} hash={image_hash[:12]}",
                throttle_key="vision_near_duplicate",
                interval_seconds=0.5,
            )
            self._write_signature_vision_event(
                "near_duplicate",
                image_hash=image_hash,
                similar_image_hash=similar_crop.get("image_hash"),
                reason=reason,
                mean_delta=round(float(similar_crop.get("mean_delta", 0.0)), 2),
                crop_shape=self._get_signature_crop_shape(number_crop),
            )
            self.signature_last_vision_skip_reason = "near_duplicate"
            return None
        overlay_artifact = self._signature_crop_has_overlay_artifact(number_crop)
        if overlay_artifact and self.signature_observer_config.get("vision_signature_reject_overlay_artifacts", True):
            self.signature_last_vision_skip_reason = "overlay_artifact"
            self._signature_debug(
                f"skipping signature vision crop with overlay artifact hash={image_hash[:12]}",
                throttle_key="vision_overlay_artifact",
                interval_seconds=0.5,
            )
            self._write_signature_vision_event(
                "overlay_artifact",
                image_hash=image_hash,
                reason=reason,
                crop_shape=self._get_signature_crop_shape(number_crop),
            )
            return None

        active_queue = self.signature_vision_queue
        if active_queue is None:
            self._start_signature_vision_worker()
            active_queue = self.signature_vision_queue
        if active_queue is None:
            self.signature_last_vision_skip_reason = "worker_unavailable"
            self._write_signature_vision_event(
                "worker_unavailable",
                image_hash=image_hash,
                reason=reason,
                crop_shape=self._get_signature_crop_shape(number_crop),
            )
            return None

        min_interval = float(self.signature_observer_config.get("vision_signature_min_interval_seconds", 5.0))
        with self.signature_observer_lock:
            self._clear_stale_signature_vision_inflight(now)
            if self.signature_observer_config.get("vision_signature_single_inflight", True) and self.signature_vision_queued_hashes:
                self._signature_debug(
                    "skipping signature vision crop because another Vision AI request is still active",
                    throttle_key="vision_single_inflight",
                    interval_seconds=0.5,
                )
                self._write_signature_vision_event(
                    "single_inflight",
                    image_hash=image_hash,
                    reason=reason,
                    active_hashes=list(self.signature_vision_queued_hashes),
                    crop_shape=self._get_signature_crop_shape(number_crop),
                )
                self.signature_last_vision_skip_reason = "single_inflight"
                return None
            if image_hash in self.signature_vision_queued_hashes:
                self.signature_last_vision_skip_reason = "already_queued"
                self._write_signature_vision_event(
                    "already_queued",
                    image_hash=image_hash,
                    reason=reason,
                    crop_shape=self._get_signature_crop_shape(number_crop),
                )
                return None
            if now - self.signature_vision_last_request_at < max(0.0, min_interval):
                self.signature_last_vision_skip_reason = "min_interval"
                remaining_seconds = max(0.0, min_interval - (now - self.signature_vision_last_request_at))
                self._signature_debug(
                    f"skipping signature vision crop due to {min_interval:.1f}s request interval",
                    throttle_key="vision_min_interval",
                    interval_seconds=0.5,
                )
                self._write_signature_vision_event(
                    "min_interval",
                    image_hash=image_hash,
                    reason=reason,
                    remaining_seconds=round(remaining_seconds, 2),
                    crop_shape=self._get_signature_crop_shape(number_crop),
                )
                return None
            self.signature_vision_queued_hashes.add(image_hash)
            self.signature_vision_queued_at_by_hash[image_hash] = now
            self.signature_vision_last_request_at = now
            self._remember_signature_vision_crop(image_hash, number_crop, now)

        image_path = self._save_signature_vision_crop(number_crop, image_hash)
        job = {
            "image": number_crop.copy(),
            "image_hash": image_hash,
            "image_path": image_path,
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "local_value": local_value,
            "overlay_artifact": overlay_artifact,
            "watch_area_rect": self.signature_last_watch_area_rect,
            "icon_match_rect": self.signature_last_icon_match_rect,
            "number_crop_rect": self.signature_last_number_crop_rect,
        }
        try:
            active_queue.put_nowait(job)
            self._signature_debug(
                f"queued signature vision analysis hash={image_hash[:12]} reason={reason}",
                throttle_key="vision_queued",
                interval_seconds=0.5,
            )
            self._write_signature_vision_event(
                "queued",
                image_hash=image_hash,
                reason=reason,
                image_path=image_path,
                crop_shape=self._get_signature_crop_shape(number_crop),
            )
        except queue.Full:
            self.signature_last_vision_skip_reason = "queue_full"
            with self.signature_observer_lock:
                self.signature_vision_queued_hashes.discard(image_hash)
                self.signature_vision_queued_at_by_hash.pop(image_hash, None)
            self._signature_debug("signature vision queue full; dropping crop", throttle_key="vision_queue_full")
            self._write_signature_vision_event(
                "queue_full",
                image_hash=image_hash,
                reason=reason,
                crop_shape=self._get_signature_crop_shape(number_crop),
            )
        return None

    def _clear_stale_signature_vision_inflight(self, now):
        timeout_seconds = float(
            self.signature_observer_config.get("vision_signature_inflight_timeout_seconds", 60.0)
        )
        if timeout_seconds <= 0:
            return

        stale_hashes = [
            image_hash
            for image_hash, queued_at in self.signature_vision_queued_at_by_hash.items()
            if now - float(queued_at) > timeout_seconds
        ]
        for image_hash in stale_hashes:
            queued_at = float(self.signature_vision_queued_at_by_hash.pop(image_hash, now))
            self.signature_vision_queued_hashes.discard(image_hash)
            age_seconds = now - queued_at
            self._write_signature_vision_event(
                "inflight_timeout",
                image_hash=image_hash,
                age_seconds=round(age_seconds, 2),
                timeout_seconds=timeout_seconds,
            )
            self._signature_debug(
                f"cleared stale signature vision inflight hash={image_hash[:12]} age={age_seconds:.1f}s",
                throttle_key="vision_inflight_timeout",
                interval_seconds=0.5,
            )

    def _get_signature_crop_shape(self, image):
        if image is None or not hasattr(image, "shape"):
            return None
        height, width = image.shape[:2]
        return {"width": int(width), "height": int(height)}

    def _write_signature_vision_event(self, event, **payload):
        if not self.signature_observer_config.get("log_signature_vision_events", True):
            return

        interval = float(
            self.signature_observer_config.get("signature_vision_event_log_interval_seconds", 2.0)
        )
        image_hash = payload.get("image_hash")
        throttle_key = f"{event}:{image_hash or ''}:{payload.get('reason') or ''}"
        now = time.time()
        last_logged_at = self.signature_vision_event_last_by_key.get(throttle_key, 0.0)
        if interval > 0 and now - last_logged_at < interval:
            return
        self.signature_vision_event_last_by_key[throttle_key] = now

        training_dir = self._get_signature_vision_training_dir()
        filename = os.path.join(training_dir, "signature_vision_events.jsonl")
        event_payload = {
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **payload,
        }
        try:
            os.makedirs(training_dir, exist_ok=True)
            with open(filename, "a", encoding="UTF-8") as file:
                file.write(json.dumps(event_payload, ensure_ascii=False) + "\n")
        except Exception as e:
            self._signature_debug(f"could not write signature vision event: {e}", throttle_key="vision_event_write_failed")

    def _get_cached_signature_vision_value(self, number_crop, image_hash=None):
        if not self.signature_observer_config.get("vision_signature_fallback_enabled", True):
            return None
        image_hash = image_hash or self._signature_crop_hash(number_crop)
        cached_result = self.signature_vision_cache.get(image_hash)
        if not cached_result:
            return None
        signature_value = cached_result.get("signature_value")
        if signature_value is None:
            return None
        corrected_value = self._correct_signature_ocr_value(signature_value)
        self.signature_last_value_source = "cache"
        self._signature_debug(
            f"using cached vision signature {signature_value}"
            + (f" corrected={corrected_value}" if corrected_value != signature_value else "")
            + f" for hash={image_hash[:12]}",
            throttle_key="vision_cache_hit",
            interval_seconds=0.5,
        )
        return corrected_value

    def _get_recent_similar_signature_vision_crop(self, number_crop, image_hash, now):
        if not self.signature_observer_config.get("vision_signature_near_duplicate_enabled", True):
            return None

        cooldown_seconds = float(
            self.signature_observer_config.get("vision_signature_near_duplicate_cooldown_seconds", 30.0)
        )
        max_mean_delta = float(
            self.signature_observer_config.get("vision_signature_near_duplicate_max_mean_delta", 18.0)
        )
        if cooldown_seconds <= 0 or max_mean_delta < 0:
            return None

        fingerprint = self._signature_crop_fingerprint(number_crop)
        best_match = None
        retained_crops = []
        for recent_crop in self.signature_vision_recent_crops:
            age = now - float(recent_crop.get("sent_at", 0.0))
            if age > cooldown_seconds:
                continue
            retained_crops.append(recent_crop)
            if recent_crop.get("image_hash") == image_hash:
                continue

            recent_fingerprint = recent_crop.get("fingerprint")
            if recent_fingerprint is None or recent_fingerprint.shape != fingerprint.shape:
                continue
            mean_delta = float(
                np.mean(cv2.absdiff(fingerprint, recent_fingerprint))
            )
            if mean_delta <= max_mean_delta and (
                best_match is None or mean_delta < best_match["mean_delta"]
            ):
                best_match = {
                    "image_hash": recent_crop.get("image_hash"),
                    "mean_delta": mean_delta,
                }

        self.signature_vision_recent_crops = retained_crops
        return best_match

    def _remember_signature_vision_crop(self, image_hash, number_crop, sent_at):
        history_size = int(
            self.signature_observer_config.get("vision_signature_near_duplicate_history_size", 8)
        )
        if history_size <= 0:
            return

        self.signature_vision_recent_crops.append(
            {
                "image_hash": image_hash,
                "fingerprint": self._signature_crop_fingerprint(number_crop),
                "sent_at": sent_at,
            }
        )
        self.signature_vision_recent_crops = self.signature_vision_recent_crops[-history_size:]

    def _signature_crop_fingerprint(self, image):
        if image is None or image.size == 0:
            return np.zeros((24, 64), dtype=np.uint8)

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        if len(image.shape) == 3:
            blue, green, red = cv2.split(image)
            max_channel = np.maximum(np.maximum(red, green), blue)
            min_channel = np.minimum(np.minimum(red, green), blue)
            white_text_mask = (max_channel > 120) & ((max_channel - min_channel) < 90)
            bright_threshold = max(120, int(np.percentile(gray, 82)))
            mask = (white_text_mask | (gray >= bright_threshold)).astype(np.uint8) * 255
        else:
            bright_threshold = max(120, int(np.percentile(gray, 82)))
            mask = (gray >= bright_threshold).astype(np.uint8) * 255

        mask = cv2.medianBlur(mask, 3)
        kernel = np.ones((2, 2), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        text_pixels = cv2.findNonZero(mask)
        if text_pixels is None:
            resized = cv2.resize(gray, (64, 24), interpolation=cv2.INTER_AREA)
            return cv2.equalizeHist(resized)

        x, y, width, height = cv2.boundingRect(text_pixels)
        pad = 2
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(mask.shape[1], x + width + pad)
        y2 = min(mask.shape[0], y + height + pad)
        text_roi = mask[y1:y2, x1:x2]
        if text_roi.size == 0:
            resized = cv2.resize(gray, (64, 24), interpolation=cv2.INTER_AREA)
            return cv2.equalizeHist(resized)

        canvas_width, canvas_height = 64, 24
        max_width, max_height = canvas_width - 4, canvas_height - 4
        scale = min(max_width / max(1, text_roi.shape[1]), max_height / max(1, text_roi.shape[0]))
        resized_width = max(1, min(max_width, int(round(text_roi.shape[1] * scale))))
        resized_height = max(1, min(max_height, int(round(text_roi.shape[0] * scale))))
        resized = cv2.resize(text_roi, (resized_width, resized_height), interpolation=cv2.INTER_AREA)
        canvas = np.zeros((canvas_height, canvas_width), dtype=np.uint8)
        x_offset = (canvas_width - resized_width) // 2
        y_offset = (canvas_height - resized_height) // 2
        canvas[y_offset:y_offset + resized_height, x_offset:x_offset + resized_width] = resized
        return cv2.GaussianBlur(canvas, (3, 3), 0)

    def _signature_crop_hash(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        resized = cv2.resize(gray, (16, 16), interpolation=cv2.INTER_AREA)
        mean_value = float(np.mean(resized))
        bits = ["1" if value > mean_value else "0" for value in resized.flatten()]
        return f"{image.shape[1]}x{image.shape[0]}_" + f"{int(''.join(bits), 2):064x}"

    def _signature_crop_has_overlay_artifact(self, image):
        if not self.signature_observer_config.get("debug_mode", False):
            return False
        if image is None or image.size == 0 or len(image.shape) != 3:
            return False

        blue, green, red = cv2.split(image)
        red_mask = (red > 180) & (green < 100) & (blue < 100)
        red_ratio = float(np.count_nonzero(red_mask)) / float(image.shape[0] * image.shape[1])
        return red_ratio > 0.003

    def _save_signature_vision_crop(self, image, image_hash):
        if not self.signature_observer_config.get("vision_signature_save_crops", True):
            return None

        training_dir = self._get_signature_vision_training_dir()
        crop_dir = os.path.join(training_dir, "crops")
        os.makedirs(crop_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"signature_{timestamp}_{image_hash[:12]}.jpg"
        path = os.path.join(crop_dir, filename)
        try:
            cv2.imwrite(path, image)
            return os.path.relpath(path, self.mining_data_path)
        except Exception as e:
            self._signature_debug(f"could not save signature vision crop: {e}", throttle_key="vision_crop_save_failed")
            return None

    def _get_signature_vision_training_dir(self):
        configured_path = str(
            self.signature_observer_config.get(
                "vision_signature_training_dir",
                "debug_data/signature_training",
            )
        )
        if os.path.isabs(configured_path):
            return configured_path
        return os.path.join(self.mining_data_path, configured_path)

    def _get_signature_vision_ocr(self):
        if self.signature_vision_ocr is not None:
            return self.signature_vision_ocr

        model = self.signature_observer_config.get("vision_signature_model")
        instructions = (
            "Read only the mining signature number shown in this cropped Star Citizen HUD image. "
            "Return only the digits with no separators and no other text. "
            "If there is no complete visible number, return NONE."
        )
        self.signature_vision_ocr = OCR(
            data_dir=self.mining_data_path,
            config=self.config,
            secret_keeper=self.secret_keeper,
            requester_name="MiningManagerSignatureVision",
            extraction_instructions=instructions,
            open_ai_model=model,
            overlay=self.overlay,
        )
        return self.signature_vision_ocr

    def _is_signature_vision_transient_error(self, status_code=None, error=None):
        if status_code == 429 or (status_code is not None and int(status_code) >= 500):
            return True

        normalized_error = str(error or "").upper()
        transient_markers = (
            "RESOURCE_EXHAUSTED",
            "RATE_LIMIT",
            "RATE LIMIT",
            "QUOTA",
            "UNAVAILABLE",
            "TIMEOUT",
            "DEADLINE",
            "INTERNAL",
        )
        return any(marker in normalized_error for marker in transient_markers)

    def _get_signature_vision_retry_after(self, response):
        headers = getattr(response, "headers", {}) or {}
        retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
        if retry_after is None:
            return None
        try:
            return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            return None

    def _apply_signature_vision_backoff(self, result):
        retry_after = result.get("retry_after_seconds")
        if retry_after is None:
            retry_after = float(self.signature_observer_config.get("vision_signature_error_backoff_seconds", 30.0))
        retry_after = max(0.0, float(retry_after))
        if retry_after <= 0:
            return

        self.signature_vision_backoff_until = max(
            self.signature_vision_backoff_until,
            time.time() + retry_after,
        )
        self._signature_debug(
            f"signature vision transient error; backing off for {retry_after:.1f}s",
            throttle_key="vision_transient_backoff",
            interval_seconds=0.5,
        )
        self._write_signature_vision_event(
            "transient_error",
            error=result.get("error"),
            status_code=result.get("status_code"),
            retry_after_seconds=retry_after,
        )
        self._show_signature_status_dot(
            "red",
            symbol="!",
            hold_ms_override=int(retry_after * 1000),
            use_cached_rect=True,
        )

    def _analyze_signature_crop_with_vision(self, job):
        vision_ocr = self._get_signature_vision_ocr()
        if not vision_ocr:
            return {"success": False, "signature_value": None, "error": "vision helper unavailable"}

        provider = vision_ocr._get_vision_provider()
        if provider == "gemini" and not vision_ocr.gemini_api_key:
            return {"success": False, "signature_value": None, "error": "Gemini API key missing"}
        if provider != "gemini" and not vision_ocr.openai_api_key:
            return {"success": False, "signature_value": None, "error": "OpenAI API key missing"}

        encode_ok, encoded = cv2.imencode(".jpg", job["image"], [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        if not encode_ok:
            return {"success": False, "signature_value": None, "error": "could not encode crop"}

        image_payload = base64.b64encode(encoded.tobytes()).decode("ascii")
        max_tokens = int(self.signature_observer_config.get("vision_signature_max_output_tokens", 512))
        try:
            response = (
                vision_ocr._call_gemini_vision(image_payload, max_output_tokens=max_tokens)
                if provider == "gemini"
                else vision_ocr._call_openai_vision(image_payload, max_output_tokens=max_tokens)
            )
        except Exception as e:
            return {
                "success": False,
                "signature_value": None,
                "error": str(e),
                "provider": provider,
                "model": vision_ocr.openai_model,
                "transient_error": self._is_signature_vision_transient_error(error=e),
            }
        if response.status_code != 200:
            error = vision_ocr._extract_error_for_logging(response)
            status_code = int(response.status_code)
            return {
                "success": False,
                "signature_value": None,
                "error": error,
                "provider": provider,
                "model": vision_ocr.openai_model,
                "status_code": status_code,
                "retry_after_seconds": self._get_signature_vision_retry_after(response),
                "transient_error": self._is_signature_vision_transient_error(status_code=status_code, error=error),
            }

        response_payload = response.json()
        message_content, finish_reason = vision_ocr._extract_message_content(response_payload)
        message_content = vision_ocr._normalize_message_content(message_content)
        signature_value, confidence = self._parse_signature_vision_value(message_content)
        return {
            "success": signature_value is not None,
            "signature_value": signature_value,
            "confidence": confidence,
            "provider": provider,
            "model": vision_ocr.openai_model,
            "finish_reason": finish_reason,
            "parse_error": None,
            "raw_text": message_content,
        }

    def _parse_signature_vision_value(self, message_content):
        normalized = (message_content or "").strip()
        if not normalized or normalized.upper() == "NONE":
            return None, None

        digit_match = re.search(r"\d{4,}", normalized)
        if not digit_match:
            return None, None
        return int(digit_match.group(0)), None

    def _write_signature_vision_training_sample(self, job, result):
        training_dir = self._get_signature_vision_training_dir()
        os.makedirs(training_dir, exist_ok=True)
        filename = os.path.join(training_dir, "signature_vision_training.jsonl")
        signature_value = result.get("signature_value")
        status = self._get_observed_signature_status(signature_value) if signature_value is not None else "no_value"
        overlay_artifact = bool(job.get("overlay_artifact"))
        training_usable = bool(
            signature_value is not None
            and status != "max_reached"
            and not overlay_artifact
        )
        if signature_value is None:
            label_state = "no_label"
        elif training_usable:
            label_state = "auto_label" if status == "known" else "auto_label_unresolved"
        elif overlay_artifact:
            label_state = "rejected_overlay_artifact"
        else:
            label_state = "rejected_auto_label"
        payload = {
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "source": "vision_ai",
            "label_state": label_state,
            "training_usable": training_usable,
            "signature_value": signature_value,
            "known": status == "known",
            "status": status,
            "confidence": result.get("confidence"),
            "provider": result.get("provider"),
            "model": result.get("model"),
            "finish_reason": result.get("finish_reason"),
            "image_hash": job.get("image_hash"),
            "image": job.get("image_path"),
            "reason": job.get("reason"),
            "local_value": job.get("local_value"),
            "overlay_artifact": overlay_artifact,
            "watch_area_rect": job.get("watch_area_rect"),
            "icon_match_rect": job.get("icon_match_rect"),
            "number_crop_rect": job.get("number_crop_rect"),
            "success": bool(result.get("success")),
            "error": result.get("error"),
            "status_code": result.get("status_code"),
            "transient_error": bool(result.get("transient_error")),
            "raw_text": result.get("raw_text"),
        }
        try:
            with open(filename, "a", encoding="UTF-8") as file:
                file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as e:
            self._signature_debug(f"could not write signature vision training sample: {e}", throttle_key="vision_training_write_failed")

    def _handle_signature_vision_result(self, job, result):
        signature_value = result.get("signature_value")
        if result.get("transient_error"):
            self._signature_debug(
                f"vision transient error status={result.get('status_code')} error={result.get('error')}",
                throttle_key="vision_transient_error",
                interval_seconds=0.5,
            )
            return
        if job.get("overlay_artifact") and self.signature_observer_config.get("vision_signature_reject_overlay_artifacts", True):
            self._signature_debug(
                f"discarding vision result from overlay artifact crop hash={job.get('image_hash', '')[:12]}",
                throttle_key="vision_overlay_result_discarded",
                interval_seconds=0.5,
            )
            return
        if signature_value is None:
            self._signature_debug(
                f"vision returned no signature value hash={job.get('image_hash', '')[:12]}",
                throttle_key="vision_no_value",
                interval_seconds=0.5,
            )
            return

        corrected_value = self._correct_signature_ocr_value(signature_value)
        status = self._get_observed_signature_status(corrected_value)
        self._signature_debug(
            f"vision read signature value {signature_value}"
            + (f" corrected={corrected_value}" if corrected_value != signature_value else "")
            + f" status={status}",
            throttle_key="vision_result",
            interval_seconds=0.5,
        )
        if not self._is_signature_analysis_active():
            return

        if status == "known":
            self.signature_last_value_source = "vision"
            self.signature_unknown_reads = 0
            if self.signature_observer_config.get("vision_signature_accept_single_result", True):
                support_threshold = int(self.signature_observer_config.get("stable_single_tick_support", 3))
                self.signature_last_ocr_value_support[corrected_value] = max(1, support_threshold)
            extension_seconds = self._extend_signature_analysis_after_value()
            if extension_seconds:
                self._signature_debug(
                    f"signature recognized by vision; OCR analysis refreshed for {int(extension_seconds)}s",
                    throttle_key="vision_recognition_extension",
                )
            self._handle_observed_signature(corrected_value, job.get("image"))
        else:
            self.signature_last_value_source = "vision"
            self._show_signature_status_dot("red")
            self._handle_unknown_signature_value(corrected_value, job.get("image"), status)

    def _correct_signature_ocr_value(self, signature_value):
        reference_entries = self.load_signature_reference()
        if self.find_signature_matches(signature_value, reference_entries):
            return signature_value

        missing_leading_one_match = self._find_missing_leading_one_signature_match(signature_value, reference_entries)
        if missing_leading_one_match:
            corrected_value = missing_leading_one_match["signature_value"]
            self.signature_last_ocr_value_support[corrected_value] = max(
                self.signature_last_ocr_value_support.get(corrected_value, 0),
                self.signature_last_ocr_value_support.get(signature_value, 0),
            )
            self._signature_debug(f"OCR corrected missing leading 1: {signature_value} -> {corrected_value}")
            return corrected_value

        fuzzy_match = self.find_fuzzy_signature_match(signature_value, reference_entries)
        if not fuzzy_match:
            return signature_value

        corrected_value = fuzzy_match["signature_value"]
        self.signature_last_ocr_value_support[corrected_value] = max(
            self.signature_last_ocr_value_support.get(corrected_value, 0),
            self.signature_last_ocr_value_support.get(signature_value, 0),
        )
        self._signature_debug(
            f"OCR fuzzy corrected {signature_value} -> {corrected_value} "
            f"(distance={fuzzy_match['ocr_fuzzy_distance']}, "
            f"weighted={fuzzy_match['ocr_fuzzy_weighted_distance']:.2f}, "
            f"delta={fuzzy_match['ocr_fuzzy_delta']})"
        )
        return corrected_value

    def _find_missing_leading_one_signature_match(self, signature_value, reference_entries):
        if not self.signature_observer_config.get("ocr_fuzzy_allow_missing_leading_one", True):
            return None
        if not isinstance(signature_value, int):
            return None

        value_text = str(signature_value)
        minimum_digits = int(self.signature_observer_config.get("minimum_signature_digits", 4))
        if len(value_text) < max(1, minimum_digits):
            return None
        if value_text.startswith("1"):
            return None

        candidate_value = int(f"1{value_text}")
        matches = self.find_signature_matches(candidate_value, reference_entries)
        if not matches:
            return None
        return self.get_preferred_signature_matches(matches)[0]

    def _ocr_signature_number(self, number_crop):
        started_at = time.perf_counter()
        variants = self._filter_signature_ocr_variants(self._build_signature_ocr_variants(number_crop))
        psm_modes = self._get_signature_ocr_psm_modes("ocr_psm_modes", [7, 8, 13])
        timeout_seconds = float(self.signature_observer_config.get("ocr_tesseract_timeout_seconds", 2.0))
        self._save_signature_ocr_debug_variants(number_crop, variants)

        ocr_results = self._run_signature_ocr_variants(
            variants,
            psm_modes=psm_modes,
            timeout_seconds=timeout_seconds,
        )

        if not ocr_results:
            self.signature_last_ocr_value_support = {}
            self._log_signature_ocr_timing("empty", started_at, 0)
            return None

        selectable_results = self._filter_short_signature_ocr_results(ocr_results)
        self.signature_last_ocr_value_support = self._count_signature_ocr_values(selectable_results)
        selected_result = self._select_signature_ocr_result(selectable_results)
        self._log_signature_ocr_candidates(ocr_results, selected_result, stage="simple")
        self._log_signature_ocr_timing("simple", started_at, len(ocr_results))
        return selected_result["value"]

    def _run_signature_ocr_variants(self, variants, psm_modes, timeout_seconds):
        ocr_results = []
        for variant_name, variant_image in variants:
            for page_segmentation_mode in psm_modes:
                try:
                    text = pytesseract.image_to_string(
                        variant_image,
                        config=(
                            f"--psm {page_segmentation_mode} "
                            "-c classify_bln_numeric_mode=1 "
                            "-c tessedit_char_whitelist=0123456789,"
                        ),
                        timeout=timeout_seconds if timeout_seconds > 0 else 0,
                    )
                except RuntimeError as e:
                    self._signature_debug(
                        f"OCR timeout/failed for {variant_name}/psm{page_segmentation_mode}: {e}",
                        throttle_key=f"ocr_timeout_{variant_name}_{page_segmentation_mode}",
                    )
                    continue
                digits = re.sub(r"\D", "", text or "")
                if not digits:
                    continue
                try:
                    value = int(digits)
                except ValueError:
                    continue
                ocr_results.append(
                    {
                        "value": value,
                        "digits": digits,
                        "variant": variant_name,
                        "psm": page_segmentation_mode,
                    }
                )
        return ocr_results

    def _filter_short_signature_ocr_results(self, ocr_results):
        minimum_digits = int(self.signature_observer_config.get("minimum_signature_digits", 4))
        plausible_results = [
            result
            for result in ocr_results
            if len(result["digits"]) >= max(1, minimum_digits)
        ]
        return plausible_results or ocr_results

    def _get_signature_ocr_psm_modes(self, config_key, default_modes):
        configured_modes = self.signature_observer_config.get(config_key, default_modes)
        if not isinstance(configured_modes, list):
            return default_modes

        modes = []
        for mode in configured_modes:
            try:
                mode = int(mode)
            except (TypeError, ValueError):
                continue
            if mode > 0:
                modes.append(mode)
        return modes or default_modes

    def _filter_signature_ocr_variants(self, variants):
        configured_names = self.signature_observer_config.get(
            "ocr_variant_names",
            ["gray", "otsu", "adaptive"],
        )
        if not isinstance(configured_names, list):
            return variants

        allowed_names = {str(name) for name in configured_names}
        filtered_variants = [
            (variant_name, variant_image)
            for variant_name, variant_image in variants
            if variant_name in allowed_names
        ]
        return filtered_variants or variants

    def _log_signature_ocr_candidates(self, ocr_results, selected_result, stage):
        if self.signature_observer_config.get("debug_log_ocr_candidates", True):
            candidate_summary = [
                f"{result['value']}:{result['variant']}/psm{result['psm']}"
                for result in ocr_results[:12]
            ]
            self._signature_debug(
                f"OCR {stage} candidates {candidate_summary}; selected {selected_result['value']}",
                throttle_key="ocr_candidates",
                interval_seconds=1.0,
            )

    def _log_signature_ocr_timing(self, stage, started_at, result_count):
        if not self.signature_observer_config.get("debug_log_ocr_timing", True):
            return
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        self._signature_debug(
            f"OCR stage={stage} results={result_count} elapsed={elapsed_ms}ms",
            throttle_key="ocr_timing",
            interval_seconds=0.5,
        )

    def _build_signature_ocr_variants(self, image):
        configured_names = self.signature_observer_config.get(
            "ocr_variant_names",
            ["gray", "light_text", "light_text_closed", "otsu", "adaptive"],
        )
        allowed_names = {str(name) for name in configured_names} if isinstance(configured_names, list) else None

        def should_build_variant(variant_name):
            return allowed_names is None or variant_name in allowed_names

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        enhanced = cv2.convertScaleAbs(gray, alpha=2.2, beta=20)
        scale = max(5, int(180 / max(1, enhanced.shape[0])))
        resized = cv2.resize(enhanced, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        resized_color = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

        variants = []
        gray_variant = self._pad_ocr_image(self._normalize_ocr_polarity(resized))
        if should_build_variant("gray"):
            variants.append(("gray", gray_variant))
        if should_build_variant("gray_inverted"):
            variants.append(("gray_inverted", self._pad_ocr_image(self._normalize_ocr_polarity(cv2.bitwise_not(resized)))))

        light_text = None
        if (
            should_build_variant("light_text")
            or should_build_variant("light_text_closed")
            or should_build_variant("light_text_thick")
            or should_build_variant("light_mask")
            or should_build_variant("light_mask_closed")
        ):
            light_text = self._build_signature_light_text_image(resized_color, resized)
        if should_build_variant("light_text") or should_build_variant("light_mask"):
            variants.append(("light_text", self._prepare_binary_ocr_image(light_text)))
        if should_build_variant("light_text_closed") or should_build_variant("light_mask_closed"):
            closed_text = cv2.morphologyEx(light_text, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
            variants.append(("light_text_closed", self._prepare_binary_ocr_image(closed_text)))
        if should_build_variant("light_text_thick"):
            thick_text = cv2.erode(light_text, np.ones((2, 2), np.uint8), iterations=1)
            thick_text = cv2.morphologyEx(thick_text, cv2.MORPH_CLOSE, np.ones((3, 2), np.uint8))
            variants.append(("light_text_thick", self._prepare_binary_ocr_image(thick_text)))

        if should_build_variant("otsu"):
            _, otsu = cv2.threshold(resized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            variants.append(("otsu", self._prepare_binary_ocr_image(self._normalize_ocr_polarity(otsu))))

        if should_build_variant("otsu_blur"):
            blurred = cv2.GaussianBlur(resized, (3, 3), 0)
            _, otsu_blur = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            variants.append(("otsu_blur", self._prepare_binary_ocr_image(self._normalize_ocr_polarity(otsu_blur))))

        for threshold_value in (70, 90, 110, 130):
            variant_name = f"threshold_{threshold_value}"
            if should_build_variant(variant_name):
                _, fixed = cv2.threshold(resized, threshold_value, 255, cv2.THRESH_BINARY)
                variants.append((variant_name, self._prepare_binary_ocr_image(self._normalize_ocr_polarity(fixed))))

        if should_build_variant("adaptive"):
            adaptive = cv2.adaptiveThreshold(
                resized,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                21,
                7,
            )
            variants.append(("adaptive", self._prepare_binary_ocr_image(self._normalize_ocr_polarity(adaptive))))
        return variants or [("gray", gray_variant)]

    def _normalize_ocr_polarity(self, image):
        return cv2.bitwise_not(image) if float(np.mean(image)) < 127.0 else image

    def _prepare_binary_ocr_image(self, image):
        normalized = self._normalize_ocr_polarity(image)
        cropped = self._crop_ocr_image_to_dark_content(normalized)
        return self._pad_ocr_image(cropped)

    def _crop_ocr_image_to_dark_content(self, image):
        dark_mask = cv2.inRange(image, 0, 210)
        dark_points = cv2.findNonZero(dark_mask)
        if dark_points is None:
            return image

        x, y, width, height = cv2.boundingRect(dark_points)
        if width < 4 or height < 4:
            return image

        pad_x = max(8, int(width * 0.08))
        pad_y = max(6, int(height * 0.25))
        x1 = max(0, x - pad_x)
        y1 = max(0, y - pad_y)
        x2 = min(image.shape[1], x + width + pad_x)
        y2 = min(image.shape[0], y + height + pad_y)
        if x2 <= x1 or y2 <= y1:
            return image

        return image[y1:y2, x1:x2]

    def _build_signature_light_text_image(self, color_image, gray_image):
        hsv = cv2.cvtColor(color_image, cv2.COLOR_BGR2HSV)
        _, _, value = cv2.split(hsv)
        threshold_value = max(130, int(np.percentile(gray_image, 92)))
        threshold_value = min(250, threshold_value)
        text_mask = cv2.bitwise_and(
            cv2.inRange(gray_image, threshold_value, 255),
            cv2.inRange(value, threshold_value, 255),
        )

        coverage = float(cv2.countNonZero(text_mask)) / max(1, text_mask.size)
        if coverage > 0.35:
            threshold_value = max(threshold_value, int(np.percentile(gray_image, 98)))
            text_mask = cv2.bitwise_and(
                cv2.inRange(gray_image, threshold_value, 255),
                cv2.inRange(value, threshold_value, 255),
            )
        elif coverage < 0.002:
            threshold_value = max(90, int(np.percentile(gray_image, 80)))
            text_mask = cv2.bitwise_and(
                cv2.inRange(gray_image, threshold_value, 255),
                cv2.inRange(value, threshold_value, 255),
            )

        text_mask = cv2.medianBlur(text_mask, 3)
        text_mask = cv2.dilate(text_mask, np.ones((2, 1), np.uint8), iterations=1)
        ocr_image = np.full_like(gray_image, 255)
        ocr_image[text_mask > 0] = 0
        return ocr_image

    def _save_signature_ocr_debug_variants(self, original_crop, variants):
        if not self.signature_observer_config.get("debug_mode", False):
            return
        if not self.signature_observer_config.get("save_ocr_debug_variants", True):
            return

        path = os.path.join(self.mining_data_path, "debug_data", "signature_ocr_variants")
        try:
            os.makedirs(path, exist_ok=True)
            if original_crop is not None:
                cv2.imwrite(os.path.join(path, "latest_original.png"), original_crop)
            for variant_name, variant_image in variants:
                cv2.imwrite(os.path.join(path, f"latest_{variant_name}.png"), variant_image)
        except Exception as e:
            self._signature_debug(f"could not save OCR debug variants: {e}", throttle_key="save_ocr_variants_failed")

    def _pad_ocr_image(self, image):
        return cv2.copyMakeBorder(
            image,
            20,
            20,
            24,
            24,
            cv2.BORDER_CONSTANT,
            value=255,
        )

    def _select_signature_ocr_result(self, ocr_results):
        result_counts = self._count_signature_ocr_values(ocr_results)

        variant_priority = {
            "light_text_thick": 0,
            "light_text_closed": 1,
            "light_text": 2,
            "gray": 3,
            "otsu": 4,
            "adaptive": 5,
        }

        def score(result):
            value = result["value"]
            digit_count = len(result["digits"])
            return (
                result_counts[value],
                -variant_priority.get(result["variant"], 20),
                -abs(digit_count - 4),
                digit_count,
            )

        return max(ocr_results, key=score)

    def _count_signature_ocr_values(self, ocr_results):
        result_counts = {}
        for result in ocr_results:
            result_counts[result["value"]] = result_counts.get(result["value"], 0) + 1
        return result_counts

    def _prepare_signature_ocr_crop(self, image, source_image=None, source_offset=(0, 0)):
        icon_match = self._find_signature_icon_match(image)
        if icon_match:
            self._remember_signature_icon_match(icon_match)
            return self._crop_signature_number_after_icon(
                source_image if source_image is not None else image,
                icon_match,
                source_offset=source_offset if source_image is not None else (0, 0),
            )

        if self.signature_observer_config.get("use_signature_icon_template", True):
            if self.signature_icon_template_loaded and self.signature_icon_template is None:
                return self._prepare_signature_ocr_crop_without_icon(image)
            return None, None

        return self._prepare_signature_ocr_crop_without_icon(image)

    def _remember_signature_icon_match(self, icon_match):
        watch_rect = self.signature_last_watch_area_rect
        if not watch_rect:
            return

        watch_x, watch_y, _, _ = watch_rect
        self._set_signature_icon_match_rect(
            watch_x + int(icon_match["x"]),
            watch_y + int(icon_match["y"]),
            int(icon_match["width"]),
            int(icon_match["height"]),
        )

    def _set_signature_icon_match_rect(self, x, y, width, height):
        self.signature_last_icon_match_rect = (
            int(x),
            int(y),
            int(width),
            int(height),
        )
        self.signature_icon_tracking_misses = 0

    def _prepare_signature_ocr_crop_without_icon(self, image):
        _, image_width = image.shape[:2]
        left_ratio = float(self.signature_observer_config.get("ocr_number_region_left_ratio", 0.35))
        left_ratio = max(0.0, min(0.80, left_ratio))
        left = min(image_width - 1, int(image_width * left_ratio))
        cropped = image[:, left:image_width]
        if cropped.size == 0:
            image_height, image_width = image.shape[:2]
            return image, (0, 0, image_width, image_height)

        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        _, bright_mask = cv2.threshold(gray, 80, 255, cv2.THRESH_BINARY)
        bright_mask = cv2.morphologyEx(bright_mask, cv2.MORPH_CLOSE, np.ones((3, 2), np.uint8))
        bright_points = cv2.findNonZero(bright_mask)
        if bright_points is None:
            return cropped, (left, 0, cropped.shape[1], cropped.shape[0])

        x, y, w, h = cv2.boundingRect(bright_points)
        if w < 4 or h < 4:
            return cropped, (left, 0, cropped.shape[1], cropped.shape[0])

        crop_x1 = max(0, x - 4)
        crop_y1 = max(0, y - 4)
        crop_x2 = min(cropped.shape[1], x + w + 6)
        crop_y2 = min(cropped.shape[0], y + h + 5)
        if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
            return cropped, (left, 0, cropped.shape[1], cropped.shape[0])

        return (
            cropped[crop_y1:crop_y2, crop_x1:crop_x2],
            (left + crop_x1, crop_y1, crop_x2 - crop_x1, crop_y2 - crop_y1),
        )

    def _find_signature_icon_match(self, image):
        if not self.signature_observer_config.get("use_signature_icon_template", True):
            return None

        template = self._load_signature_icon_template()
        if template is None or image is None:
            return None

        try:
            image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        except Exception as e:
            self._signature_debug(f"could not prepare signature icon template match: {e}", throttle_key="signature_icon_prepare_failed")
            return None

        threshold = float(self.signature_observer_config.get("signature_icon_match_threshold", 0.70))
        scales = self.signature_observer_config.get("signature_icon_scales", [0.85, 1.0, 1.15])
        if not isinstance(scales, list):
            scales = [1.0]

        best_match = None
        for scale in scales:
            try:
                scale = float(scale)
            except (TypeError, ValueError):
                continue
            if scale <= 0:
                continue

            scaled_width = max(4, int(template_gray.shape[1] * scale))
            scaled_height = max(4, int(template_gray.shape[0] * scale))
            if scaled_width > image_gray.shape[1] or scaled_height > image_gray.shape[0]:
                continue

            resized_template = cv2.resize(
                template_gray,
                (scaled_width, scaled_height),
                interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC,
            )
            match_result = cv2.matchTemplate(image_gray, resized_template, cv2.TM_CCOEFF_NORMED)
            _, max_value, _, max_location = cv2.minMaxLoc(match_result)
            if best_match is None or max_value > best_match["score"]:
                best_match = {
                    "score": float(max_value),
                    "x": int(max_location[0]),
                    "y": int(max_location[1]),
                    "width": scaled_width,
                    "height": scaled_height,
                    "scale": scale,
                }

        if not best_match or best_match["score"] < threshold:
            if best_match:
                self._signature_debug(
                    f"signature icon match below threshold score={best_match['score']:.2f} threshold={threshold:.2f}",
                    throttle_key="signature_icon_low_score",
                    interval_seconds=0.5,
                )
            return None

        self._signature_debug(
            f"signature icon matched score={best_match['score']:.2f} pos=({best_match['x']},{best_match['y']}) scale={best_match['scale']:.2f}",
            throttle_key="signature_icon_match",
            interval_seconds=0.5,
        )
        return best_match

    def _load_signature_icon_template(self):
        if self.signature_icon_template_loaded:
            return self.signature_icon_template

        self.signature_icon_template_loaded = True
        configured_path = str(
            self.signature_observer_config.get(
                "signature_icon_template_path",
                "templates/scans/scan_signature_icon.png",
            )
        )
        template_path = configured_path
        if not os.path.isabs(template_path):
            template_path = os.path.join(self.mining_data_path, template_path)

        self.signature_icon_template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if self.signature_icon_template is None:
            self._signature_debug(f"signature icon template not found: {template_path}", throttle_key="signature_icon_template_missing")
        return self.signature_icon_template

    def _crop_signature_number_after_icon(self, image, icon_match, source_offset=(0, 0)):
        image_height, image_width = image.shape[:2]
        left_padding = int(self.signature_observer_config.get("signature_number_crop_left_padding", 2))
        fixed_width = int(self.signature_observer_config.get("signature_number_crop_width", 120))
        min_width = int(self.signature_observer_config.get("signature_number_crop_min_width", 80))
        right_padding = int(self.signature_observer_config.get("signature_number_crop_right_padding", 36))
        vertical_padding = int(self.signature_observer_config.get("signature_number_crop_vertical_padding", 8))
        source_x, source_y = source_offset

        x1 = min(image_width - 1, max(0, source_x + icon_match["x"] + icon_match["width"] + left_padding))
        if fixed_width > 0:
            x2 = min(image_width, max(x1 + 1, x1 + fixed_width))
        else:
            x2 = min(image_width, max(x1 + 1, image_width - max(0, right_padding)))
        y1 = max(0, source_y + icon_match["y"] - max(0, vertical_padding))
        y2 = min(image_height, source_y + icon_match["y"] + icon_match["height"] + max(0, vertical_padding))
        if x2 <= x1 or y2 <= y1:
            if source_offset != (0, 0):
                return None, None
            return self._prepare_signature_ocr_crop_without_icon(image)

        if fixed_width > 0 and x2 - x1 < max(1, min_width):
            self._signature_debug(
                f"signature number crop too narrow width={x2 - x1}px min={min_width}px "
                f"icon_x={icon_match['x']} image_width={image_width}",
                throttle_key="signature_number_crop_too_narrow",
                interval_seconds=0.5,
            )
            return None, (x1 - source_x, y1 - source_y, x2 - x1, y2 - y1)

        number_crop = image[y1:y2, x1:x2]
        if number_crop.size == 0:
            if source_offset != (0, 0):
                return None, None
            return self._prepare_signature_ocr_crop_without_icon(image)

        return number_crop, (x1 - source_x, y1 - source_y, x2 - x1, y2 - y1)

    def _get_observed_signature_status(self, signature_value):
        reference_entries = self.load_signature_reference()
        if self.find_signature_matches(signature_value, reference_entries):
            return "known"
        if self.is_above_max_known_signature(signature_value, reference_entries):
            return "max_reached"
        return "unknown"

    def _handle_unknown_signature_value(self, signature_value, number_crop, signature_status):
        self.signature_unknown_reads += 1

        if self.signature_observer_config.get("save_number_crops", True):
            self._save_signature_number_crop(signature_value, number_crop)

        self._log_observed_signature_matches(signature_value)
        clear_reads = int(self.signature_observer_config.get("unknown_clear_reads", 3))
        if self.signature_unknown_reads >= max(1, clear_reads):
            self._signature_debug(
                f"clearing signature overlay after {self.signature_unknown_reads} consecutive {signature_status} reads"
            )
            self.signature_candidate_value = None
            self.signature_candidate_reads = 0
            self.signature_candidate_misses = 0
            self._clear_signature_overlay()

    def _handle_signature_miss(self):
        if self.signature_candidate_value is None:
            return

        self.signature_candidate_misses += 1
        miss_tolerance = int(self.signature_observer_config.get("stable_miss_tolerance", 2))
        if self.signature_candidate_misses <= max(0, miss_tolerance):
            return

        self.signature_candidate_value = None
        self.signature_candidate_reads = 0
        self.signature_candidate_misses = 0

    def _handle_observed_signature(self, signature_value, number_crop):
        if not self._is_signature_analysis_active():
            self._signature_debug(
                "skipping signature overlay because analysis is inactive",
                throttle_key="inactive_overlay",
            )
            return

        stable_reads = int(self.signature_observer_config.get("stable_reads", 2))
        if signature_value == self.signature_candidate_value:
            self.signature_candidate_reads += 1
            self.signature_candidate_misses = 0
        else:
            self.signature_candidate_value = signature_value
            self.signature_candidate_reads = 1
            self.signature_candidate_misses = 0

        single_tick_support_threshold = int(self.signature_observer_config.get("stable_single_tick_support", 3))
        single_tick_support = int(self.signature_last_ocr_value_support.get(signature_value, 0))
        if single_tick_support_threshold > 0 and single_tick_support >= single_tick_support_threshold:
            if self.signature_candidate_reads < max(1, stable_reads):
                self._signature_debug(
                    f"candidate signature {signature_value} accepted from single OCR tick "
                    f"support={single_tick_support}/{single_tick_support_threshold}"
                )
            self.signature_candidate_reads = max(self.signature_candidate_reads, max(1, stable_reads))

        if self.signature_candidate_reads < max(1, stable_reads):
            self._signature_debug(
                f"candidate signature {signature_value} pending {self.signature_candidate_reads}/{stable_reads}",
                throttle_key="signature_candidate_pending",
                interval_seconds=0.5,
            )
            self._show_signature_status_dot("yellow")
            return

        self._show_signature_status_dot(
            "green",
            symbol="C" if self.signature_last_value_source == "cache" else None,
        )
        now = time.time()
        display_cooldown = float(self.signature_observer_config.get("display_cooldown_seconds", 3.0))
        if signature_value == self.last_signature_value and now - self.last_signature_display_time < display_cooldown:
            self._signature_debug(
                f"suppressing duplicate signature display for {signature_value} during cooldown",
                throttle_key="signature_display_cooldown",
                interval_seconds=0.5,
            )
            return

        overlay_text = self._build_signature_overlay_text(signature_value)
        if not overlay_text:
            self._signature_debug(
                f"stable signature {signature_value} has no display text",
                throttle_key="signature_no_display_text",
                interval_seconds=0.5,
            )
            return

        self.last_signature_value = signature_value
        self.last_signature_display_time = now

        if self.signature_observer_config.get("save_number_crops", True):
            self._save_signature_number_crop(signature_value, number_crop)

        if not self._is_signature_analysis_active():
            self._signature_debug(
                "skipping signature overlay because analysis expired before display",
                throttle_key="expired_before_display",
            )
            return

        self._log_observed_signature_matches(signature_value)
        self._signature_debug(f"displaying stable signature {signature_value}: {overlay_text}")
        self._display_signature_overlay_text(overlay_text)

    def _clear_signature_overlay(self):
        if not self.signature_overlay_visible and self.last_signature_value is None:
            return
        self.overlay.clear_overlay_text()
        self.signature_overlay_visible = False
        self.last_signature_value = None
        self.last_signature_display_time = 0.0

    def _refresh_signature_overlay_text_position(self):
        if not self.signature_overlay_visible or self.last_signature_value is None:
            return

        overlay_text = self._build_signature_overlay_text(self.last_signature_value)
        if not overlay_text:
            return

        self._display_signature_overlay_text(overlay_text)

    def _display_signature_overlay_text(self, text):
        if not text:
            return
        display_duration = int(self.signature_observer_config.get("display_duration_ms", 5000))
        try:
            active_window = pygetwindow.getActiveWindow()
            if not active_window:
                raise ValueError("No active window available.")

            relative_rect = self.signature_last_watch_area_rect
            if not relative_rect:
                watch_area = self.signature_observer_config.get("watch_area", {})
                relative_rect = self._resolve_signature_watch_area_rect(active_window, watch_area)
            if not relative_rect:
                raise ValueError("No watch area available.")

            dot_size = int(self.signature_observer_config.get("status_dot_size", 10))
            dot_x, dot_y = self._get_signature_status_dot_position(active_window, relative_rect, dot_size)
            x_offset = int(self.signature_observer_config.get("overlay_text_offset_x_pixels", 130))
            y_offset = int(self.signature_observer_config.get("overlay_text_offset_y_pixels", 8))
            x_center = dot_x + x_offset
            y_bottom = dot_y - y_offset
            y_bottom = max(active_window.top, y_bottom)
            self.overlay.display_overlay_text_at(
                text,
                x_center=x_center,
                y_bottom=y_bottom,
                display_duration=display_duration,
            )
            self.signature_overlay_visible = True
        except Exception as e:
            self._signature_debug(f"falling back to centered overlay: {e}")
            self.overlay.display_overlay_text(
                text,
                vertical_position_ratio=4,
                display_duration=display_duration,
            )
            self.signature_overlay_visible = True

    def _save_signature_number_crop(self, signature_value, number_crop):
        if number_crop is None:
            return
        path = os.path.join(self.mining_data_path, "screenshots", "signatures")
        os.makedirs(path, exist_ok=True)
        if self.signature_observer_config.get("overwrite_number_crop", True):
            filename = os.path.join(path, "latest_signature_number.png")
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = os.path.join(path, f"signature_{signature_value}_{timestamp}.png")
        cv2.imwrite(filename, number_crop)

    def _build_signature_overlay_text(self, signature_value):
        reference_entries = self.load_signature_reference()
        if self.is_above_max_known_signature(signature_value, reference_entries):
            return None

        exact_matches = self.find_signature_matches(signature_value, reference_entries)
        if exact_matches:
            preferred_match = self.get_preferred_signature_matches(exact_matches)[0]
            if preferred_match.get("specific_cluster_size"):
                return f"{signature_value} -> {preferred_match['resource']} cluster {preferred_match['cluster_size']}"
            return f"{signature_value} -> {preferred_match['count']} x {preferred_match['resource']}"
        return None

    def _log_observed_signature_matches(self, signature_value):
        reference_entries = self.load_signature_reference()
        if self.is_above_max_known_signature(signature_value, reference_entries):
            max_known_signature = self.get_max_known_signature_value(reference_entries)
            self._signature_debug(
                f"observed signature {signature_value}; max reached above known maximum {max_known_signature}"
            )
            self._write_signature_cluster_observation(signature_value, [], status="max_reached")
            return

        exact_matches = self.find_signature_matches(signature_value, reference_entries)
        if not exact_matches:
            self._signature_debug(f"observed signature {signature_value}; no cluster match found")
            self._write_signature_cluster_observation(signature_value, [], status="unknown")
            return

        preferred_matches = self.get_preferred_signature_matches(exact_matches)
        match_descriptions = [
            self.format_signature_match_description(match)
            for match in preferred_matches
        ]
        self._signature_debug(
            f"observed signature {signature_value}; cluster match: {', '.join(match_descriptions)}"
        )
        self._write_signature_cluster_observation(signature_value, preferred_matches, status="matched")

    def _write_signature_cluster_observation(self, signature_value, matches, status):
        if not self.signature_observer_config.get("log_observed_clusters", True):
            return

        path = os.path.join(self.mining_data_path, "debug_data")
        os.makedirs(path, exist_ok=True)
        filename = os.path.join(path, "signature_cluster_observations.jsonl")
        payload = {
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "signature_value": signature_value,
            "cluster_sizes": sorted({
                match.get("cluster_size", match.get("count"))
                for match in matches
                if match.get("cluster_size", match.get("count")) is not None
            }),
            "matches": [
                {
                    "resource": match.get("resource"),
                    "category": match.get("category"),
                    "base_signature": match.get("base_signature"),
                    "signature_value": match.get("signature_value"),
                    "cluster_size": match.get("cluster_size", match.get("count")),
                    "specific_cluster_size": bool(match.get("specific_cluster_size")),
                }
                for match in matches
            ],
        }
        try:
            with open(filename, "a", encoding="UTF-8") as file:
                file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as e:
            self._signature_debug(f"could not write signature cluster observation: {e}")

