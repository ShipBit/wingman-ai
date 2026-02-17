"""
HUD Skill - Display messages, info panels, progress bars, and timers on a HUD overlay.

This skill uses the integrated HUD Server (enabled in global settings) to display
information on a transparent overlay. It supports:
- Chat message display (user and assistant messages)
- Persistent information panels
- Progress bars
- Countdown timers

The HUD Server must be enabled in global settings for this skill to work.
"""

import asyncio
import inspect
import json
import os
import threading
import time
import re
from os import path
from typing import TYPE_CHECKING, Optional

from api.enums import LogType, WingmanInitializationErrorType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from services.file import get_writable_dir
from services.printr import Printr
from skills.skill_base import Skill, tool
from hud_server.http_client import HudHttpClient
from hud_server.types import Anchor, HudColor, FontFamily, LayoutMode, MessageProps, PersistentProps, WindowType
from hud_server.validation import validate_hud_settings

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman

printr = Printr()


class HUD(Skill):
    """
    HUD Skill - Display information on a transparent overlay.

    Uses the integrated HUD Server which must be enabled in global settings.
    """

    # Valid anchor values from the Anchor enum
    VALID_ANCHORS = [a.value for a in Anchor]

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman"
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

        # State
        self.active = False
        self.stop_event = threading.Event()
        self.expecting_audio = False
        self.audio_expect_start_time = 0.0

        # Persistent items storage
        self._persistent_items: dict[str, dict] = {}

        # Data persistence
        self.data_path = get_writable_dir(path.join("skills", "hud", "data"))
        self.persistent_file = path.join(
            self.data_path,
            f"persistent_info_{self.wingman.name}.json"
        )

        # HTTP client
        self._client: Optional[HudHttpClient] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None

        # Group name for HUD (just wingman identifier, element passed separately)
        self._group_name = re.sub(r'[^a-zA-Z0-9_-]', '_', self.wingman.name)

    # ─────────────────────────────── Helpers ─────────────────────────────── #

    @staticmethod
    def _is_valid_hex_color(color: str) -> bool:
        """Validate a hex color string (#RGB, #RRGGBB, or #RRGGBBAA)."""
        if not isinstance(color, str):
            return False
        if not color.startswith('#'):
            return False
        hex_part = color[1:]
        if len(hex_part) not in (3, 6, 8):
            return False
        try:
            int(hex_part, 16)
            return True
        except ValueError:
            return False

    # ─────────────────────────────── Configuration ─────────────────────────────── #

    async def validate(self) -> list[WingmanInitializationError]:
        """Validate skill configuration."""
        errors = await super().validate()

        # Check if HUD server is enabled
        hud_settings = getattr(self.settings, 'hud_server', None)
        if not hud_settings or not hud_settings.enabled:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="HUD Server is not enabled in global settings. "
                           "Go to Settings → HUD Server and enable it.",
                    error_type=WingmanInitializationErrorType.UNKNOWN
                )
            )

        # Validate accent_color
        accent_color = self.retrieve_custom_property_value("accent_color", errors)
        if not self._is_valid_hex_color(accent_color):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid accent_color: '{accent_color}'. Must be a valid hex color (e.g., #ffffff).",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        # Validate bg_color
        bg_color = self.retrieve_custom_property_value("bg_color", errors)
        if not self._is_valid_hex_color(bg_color):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid bg_color: '{bg_color}'. Must be a valid hex color (e.g., #ffffff).",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        # Validate text_color
        text_color = self.retrieve_custom_property_value("text_color", errors)
        if not self._is_valid_hex_color(text_color):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid text_color: '{text_color}'. Must be a valid hex color (e.g., #ffffff).",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        # Validate chat_anchor
        chat_anchor = self.retrieve_custom_property_value("chat_anchor", errors)
        if chat_anchor not in self.VALID_ANCHORS:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid chat_anchor: '{chat_anchor}'. Must be one of: {', '.join(self.VALID_ANCHORS)}.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        # Validate chat_priority
        chat_priority = self.retrieve_custom_property_value("chat_priority", errors)
        if not isinstance(chat_priority, (int, float)) or chat_priority < 0:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid chat_priority: '{chat_priority}'. Must be a non-negative number.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        # Validate hud_width
        hud_width = self.retrieve_custom_property_value("hud_width", errors)
        if not isinstance(hud_width, (int, float)) or hud_width <= 0:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid hud_width: '{hud_width}'. Must be a positive number.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        # Validate hud_max_height
        hud_max_height = self.retrieve_custom_property_value("hud_max_height", errors)
        if not isinstance(hud_max_height, (int, float)) or hud_max_height <= 0:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid hud_max_height: '{hud_max_height}'. Must be a positive number.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        # Validate persistent_anchor
        persistent_anchor = self.retrieve_custom_property_value("persistent_anchor", errors)
        if persistent_anchor not in self.VALID_ANCHORS:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid persistent_anchor: '{persistent_anchor}'. Must be one of: {', '.join(self.VALID_ANCHORS)}.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        # Validate persistent_priority
        persistent_priority = self.retrieve_custom_property_value("persistent_priority", errors)
        if not isinstance(persistent_priority, (int, float)) or persistent_priority < 0:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid persistent_priority: '{persistent_priority}'. Must be a non-negative number.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        # Validate persistent_width
        persistent_width = self.retrieve_custom_property_value("persistent_width", errors)
        if not isinstance(persistent_width, (int, float)) or persistent_width <= 0:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid persistent_width: '{persistent_width}'. Must be a positive number.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        # Validate persistent_max_height
        persistent_max_height = self.retrieve_custom_property_value("persistent_max_height", errors)
        if not isinstance(persistent_max_height, (int, float)) or persistent_max_height <= 0:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid persistent_max_height: '{persistent_max_height}'. Must be a positive number.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        # Validate opacity (0-100 range from slider)
        opacity = self.retrieve_custom_property_value("opacity", errors)
        if not isinstance(opacity, (int, float)) or not (0 <= opacity <= 100):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid opacity: '{opacity}'. Must be a number between 0 and 100.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        # Validate border_radius
        border_radius = self.retrieve_custom_property_value("border_radius", errors)
        if not isinstance(border_radius, (int, float)) or border_radius < 0:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid border_radius: '{border_radius}'. Must be a non-negative number.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        # Validate content_padding
        content_padding = self.retrieve_custom_property_value("content_padding", errors)
        if not isinstance(content_padding, (int, float)) or content_padding < 0:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid content_padding: '{content_padding}'. Must be a non-negative number.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        # Validate font_size
        font_size = self.retrieve_custom_property_value("font_size", errors)
        if not isinstance(font_size, (int, float)) or font_size <= 0:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid font_size: '{font_size}'. Must be a positive number.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        # Validate font_family
        font_family = self.retrieve_custom_property_value("font_family", errors)
        if not isinstance(font_family, str) or not font_family.strip():
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid font_family: '{font_family}'. Must be a non-empty string.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        # Validate max_display_time
        max_display_time = self.retrieve_custom_property_value("max_display_time", errors)
        if not isinstance(max_display_time, (int, float)) or max_display_time <= 0:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid max_display_time: '{max_display_time}'. Must be a positive number.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        # Validate typewriter_effect
        typewriter_effect = self.retrieve_custom_property_value("typewriter_effect", errors)
        if not isinstance(typewriter_effect, bool):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid typewriter_effect: '{typewriter_effect}'. Must be a boolean.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        # Validate restore_persistent_items
        restore_persistent_items = self.retrieve_custom_property_value("restore_persistent_items", errors)
        if not isinstance(restore_persistent_items, bool):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid restore_persistent_items: '{restore_persistent_items}'. Must be a boolean.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        # Validate show_chat_messages
        show_chat_messages = self.retrieve_custom_property_value("show_chat_messages", errors)
        if not isinstance(show_chat_messages, bool):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid show_chat_messages: '{show_chat_messages}'. Must be a boolean.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        # Validate display_tool_names
        display_tool_names = self.retrieve_custom_property_value("display_tool_names", errors)
        if not isinstance(display_tool_names, bool):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message=f"Invalid display_tool_names: '{display_tool_names}'. Must be a boolean.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG
                )
            )

        return errors

    def _get_prop(self, key: str, default):
        """Get a custom property value with fallback to default."""
        val = self.retrieve_custom_property_value(key, [])
        return val if val is not None else default

    def _get_hud_props(self) -> MessageProps:
        """Get all HUD visual properties as a dictionary."""
        return MessageProps(
            anchor=str(self._get_prop("chat_anchor", Anchor.TOP_LEFT)),
            priority=int(self._get_prop("chat_priority", 20)),
            layout_mode=LayoutMode.AUTO,
            width=int(self._get_prop("hud_width", 400)),
            max_height=int(self._get_prop("hud_max_height", 600)),
            bg_color=str(self._get_prop("bg_color", HudColor.BG_DARK)),
            text_color=str(self._get_prop("text_color", HudColor.TEXT_PRIMARY)),
            accent_color=str(self._get_prop("accent_color", HudColor.ACCENT_BLUE)),
            opacity=float(self._get_prop("opacity", 85)) / 100.0,
            border_radius=int(self._get_prop("border_radius", 12)),
            font_size=int(self._get_prop("font_size", 16)),
            content_padding=int(self._get_prop("content_padding", 16)),
            font_family=str(self._get_prop("font_family", FontFamily.SEGOE_UI)),
            typewriter_effect=bool(self._get_prop("typewriter_effect", True)),
        )

    def _get_persistent_props(self) -> PersistentProps:
        """Get properties for persistent info panels."""
        return PersistentProps(
            anchor=str(self._get_prop("persistent_anchor", Anchor.TOP_LEFT)),
            priority=int(self._get_prop("persistent_priority", 10)),
            layout_mode=LayoutMode.AUTO,
            width=int(self._get_prop("persistent_width", 400)),
            max_height=int(self._get_prop("persistent_max_height", 600)),
            bg_color=str(self._get_prop("bg_color", HudColor.BG_DARK)),
            text_color=str(self._get_prop("text_color", HudColor.TEXT_PRIMARY)),
            accent_color=str(self._get_prop("accent_color", HudColor.ACCENT_BLUE)),
            opacity=float(self._get_prop("opacity", 85)) / 100.0,
            border_radius=int(self._get_prop("border_radius", 12)),
            font_size=int(self._get_prop("font_size", 16)),
            content_padding=int(self._get_prop("content_padding", 16)),
            font_family=str(self._get_prop("font_family", FontFamily.SEGOE_UI))
        )

    async def update_config(self, new_config) -> None:
        """Handle configuration updates - recreate HUD groups with new settings."""
        # Check if custom_properties actually changed before doing anything
        old_config = self.config
        await super().update_config(new_config)

        if old_config.custom_properties == new_config.custom_properties:
            return

        if not await self._ensure_connected():
            return

        # Get new props
        msg_props = self._get_hud_props()
        pers_props = self._get_persistent_props()

        # Delete and recreate message group
        await self._client.delete_group(self._group_name, WindowType.MESSAGE)
        await self._client.create_group(self._group_name, WindowType.MESSAGE, props=msg_props)

        # Delete and recreate persistent group, then restore items
        await self._client.delete_group(self._group_name, WindowType.PERSISTENT)
        await self._client.create_group(self._group_name, WindowType.PERSISTENT, props=pers_props)

        # Re-add all persistent items with the new group settings
        if self._persistent_items:
            await self._restore_persistent_items()

    async def _ensure_connected(self) -> bool:
        """Ensure the HUD client is connected. Create client and connect if needed."""
        # Get HUD server settings
        hud_settings = getattr(self.settings, 'hud_server', None)
        if not hud_settings or not hud_settings.enabled:
            return False

        # Check if we're in a different event loop than when the client was created
        # If so, we need to create a new client
        try:
            current_loop = asyncio.get_running_loop()
            if self._main_loop is not None and self._main_loop != current_loop:
                # Event loop changed - need to recreate client
                if self._client:
                    try:
                        await self._client.disconnect()
                    except Exception:
                        pass
                    self._client = None
                self._main_loop = current_loop
        except RuntimeError:
            pass

        # Create client if it doesn't exist (e.g., after skill reactivation or loop change)
        if not self._client:
            validated = validate_hud_settings(hud_settings)
            base_url = f"http://{validated['host']}:{validated['port']}"
            self._client = HudHttpClient(base_url=base_url)

            # Store current loop reference
            try:
                self._main_loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

        if not self._client.connected:
            # Try to connect/reconnect
            try:
                if await self._client.connect(timeout=3.0):
                    await printr.print_async(
                        "[HUD] Connected to HUD server",
                        color=LogType.INFO,
                        server_only=True
                    )
                    self.active = True

                    # Create/update groups after connect
                    msg_props = self._get_hud_props()
                    pers_props = self._get_persistent_props()
                    await self._client.create_group(self._group_name, WindowType.MESSAGE, props=msg_props)
                    await self._client.create_group(self._group_name, WindowType.PERSISTENT, props=pers_props)

                    # Start audio monitor if not running
                    if not self._monitor_task or self._monitor_task.done():
                        self.stop_event.clear()
                        self._monitor_task = asyncio.create_task(self._audio_monitor_loop())

                    return True
                else:
                    return False
            except Exception as e:
                await printr.print_async(
                    f"[HUD] Connection failed: {e}",
                    color=LogType.WARNING,
                    server_only=True
                )
                return False
        return True

    # ─────────────────────────────── Lifecycle ─────────────────────────────── #

    async def prepare(self) -> None:
        """Prepare the skill - connect to HUD server."""
        await super().prepare()
        self.stop_event.clear()

        # Get HUD server settings
        hud_settings = getattr(self.settings, 'hud_server', None)
        if not hud_settings or not hud_settings.enabled:
            await printr.print_async(
                "[HUD] HUD Server is not enabled in global settings.",
                color=LogType.ERROR,
                server_only=True
            )
            self.active = False
            return

        # Connect to HUD server
        validated = validate_hud_settings(hud_settings)
        base_url = f"http://{validated['host']}:{validated['port']}"
        self._client = HudHttpClient(base_url=base_url)

        # store the loop where the client was created
        try:
            self._main_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        
        try:
            if await self._client.connect(timeout=3.0):
                await printr.print_async(
                    f"[HUD] Connected to HUD server at {base_url}",
                    color=LogType.INFO,
                    server_only=True
                )
                self.active = True
                
                # Create/Ensure groups exist with this wingman's HUD props
                try:
                    msg_props = self._get_hud_props()
                    pers_props = self._get_persistent_props()
                    await self._client.create_group(self._group_name, WindowType.MESSAGE, props=msg_props)
                    await self._client.create_group(self._group_name, WindowType.PERSISTENT, props=pers_props)
                except Exception:
                    pass
            else:
                await printr.print_async(
                    f"[HUD] Failed to connect to HUD server at {base_url}. "
                    "Make sure it's enabled and running.",
                    color=LogType.ERROR,
                    server_only=True
                )
                self._client = None
                self.active = False
                return
        except Exception as e:
            await printr.print_async(
                f"[HUD] Connection error: {e}",
                color=LogType.ERROR,
                server_only=True
            )
            self._client = None
            self.active = False
            return

        # Restore persistent items
        await self._restore_persistent_items()

        # Start audio monitor
        self._monitor_task = asyncio.create_task(self._audio_monitor_loop())

        # Show init message
        accent_color = str(self._get_prop("accent_color", "#00aaff"))
        message = "HUD initialized"
        if self._get_prop("restore_persistent_items", True):
            message += " & restored elements"
        await self._show_message(self.wingman.name, message, accent_color, duration=4.0)

    async def unload(self) -> None:
        """Cleanup when skill is unloaded."""
        await super().unload()

        printr.print(
            f"[HUD] Unloading for {self.wingman.name}",
            color=LogType.INFO,
            server_only=True
        )

        self.stop_event.set()

        # Cancel monitor task
        if self._monitor_task:
            try:
                task_loop = self._monitor_task.get_loop()
                current_loop = None
                try:
                    current_loop = asyncio.get_running_loop()
                except RuntimeError:
                    pass

                if current_loop and task_loop == current_loop:
                    self._monitor_task.cancel()
                    try:
                        await self._monitor_task
                    except asyncio.CancelledError:
                        pass
                else:
                    # Task is on a different loop, await would crash
                    if not task_loop.is_closed():
                        task_loop.call_soon_threadsafe(self._monitor_task.cancel)
            except Exception as e:
                printr.print(
                    f"[HUD] Error cancelling monitor task: {e}",
                    color=LogType.WARNING,
                    server_only=True
                )
            self._monitor_task = None

        # Save state
        self._save_persistent_items()

        # Clear HUD items - wrap in try-except to handle server unavailability
        try:
            await self.hud_clear_all(False)
        except Exception as e:
            printr.print(
                f"[HUD] Error clearing items during unload: {e}",
                color=LogType.WARNING,
                server_only=True
            )

        # Delete groups if client exists - wrap in try-except
        if self._client:
            try:
                await self._client.delete_group(self._group_name, WindowType.MESSAGE)
                await self._client.delete_group(self._group_name, WindowType.PERSISTENT)
            except Exception as e:
                printr.print(
                    f"[HUD] Error deleting groups during unload: {e}",
                    color=LogType.WARNING,
                    server_only=True
                )

        # Disconnect client
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None

        self.active = False

    # ─────────────────────────────── Audio Monitor ─────────────────────────────── #

    async def _audio_monitor_loop(self):
        """Monitor audio playback and hide messages when audio stops."""
        was_playing = False

        while not self.stop_event.is_set():
            try:
                # Check audio status
                is_playing = False
                try:
                    if self.wingman and self.wingman.audio_player:
                        is_playing = self.wingman.audio_player.is_playing
                except Exception:
                    pass

                # Audio just started - reset expecting flag
                if is_playing and not was_playing:
                    self.expecting_audio = False

                # Hide message when audio stops
                if was_playing and not is_playing:
                    await asyncio.sleep(0.5)  # Brief delay for readability

                    # Re-check if audio started during the delay
                    still_not_playing = True
                    try:
                        if self.wingman and self.wingman.audio_player:
                            still_not_playing = not self.wingman.audio_player.is_playing
                    except Exception:
                        pass

                    if still_not_playing:
                        await self._hide_message()
                    self.expecting_audio = False

                was_playing = is_playing

                # Handle audio timeout - hide message if audio doesn't start in time
                if not is_playing and self.expecting_audio:
                    max_display_time = float(self._get_prop("max_display_time", 5))
                    elapsed = time.time() - self.audio_expect_start_time
                    if elapsed > max_display_time:
                        self.expecting_audio = False
                        await self._hide_message()

                await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                await printr.print_async(
                    f"[HUD] Monitor error: {e}",
                    color=LogType.ERROR,
                    server_only=True
                )
                await asyncio.sleep(1.0)

    # ─────────────────────────────── HTTP Client Helpers ─────────────────────────────── #

    async def _show_message(
        self,
        title: str,
        message: str,
        color: str,
        tools: Optional[list] = None,
        duration: float = 180.0
    ):
        """Show a message on the HUD."""
        if not await self._ensure_connected():
            return

        props = self._get_hud_props()
        props.fade_delay = duration

        result = await self._client.show_message(
            group_name=self._group_name,
            element=WindowType.MESSAGE,
            title=title,
            content=message,
            color=color,
            tools=tools,
            props=props,
            duration=duration
        )
        if result is None and self.active:
            await printr.print_async(
                "[HUD] Failed to show message - server may be unavailable",
                color=LogType.WARNING,
                server_only=True
            )

    async def _hide_message(self):
        """Hide the current message."""
        if not await self._ensure_connected():
            return

        await self._client.hide_message(group_name=self._group_name, element=WindowType.MESSAGE)

    async def _show_loader(self, show: bool, color: str = None):
        """Show or hide the loading animation."""
        if not await self._ensure_connected():
            return
        await self._client.show_loader(group_name=self._group_name, element=WindowType.MESSAGE, show=show, color=color)

    def _send_command_sync(self, coro):
        """Send a command synchronously (for @tool methods)."""
        if self._main_loop and self._main_loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, self._main_loop)
            return

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(coro, loop)
                    future.result(timeout=5.0)
                else:
                    loop.run_until_complete(coro)
            except Exception as e:
                printr.print(
                    f"[HUD] Command error: {e}",
                    color=LogType.ERROR,
                    server_only=True
                )

    # ─────────────────────────────── Persistence ─────────────────────────────── #

    def _save_persistent_items(self):
        """Save persistent items to file."""
        try:
            os.makedirs(os.path.dirname(self.persistent_file), exist_ok=True)
            with open(self.persistent_file, "w", encoding="utf-8") as f:
                json.dump(self._persistent_items, f, indent=2)
        except Exception as e:
            printr.print(
                f"[HUD] Failed to save state: {e}",
                color=LogType.ERROR,
                server_only=True
            )

    async def _restore_persistent_items(self):
        """Restore persistent items from file."""
        if not path.exists(self.persistent_file):
            return

        if not self._get_prop("restore_persistent_items", True):
            return

        try:
            with open(self.persistent_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except Exception as e:
            await printr.print_async(
                f"[HUD] Failed to load state: {e}",
                color=LogType.ERROR,
                server_only=True
            )
            return

        now = time.time()
        for title, item in saved.items():
            # Skip expired items
            if item.get('expiry') and now > item['expiry']:
                continue

            if item.get('is_progress'):
                if item.get('is_timer'):
                    # Handle timer restoration
                    elapsed = now - item.get('timer_start', item['added_at'])
                    remaining = item['timer_duration'] - elapsed

                    if remaining > 0 or not item.get('auto_close', True):
                        self._persistent_items[title] = item
                        self._send_command_sync(
                            self._client.show_timer(
                                group_name=self._group_name,
                                element=WindowType.PERSISTENT,
                                title=title,
                                duration=item['timer_duration'],
                                description=item.get('description', ''),
                                color=item.get('color'),
                                auto_close=item.get('auto_close', True),
                                initial_progress=elapsed
                            )
                        )
                else:
                    # Regular progress bar
                    self._persistent_items[title] = item
                    self._send_command_sync(
                        self._client.show_progress(
                            group_name=self._group_name,
                            element=WindowType.PERSISTENT,
                            title=title,
                            current=item.get('current', 0),
                            maximum=item.get('maximum', 100),
                            description=item.get('description', ''),
                            color=item.get('color'),
                            auto_close=item.get('auto_close', False)
                        )
                    )
            else:
                # Info panel
                remaining_duration = None
                if item.get('duration'):
                    remaining_duration = item['duration'] - (now - item['added_at'])
                    if remaining_duration <= 0:
                        continue

                self._persistent_items[title] = item
                self._send_command_sync(
                    self._client.add_item(
                        group_name=self._group_name,
                        element=WindowType.PERSISTENT,
                        title=title,
                        description=item.get('description', ''),
                        duration=remaining_duration
                    )
                )

    # ─────────────────────────────── Event Hooks ─────────────────────────────── #

    async def on_add_user_message(self, message: str) -> None:
        """Handle user message - display on HUD."""
        if not self._get_prop("show_chat_messages", True):
            return

        # Use accent color for user messages (user_color was unused)
        accent_color = str(self._get_prop("accent_color", "#00aaff"))
        await self._show_message("USER", message, accent_color)

        await self._show_loader(True, accent_color)

    async def on_add_assistant_message(self, message: str, tool_calls: list) -> None:
        """Handle assistant message - display on HUD with tool info."""
        if not self._get_prop("show_chat_messages", True):
            return

        accent_color = str(self._get_prop("accent_color", "#00aaff"))
        display_tool_names = bool(self._get_prop("display_tool_names", False))
        is_processing = bool(tool_calls)

        await self._show_loader(is_processing, accent_color)

        # Build tool info
        tools_data = []
        if tool_calls:
            for tc in tool_calls:
                tool_name = tc.function.name
                source = "System"
                source_type = "system"
                icon_path = None

                # Check if skill
                if self.wingman.tool_skills and tool_name in self.wingman.tool_skills:
                    skill = self.wingman.tool_skills[tool_name]
                    source = skill.name
                    source_type = "skill"
                    try:
                        skill_file = inspect.getfile(skill.__class__)
                        skill_dir = os.path.dirname(skill_file)
                        logo_path = os.path.join(skill_dir, "logo.png")
                        if os.path.exists(logo_path):
                            icon_path = logo_path
                    except Exception:
                        pass

                # Check if MCP tool
                elif (self.wingman.mcp_registry and
                      hasattr(self.wingman.mcp_registry, '_tool_to_server')):
                    server_name = self.wingman.mcp_registry._tool_to_server.get(tool_name)
                    if server_name:
                        if (hasattr(self.wingman.mcp_registry, '_manifests') and
                            server_name in self.wingman.mcp_registry._manifests):
                            source = self.wingman.mcp_registry._manifests[server_name].display_name
                        else:
                            source = server_name
                        source_type = "mcp"

                # Use tool name if configured
                if display_tool_names:
                    source = tool_name

                tools_data.append({
                    'name': tool_name,
                    'source': source,
                    'type': source_type,
                    'icon': icon_path
                })

        if message:
            self.expecting_audio = True
            self.audio_expect_start_time = time.time()
            await self._show_message(
                self.wingman.name,
                message,
                accent_color,
                tools=tools_data
            )
        elif tool_calls and tools_data:
            await self._show_message(self.wingman.name, "", accent_color, tools=tools_data)
        else:
            await self._hide_message()

    # ─────────────────────────────── Tool Methods ─────────────────────────────── #

    @tool()
    async def hud_add_info(
        self,
        title: str,
        description_markdown: str,
        duration: Optional[float] = None
    ) -> str:
        """
        Add or update a persistent information panel on the HUD overlay.
        Use Markdown formatting for better readability.

        :param title: Unique identifier and display title for this info panel.
        :param description_markdown: Content to display (Markdown supported).
        :param duration: Auto-remove after this many seconds. If not set, stays until removed.
        """
        if not await self._ensure_connected():
            return "HUD server is not available."

        valid_duration = duration if duration and duration > 0 else None

        self._persistent_items[title] = {
            'description': description_markdown,
            'duration': valid_duration,
            'added_at': time.time(),
            'expiry': time.time() + valid_duration if valid_duration else None
        }

        self._send_command_sync(
                self._client.add_item(
                    group_name=self._group_name,
                    element=WindowType.PERSISTENT,
                    title=title,
                    description=description_markdown,
                    duration=valid_duration
                )
            )

        self._save_persistent_items()
        return f"Added/Updated info panel: {title}"

    @tool()
    async def hud_remove_info(self, title: str) -> str:
        """
        Remove a persistent information panel from the HUD.

        :param title: The title of the info panel to remove.
        """
        if not await self._ensure_connected():
            return "HUD server is not available."

        self._persistent_items.pop(title, None)

        self._send_command_sync(
            self._client.remove_item(group_name=self._group_name, element=WindowType.PERSISTENT, title=title)
        )

        self._save_persistent_items()
        return f"Removed info panel: {title}"

    @tool()
    async def hud_list_info(self) -> str:
        """
        List all currently visible information panels on the HUD.
        Returns JSON with all active panels.
        """
        now = time.time()
        active_items = []
        expired_keys = []

        for title, info in self._persistent_items.items():
            if info.get('expiry') and now > info['expiry']:
                expired_keys.append(title)
                continue

            active_items.append({
                'title': title,
                'description': info.get('description', ''),
                'expires_in_seconds': (
                    int(info['expiry'] - now) if info.get('expiry') else None
                )
            })

        for k in expired_keys:
            del self._persistent_items[k]

        self._save_persistent_items()

        if not active_items:
            return "No information panels currently displayed."

        return json.dumps(active_items, indent=2)

    @tool()
    async def hud_clear_all(self, save: bool = True) -> str:
        """
        Remove all information panels and progress bars from the HUD.
        """
        if not await self._ensure_connected():
            return "HUD server is not available."

        # Create a copy of keys to iterate because we will modify the dict
        items_to_remove = list(self._persistent_items.keys())
        cleared_count = len(items_to_remove)

        for title in items_to_remove:
            self._persistent_items.pop(title, None)
            if self._client:
                self._send_command_sync(
                    self._client.remove_item(group_name=self._group_name, element=WindowType.PERSISTENT, title=title)
                )

        if save:
            self._save_persistent_items()

        return f"Cleared {cleared_count} item(s) from HUD."

    @tool()
    async def hud_show_progress(
        self,
        title: str,
        current: float,
        maximum: float,
        description_markdown: Optional[str] = None,
        auto_close: bool = False,
        color: Optional[str] = None
    ) -> str:
        """
        Show or update a progress bar on the HUD.

        :param title: Unique identifier and title for this progress bar.
        :param current: Current progress value.
        :param maximum: Maximum value (100% when current equals maximum).
        :param description_markdown: Optional description below the progress bar.
        :param auto_close: If True, removes the bar when reaching 100%.
        :param color: Optional color for the progress bar (hex color like #00ff00).
        """
        if not await self._ensure_connected():
            return "HUD server is not available."

        if maximum <= 0:
            maximum = 100

        percentage = min(100.0, max(0.0, (current / maximum) * 100))

        self._persistent_items[title] = {
            'description': description_markdown or '',
            'added_at': time.time(),
            'is_progress': True,
            'current': current,
            'maximum': maximum,
            'auto_close': auto_close,
            'color': color
        }

        if self._client:
            self._send_command_sync(
                self._client.show_progress(
                    group_name=self._group_name,
                    element=WindowType.PERSISTENT,
                    title=title,
                    current=current,
                    maximum=maximum,
                    description=description_markdown or '',
                    color=color,
                    auto_close=auto_close
                )
            )

        self._save_persistent_items()
        return f"Progress '{title}': {percentage:.1f}%"

    @tool()
    async def hud_show_timer(
        self,
        title: str,
        duration_seconds: float,
        description_markdown: Optional[str] = None,
        auto_close: bool = True,
        color: Optional[str] = None
    ) -> str:
        """
        Show a countdown timer that fills a progress bar over the specified duration.

        :param title: Unique identifier and title for this timer.
        :param duration_seconds: Time in seconds until the progress bar reaches 100%.
        :param description_markdown: Optional description below the timer.
        :param auto_close: If True (default), removes the timer after completion.
        :param color: Optional color for the timer bar (hex color like #00ff00).
        """
        if not await self._ensure_connected():
            return "HUD server is not available."

        if duration_seconds <= 0:
            duration_seconds = 1

        now = time.time()

        self._persistent_items[title] = {
            'description': description_markdown or '',
            'added_at': now,
            'is_progress': True,
            'is_timer': True,
            'timer_start': now,
            'timer_duration': duration_seconds,
            'auto_close': auto_close,
            'color': color
        }

        if self._client:
            self._send_command_sync(
                self._client.show_timer(
                    group_name=self._group_name,
                    element=WindowType.PERSISTENT,
                    title=title,
                    duration=duration_seconds,
                    description=description_markdown or '',
                    color=color,
                    auto_close=auto_close
                )
            )

        self._save_persistent_items()
        return f"Timer '{title}' started: {duration_seconds:.1f}s"

    @tool()
    async def hud_update_progress(
        self,
        title: str,
        current: float,
        maximum: Optional[float] = None,
        description_markdown: Optional[str] = None
    ) -> str:
        """
        Update an existing progress bar's values.

        :param title: The title of the progress bar to update.
        :param current: The new current value.
        :param maximum: Optional new maximum value.
        :param description_markdown: Optional new description.
        """
        if not await self._ensure_connected():
            return "HUD server is not available."

        if title not in self._persistent_items:
            return f"Progress '{title}' not found. Use hud_show_progress first."

        item = self._persistent_items[title]
        if not item.get('is_progress'):
            return f"'{title}' is not a progress bar."

        if item.get('is_timer'):
            return f"'{title}' is a timer. Timers cannot be updated manually."

        if maximum is not None and maximum > 0:
            item['maximum'] = maximum
        else:
            maximum = item.get('maximum', 100)

        item['current'] = current
        if description_markdown is not None:
            item['description'] = description_markdown

        percentage = min(100.0, max(0.0, (current / maximum) * 100))

        if self._client:
            self._send_command_sync(
                self._client.show_progress(
                    group_name=self._group_name,
                    element=WindowType.PERSISTENT,
                    title=title,
                    current=current,
                    maximum=maximum,
                    description=description_markdown or item.get('description', ''),
                    color=item.get('color')
                )
            )

        self._save_persistent_items()
        return f"Updated progress '{title}': {percentage:.1f}%"

    @tool()
    async def hud_update_info(
        self,
        title: str,
        description_markdown: str,
        duration: Optional[float] = None
    ) -> str:
        """
        Update an existing information panel's content.

        :param title: The title of the info panel to update.
        :param description_markdown: The new content (Markdown supported).
        :param duration: Optional new auto-remove timer in seconds.
        """
        if not await self._ensure_connected():
            return "HUD server is not available."

        if title not in self._persistent_items:
            return f"Info '{title}' not found. Use hud_add_info first."

        item = self._persistent_items[title]
        item['description'] = description_markdown

        send_duration = None
        if duration is not None:
            if duration > 0:
                item['duration'] = duration
                item['expiry'] = time.time() + duration
                send_duration = duration
            else:
                item['duration'] = None
                item['expiry'] = None

        if self._client:
            self._send_command_sync(
                self._client.update_item(
                    group_name=self._group_name,
                    element=WindowType.PERSISTENT,
                    title=title,
                    description=description_markdown,
                    duration=send_duration
                )
            )

        self._save_persistent_items()
        return f"Updated info panel: {title}"

    @tool()
    async def hud_hide(self) -> str:
        """
        Hide the HUD elements (message window and persistent info panel).

        The HUD elements will no longer be displayed but will still receive updates
        and perform all logic (timers, auto-hide, item updates) in the background.
        Use hud_show to display them again.
        """
        if not await self._ensure_connected():
            return "HUD server is not available."

        self._send_command_sync(
            self._client.hide_element(
                group_name=self._group_name,
                element=WindowType.PERSISTENT
            )
        )
        self._send_command_sync(
            self._client.hide_element(
                group_name=self._group_name,
                element=WindowType.MESSAGE
            )
        )

        return "HUD is now hidden."

    @tool()
    async def hud_show(self) -> str:
        """
        Show the HUD elements (message window and persistent info panel).

        The HUD elements will continue to receive updates and perform all logic,
        and will now be displayed again.
        """
        if self._client:
            self._send_command_sync(
                self._client.show_element(
                    group_name=self._group_name,
                    element=WindowType.PERSISTENT
                )
            )
            self._send_command_sync(
                self._client.show_element(
                    group_name=self._group_name,
                    element=WindowType.MESSAGE
                )
            )

        return "HUD is now visible."
