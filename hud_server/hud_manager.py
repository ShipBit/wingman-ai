"""
HUD Manager - State management for HUD groups.

Manages the state of all HUD groups, supporting:
- Multiple independent groups
- State persistence for client-side restore
- Thread-safe operations
"""

import threading
import time
import uuid
from typing import Any, Optional
from dataclasses import asdict, dataclass, field

from api.enums import LogType
from services.printr import Printr

printr = Printr()


@dataclass
class HudMessage:
    """A message displayed in a HUD group."""
    title: str
    content: str
    color: Optional[str] = None
    tools: list[dict[str, Any]] = field(default_factory=list)
    props: Optional[dict[str, Any]] = None
    timestamp: float = field(default_factory=time.time)
    duration: Optional[float] = None
    title_icon: Optional[str] = None
    """Local file path to an icon shown in front of the title (e.g. a wingman avatar)."""


@dataclass
class HudItem:
    """A persistent item in a HUD group."""
    title: str
    description: str = ""
    color: Optional[str] = None
    duration: Optional[float] = None
    added_at: float = field(default_factory=time.time)
    added_by: Optional[str] = None
    """Who put it there, e.g. a Wingman's name, so others know it is not theirs."""

    # Progress bar support
    is_progress: bool = False
    progress_current: float = 0
    progress_maximum: float = 100
    progress_color: Optional[str] = None

    # Timer support
    is_timer: bool = False
    timer_duration: float = 0
    timer_start: float = 0
    auto_close: bool = True


@dataclass
class ChatMessage:
    """A chat message."""
    sender: str
    text: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    color: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    icon: Optional[str] = None
    """Path of the sender's picture, shown round next to the message."""
    own: bool = False
    """Written by the user: a bubble on the right, like in a messenger."""
    tools: list = field(default_factory=list)
    """Tool chips under the message, as with show_message."""


@dataclass
class GroupState:
    """State of a HUD group."""
    props: dict[str, Any] = field(default_factory=dict)
    current_message: Optional[HudMessage] = None
    items: dict[str, HudItem] = field(default_factory=dict)
    chat_messages: list[ChatMessage] = field(default_factory=list)



