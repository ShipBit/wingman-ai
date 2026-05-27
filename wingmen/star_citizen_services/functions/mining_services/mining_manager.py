import json
import os
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
    "activation_duration_seconds": 120,
    "stable_reads": 1,
    "display_duration_ms": 2500,
    "display_cooldown_seconds": 3.0,
    "overlay_offset_pixels": 8,
    "save_number_crops": False,
    "overwrite_number_crop": True,
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
        "Watch the mining signature HUD with local OCR while active",
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
        self.last_signature_value = None
        self.last_signature_display_time = 0.0
        self.signature_candidate_value = None
        self.signature_candidate_reads = 0
        self.signature_ocr_unavailable_reported = False
        self.signature_debug_last_by_key = {}

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
            match_descriptions = [
                f"{match['resource']} x{match['count']} ({match['category']})"
                for match in exact_matches
            ]
            return {
                "success": True,
                "signature_value": signature_value,
                "matches": exact_matches,
                "message": f"Signature {signature_value} matches: {', '.join(match_descriptions)}.",
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
                item["signature_value"],
            ),
        )[:limit]

    def sort_signature_matches(self, matches):
        return sorted(
            matches,
            key=lambda item: (
                self.get_signature_match_priority(item),
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

    def iter_signature_reference_values(self, reference_entries):
        for entry in reference_entries:
            resource = entry.get("resource")
            base_signature = entry.get("base_signature")
            max_count = entry.get("max_count")
            if not resource or not isinstance(base_signature, int) or not isinstance(max_count, int):
                continue
            for count in range(1, max_count + 1):
                yield {
                    "resource": resource,
                    "category": entry.get("category", "Mining Resource"),
                    "count": count,
                    "base_signature": base_signature,
                    "signature_value": base_signature * count,
                }

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
        return merged

    def start_signature_observer(self):
        with self.signature_observer_lock:
            if self.signature_observer_thread and self.signature_observer_thread.is_alive():
                return

            self.signature_observer_stop_event = threading.Event()
            self.signature_observer_active_until = 0.0
            self.signature_tab_listener = keyboard.Listener(on_press=self._on_signature_observer_key_press)
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
        if tab_listener:
            tab_listener.stop()
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        printr.print("Mining signature observer stopped.", tags="info")

    def _on_signature_observer_key_press(self, key):
        if key != keyboard.Key.tab or not self._is_star_citizen_window_active():
            if key == keyboard.Key.tab:
                self._signature_debug("Tab ignored because Star Citizen is not the active window")
            return

        duration_seconds = float(self.signature_observer_config.get("activation_duration_seconds", 120))
        with self.signature_observer_lock:
            self.signature_observer_active_until = time.time() + max(1.0, duration_seconds)
            self.signature_candidate_value = None
            self.signature_candidate_reads = 0
        printr.print(f"Mining signature OCR active for {int(duration_seconds)} seconds.", tags="info")
        self._signature_debug(
            f"Tab detected; OCR analysis active until {datetime.fromtimestamp(self.signature_observer_active_until).strftime('%H:%M:%S')}"
        )

    def _signature_observer_loop(self, stop_event):
        interval_seconds = float(self.signature_observer_config.get("interval_seconds", 0.75))
        while not stop_event.is_set():
            try:
                if self._should_analyze_signature_hud():
                    self._signature_debug("analysis tick", throttle_key="analysis_tick")
                    watch_image = self._capture_signature_watch_area()
                    signature_value, number_crop = self._read_signature_value(watch_image)
                    if signature_value is not None:
                        self._signature_debug(f"OCR read signature value {signature_value}")
                        self._handle_observed_signature(signature_value, number_crop)
                    else:
                        self._signature_debug("no signature value detected in watch area", throttle_key="no_value")
                        self.signature_candidate_value = None
                        self.signature_candidate_reads = 0
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

            stop_event.wait(timeout=max(0.1, interval_seconds))

    def _should_analyze_signature_hud(self):
        if not self._is_star_citizen_window_active():
            with self.signature_observer_lock:
                was_active = time.time() < self.signature_observer_active_until
                self.signature_observer_active_until = 0.0
                self.signature_candidate_value = None
                self.signature_candidate_reads = 0
            if was_active:
                self._signature_debug("analysis stopped: Star Citizen lost focus")
            return False
        with self.signature_observer_lock:
            active = time.time() < self.signature_observer_active_until
        if not active:
            self._signature_debug("analysis inactive: waiting for Tab ping", throttle_key="waiting_for_tab")
        return active

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
            return None

        rel_x, rel_y, width, height = relative_rect
        x = active_window.left + rel_x
        y = active_window.top + rel_y
        if width <= 0 or height <= 0:
            self._signature_debug(f"invalid watch area: {relative_rect}", throttle_key="invalid_area")
            return None

        self._signature_debug(
            f"capturing watch area relative=({rel_x}, {rel_y}, {width}, {height}) screen=({x}, {y}, {width}, {height})",
            throttle_key="capture_area",
        )
        screenshot_pil = pyautogui.screenshot(region=(x, y, width, height))
        return cv2.cvtColor(np.array(screenshot_pil), cv2.COLOR_RGB2BGR)

    def _resolve_signature_watch_area_rect(self, active_window, watch_area):
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

    def _read_signature_value(self, watch_image):
        if watch_image is None:
            return None, None

        number_crop = self._find_signature_number_crop(watch_image)
        if number_crop is None:
            self._signature_debug("number crop not found", throttle_key="no_crop")
            return None, None

        signature_value = self._ocr_signature_number(number_crop)
        if signature_value is None:
            self._signature_debug("OCR returned no digits", throttle_key="ocr_no_digits")
        return signature_value, number_crop

    def _find_signature_number_crop(self, image):
        icon_rect = self._find_signature_icon_rect_by_contrast(image)
        if icon_rect:
            self._signature_debug(f"contrast icon candidate found at {icon_rect}", throttle_key="icon_candidate")
            number_crop = self._crop_signature_number_area(image, icon_rect)
            if number_crop is not None:
                return number_crop

        self._signature_debug("falling back to likely-number crop search", throttle_key="number_fallback")
        return self._crop_likely_signature_number_area(image)

    def _find_signature_icon_rect_by_contrast(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        _, bright_mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        bright_mask = cv2.morphologyEx(bright_mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
        contours, _ = cv2.findContours(bright_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        image_height, image_width = image.shape[:2]
        candidates = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = cv2.contourArea(contour)
            if area < 15 or w < 4 or h < 8:
                continue
            if x > image_width * 0.65:
                continue
            candidates.append((area * h, x, y, w, h))

        if not candidates:
            return None

        _, x, y, w, h = max(candidates, key=lambda item: item[0])
        if h < image_height * 0.12:
            return None
        return (x, y, w, h)

    def _crop_likely_signature_number_area(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, bright_mask = cv2.threshold(gray, 95, 255, cv2.THRESH_BINARY)
        bright_mask = cv2.morphologyEx(bright_mask, cv2.MORPH_CLOSE, np.ones((3, 2), np.uint8))
        contours, _ = cv2.findContours(bright_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        image_height, image_width = image.shape[:2]
        candidates = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w < image_width * 0.12 or h < image_height * 0.12:
                continue
            if x < image_width * 0.15:
                continue
            if not self._has_left_signature_icon_blob(bright_mask, x, y, h):
                continue
            candidates.append((w * h, x, y, w, h))

        if not candidates:
            return None

        _, x, y, w, h = max(candidates, key=lambda item: item[0])
        crop_x1 = max(0, x - 4)
        crop_y1 = max(0, y - 4)
        crop_x2 = min(image_width, x + w + 8)
        crop_y2 = min(image_height, y + h + 6)
        return image[crop_y1:crop_y2, crop_x1:crop_x2]

    def _has_left_signature_icon_blob(self, mask, number_x, number_y, number_height):
        image_height, _ = mask.shape[:2]
        left_x1 = max(0, number_x - int(number_height * 3.0))
        left_x2 = max(0, number_x - 2)
        left_y1 = max(0, number_y - int(number_height * 0.6))
        left_y2 = min(image_height, number_y + int(number_height * 1.6))
        if left_x2 <= left_x1 or left_y2 <= left_y1:
            return False

        icon_area = mask[left_y1:left_y2, left_x1:left_x2]
        contours, _ = cv2.findContours(icon_area, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        return any(cv2.contourArea(contour) >= max(8, number_height * 0.5) for contour in contours)

    def _crop_signature_number_area(self, image, icon_rect):
        x, y, w, h = icon_rect
        image_height, image_width = image.shape[:2]
        start_x = min(image_width - 1, x + w + 4)
        right_side = image[:, start_x:image_width]
        if right_side.size == 0:
            return None

        gray = cv2.cvtColor(right_side, cv2.COLOR_BGR2GRAY)
        _, bright_mask = cv2.threshold(gray, 95, 255, cv2.THRESH_BINARY)
        bright_points = cv2.findNonZero(bright_mask)
        if bright_points is None:
            return None

        rx, ry, rw, rh = cv2.boundingRect(bright_points)
        crop_x1 = max(0, start_x + rx - 4)
        crop_y1 = max(0, ry - 4)
        crop_x2 = min(image_width, start_x + rx + rw + 8)
        crop_y2 = min(image_height, ry + rh + 6)
        if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
            return None
        return image[crop_y1:crop_y2, crop_x1:crop_x2]

    def _ocr_signature_number(self, number_crop):
        gray = cv2.cvtColor(number_crop, cv2.COLOR_BGR2GRAY)
        scale = max(3, int(90 / max(1, gray.shape[0])))
        resized = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        resized = cv2.GaussianBlur(resized, (3, 3), 0)
        _, binary = cv2.threshold(resized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        binary = cv2.bitwise_not(binary)

        text = pytesseract.image_to_string(
            binary,
            config="--psm 7 -c tessedit_char_whitelist=0123456789,",
        )
        digits = re.sub(r"\D", "", text or "")
        if not digits:
            return None
        try:
            return int(digits)
        except ValueError:
            return None

    def _handle_observed_signature(self, signature_value, number_crop):
        stable_reads = int(self.signature_observer_config.get("stable_reads", 2))
        if signature_value == self.signature_candidate_value:
            self.signature_candidate_reads += 1
        else:
            self.signature_candidate_value = signature_value
            self.signature_candidate_reads = 1

        if self.signature_candidate_reads < max(1, stable_reads):
            return

        now = time.time()
        display_cooldown = float(self.signature_observer_config.get("display_cooldown_seconds", 3.0))
        if signature_value == self.last_signature_value and now - self.last_signature_display_time < display_cooldown:
            return

        self.last_signature_value = signature_value
        self.last_signature_display_time = now

        if self.signature_observer_config.get("save_number_crops", True):
            self._save_signature_number_crop(signature_value, number_crop)

        self._display_signature_overlay_text(self._build_signature_overlay_text(signature_value))

    def _display_signature_overlay_text(self, text):
        display_duration = int(self.signature_observer_config.get("display_duration_ms", 2500))
        try:
            active_window = pygetwindow.getActiveWindow()
            if not active_window:
                raise ValueError("No active window available.")

            watch_area = self.signature_observer_config.get("watch_area", {})
            relative_rect = self._resolve_signature_watch_area_rect(active_window, watch_area)
            if not relative_rect:
                raise ValueError("No watch area available.")

            rel_x, rel_y, width, _ = relative_rect
            offset = int(self.signature_observer_config.get("overlay_offset_pixels", 8))
            x_center = active_window.left + rel_x + width // 2
            y_bottom = max(active_window.top, active_window.top + rel_y - offset)
            self.overlay.display_overlay_text_at(
                text,
                x_center=x_center,
                y_bottom=y_bottom,
                display_duration=display_duration,
            )
        except Exception as e:
            self._signature_debug(f"falling back to centered overlay: {e}")
            self.overlay.display_overlay_text(
                text,
                vertical_position_ratio=4,
                display_duration=display_duration,
            )

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
        exact_matches = self.find_signature_matches(signature_value, reference_entries)
        if exact_matches:
            preferred_match = exact_matches[0]
            return f"{preferred_match['count']} x {preferred_match['resource']}"
        return "unknown"

