"""The HUD as Core runs it: profiles, the shared chat and info containers, and
the preview.

The HUD server (hud_server/) draws whatever it is told. This service decides
what that is:

- which HUD profile applies (the one naming the loaded config, otherwise the
  default) and hands its style and areas to the server as defaults,
- the conversation in the shared chat container, hidden again after the
  Wingman finished speaking,
- the shared info panel, kept across restarts when the profile says so,
- the preview of a profile's containers, which the mouse can move and resize.

Core runs the HUD server in its own process, so this talks to its HudManager
directly instead of over HTTP. Other programs keep using the HTTP API.
"""

import asyncio
import json
import os
import time
from os import path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional

import yaml
from fastapi import APIRouter, HTTPException

from api.enums import LogType
from api.interface import (
    CreateHudProfileRequest,
    HudProfile,
    HudProfilePreviewRequest,
    HudProfilesState,
)
from hud_server.constants import GROUP_CHAT, GROUP_INFO
from services import hud_profiles
from services.file import get_users_dir
from services.printr import Printr

if TYPE_CHECKING:
    from hud_server.hud_manager import HudManager
    from hud_server.server import HudServer
    from services.config_manager import ConfigManager
    from services.config_service import ConfigService
    from wingmen.wingman import Wingman

MESSAGE = "message"
PERSISTENT = "persistent"

# The chat container hides itself after this long even if no playback event
# arrives (a crashed TTS, a missed event). Core hides it much earlier normally.
CHAT_SAFETY_SECONDS = 600.0
# Without a reply, a user message and its loader go away after this long.
USER_MESSAGE_SECONDS = 60.0

INFO_FILE = "info_panel.json"