class HudManager:
    """
    Manages all HUD groups and their state.

    Thread-safe for concurrent access from multiple clients.
    Supports callbacks for real-time overlay integration.
    """

    def __init__(self):
        self._groups: dict[str, GroupState] = {}
        self._lock = threading.RLock()
        self._command_callbacks: list = []  # Callbacks for overlay integration
        # Values a call leaves out: "props" for every group, "groups" per group name
        self._defaults: dict[str, Any] = {"props": {}, "groups": {}}
        # Preview of the shared containers: {"containers": {...}, "interactive": bool}
        self._preview: Optional[dict[str, Any]] = None

    def register_command_callback(self, callback) -> None:
        """
        Register a callback to receive commands for overlay rendering.

        Args:
            callback: Callable that accepts a dict command parameter
        """
        with self._lock:
            if callback not in self._command_callbacks:
                self._command_callbacks.append(callback)

    def unregister_command_callback(self, callback) -> None:
        """
        Unregister a command callback.

        Args:
            callback: Previously registered callback to remove
        """
        with self._lock:
            if callback in self._command_callbacks:
                self._command_callbacks.remove(callback)

    def _notify_callbacks(self, command: dict[str, Any]) -> None:
        """Notify all registered callbacks of a command."""
        for i, callback in enumerate(self._command_callbacks):
            try:
                callback(command)
            except Exception as e:
                printr.print(
                    f"[HUD Manager] Callback {i} failed for command '{command.get('type', 'unknown')}': "
                    f"{type(e).__name__}: {e}",
                    color=LogType.ERROR,
                    server_only=True
                )

    # ─────────────────────────────── Defaults ─────────────────────────────── #

    def set_defaults(
        self,
        props: Optional[dict[str, Any]] = None,
        groups: Optional[dict[str, dict[str, Any]]] = None,
    ) -> None:
        """Replace the defaults. Existing windows pick them up immediately.

        Resolution order for every window: the overlay's built-in values, then
        `props`, then `groups[group_name]`, then the group's own props, then the
        props of the call itself.
        """
        with self._lock:
            self._defaults = {
                "props": dict(props or {}),
                "groups": {name: dict(p) for name, p in (groups or {}).items()},
            }
            self._notify_callbacks({"type": "set_defaults", **self.get_defaults()})

    def get_defaults(self) -> dict[str, Any]:
        with self._lock:
            return {
                "props": dict(self._defaults["props"]),
                "groups": {name: dict(p) for name, p in self._defaults["groups"].items()},
            }

    # ─────────────────────────────── Preview ─────────────────────────────── #

    def set_preview(self, containers: dict[str, dict[str, Any]], interactive: bool = False) -> None:
        """Show (or update) the preview of the chat and info containers.

        `containers` maps "chat" and/or "info" to fully resolved props; the
        preview always fills the whole area (x, y, width, max_height).
        """
        with self._lock:
            self._preview = {
                "containers": {name: dict(p) for name, p in containers.items()},
                "interactive": bool(interactive),
            }
            self._notify_callbacks({"type": "set_preview", **self.get_preview()})

    def clear_preview(self) -> None:
        with self._lock:
            if self._preview is None:
                return
            self._preview = None
            self._notify_callbacks({"type": "clear_preview"})

    def get_preview(self) -> Optional[dict[str, Any]]:
        with self._lock:
            if self._preview is None:
                return None
            return {
                "containers": {name: dict(p) for name, p in self._preview["containers"].items()},
                "interactive": self._preview["interactive"],
            }

    def preview_moved(self, container: str, x1: int, y1: int, x2: int, y2: int) -> None:
        """The overlay moved or resized a preview container with the mouse."""
        with self._lock:
            if self._preview is None or container not in self._preview["containers"]:
                return
            self._preview["containers"][container].update(
                {"x": x1, "y": y1, "width": x2 - x1, "max_height": y2 - y1}
            )

    # ─────────────────────────────── Group Management ─────────────────────────────── #

    def _make_key(self, group_name: str, element: str) -> str:
        """Create internal key from group_name and element."""
        return f"{element}_{group_name}"

    def create_group(self, group_name: str, element: str, props: Optional[dict[str, Any]] = None) -> bool:
        """Create or update a HUD group."""
        key = self._make_key(group_name, element)
        with self._lock:
            if key not in self._groups:
                self._groups[key] = GroupState()

            if props:
                self._groups[key].props.update(props)

            self._notify_callbacks({
                "type": "create_group",
                "group": group_name,
                "element": element,
                "props": props or {}
            })

            return True

    def update_group(self, group_name: str, element: str, props: dict[str, Any]) -> bool:
        """Update properties of an existing group."""
        key = self._make_key(group_name, element)
        with self._lock:
            if key not in self._groups:
                return False

            self._groups[key].props.update(props)

            self._notify_callbacks({
                "type": "update_group",
                "group": group_name,
                "element": element,
                "props": props
            })

            return True

    def delete_group(self, group_name: str, element: str) -> bool:
        """Delete a HUD group."""
        key = self._make_key(group_name, element)
        with self._lock:
            if key in self._groups:
                del self._groups[key]

                self._notify_callbacks({
                    "type": "delete_group",
                    "group": group_name,
                    "element": element,
                })

                return True
            return False

    def get_groups(self) -> list[str]:
        """Get list of all group names."""
        with self._lock:
            return list(self._groups.keys())

    # ─────────────────────────────── Messages ─────────────────────────────── #

    def show_message(
        self,
        group_name: str,
        element: str,
        title: str,
        content: str,
        color: Optional[str] = None,
        tools: Optional[list[dict]] = None,
        props: Optional[dict[str, Any]] = None,
        duration: Optional[float] = None,
        title_icon: Optional[str] = None
    ) -> bool:
        """Show a message in a group."""
        key = self._make_key(group_name, element)
        with self._lock:
            if key not in self._groups:
                self.create_group(group_name, element)

            self._groups[key].current_message = HudMessage(
                title=title,
                content=content,
                color=color,
                tools=tools or [],
                props=props,
                duration=duration,
                title_icon=title_icon
            )

            # Build props dict for overlay
            overlay_props = dict(self._groups[key].props)
            if props:
                overlay_props.update(props)
            if duration is not None:
                overlay_props["duration"] = duration

            self._notify_callbacks({
                "type": "show_message",
                "group": group_name,
                "title": title,
                "content": content,
                "color": color,
                "tools": tools,
                "props": overlay_props,
                "title_icon": title_icon,
            })

            return True

    def append_message(self, group_name: str, element: str, content: str) -> bool:
        """Append content to the current message (for streaming)."""
        key = self._make_key(group_name, element)
        with self._lock:
            if key not in self._groups:
                return False

            state = self._groups[key]
            if state.current_message:
                state.current_message.content += content

                # Re-send the full message for streaming
                overlay_props = dict(state.props)
                if state.current_message.props:
                    overlay_props.update(state.current_message.props)
                if state.current_message.duration is not None:
                    overlay_props["duration"] = state.current_message.duration

                self._notify_callbacks({
                    "type": "show_message",
                    "group": group_name,
                    "title": state.current_message.title,
                    "content": state.current_message.content,
                    "color": state.current_message.color,
                    "tools": state.current_message.tools,
                    "props": overlay_props,
                    "title_icon": state.current_message.title_icon,
                })

            return True

    def hide_message(self, group_name: str, element: str) -> bool:
        """Hide/fade out the current message."""
        key = self._make_key(group_name, element)
        with self._lock:
            if key not in self._groups:
                return False

            self._groups[key].current_message = None

            self._notify_callbacks({
                "type": "hide_message",
                "group": group_name
            })

            return True

    # ─────────────────────────────── Loader ─────────────────────────────── #

    def set_loader(self, group_name: str, element: str, show: bool, color: Optional[str] = None) -> bool:
        """Show or hide the loader animation."""
        key = self._make_key(group_name, element)
        with self._lock:
            if key not in self._groups:
                self.create_group(group_name, element)

            self._notify_callbacks({
                "type": "set_loader",
                "group": group_name,
                "element": element,
                "show": show,
                "color": color
            })

            return True

    # ─────────────────────────────── Items ─────────────────────────────── #

    def add_item(
        self,
        group_name: str,
        element: str,
        title: str,
        description: str = "",
        color: Optional[str] = None,
        duration: Optional[float] = None,
        added_by: Optional[str] = None,
    ) -> bool:
        """Add a persistent item to a group."""
        key = self._make_key(group_name, element)
        with self._lock:
            if key not in self._groups:
                self.create_group(group_name, element)

            self._groups[key].items[title] = HudItem(
                title=title,
                description=description,
                color=color,
                duration=duration,
                added_by=added_by,
            )

            self._notify_callbacks({
                "type": "add_item",
                "group": group_name,
                "title": title,
                "description": description,
                "color": color,
                "duration": duration
            })

            return True

    def update_item(
        self,
        group_name: str,
        element: str,
        title: str,
        description: Optional[str] = None,
        color: Optional[str] = None,
        duration: Optional[float] = None
    ) -> bool:
        """Update an existing item."""
        key = self._make_key(group_name, element)
        with self._lock:
            if key not in self._groups:
                return False

            if title not in self._groups[key].items:
                return False

            item = self._groups[key].items[title]
            if description is not None:
                item.description = description
            if color is not None:
                item.color = color
            if duration is not None:
                item.duration = duration

            self._notify_callbacks({
                "type": "update_item",
                "group": group_name,
                "title": title,
                "description": description,
                "color": color,
                "duration": duration
            })

            return True

    def remove_item(self, group_name: str, element: str, title: str) -> bool:
        """Remove an item from a group."""
        key = self._make_key(group_name, element)
        with self._lock:
            if key not in self._groups:
                return False

            if title in self._groups[key].items:
                del self._groups[key].items[title]

                self._notify_callbacks({
                    "type": "remove_item",
                    "group": group_name,
                    "title": title
                })

                return True
            return False

    # The overlay removes a finished auto-closing timer or progress bar this long after
    AUTO_CLOSE_DELAY = 2.0

    @classmethod
    def _gone(cls, item: HudItem, now: float) -> bool:
        """Off the screen already: expired, or a finished timer/bar that closes itself."""
        if item.duration and now > item.added_at + item.duration:
            return True
        if item.auto_close and item.is_timer:
            return now >= item.timer_start + item.timer_duration + cls.AUTO_CLOSE_DELAY
        if item.auto_close and item.is_progress:
            return item.progress_current >= item.progress_maximum
        return False

    def get_items(self, group_name: str, element: str) -> list[dict[str, Any]]:
        """The group's items as they are on screen, oldest first."""
        key = self._make_key(group_name, element)
        now = time.time()
        with self._lock:
            state = self._groups.get(key)
            if not state:
                return []
            for title in [t for t, item in state.items.items() if self._gone(item, now)]:
                del state.items[title]
            items = [asdict(item) for item in state.items.values()]
        return sorted(items, key=lambda i: i["added_at"])

    def clear_items(self, group_name: str, element: str) -> bool:
        """Clear all items from a group."""
        key = self._make_key(group_name, element)
        with self._lock:
            if key not in self._groups:
                return False

            self._groups[key].items.clear()

            self._notify_callbacks({
                "type": "clear_items",
                "group": group_name
            })

            return True

    # ─────────────────────────────── Progress ─────────────────────────────── #

    def show_progress(
        self,
        group_name: str,
        element: str,
        title: str,
        current: float,
        maximum: float = 100,
        description: str = "",
        color: Optional[str] = None,
        auto_close: bool = False,
        added_by: Optional[str] = None,
    ) -> bool:
        """Show or update a progress bar."""
        key = self._make_key(group_name, element)
        with self._lock:
            if key not in self._groups:
                self.create_group(group_name, element)

            items = self._groups[key].items
            if title in items:
                item = items[title]
                item.progress_current = current
                item.progress_maximum = maximum
                if description:
                    item.description = description
                if color:
                    item.progress_color = color
                if added_by:
                    item.added_by = added_by
            else:
                items[title] = HudItem(
                    title=title,
                    description=description,
                    is_progress=True,
                    progress_current=current,
                    progress_maximum=maximum,
                    progress_color=color,
                    auto_close=auto_close,
                    added_by=added_by,
                )

            self._notify_callbacks({
                "type": "show_progress",
                "group": group_name,
                "title": title,
                "current": current,
                "maximum": maximum,
                "description": description,
                "color": color,
                "auto_close": auto_close
            })

            return True

    def show_timer(
        self,
        group_name: str,
        element: str,
        title: str,
        duration: float,
        description: str = "",
        color: Optional[str] = None,
        auto_close: bool = True,
        initial_progress: float = 0,
        added_by: Optional[str] = None,
    ) -> bool:
        """Show a timer-based progress bar."""
        key = self._make_key(group_name, element)
        with self._lock:
            if key not in self._groups:
                self.create_group(group_name, element)

            now = time.time()
            self._groups[key].items[title] = HudItem(
                title=title,
                description=description,
                is_progress=True,
                is_timer=True,
                timer_duration=duration,
                timer_start=now - initial_progress,  # Adjust for initial progress
                progress_current=initial_progress,
                progress_maximum=duration,
                progress_color=color,
                auto_close=auto_close,
                added_by=added_by,
            )

            self._notify_callbacks({
                "type": "show_timer",
                "group": group_name,
                "title": title,
                "duration": duration,
                "description": description,
                "color": color,
                "auto_close": auto_close,
                "initial_progress": initial_progress
            })

            return True

    # ─────────────────────────────── Chat Window ─────────────────────────────── #

    def send_chat_message(
        self,
        group_name: str,
        element: str,
        sender: str,
        text: str,
        color: Optional[str] = None,
        icon: Optional[str] = None,
        own: bool = False,
        tools: Optional[list] = None,
        restored: bool = False,
    ) -> Optional[str]:
        """Send a message to a chat window.

        Returns the message ID if successful, None if the window was not found.
        Every message is an entry of its own, except tool calls without text:
        they join the sender's last entry, under what it said before calling
        them, and that entry's ID is returned. A `restored` message (history put
        back) is never merged, does not type itself out and leaves the window
        hidden until the next message.
        """
        key = self._make_key(group_name, element)
        with self._lock:
            if key not in self._groups:
                return None

            state = self._groups[key]

            # Tool calls without text join the sender's last entry; anything
            # said is an entry of its own, the user's lines as much as a Wingman's
            last = state.chat_messages[-1] if state.chat_messages else None
            if (
                not restored and not text and tools and last
                and last.sender == sender and last.own == own
            ):
                last.tools.extend(tools)
                last.icon = icon or last.icon
                message_id = last.id
            else:
                msg = ChatMessage(
                    sender=sender,
                    text=text,
                    color=color,
                    icon=icon,
                    own=own,
                    tools=list(tools or []),
                )
                state.chat_messages.append(msg)
                message_id = msg.id

            # Limit chat history
            max_messages = state.props.get("max_messages", 50)
            if len(state.chat_messages) > max_messages:
                state.chat_messages = state.chat_messages[-max_messages:]

            self._notify_callbacks({
                "type": "chat_message",
                "group": group_name,
                "element": element,
                "id": message_id,
                "sender": sender,
                "text": text,
                "color": color,
                "icon": icon,
                "own": own,
                "tools": list(tools or []),
                "restored": restored,
            })

            return message_id

    def get_chat_messages(self, group_name: str, element: str) -> list[dict[str, Any]]:
        """A chat window's messages, oldest first."""
        key = self._make_key(group_name, element)
        with self._lock:
            state = self._groups.get(key)
            return [asdict(message) for message in state.chat_messages] if state else []

    def update_chat_message(
        self,
        group_name: str,
        element: str,
        message_id: str,
        text: str
    ) -> bool:
        """Update an existing chat message's text content.

        Finds the message by ID in the specified chat window and replaces its text.
        Works for both current and past messages in the chat history.

        Returns True if the message was found and updated, False otherwise.
        """
        key = self._make_key(group_name, element)
        with self._lock:
            if key not in self._groups:
                return False

            state = self._groups[key]

            for msg in state.chat_messages:
                if msg.id == message_id:
                    msg.text = text
                    self._notify_callbacks({
                        "type": "update_chat_message",
                        "group": group_name,
                        "id": message_id,
                        "text": text
                    })
                    return True

            return False

    def clear_chat_window(self, group_name: str, element: str) -> bool:
        """Clear all messages from a chat window."""
        key = self._make_key(group_name, element)
        with self._lock:
            if key not in self._groups:
                return False

            self._groups[key].chat_messages.clear()

            self._notify_callbacks({
                "type": "clear_chat_window",
                "group": group_name
            })

            return True

    def show_chat_window(self, group_name: str, element: str) -> bool:
        """Show a hidden chat window."""
        key = self._make_key(group_name, element)
        with self._lock:
            if key not in self._groups:
                return False

            self._notify_callbacks({
                "type": "show_chat_window",
                "group": group_name
            })

            return True

    def hide_chat_window(self, group_name: str, element: str) -> bool:
        """Hide a chat window."""
        key = self._make_key(group_name, element)
        with self._lock:
            if key not in self._groups:
                return False

            self._notify_callbacks({
                "type": "hide_chat_window",
                "group": group_name
            })

            return True

    def show_element(self, group_name: str, element: str) -> bool:
        """Show a hidden HUD element.

        The element will continue to receive updates and perform all logic,
        but will now be displayed again.

        Args:
            group_name: Name of the HUD group
            element: Element type - "message", "persistent", or "chat"

        Returns:
            True if successful, False if group not found
        """
        key = self._make_key(group_name, element)
        with self._lock:
            if key not in self._groups:
                return False

            self._notify_callbacks({
                "type": "show_element",
                "group": group_name,
                "element": element
            })

            return True

    def hide_element(self, group_name: str, element: str) -> bool:
        """Hide a HUD element.

        The element will no longer be displayed but will still receive updates
        and perform all logic (timers, auto-hide, updates) in the background.

        Args:
            group_name: Name of the HUD group
            element: Element type - "message", "persistent", or "chat"

        Returns:
            True if successful, False if group not found
        """
        key = self._make_key(group_name, element)
        with self._lock:
            if key not in self._groups:
                return False

            self._notify_callbacks({
                "type": "hide_element",
                "group": group_name,
                "element": element
            })

            return True
