import json
import os
import re
import time
from typing import Optional, Tuple

import pyperclip

from services.printr import Printr

from wingmen.star_citizen_services.ai_context_enum import AIContext
from wingmen.star_citizen_services.function_manager import FunctionManager
from wingmen.star_citizen_services.helper import screenshots, find_best_match
from wingmen.star_citizen_services.keybindings import SCKeybindings
from wingmen.star_citizen_services.overlay import StarCitizenOverlay
from wingmen.star_citizen_services.functions.uex_v2.uex_api_module import UEXApi2
from wingmen.star_citizen_services.functions.uex_v2 import uex_api_module

try:
    import pydirectinput as key_module
except Exception:
    import pyautogui as key_module

try:
    import pyautogui as scroll_module
except Exception:
    scroll_module = key_module


DEBUG = True
printr = Printr()


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class NavigationManager(FunctionManager):
    MANAGER_CONTEXT = AIContext.CORA
    MANAGER_DESCRIPTION = (
        "Opens the starmap and automates destination routing with cached click coordinates."
    )
    MANAGER_CAPABILITIES = [
        "Open starmap, search for destination, select it, and calculate route.",
    ]

    def __init__(self, config, secret_keeper):
        super().__init__(config, secret_keeper)
        self.config = config
        self.overlay = StarCitizenOverlay()
        self.sc_keybinding_service = SCKeybindings(config, secret_keeper)

        self.navigation_data_path = os.path.join(
            self.config.get("data-root-directory", "star_citizen_data"),
            "navigation-data",
        )

        feature_entry = self.config.get("features", {}).get(self.__class__.__name__, {})
        self.feature_config = feature_entry if isinstance(feature_entry, dict) else {}

        self.zoom_out_scroll_clicks = int(
            self.feature_config.get("zoom_out_scroll_clicks", 32)
        )
        self.zoom_out_scroll_step = int(
            self.feature_config.get("zoom_out_scroll_step", 120)
        )
        self.zoom_out_scroll_direction = int(
            self.feature_config.get("zoom_out_scroll_direction", -1)
        )
        self.zoom_out_scroll_pause_seconds = float(
            self.feature_config.get("zoom_out_scroll_pause_seconds", 0.01)
        )
        self.zoom_out_center_mouse_before_scroll = bool(
            self.feature_config.get("zoom_out_center_mouse_before_scroll", True)
        )
        self.zoom_out_center_click_before_scroll = bool(
            self.feature_config.get("zoom_out_center_click_before_scroll", False)
        )
        self.zoom_out_recenter_each_scroll = bool(
            self.feature_config.get("zoom_out_recenter_each_scroll", False)
        )
        self.location_match_score_cutoff = int(
            self.feature_config.get("location_match_score_cutoff", 70)
        )
        self.post_click_wait_seconds = float(
            self.feature_config.get("post_click_wait_seconds", 0.35)
        )
        self.post_type_wait_seconds = float(
            self.feature_config.get("post_type_wait_seconds", 0.30)
        )
        self.map_open_wait_seconds = float(
            self.feature_config.get("map_open_wait_seconds", 0.55)
        )
        self.map_input_activation_wait_seconds = float(
            self.feature_config.get("map_input_activation_wait_seconds", 0.45)
        )
        self.post_zoom_wait_seconds = float(
            self.feature_config.get("post_zoom_wait_seconds", 0.20)
        )
        self.post_center_before_scroll_wait_seconds = float(
            self.feature_config.get("post_center_before_scroll_wait_seconds", 0.08)
        )
        self.selection_wait_seconds = float(
            self.feature_config.get("selection_wait_seconds", 0.35)
        )
        self.mouse_settle_wait_seconds = float(
            self.feature_config.get("mouse_settle_wait_seconds", 0.1)
        )
        self.mouse_click_hold_seconds = float(
            self.feature_config.get("mouse_click_hold_seconds", 0.03)
        )
        self.capture_click_timeout_seconds = float(
            self.feature_config.get("capture_click_timeout_seconds", 20.0)
        )
        self.capture_click_poll_interval_seconds = float(
            self.feature_config.get("capture_click_poll_interval_seconds", 0.02)
        )
        self.lock_mouse_until_route_clicked = bool(
            self.feature_config.get("lock_mouse_until_route_clicked", True)
        )
        self.coordinate_cache_path = os.path.join(
            self.navigation_data_path, "coordinate_cache.json"
        )
        self.coordinate_cache = self._load_click_coordinate_cache()
        self.uex_service = None
        self._navigation_location_names = []
        self._navigation_location_names_by_category = {}

        try:
            self.uex2_api_key = secret_keeper.retrieve(
                requester="NavigationManager",
                key="uex2_api_key",
                friendly_key_name="UEX2 API key",
                prompt_if_missing=False,
            )
            self.uex2_secret_key = secret_keeper.retrieve(
                requester="NavigationManager",
                key="uex2_secret_key",
                friendly_key_name="UEX2 secret user key",
                prompt_if_missing=False,
            )
            self.uex_service = UEXApi2.init(
                uex_api_key=self.uex2_api_key,
                user_secret_key=self.uex2_secret_key,
            )
            self._navigation_location_names = self._build_navigation_location_names()
        except Exception as e:
            printr.print_warn(f"NavigationManager: could not initialize UEX location matching: {e}")

    def get_context_mapping(self) -> AIContext:
        return AIContext.CORA

    def register_functions(self, function_register):
        function_register[self.navigate_to_location.__name__] = self.navigate_to_location

    def get_function_prompt(self) -> str:
        return (
            f"Call '{self.navigate_to_location.__name__}' when the user asks to navigate/route to a destination in starmap. "
            "Use the destination name provided by the user as-is and do not invent missing names. "
            "If the user specifies a category, pass it as optional 'location_category' "
            "(for example: outpost, station, city, moon, orbit, planet). "
            "If the function returns a confirmation_request because the score is too low, do not start navigation. "
            "Ask the user if they meant the suggested location and only call the function again after confirmation."
        )

    def get_function_tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": self.navigate_to_location.__name__,
                    "description": (
                        "Opens Star Citizen starmap, searches for the given destination, selects the target, and calculates route."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location_name": {
                                "type": "string",
                                "description": "Exact destination name the user asked for.",
                            },
                            "location_category": {
                                "type": "string",
                                "description": (
                                    "Optional category hint to restrict matching. "
                                    "Examples: outpost, station, city, moon, orbit, planet."
                                ),
                            }
                        },
                        "required": ["location_name"],
                    },
                },
            }
        ]

    def navigate_to_location(self, function_args):
        function_args = function_args or {}
        print_debug(
            "NavigationManager.navigate_to_location function_args:\n"
            f"{json.dumps(function_args, indent=2, ensure_ascii=False)}"
        )

        requested_location_name = (function_args.get("location_name") or "").strip()
        requested_location_category_raw = (function_args.get("location_category") or "").strip()
        requested_location_category = self._normalize_navigation_location_category(
            requested_location_category_raw
        )

        if not requested_location_name:
            return {
                "success": False,
                "instructions": "Ask the user for the destination name.",
                "message": "Missing location_name.",
                "do_not_cache": True,
            }

        if requested_location_category_raw and not requested_location_category:
            valid_categories = ", ".join(self._get_navigation_category_input_examples())
            print_debug(
                "NavigationManager.navigate_to_location invalid location_category: "
                f"'{requested_location_category_raw}'"
            )
            return {
                "success": False,
                "message": (
                    f"Unknown location_category '{requested_location_category_raw}'. "
                    f"Use one of: {valid_categories}."
                ),
                "instructions": (
                    "Ask the user to repeat the category using one of the supported values."
                ),
                "location_match": {
                    "matched": False,
                    "method": "category_validation",
                    "requested_category": requested_location_category_raw,
                    "valid_categories": self._get_navigation_category_input_examples(),
                },
                "do_not_cache": True,
            }

        print_debug(
            "NavigationManager.navigate_to_location normalized args: "
            f"location_name='{requested_location_name}', "
            f"location_category='{requested_location_category}'"
        )

        resolved_location_name, location_match_result, matched = self._resolve_destination_name(
            requested_location_name,
            requested_location_category=requested_location_category,
        )
        if not matched:
            best_candidate = location_match_result.get("best_candidate")
            best_candidate_category = location_match_result.get("best_candidate_category")
            best_candidate_score = location_match_result.get("score")
            category_label = (
                f" within category '{requested_location_category}'"
                if requested_location_category
                else ""
            )
            response = {
                "success": False,
                "message": (
                    f"Could not match '{requested_location_name}'{category_label} "
                    "to a known navigation destination."
                ),
                "location_match": location_match_result,
                "do_not_cache": True,
            }
            if best_candidate:
                response["confirmation_request"] = {
                    "required": True,
                    "candidate_location_name": best_candidate,
                    "candidate_location_category": best_candidate_category,
                    "candidate_score": best_candidate_score,
                    "reason": "Best fuzzy candidate is below auto-match threshold.",
                }
                response["instructions"] = (
                    f"Do not execute navigation yet. Ask the user if they meant "
                    f"'{best_candidate}'"
                    f"{f' in category {best_candidate_category}' if best_candidate_category else ''}. "
                    "If the user confirms, call navigate_to_location again using the "
                    "suggested candidate_location_name and candidate_location_category exactly."
                )
            else:
                response["instructions"] = (
                    "Ask the user to repeat or clarify the destination name."
                )
            return response

        printr.print(
            f"-> Navigation: route calculation requested for '{requested_location_name}' "
            f"(resolved: '{resolved_location_name}', category: '{requested_location_category}').",
            tags="info",
        )
        self.overlay.display_overlay_text(
            f"Cora: Navigating to {resolved_location_name}",
            vertical_position_ratio=3,
            display_duration=2500,
        )

        result = self._execute_navigation_sequence(resolved_location_name)
        result["requested_location"] = requested_location_name
        result["requested_location_category"] = requested_location_category
        result["resolved_location_name"] = resolved_location_name
        result["location_match"] = location_match_result
        result["do_not_cache"] = True
        printr.print(f"-> Result: {json.dumps(result, indent=2)}", tags="info")
        return result

    def _execute_navigation_sequence(self, location_name: str) -> dict:
        opened, open_message = self._execute_sc_command("spaceship_hud_v_starmap")
        if not opened:
            return self._navigation_error(
                "Could not open starmap.",
                open_message,
            )

        time.sleep(self.map_open_wait_seconds)
        self._focus_sc_window_for_input(wait_seconds=self.map_input_activation_wait_seconds)
        self._zoom_out_map()
        if self.post_zoom_wait_seconds > 0:
            time.sleep(self.post_zoom_wait_seconds)

        search_point, search_from_cache, search_error = self._get_or_capture_click_point(
            point_key="search_box",
            overlay_prompt="Please move cursor over search box and click.",
        )
        if search_error:
            return self._navigation_error(
                "Could not focus starmap search field.",
                search_error,
            )

        self._focus_sc_window_for_input(wait_seconds=0.0)
        if search_from_cache and not self._click_screen_coordinates(
            search_point[0], search_point[1], move_first=True
        ):
            return self._navigation_error(
                "Could not focus starmap search field.",
                "Search click failed.",
            )
        time.sleep(self.post_click_wait_seconds)
        self._typewrite_text(location_name)
        time.sleep(self.post_type_wait_seconds)

        selection_point, selection_from_cache, selection_error = self._get_or_capture_click_point(
            point_key="selection_target",
            overlay_prompt="Please move cursor over destination selection and click.",
        )
        if selection_error:
            return self._navigation_error(
                "Could not find destination selection area.",
                selection_error,
            )

        route_cached_exists = self._has_cached_click_point("route_button")
        route_point: Optional[Tuple[int, int]] = None
        route_from_cache = False
        route_error = None

        unblock_mouse = lambda: None
        should_block_mouse = (
            self.lock_mouse_until_route_clicked
            and selection_from_cache
            and route_cached_exists
        )
        if should_block_mouse:
            unblock_mouse = self._temporarily_block_mouse_input()

        try:
            if selection_from_cache and not self._click_screen_coordinates(
                selection_point[0], selection_point[1], move_first=True
            ):
                return self._navigation_error(
                    "Could not click destination selection.",
                    "Destination selection click failed.",
                )

            time.sleep(self.selection_wait_seconds)

            route_point, route_from_cache, route_error = self._get_or_capture_click_point(
                point_key="route_button",
                overlay_prompt="Please move cursor over route button and click.",
            )
            if route_error:
                return self._navigation_error(
                    "Could not find route button.",
                    route_error,
                )
            if route_from_cache and not self._click_screen_coordinates(
                route_point[0], route_point[1], move_first=True
            ):
                return self._navigation_error(
                    "Could not click route button.",
                    "Route click failed.",
                )
        finally:
            try:
                unblock_mouse()
            except Exception:
                pass

        if route_point is None:
            return self._navigation_error(
                "Could not click route button.",
                "No route point available.",
            )

        self.overlay.display_overlay_text(
            f"Cora: Route set for {location_name}",
            vertical_position_ratio=3,
            display_duration=2500,
        )
        return {
            "success": True,
            "message": f"Route to '{location_name}' is set.",
            "requested_location": location_name,
            "instructions": "Confirm route plotting in one short sentence.",
        }

    def _navigation_error(self, user_message, error_details):
        self.overlay.display_overlay_text(
            "Cora: Navigation error",
            vertical_position_ratio=3,
            display_duration=2500,
        )
        return {
            "success": False,
            "message": user_message,
            "error": error_details,
        }

    @staticmethod
    def _focus_sc_window_for_input(wait_seconds: float = 0.0):
        sc_window = screenshots.find_and_activate_sc_window()
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        return sc_window

    def _zoom_out_map(self):
        sc_window = self._focus_sc_window_for_input(wait_seconds=0.0)
        scroll_anchor = None
        if self.zoom_out_center_mouse_before_scroll:
            scroll_anchor = self._center_mouse_for_scroll(sc_window)
            if self.post_center_before_scroll_wait_seconds > 0:
                time.sleep(self.post_center_before_scroll_wait_seconds)

        direction = -1 if self.zoom_out_scroll_direction < 0 else 1
        scroll_amount = direction * max(1, abs(self.zoom_out_scroll_step))
        for _ in range(self.zoom_out_scroll_clicks):
            if (
                self.zoom_out_center_mouse_before_scroll
                and self.zoom_out_recenter_each_scroll
            ):
                refreshed_anchor = self._center_mouse_for_scroll(sc_window)
                if refreshed_anchor is not None:
                    scroll_anchor = refreshed_anchor

            if not self._send_scroll_amount(scroll_amount, scroll_anchor):
                break

            if self.zoom_out_scroll_pause_seconds > 0:
                time.sleep(self.zoom_out_scroll_pause_seconds)

    def _center_mouse_for_scroll(self, sc_window):
        if not sc_window:
            sc_window = screenshots.find_and_activate_sc_window()
        if not sc_window:
            printr.print_warn("Cannot center mouse for scroll: SC window not found.")
            return None

        center_x = int(sc_window.left + (sc_window.width / 2))
        center_y = int(sc_window.top + (sc_window.height / 2))

        unblock_mouse = lambda: None
        if os.name == "nt":
            unblock_mouse = self._temporarily_block_mouse_input()
        try:
            moved = self._move_cursor_to_screen_point(center_x, center_y)
        finally:
            try:
                unblock_mouse()
            except Exception:
                pass

        if not moved:
            printr.print_warn(
                "Could not reliably move mouse to Star Citizen center before scrolling."
            )

        if self.zoom_out_center_click_before_scroll and moved:
            try:
                if hasattr(key_module, "click"):
                    key_module.click(x=center_x, y=center_y, duration=0.05)
            except Exception:
                pass

        return center_x, center_y

    def _load_click_coordinate_cache(self) -> dict:
        if not os.path.isfile(self.coordinate_cache_path):
            return {}
        try:
            with open(self.coordinate_cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            print_debug(f"Could not load coordinate cache: {exc}")
            return {}

    def _save_click_coordinate_cache(self):
        try:
            os.makedirs(os.path.dirname(self.coordinate_cache_path), exist_ok=True)
            with open(self.coordinate_cache_path, "w", encoding="utf-8") as f:
                json.dump(self.coordinate_cache, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            print_debug(f"Could not save coordinate cache: {exc}")

    def _has_cached_click_point(self, point_key: str) -> bool:
        entry = self.coordinate_cache.get(point_key)
        return isinstance(entry, dict) and "x_ratio" in entry and "y_ratio" in entry

    def _get_cached_click_point(self, point_key: str) -> Optional[Tuple[int, int]]:
        entry = self.coordinate_cache.get(point_key)
        if not isinstance(entry, dict):
            return None
        x_ratio = entry.get("x_ratio")
        y_ratio = entry.get("y_ratio")
        if x_ratio is None or y_ratio is None:
            return None
        try:
            x_ratio = float(x_ratio)
            y_ratio = float(y_ratio)
        except Exception:
            return None

        sc_window = screenshots.find_and_activate_sc_window()
        if not sc_window or sc_window.width <= 0 or sc_window.height <= 0:
            return None

        x_ratio = min(1.0, max(0.0, x_ratio))
        y_ratio = min(1.0, max(0.0, y_ratio))
        screen_x = int(sc_window.left + (x_ratio * sc_window.width))
        screen_y = int(sc_window.top + (y_ratio * sc_window.height))
        return screen_x, screen_y

    def _store_click_point(self, point_key: str, screen_point: Tuple[int, int]):
        sc_window = screenshots.find_and_activate_sc_window()
        if not sc_window or sc_window.width <= 0 or sc_window.height <= 0:
            return

        screen_x = int(screen_point[0])
        screen_y = int(screen_point[1])
        x_ratio = (screen_x - sc_window.left) / float(sc_window.width)
        y_ratio = (screen_y - sc_window.top) / float(sc_window.height)
        x_ratio = min(1.0, max(0.0, x_ratio))
        y_ratio = min(1.0, max(0.0, y_ratio))

        self.coordinate_cache[point_key] = {
            "x_ratio": x_ratio,
            "y_ratio": y_ratio,
            "last_screen_x": screen_x,
            "last_screen_y": screen_y,
            "window_width": int(sc_window.width),
            "window_height": int(sc_window.height),
            "updated_at": time.time(),
        }
        self._save_click_coordinate_cache()

    @staticmethod
    def _is_left_mouse_pressed() -> bool:
        if os.name != "nt":
            return False
        try:
            import ctypes

            return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
        except Exception:
            return False

    def _capture_manual_click_point(self) -> Optional[Tuple[int, int]]:
        timeout_seconds = max(1.0, float(self.capture_click_timeout_seconds))
        poll_seconds = max(0.005, float(self.capture_click_poll_interval_seconds))
        deadline = time.time() + timeout_seconds

        # Wait for a released state first so an already held button does not trigger instantly.
        while self._is_left_mouse_pressed() and time.time() < deadline:
            time.sleep(poll_seconds)

        prev_down = self._is_left_mouse_pressed()
        while time.time() < deadline:
            now_down = self._is_left_mouse_pressed()
            if now_down and not prev_down:
                pos = self._get_cursor_position()
                while self._is_left_mouse_pressed() and time.time() < deadline:
                    time.sleep(poll_seconds)
                return pos
            prev_down = now_down
            time.sleep(poll_seconds)

        return None

    def _get_or_capture_click_point(self, point_key: str, overlay_prompt: str):
        cached_point = self._get_cached_click_point(point_key)
        if cached_point:
            return cached_point, True, None

        self.overlay.display_overlay_text(
            f"Cora: {overlay_prompt}",
            vertical_position_ratio=3,
            display_duration=8000,
        )
        printr.print(f"-> Navigation: waiting for manual click for '{point_key}'.", tags="info")
        manual_point = self._capture_manual_click_point()
        if not manual_point:
            return None, False, f"Timeout while waiting for manual click for '{point_key}'."
        self._store_click_point(point_key, manual_point)
        printr.print(
            f"-> Navigation: stored click point '{point_key}' at {manual_point}.",
            tags="info",
        )
        return manual_point, False, None

    @staticmethod
    def _set_cursor_position(x, y):
        if os.name != "nt":
            return
        try:
            import ctypes

            ctypes.windll.user32.SetCursorPos(int(x), int(y))
        except Exception:
            pass

    @staticmethod
    def _get_cursor_position():
        if os.name != "nt":
            return None
        try:
            import ctypes

            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

            point = POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
                return int(point.x), int(point.y)
        except Exception:
            return None
        return None

    def _move_cursor_to_screen_point(self, x: int, y: int) -> bool:
        target_x = int(x)
        target_y = int(y)
        if os.name != "nt":
            for module in (key_module, scroll_module):
                if not hasattr(module, "moveTo"):
                    continue
                try:
                    module.moveTo(target_x, target_y, duration=0)
                    return True
                except TypeError:
                    try:
                        module.moveTo(target_x, target_y)
                        return True
                    except Exception:
                        continue
                except Exception:
                    continue
            return False

        max_attempts = 3
        for _ in range(max_attempts):
            self._set_cursor_position(target_x, target_y)
            current = self._get_cursor_position()
            if current is None:
                return True
            if abs(current[0] - target_x) <= 3 and abs(current[1] - target_y) <= 3:
                return True

            for module in (key_module, scroll_module):
                if not hasattr(module, "moveTo"):
                    continue
                try:
                    module.moveTo(target_x, target_y, duration=0)
                except TypeError:
                    try:
                        module.moveTo(target_x, target_y)
                    except Exception:
                        continue
                except Exception:
                    continue

                current = self._get_cursor_position()
                if current is None:
                    return True
                if abs(current[0] - target_x) <= 3 and abs(current[1] - target_y) <= 3:
                    return True

            time.sleep(0.01)

        return False

    @staticmethod
    def _scroll_with_anchor(module, scroll_amount: int, anchor):
        if not hasattr(module, "scroll"):
            return False

        if anchor:
            try:
                module.scroll(scroll_amount, x=anchor[0], y=anchor[1])
                return True
            except TypeError:
                pass
            except Exception:
                return False

        try:
            module.scroll(scroll_amount)
            return True
        except Exception:
            return False

    def _send_scroll_amount(self, scroll_amount: int, anchor) -> bool:
        if self._scroll_with_anchor(key_module, scroll_amount, anchor):
            return True
        if self._scroll_with_anchor(scroll_module, scroll_amount, anchor):
            return True
        return False

    @staticmethod
    def _temporarily_block_mouse_input():
        if os.name != "nt":
            return lambda: None
        try:
            import ctypes

            success = bool(ctypes.windll.user32.BlockInput(True))
            if not success:
                return lambda: None
        except Exception as exc:
            print_debug(f"BlockInput failed: {exc}")
            return lambda: None

        released = {"done": False}

        def unblock():
            if released["done"]:
                return
            released["done"] = True
            try:
                ctypes.windll.user32.BlockInput(False)
            except Exception as unblock_exc:
                print_debug(f"BlockInput release failed: {unblock_exc}")

        return unblock

    def _typewrite_text(self, text: str):
        pyperclip.copy(text)

        key_module.keyDown("ctrl")
        key_module.press("a")
        key_module.keyUp("ctrl")
        time.sleep(0.05)

        key_module.press("backspace")
        time.sleep(0.05)

        key_module.keyDown("ctrl")
        key_module.keyDown("v")
        key_module.keyUp("v")
        key_module.keyUp("ctrl")

    def _click_screen_coordinates(self, screen_x: int, screen_y: int, move_first: bool) -> bool:
        target_x = int(screen_x)
        target_y = int(screen_y)

        if move_first and not self._move_cursor_to_screen_point(target_x, target_y):
            return False
        if self.mouse_settle_wait_seconds > 0:
            time.sleep(self.mouse_settle_wait_seconds)

        for module in (key_module, scroll_module):
            if hasattr(module, "click"):
                module_name = getattr(module, "__name__", str(module))
                print_debug(f"Attempting click at ({target_x}, {target_y}) using {module_name}")
                try:
                    module.click(x=target_x, y=target_y)
                    return True
                except TypeError:
                    try:
                        module.click()
                        return True
                    except Exception:
                        pass
                except Exception:
                    pass

            if hasattr(module, "mouseDown") and hasattr(module, "mouseUp"):
                module_name = getattr(module, "__name__", str(module))
                print_debug(
                    f"Attempting mouseDown/mouseUp at ({target_x}, {target_y}) using {module_name}"
                )
                try:
                    try:
                        module.mouseDown(x=target_x, y=target_y, button="left")
                    except TypeError:
                        module.mouseDown(button="left")
                    if self.mouse_click_hold_seconds > 0:
                        time.sleep(self.mouse_click_hold_seconds)
                    try:
                        module.mouseUp(x=target_x, y=target_y, button="left")
                    except TypeError:
                        module.mouseUp(button="left")
                    return True
                except Exception:
                    pass

        return False

    def _execute_sc_command(self, command_name: str):
        command = self.sc_keybinding_service.get_command(command_name)
        if not command:
            return False, f"SC command not found: {command_name}"

        avoid_filter_names = set(self.config.get("avoid-commands", []))
        if command_name in avoid_filter_names:
            return False, f"SC command blocked by avoid-commands: {command_name}"

        keys_string = command.get("keyboard-mapping", "")
        if not keys_string:
            return False, f"No keyboard mapping for command '{command_name}'."

        keys = keys_string.split("+")
        key_mapping_config = (
            self.config.get("sc-keybind-mappings", {}).get("key-mappings", {}) or {}
        )

        modifier_order = [
            "alt",
            "ctrl",
            "shift",
            "altleft",
            "ctrlleft",
            "shiftleft",
            "altright",
            "ctrlright",
            "shiftright",
        ]
        modifiers = set(modifier_order)
        keys = sorted(keys, key=lambda value: modifier_order.index(value) if value in modifiers else len(modifier_order))

        hold_mapping = (
            self.config.get("sc-keybind-mappings", {}).get("key-press-mappings", {}) or {}
        )
        activation_mode = command.get("activationMode")
        hold = hold_mapping.get(activation_mode, 1)
        if hold == "notSupported":
            return False, f"Activation mode not supported: {activation_mode}"

        if hold == "double_tap" and len(keys) == 1:
            mapped_key, is_mouse = self._resolve_sc_key(keys[0], key_mapping_config)
            self._press_sc_key(mapped_key, is_mouse)
            time.sleep(0.05)
            self._press_sc_key(mapped_key, is_mouse)
            return True, "OK"

        active_modifiers = []
        try:
            for sc_key in keys:
                mapped_key, is_mouse = self._resolve_sc_key(sc_key, key_mapping_config)
                if mapped_key in modifiers:
                    key_module.keyDown(mapped_key)
                    active_modifiers.insert(0, mapped_key)
                    continue

                if hold in ["unknown", None]:
                    self._press_sc_key(mapped_key, is_mouse)
                elif isinstance(hold, (int, float)) and hold > 1:
                    self._hold_and_release_sc_key(mapped_key, is_mouse, hold)
                else:
                    self._press_sc_key(mapped_key, is_mouse)
        except Exception as exc:
            return False, str(exc)
        finally:
            for modifier in active_modifiers:
                try:
                    key_module.keyUp(modifier)
                except Exception:
                    pass

        return True, "OK"

    @staticmethod
    def _resolve_sc_key(sc_key: str, key_mapping_config: dict):
        mapped_key = key_mapping_config.get(sc_key, sc_key)
        is_mouse = isinstance(mapped_key, str) and mapped_key.startswith("mouse_")
        return mapped_key, is_mouse

    @staticmethod
    def _press_sc_key(mapped_key: str, is_mouse: bool):
        if is_mouse:
            key_module.click(button=mapped_key.split("mouse_")[-1], duration=0.08)
        else:
            key_module.press(mapped_key)

    @staticmethod
    def _hold_and_release_sc_key(mapped_key: str, is_mouse: bool, hold_ms):
        hold_seconds = float(hold_ms) / 1000.0
        if is_mouse:
            button = mapped_key.split("mouse_")[-1]
            key_module.mouseDown(button=button)
            time.sleep(hold_seconds)
            key_module.mouseUp(button=button)
            return
        key_module.keyDown(mapped_key)
        time.sleep(hold_seconds)
        key_module.keyUp(mapped_key)

    def _build_navigation_location_names(self):
        if not self.uex_service:
            self._navigation_location_names_by_category = {}
            return []

        categories = self._get_navigation_location_categories_in_priority_order()
        names_by_category = {}
        deduped = []
        seen = set()
        for category in categories:
            category_names = []
            try:
                category_names = self.uex_service.get_category_names(category)
            except Exception as e:
                print_debug(f"Could not load names for category '{category}': {e}")

            category_deduped = []
            category_seen = set()
            for name in category_names:
                normalized = (name or "").strip().lower()
                if not normalized or normalized in category_seen:
                    continue
                category_seen.add(normalized)
                category_deduped.append(name)
                if normalized in seen:
                    continue
                seen.add(normalized)
                deduped.append(name)

            names_by_category[category] = category_deduped

        self._navigation_location_names_by_category = names_by_category
        return deduped

    @staticmethod
    def _get_navigation_location_categories_in_priority_order():
        return [
            uex_api_module.CATEGORY_OUTPOSTS,
            uex_api_module.CATEGORY_STATIONS,
            uex_api_module.CATEGORY_CITIES,
            uex_api_module.CATEGORY_MOONS,
            uex_api_module.CATEGORY_ORBITS,
        ]

    @staticmethod
    def _get_navigation_category_alias_map():
        return {
            "outpost": uex_api_module.CATEGORY_OUTPOSTS,
            "outposts": uex_api_module.CATEGORY_OUTPOSTS,
            "station": uex_api_module.CATEGORY_STATIONS,
            "stations": uex_api_module.CATEGORY_STATIONS,
            "space_station": uex_api_module.CATEGORY_STATIONS,
            "space_stations": uex_api_module.CATEGORY_STATIONS,
            "space station": uex_api_module.CATEGORY_STATIONS,
            "space stations": uex_api_module.CATEGORY_STATIONS,
            "city": uex_api_module.CATEGORY_CITIES,
            "cities": uex_api_module.CATEGORY_CITIES,
            "moon": uex_api_module.CATEGORY_MOONS,
            "moons": uex_api_module.CATEGORY_MOONS,
            "orbit": uex_api_module.CATEGORY_ORBITS,
            "orbits": uex_api_module.CATEGORY_ORBITS,
            "planet": uex_api_module.CATEGORY_ORBITS,
            "planets": uex_api_module.CATEGORY_ORBITS,
        }

    @classmethod
    def _get_navigation_category_input_examples(cls):
        return ["outpost", "station", "city", "moon", "orbit", "planet"]

    def _normalize_navigation_location_category(self, requested_category: Optional[str]) -> Optional[str]:
        normalized_category = (requested_category or "").strip().lower()
        if not normalized_category:
            return None

        normalized_category = normalized_category.replace("-", "_")
        return self._get_navigation_category_alias_map().get(normalized_category)

    def _get_navigation_search_categories(
        self, requested_location_category: Optional[str] = None
    ) -> list[str]:
        if requested_location_category:
            return [requested_location_category]
        return self._get_navigation_location_categories_in_priority_order()

    def _ensure_navigation_location_names_loaded(self):
        if self._navigation_location_names and self._navigation_location_names_by_category:
            return
        self._navigation_location_names = self._build_navigation_location_names()

    def _find_exact_location_match_by_category(
        self,
        requested_location_name: str,
        requested_location_category: Optional[str] = None,
    ):
        normalized_request = (requested_location_name or "").strip().lower()
        search_categories = self._get_navigation_search_categories(requested_location_category)
        print_debug(
            f"Navigation exact search for '{requested_location_name}' in categories: "
            f"{search_categories}"
        )
        for category in search_categories:
            for value in self._navigation_location_names_by_category.get(category, []):
                if value.lower().strip() == normalized_request:
                    print_debug(
                        f"Navigation exact match in category '{category}': '{value}'"
                    )
                    return category, value
        return None, None

    def _find_fuzzy_location_match_by_category(
        self,
        requested_location_name: str,
        score_cutoff: int,
        requested_location_category: Optional[str] = None,
    ):
        best_match = None
        best_category = None

        search_categories = self._get_navigation_search_categories(requested_location_category)
        for category in search_categories:
            category_names = self._navigation_location_names_by_category.get(category, [])
            if not category_names:
                print_debug(f"Navigation fuzzy search skipped empty category '{category}'")
                continue

            fuzzy_match, fuzzy_success = find_best_match.find_best_match(
                requested_location_name,
                category_names,
                score_cutoff=score_cutoff,
            )
            if not fuzzy_success:
                print_debug(
                    f"Navigation fuzzy search in category '{category}' found no match "
                    f"for '{requested_location_name}' with cutoff {score_cutoff}"
                )
                continue

            score = fuzzy_match.get("score", 0)
            print_debug(
                f"Navigation fuzzy search in category '{category}' matched "
                f"'{fuzzy_match.get('matched_value')}' with score {score} "
                f"(cutoff {score_cutoff})"
            )
            if score_cutoff > 0:
                return category, fuzzy_match

            if best_match is None or score > best_match.get("score", 0):
                best_match = fuzzy_match
                best_category = category

        return best_category, best_match

    @staticmethod
    def _strip_parenthetical_suffix(location_name: str) -> str:
        cleaned_name = re.sub(r"\s*\([^)]*\)\s*$", "", (location_name or "").strip())
        return cleaned_name.strip() or (location_name or "").strip()

    def _resolve_destination_name(
        self,
        requested_location_name: str,
        requested_location_category: Optional[str] = None,
    ):
        self._ensure_navigation_location_names_loaded()

        if not self._navigation_location_names:
            return (
                requested_location_name,
                {
                    "matched": True,
                    "method": "raw_input_fallback",
                    "score": None,
                    "matched_value": requested_location_name,
                    "reason": "UEX location pool unavailable.",
                },
                True,
            )

        matched_category, exact = self._find_exact_location_match_by_category(
            requested_location_name,
            requested_location_category=requested_location_category,
        )
        if exact:
            cleaned_exact = self._strip_parenthetical_suffix(exact)
            return (
                cleaned_exact,
                {
                    "matched": True,
                    "method": "exact",
                    "score": 100,
                    "requested_category": requested_location_category,
                    "matched_category": matched_category,
                    "matched_value": cleaned_exact,
                },
                True,
            )

        matched_category, fuzzy_match = self._find_fuzzy_location_match_by_category(
            requested_location_name,
            score_cutoff=self.location_match_score_cutoff,
            requested_location_category=requested_location_category,
        )
        if fuzzy_match:
            matched_value = fuzzy_match.get("matched_value", requested_location_name)
            cleaned_matched_value = self._strip_parenthetical_suffix(matched_value)
            return (
                cleaned_matched_value,
                {
                    "matched": True,
                    "method": "fuzzy",
                    "score": fuzzy_match.get("score"),
                    "requested_category": requested_location_category,
                    "matched_category": matched_category,
                    "matched_value": cleaned_matched_value,
                    "score_cutoff": self.location_match_score_cutoff,
                },
                True,
            )

        suggestion_category, best_candidate = self._find_fuzzy_location_match_by_category(
            requested_location_name,
            score_cutoff=0,
            requested_location_category=requested_location_category,
        )
        suggestion = best_candidate.get("matched_value") if best_candidate else None
        cleaned_suggestion = self._strip_parenthetical_suffix(suggestion) if suggestion else None
        suggestion_score = best_candidate.get("score") if best_candidate else None
        if best_candidate:
            print_debug(
                f"Navigation no-match fallback for '{requested_location_name}': "
                f"best candidate '{cleaned_suggestion}' in category "
                f"'{suggestion_category}' with score {suggestion_score}"
            )
        else:
            print_debug(
                f"Navigation no-match fallback for '{requested_location_name}': "
                "no candidate found in search space"
            )
        return (
            requested_location_name,
            {
                "matched": False,
                "method": "fuzzy",
                "score": suggestion_score,
                "requested_category": requested_location_category,
                "best_candidate": cleaned_suggestion,
                "best_candidate_category": suggestion_category,
                "score_cutoff": self.location_match_score_cutoff,
            },
            False,
        )