class HudService:
    """Process-wide singleton (house pattern, like Printr/ScGameLogService)."""

    _instance: "HudService | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        self.printr = Printr()
        self.config_manager: Optional["ConfigManager"] = None
        self.config_service: Optional["ConfigService"] = None
        self.broadcast_state: Optional[Callable[[HudProfilesState], Awaitable[None]]] = None
        """Set by WingmanCore: tells an open settings page about every change."""
        self.run_on_main_loop: Optional[Callable[[Awaitable], None]] = None
        """Set by WingmanCore: overlay events arrive on the overlay thread."""

        self._server: Optional["HudServer"] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        """Core's loop. Chat state and its timers live there; skills call from their own."""
        self._preview_profile_id: Optional[str] = None

        # Chat container: who wrote the message on it, and when it goes away
        self._chat_owner: Optional[str] = None
        self._chat_token = 0
        self._chat_waiting_for_audio = False
        self._chat_hide: Optional[asyncio.TimerHandle] = None
        self._chat_last: Optional[dict] = None
        self._chat_hidden_early = False

        self.router = APIRouter()
        tags = ["hud"]
        self.router.add_api_route(
            methods=["GET"], path="/hud/profiles", endpoint=self.get_hud_profiles,
            response_model=HudProfilesState, tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"], path="/hud/profiles", endpoint=self.create_hud_profile,
            response_model=HudProfilesState, tags=tags,
        )
        self.router.add_api_route(
            methods=["PUT"], path="/hud/profiles/{profile_id}", endpoint=self.update_hud_profile,
            response_model=HudProfilesState, tags=tags,
        )
        self.router.add_api_route(
            methods=["DELETE"], path="/hud/profiles/{profile_id}", endpoint=self.delete_hud_profile,
            response_model=HudProfilesState, tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"], path="/hud/profiles/{profile_id}/default",
            endpoint=self.set_default_hud_profile, response_model=HudProfilesState, tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"], path="/hud/profiles/{profile_id}/preview",
            endpoint=self.set_hud_profile_preview, response_model=HudProfilesState, tags=tags,
        )

    def configure(self, config_manager: "ConfigManager", config_service: "ConfigService") -> None:
        self.config_manager = config_manager
        self.config_service = config_service
        config_service.config_events.subscribe("config_loaded", self._on_config_loaded)
        config_service.config_events.subscribe("config_renamed", self._on_config_renamed)
        config_service.config_events.subscribe("config_deleted", self._on_config_deleted)

    # ─────────────────────────────── state ─────────────────────────────── #

    @property
    def available(self) -> bool:
        """The HUD server runs: switched on in the settings, on an OS the HUD
        supports (hud_server.platform; Windows for now)."""
        return self._server is not None and self._server.is_running

    @property
    def _manager(self) -> Optional["HudManager"]:
        return self._server.manager if self.available else None

    @property
    def _profiles(self) -> list[HudProfile]:
        return self.config_manager.settings_config.hud_profiles

    def _current_config_name(self) -> Optional[str]:
        config_dir = getattr(self.config_service, "current_config_dir", None)
        return getattr(config_dir, "name", None)

    def active_profile(self) -> Optional[HudProfile]:
        """The profile the loaded config uses."""
        if self.config_manager is None:
            return None
        return hud_profiles.active_profile(self._profiles, self._current_config_name())

    def state(self) -> HudProfilesState:
        active = self.active_profile()
        return HudProfilesState(
            profiles=self._profiles,
            active_profile_id=active.id if active else None,
            preview_profile_id=self._preview_profile_id,
            hud_available=self.available,
        )

    async def _changed(self, save: bool = True, apply: bool = True) -> HudProfilesState:
        """After every profile change: save, show it on the HUD, tell the client."""
        hud_profiles.normalize(self._profiles)
        if save:
            self.config_manager.save_settings_config()
        if apply:
            self._apply_active_profile()
        self._refresh_preview()
        state = self.state()
        if self.broadcast_state:
            await self.broadcast_state(state)
        return state

    # ─────────────────────────────── API ─────────────────────────────── #

    # GET /hud/profiles
    async def get_hud_profiles(self) -> HudProfilesState:
        return self.state()

    # POST /hud/profiles
    async def create_hud_profile(self, request: CreateHudProfileRequest) -> HudProfilesState:
        source = self._template_profile()
        if request.copy_from:
            source = self._find(request.copy_from)
        self._profiles.append(hud_profiles.new_profile(request.name.strip() or "HUD profile", source))
        return await self._changed()

    # PUT /hud/profiles/{profile_id}
    async def update_hud_profile(self, profile_id: str, profile: HudProfile) -> HudProfilesState:
        stored = self._find(profile_id)
        index = self._profiles.index(stored)
        # The default flag has its own endpoint; a stale page must not move it
        updated = profile.model_copy(update={"id": stored.id, "is_default": stored.is_default})
        self._profiles[index] = updated
        hud_profiles.assign_configs(self._profiles, stored.id, updated.configs)
        return await self._changed()

    # DELETE /hud/profiles/{profile_id}
    async def delete_hud_profile(self, profile_id: str) -> HudProfilesState:
        self._find(profile_id)
        try:
            hud_profiles.delete_profile(self._profiles, profile_id)
        except hud_profiles.HudProfileError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        if self._preview_profile_id == profile_id:
            self._stop_preview()
        return await self._changed()

    # POST /hud/profiles/{profile_id}/default
    async def set_default_hud_profile(self, profile_id: str) -> HudProfilesState:
        self._find(profile_id)
        hud_profiles.normalize(self._profiles, default_id=profile_id)
        return await self._changed()

    # POST /hud/profiles/{profile_id}/preview
    async def set_hud_profile_preview(
        self, profile_id: str, request: HudProfilePreviewRequest
    ) -> HudProfilesState:
        self._find(profile_id)
        if request.enabled:
            # One preview at a time: this one replaces any other
            self._preview_profile_id = profile_id
            self._refresh_preview()
        elif self._preview_profile_id == profile_id:
            self._stop_preview()
        return await self._changed(save=False)

    def _find(self, profile_id: str) -> HudProfile:
        try:
            return hud_profiles.find_profile(self._profiles, profile_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"HUD profile '{profile_id}' not found")

    def _template_profile(self) -> HudProfile:
        """The profile shipped in templates/configs/settings.yaml."""
        template = path.join(self.config_manager.templates_dir, "configs", "settings.yaml")
        with open(template, "r", encoding="utf-8") as f:
            return HudProfile(**yaml.safe_load(f)["hud_profiles"][0])

    # ─────────────────────────────── configs ─────────────────────────────── #

    async def _on_config_loaded(self, _config_dir_info=None) -> None:
        self._apply_active_profile()
        if self.broadcast_state:
            await self.broadcast_state(self.state())

    async def _on_config_renamed(self, names: tuple[str, str]) -> None:
        old, _new = names
        if hud_profiles.rename_config(self._profiles, *names):
            # The loaded config is reloaded under its new name right after; until
            # then the old name finds no profile and would apply the default
            await self._changed(apply=old != self._current_config_name())

    async def _on_config_deleted(self, name: str) -> None:
        if hud_profiles.remove_config(self._profiles, name):
            await self._changed()

    # ─────────────────────────────── HUD server ─────────────────────────────── #

    async def attach_server(self, server: "HudServer") -> None:
        """The HUD server started: give it the profile and the shared containers."""
        self._server = server
        self._loop = asyncio.get_running_loop()
        server.add_event_listener(self._on_overlay_event)
        manager = server.manager
        self._apply_active_profile()
        manager.create_group(GROUP_CHAT, MESSAGE)
        manager.create_group(GROUP_INFO, PERSISTENT)
        profile = self.active_profile()
        if profile and profile.restore_info_items:
            self._restore_info_items()
        if self.broadcast_state:
            await self.broadcast_state(self.state())

    async def detach_server(self) -> None:
        """The HUD server is about to stop."""
        if self._server is None:
            return
        self._save_info_items()
        self._server.remove_event_listener(self._on_overlay_event)
        self._preview_profile_id = None
        self._cancel_chat_hide()
        self._server = None
        if self.broadcast_state:
            await self.broadcast_state(self.state())

    def _apply_active_profile(self) -> None:
        manager = self._manager
        profile = self.active_profile()
        if manager is None or profile is None:
            return
        props, groups = hud_profiles.hud_defaults(profile)
        manager.set_defaults(props, groups)

    # ─────────────────────────────── preview ─────────────────────────────── #

    def _refresh_preview(self) -> None:
        manager = self._manager
        if manager is None or self._preview_profile_id is None:
            return
        try:
            profile = hud_profiles.find_profile(self._profiles, self._preview_profile_id)
        except KeyError:
            self._stop_preview()
            return
        manager.set_preview(hud_profiles.preview_containers(profile), interactive=True)

    def _stop_preview(self) -> None:
        self._preview_profile_id = None
        if self._manager is not None:
            self._manager.clear_preview()

    def _on_overlay_event(self, event: dict) -> None:
        """From the overlay thread: a preview container was moved or resized."""
        if event.get("type") != "preview_changed" or self.run_on_main_loop is None:
            return
        self.run_on_main_loop(self._preview_moved(event))

    async def _preview_moved(self, event: dict) -> None:
        if self._preview_profile_id is None:
            return
        try:
            profile = hud_profiles.find_profile(self._profiles, self._preview_profile_id)
        except KeyError:
            return
        container = event["container"]
        if container not in ("chat", "info"):
            return
        area = hud_profiles.area_from_rect(
            getattr(profile, container), event["x1"], event["y1"], event["x2"], event["y2"]
        )
        setattr(profile, container, area)
        if event.get("final"):
            self.config_manager.save_settings_config()
            self._apply_active_profile()
        if self.broadcast_state:
            await self.broadcast_state(self.state())

    # ─────────────────────────────── chat ─────────────────────────────── #

    def _chat_on(self, wingman: "Wingman") -> bool:
        hud = getattr(wingman.config, "hud", None)
        return self.available and bool(hud and hud.chat)

    def _on_main_loop(self, fn: Callable, *args) -> None:
        """Run `fn` on Core's loop: skills add messages from their own threads."""
        loop = self._loop
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if loop is None or loop is running or loop.is_closed() or not loop.is_running():
            fn(*args)
        else:
            loop.call_soon_threadsafe(fn, *args)

    async def on_conversation_message(
        self, wingman: "Wingman", role: str, content: Any, tool_calls: Optional[list]
    ) -> None:
        """The conversation of a Wingman, shown in the shared chat container."""
        if not self._chat_on(wingman):
            return
        self._on_main_loop(self._show_conversation, wingman, role, content, tool_calls or [])

    def _show_conversation(
        self, wingman: "Wingman", role: str, content: Any, tool_calls: list
    ) -> None:
        if self._manager is None:
            return
        if role == "user":
            self._show_user_message(content)
        else:
            self._show_assistant_message(wingman, content, tool_calls)

    def _show_user_message(self, content: Any) -> None:
        text = content if isinstance(content, str) else ""
        if not text:
            return
        name = getattr(self.config_manager.settings_config, "user_name", None) or "User"
        self._chat_owner = None
        self._show_chat(name, text, icon=None, tools=[])
        self._manager.set_loader(GROUP_CHAT, MESSAGE, True)
        self._schedule_chat_hide(USER_MESSAGE_SECONDS)

    def _show_assistant_message(self, wingman: "Wingman", content: Any, tool_calls: list) -> None:
        profile = self.active_profile()
        text = content if isinstance(content, str) else ""
        tools = self._tool_chips(wingman, tool_calls, bool(profile and profile.display_tool_names))
        manager = self._manager
        manager.set_loader(GROUP_CHAT, MESSAGE, bool(tool_calls))

        if not text and not tools:
            self._hide_chat()
            return

        self._chat_owner = wingman.name
        self._show_chat(wingman.name, text, icon=wingman.get_avatar_path(), tools=tools)
        if text:
            # Stays while the Wingman speaks; goes if no speech starts in time
            self._chat_waiting_for_audio = True
            self._schedule_chat_hide(profile.max_display_time if profile else 5.0, early=True)
        else:
            self._schedule_chat_hide(USER_MESSAGE_SECONDS)

    def _show_chat(self, title: str, text: str, icon: Optional[str], tools: list) -> None:
        self._chat_token += 1
        self._chat_hidden_early = False
        self._chat_last = {"title": title, "text": text, "icon": icon, "tools": tools}
        self._manager.show_message(
            GROUP_CHAT, MESSAGE, title, text, tools=tools,
            duration=CHAT_SAFETY_SECONDS, title_icon=icon,
        )

    def _hide_chat(self) -> None:
        self._cancel_chat_hide()
        self._chat_waiting_for_audio = False
        if self._manager is not None:
            self._manager.hide_message(GROUP_CHAT, MESSAGE)

    def _schedule_chat_hide(self, delay: float, early: bool = False) -> None:
        self._cancel_chat_hide()
        token = self._chat_token

        def hide():
            if token != self._chat_token:
                return
            self._chat_hide = None
            self._chat_hidden_early = early
            if self._manager is not None:
                self._manager.hide_message(GROUP_CHAT, MESSAGE)

        try:
            self._chat_hide = asyncio.get_running_loop().call_later(max(0.0, delay), hide)
        except RuntimeError:
            self._chat_hide = None

    def _release_chat(self) -> None:
        self._cancel_chat_hide()
        self._chat_owner = None
        self._chat_last = None
        self._chat_waiting_for_audio = False
        self._chat_token += 1

    def _cancel_chat_hide(self) -> None:
        if self._chat_hide is not None:
            self._chat_hide.cancel()
            self._chat_hide = None

    def _speaks_on_screen(self, wingman_name: str) -> bool:
        """Playback of the Wingman whose answer the chat container shows. A
        message of tool chips only is not what is being spoken."""
        return (
            self.available
            and wingman_name == self._chat_owner
            and bool(self._chat_last and self._chat_last.get("text"))
        )

    def playback_started(self, wingman_name: str) -> None:
        """The message stays while its Wingman speaks."""
        self._on_main_loop(self._playback_started, wingman_name)

    def playback_finished(self, wingman_name: str) -> None:
        # Streaming TTS reports from the speaking thread's own loop, which closes
        # right after: a hide timer scheduled there never fires
        self._on_main_loop(self._playback_finished, wingman_name)

    def _playback_started(self, wingman_name: str) -> None:
        if not self._speaks_on_screen(wingman_name):
            return
        self._cancel_chat_hide()
        self._chat_waiting_for_audio = False
        if self._chat_hidden_early and self._chat_last:
            # Speech started after the wait ran out: bring the message back
            last = self._chat_last
            self._show_chat(last["title"], last["text"], last["icon"], last["tools"])

    def _playback_finished(self, wingman_name: str) -> None:
        if not self._speaks_on_screen(wingman_name):
            return
        if self._chat_waiting_for_audio:
            # An earlier line ended (a filler, the waiting response); the answer
            # on screen has not been spoken yet and keeps its own timer
            return
        profile = self.active_profile()
        self._schedule_chat_hide(profile.audio_stop_delay if profile else 1.0)

    @staticmethod
    def _tool_chips(wingman: "Wingman", tool_calls: list, use_tool_names: bool) -> list[dict]:
        """One chip per tool call: where the tool comes from, and its icon."""
        if not tool_calls:
            return []
        from wingmen.facade import SkillTools

        tools = SkillTools(wingman)
        try:
            mcp_names = {s["display_name"] for s in tools.servers()}
        except Exception:
            mcp_names = set()
        chips = []
        for call in tool_calls:
            function = call.get("function") if isinstance(call, dict) else getattr(call, "function", None)
            name = function.get("name") if isinstance(function, dict) else getattr(function, "name", None)
            if not name:
                continue
            source, source_type, icon = "System", "system", None
            try:
                origin = tools.source(name)
                if origin is not None:
                    source = origin
                    source_type = "mcp" if origin in mcp_names else "skill"
                    icon = tools.icon(name)
            except Exception:
                pass
            chips.append({
                "name": name,
                "source": name if use_tool_names else source,
                "type": source_type,
                "icon": icon,
            })
        return chips

    # ─────────────────────────────── drawing for skills and tools ─────────────────────────────── #

    def show_message(
        self, group: str, title: str, text: str, *, duration: float = 10.0,
        color: Optional[str] = None, icon: Optional[str] = None,
    ) -> bool:
        manager = self._manager
        if manager is None:
            return False
        if group == GROUP_CHAT:
            # A skill's line: it hides itself after `duration`, playback has no say
            self._on_main_loop(self._release_chat)
        return manager.show_message(
            group, MESSAGE, title, text, color=color, duration=duration, title_icon=icon
        )

    def hide_message(self, group: str) -> bool:
        manager = self._manager
        return bool(manager and manager.hide_message(group, MESSAGE))

    def add_info(
        self, group: str, title: str, text: str = "", *, color: Optional[str] = None,
        duration: Optional[float] = None, added_by: Optional[str] = None,
    ) -> bool:
        manager = self._manager
        if manager is None:
            return False
        manager.add_item(
            group, PERSISTENT, title, text, color=color, duration=duration, added_by=added_by
        )
        self._info_changed(group)
        return True

    def remove_info(self, group: str, title: str) -> bool:
        manager = self._manager
        if manager is None:
            return False
        removed = manager.remove_item(group, PERSISTENT, title)
        self._info_changed(group)
        return removed

    def show_progress(
        self, group: str, title: str, current: float, maximum: float = 100, *,
        text: str = "", color: Optional[str] = None, auto_close: bool = False,
        added_by: Optional[str] = None,
    ) -> bool:
        manager = self._manager
        if manager is None:
            return False
        manager.show_progress(
            group, PERSISTENT, title, current, maximum, description=text, color=color,
            auto_close=auto_close, added_by=added_by,
        )
        self._info_changed(group)
        return True

    def show_timer(
        self, group: str, title: str, seconds: float, *, text: str = "",
        color: Optional[str] = None, auto_close: bool = True, added_by: Optional[str] = None,
    ) -> bool:
        manager = self._manager
        if manager is None:
            return False
        manager.show_timer(
            group, PERSISTENT, title, seconds, description=text, color=color,
            auto_close=auto_close, added_by=added_by,
        )
        self._info_changed(group)
        return True

    def info_items(self, group: str = GROUP_INFO) -> list[dict]:
        """What the panel shows right now, oldest first."""
        manager = self._manager
        return manager.get_items(group, PERSISTENT) if manager is not None else []

    def create_group(self, group: str, element: str, props: Optional[dict] = None) -> bool:
        manager = self._manager
        return bool(manager and manager.create_group(group, element, props))

    def update_group(self, group: str, element: str, props: dict) -> bool:
        manager = self._manager
        if manager is None:
            return False
        manager.create_group(group, element)
        return manager.update_group(group, element, props)

    def delete_group(self, group: str, element: str) -> bool:
        manager = self._manager
        return bool(manager and manager.delete_group(group, element))

    # ─────────────────────────────── info panel across restarts ─────────────────────────────── #

    def _info_file(self) -> str:
        """Next to the version folders, so an update keeps the panels."""
        folder = path.join(get_users_dir(), "hud")
        os.makedirs(folder, exist_ok=True)
        return path.join(folder, INFO_FILE)

    def _info_changed(self, group: str) -> None:
        if group == GROUP_INFO:
            self._save_info_items()

    def _save_info_items(self) -> None:
        manager = self._manager
        if manager is None:
            return
        try:
            with open(self._info_file(), "w", encoding="utf-8") as f:
                json.dump(manager.get_items(GROUP_INFO, PERSISTENT), f, indent=2)
        except Exception as e:
            self.printr.print(f"[HUD] Could not save the info panel: {e}", color=LogType.WARNING, server_only=True)

    def _restore_info_items(self) -> None:
        manager = self._manager
        file = self._info_file()
        if manager is None or not path.exists(file):
            return
        try:
            with open(file, "r", encoding="utf-8") as f:
                items = json.load(f)
        except Exception as e:
            self.printr.print(f"[HUD] Could not read the saved info panel: {e}", color=LogType.WARNING, server_only=True)
            return

        now = time.time()
        for item in sorted(items, key=lambda i: i.get("added_at", 0)):
            title = item.get("title")
            if not title:
                continue
            description = item.get("description", "")
            if item.get("is_timer"):
                elapsed = now - item.get("timer_start", now)
                duration = float(item.get("timer_duration", 0))
                if elapsed < duration or not item.get("auto_close", True):
                    manager.show_timer(
                        GROUP_INFO, PERSISTENT, title, duration, description=description,
                        color=item.get("progress_color"), auto_close=item.get("auto_close", True),
                        initial_progress=min(elapsed, duration), added_by=item.get("added_by"),
                    )
            elif item.get("is_progress"):
                manager.show_progress(
                    GROUP_INFO, PERSISTENT, title, item.get("progress_current", 0),
                    item.get("progress_maximum", 100), description=description,
                    color=item.get("progress_color"), auto_close=item.get("auto_close", False),
                    added_by=item.get("added_by"),
                )
            else:
                remaining = None
                if item.get("duration"):
                    remaining = float(item["duration"]) - (now - item.get("added_at", now))
                    if remaining <= 0:
                        continue
                manager.add_item(
                    GROUP_INFO, PERSISTENT, title, description, color=item.get("color"),
                    duration=remaining, added_by=item.get("added_by"),
                )
