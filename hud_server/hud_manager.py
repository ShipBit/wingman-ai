"""
HUD Manager - State management for HUD groups.

Manages the state of all HUD groups, supporting:
- Multiple independent groups
- State persistence for client-side restore
- Thread-safe operations
"""

import threading
import time
from typing import Any, Optional
from dataclasses import dataclass, field

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


@dataclass
class HudItem:
    """A persistent item in a HUD group."""
    title: str
    description: str = ""
    color: Optional[str] = None
    duration: Optional[float] = None
    added_at: float = field(default_factory=time.time)

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
    color: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class GroupState:
    """State of a HUD group."""
    props: dict[str, Any] = field(default_factory=dict)
    current_message: Optional[HudMessage] = None
    items: dict[str, HudItem] = field(default_factory=dict)
    chat_messages: list[ChatMessage] = field(default_factory=list)
    loader_visible: bool = False
    loader_color: Optional[str] = None
    is_chat_window: bool = False
    visible: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert state to dictionary for persistence."""
        return {
            "props": self.props,
            "current_message": {
                "title": self.current_message.title,
                "content": self.current_message.content,
                "color": self.current_message.color,
                "tools": self.current_message.tools,
                "props": self.current_message.props,
                "timestamp": self.current_message.timestamp,
                "duration": self.current_message.duration,
            } if self.current_message else None,
            "items": {
                title: {
                    "title": item.title,
                    "description": item.description,
                    "color": item.color,
                    "duration": item.duration,
                    "added_at": item.added_at,
                    "is_progress": item.is_progress,
                    "progress_current": item.progress_current,
                    "progress_maximum": item.progress_maximum,
                    "progress_color": item.progress_color,
                    "is_timer": item.is_timer,
                    "timer_duration": item.timer_duration,
                    "timer_start": item.timer_start,
                    "auto_close": item.auto_close,
                }
                for title, item in self.items.items()
            },
            "chat_messages": [
                {
                    "sender": msg.sender,
                    "text": msg.text,
                    "color": msg.color,
                    "timestamp": msg.timestamp,
                }
                for msg in self.chat_messages
            ],
            "loader_visible": self.loader_visible,
            "loader_color": self.loader_color,
            "is_chat_window": self.is_chat_window,
            "visible": self.visible,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GroupState":
        """Create state from dictionary."""
        state = cls()
        state.props = data.get("props", {})
        state.loader_visible = data.get("loader_visible", False)
        state.loader_color = data.get("loader_color")
        state.is_chat_window = data.get("is_chat_window", False)
        state.visible = data.get("visible", True)

        # Restore current message
        msg_data = data.get("current_message")
        if msg_data:
            state.current_message = HudMessage(
                title=msg_data.get("title", ""),
                content=msg_data.get("content", ""),
                color=msg_data.get("color"),
                tools=msg_data.get("tools", []),
                props=msg_data.get("props"),
                timestamp=msg_data.get("timestamp", time.time()),
                duration=msg_data.get("duration"),
            )

        # Restore items
        for title, item_data in data.get("items", {}).items():
            state.items[title] = HudItem(
                title=item_data.get("title", title),
                description=item_data.get("description", ""),
                color=item_data.get("color"),
                duration=item_data.get("duration"),
                added_at=item_data.get("added_at", time.time()),
                is_progress=item_data.get("is_progress", False),
                progress_current=item_data.get("progress_current", 0),
                progress_maximum=item_data.get("progress_maximum", 100),
                progress_color=item_data.get("progress_color"),
                is_timer=item_data.get("is_timer", False),
                timer_duration=item_data.get("timer_duration", 0),
                timer_start=item_data.get("timer_start", 0),
                auto_close=item_data.get("auto_close", True),
            )

        # Restore chat messages
        for msg_data in data.get("chat_messages", []):
            state.chat_messages.append(ChatMessage(
                sender=msg_data.get("sender", ""),
                text=msg_data.get("text", ""),
                color=msg_data.get("color"),
                timestamp=msg_data.get("timestamp", time.time()),
            ))

        return state


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

    # ─────────────────────────────── Group Management ─────────────────────────────── #

    def create_group(self, group_name: str, props: Optional[dict[str, Any]] = None) -> bool:
        """Create or update a HUD group."""
        with self._lock:
            if group_name not in self._groups:
                self._groups[group_name] = GroupState()

            if props:
                self._groups[group_name].props.update(props)
                self._groups[group_name].is_chat_window = props.get("is_chat_window", False)

            self._notify_callbacks({
                "type": "create_group",
                "group": group_name,
                "props": props or {}
            })

            return True

    def update_group(self, group_name: str, props: dict[str, Any]) -> bool:
        """Update properties of an existing group."""
        with self._lock:
            if group_name not in self._groups:
                return False

            self._groups[group_name].props.update(props)

            self._notify_callbacks({
                "type": "update_group",
                "group": group_name,
                "props": props
            })

            return True

    def delete_group(self, group_name: str) -> bool:
        """Delete a HUD group."""
        with self._lock:
            if group_name in self._groups:
                del self._groups[group_name]

                self._notify_callbacks({
                    "type": "delete_group",
                    "group": group_name
                })

                return True
            return False

    def get_groups(self) -> list[str]:
        """Get list of all group names."""
        with self._lock:
            return list(self._groups.keys())

    def get_group_state(self, group_name: str) -> Optional[dict[str, Any]]:
        """Get the current state of a group for persistence."""
        with self._lock:
            if group_name in self._groups:
                return self._groups[group_name].to_dict()
            return None

    def restore_group_state(self, group_name: str, state: dict[str, Any]) -> bool:
        """Restore a group's state from a previous snapshot."""
        with self._lock:
            self._groups[group_name] = GroupState.from_dict(state)

            # Notify overlay to restore visuals
            self._notify_callbacks({
                "type": "restore_state",
                "group": group_name,
                "state": state
            })

            return True

    # ─────────────────────────────── Messages ─────────────────────────────── #

    def show_message(
        self,
        group_name: str,
        title: str,
        content: str,
        color: Optional[str] = None,
        tools: Optional[list[dict]] = None,
        props: Optional[dict[str, Any]] = None,
        duration: Optional[float] = None
    ) -> bool:
        """Show a message in a group."""
        with self._lock:
            if group_name not in self._groups:
                self.create_group(group_name)

            self._groups[group_name].current_message = HudMessage(
                title=title,
                content=content,
                color=color,
                tools=tools or [],
                props=props,
                duration=duration
            )

            # Build props dict for overlay
            overlay_props = dict(self._groups[group_name].props)
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
            })

            return True

    def append_message(self, group_name: str, content: str) -> bool:
        """Append content to the current message (for streaming)."""
        with self._lock:
            if group_name not in self._groups:
                return False

            state = self._groups[group_name]
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
                })

            return True

    def hide_message(self, group_name: str) -> bool:
        """Hide/fade out the current message."""
        with self._lock:
            if group_name not in self._groups:
                return False

            self._groups[group_name].current_message = None

            self._notify_callbacks({
                "type": "hide_message",
                "group": group_name
            })

            return True

    # ─────────────────────────────── Loader ─────────────────────────────── #

    def set_loader(self, group_name: str, show: bool, color: Optional[str] = None) -> bool:
        """Show or hide the loader animation."""
        with self._lock:
            if group_name not in self._groups:
                self.create_group(group_name)

            self._groups[group_name].loader_visible = show
            if color:
                self._groups[group_name].loader_color = color

            self._notify_callbacks({
                "type": "set_loader",
                "group": group_name,
                "show": show,
                "color": color
            })

            return True

    # ─────────────────────────────── Items ─────────────────────────────── #

    def add_item(
        self,
        group_name: str,
        title: str,
        description: str = "",
        color: Optional[str] = None,
        duration: Optional[float] = None
    ) -> bool:
        """Add a persistent item to a group."""
        with self._lock:
            if group_name not in self._groups:
                self.create_group(group_name)

            self._groups[group_name].items[title] = HudItem(
                title=title,
                description=description,
                color=color,
                duration=duration
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
        title: str,
        description: Optional[str] = None,
        color: Optional[str] = None,
        duration: Optional[float] = None
    ) -> bool:
        """Update an existing item."""
        with self._lock:
            if group_name not in self._groups:
                return False

            if title not in self._groups[group_name].items:
                return False

            item = self._groups[group_name].items[title]
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

    def remove_item(self, group_name: str, title: str) -> bool:
        """Remove an item from a group."""
        with self._lock:
            if group_name not in self._groups:
                return False

            if title in self._groups[group_name].items:
                del self._groups[group_name].items[title]

                self._notify_callbacks({
                    "type": "remove_item",
                    "group": group_name,
                    "title": title
                })

                return True
            return False

    def clear_items(self, group_name: str) -> bool:
        """Clear all items from a group."""
        with self._lock:
            if group_name not in self._groups:
                return False

            self._groups[group_name].items.clear()

            self._notify_callbacks({
                "type": "clear_items",
                "group": group_name
            })

            return True

    # ─────────────────────────────── Progress ─────────────────────────────── #

    def show_progress(
        self,
        group_name: str,
        title: str,
        current: float,
        maximum: float = 100,
        description: str = "",
        color: Optional[str] = None,
        auto_close: bool = False
    ) -> bool:
        """Show or update a progress bar."""
        with self._lock:
            if group_name not in self._groups:
                self.create_group(group_name)

            items = self._groups[group_name].items
            if title in items:
                item = items[title]
                item.progress_current = current
                item.progress_maximum = maximum
                if description:
                    item.description = description
                if color:
                    item.progress_color = color
            else:
                items[title] = HudItem(
                    title=title,
                    description=description,
                    is_progress=True,
                    progress_current=current,
                    progress_maximum=maximum,
                    progress_color=color,
                    auto_close=auto_close
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
        title: str,
        duration: float,
        description: str = "",
        color: Optional[str] = None,
        auto_close: bool = True,
        initial_progress: float = 0
    ) -> bool:
        """Show a timer-based progress bar."""
        with self._lock:
            if group_name not in self._groups:
                self.create_group(group_name)

            now = time.time()
            self._groups[group_name].items[title] = HudItem(
                title=title,
                description=description,
                is_progress=True,
                is_timer=True,
                timer_duration=duration,
                timer_start=now - initial_progress,  # Adjust for initial progress
                progress_current=initial_progress,
                progress_maximum=duration,
                progress_color=color,
                auto_close=auto_close
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

    def create_chat_window(
        self,
        name: str,
        props: Optional[dict[str, Any]] = None
    ) -> bool:
        """Create a chat window group."""
        with self._lock:
            final_props = props or {}
            final_props["is_chat_window"] = True

            if name not in self._groups:
                self._groups[name] = GroupState()
            self._groups[name].props.update(final_props)
            self._groups[name].is_chat_window = True

            # Use 'create_chat_window' command for overlay compatibility
            self._notify_callbacks({
                "type": "create_chat_window",
                "name": name,
                "props": final_props
            })

            return True

    def send_chat_message(
        self,
        window_name: str,
        sender: str,
        text: str,
        color: Optional[str] = None
    ) -> bool:
        """Send a message to a chat window."""
        with self._lock:
            if window_name not in self._groups:
                return False

            state = self._groups[window_name]

            # Append to last message if same sender
            if (
                state.chat_messages
                and state.chat_messages[-1].sender == sender
            ):
                state.chat_messages[-1].text += " " + text
            else:
                state.chat_messages.append(ChatMessage(
                    sender=sender,
                    text=text,
                    color=color
                ))

            # Limit chat history
            max_messages = state.props.get("max_messages", 50)
            if len(state.chat_messages) > max_messages:
                state.chat_messages = state.chat_messages[-max_messages:]

            self._notify_callbacks({
                "type": "chat_message",
                "name": window_name,
                "sender": sender,
                "text": text,
                "color": color
            })

            return True

    def clear_chat_window(self, name: str) -> bool:
        """Clear all messages from a chat window."""
        with self._lock:
            if name not in self._groups:
                return False

            self._groups[name].chat_messages.clear()

            self._notify_callbacks({
                "type": "clear_chat_window",
                "name": name
            })

            return True

    def show_chat_window(self, name: str) -> bool:
        """Show a hidden chat window."""
        with self._lock:
            if name not in self._groups:
                return False

            self._groups[name].visible = True

            self._notify_callbacks({
                "type": "show_chat_window",
                "name": name
            })

            return True

    def hide_chat_window(self, name: str) -> bool:
        """Hide a chat window."""
        with self._lock:
            if name not in self._groups:
                return False

            self._groups[name].visible = False

            self._notify_callbacks({
                "type": "hide_chat_window",
                "name": name
            })

            return True

    def clear_all(self) -> None:
        """
        Clear all groups and reset state (fresh start).

        Useful for resetting the HUD system without restarting the server.
        """
        with self._lock:
            self._groups.clear()

            self._notify_callbacks({
                "type": "clear_all"
            })
