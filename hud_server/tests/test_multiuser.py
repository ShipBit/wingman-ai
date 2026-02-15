"""
Test Multiuser - Multi-user HUD session tests with shared groups.

Tests:
- Multiple users each with their own HUD groups
- Shared groups accessible by multiple users
- Disconnect and reconnect scenarios:
  - With state persistence (save/restore)
  - Without state persistence (clean start)
- HUDs with different configurations positioned across the screen

This test simulates a realistic multi-user scenario like a gaming team
or collaborative workspace where users have private and shared HUD areas.
"""

import asyncio
from typing import Any, Optional
from dataclasses import dataclass, field

from hud_server.http_client import HudHttpClient
from hud_server.types import (
    HudColor, LayoutMode,
    MessageProps, PersistentProps, ChatWindowProps, WindowType
)


# =============================================================================
# USER CONFIGURATIONS - Different visual styles across the screen
# =============================================================================

USER_CONFIGS = {
    "alice": {
        "display_name": "Alice",
        # Private HUD - top-left corner (blue theme)
        "private_hud": {
            "layout_mode": LayoutMode.MANUAL.value,
            "x": 20,
            "y": 20,
            "width": 380,
            "max_height": 350,
            "bg_color": "#1a2332",
            "text_color": "#e8f4ff",
            "accent_color": HudColor.ACCENT_BLUE.value,
            "opacity": 0.92,
            "border_radius": 10,
            "font_size": 15,
            "typewriter_effect": True,
            "fade_delay": 10.0,
            "z_order": 10,
        },
        # Private persistent panel - below main HUD
        "private_persistent": {
            "layout_mode": LayoutMode.MANUAL.value,
            "x": 20,
            "y": 390,
            "width": 320,
            "max_height": 300,
            "bg_color": "#1a2332",
            "text_color": "#e8f4ff",
            "accent_color": HudColor.ACCENT_GREEN.value,
            "opacity": 0.85,
            "border_radius": 8,
            "font_size": 14,
            "typewriter_effect": False,
            "z_order": 5,
        },
    },
    "bob": {
        "display_name": "Bob",
        # Private HUD - top-right corner (orange theme)
        "private_hud": {
            "layout_mode": LayoutMode.MANUAL.value,
            "x": 1500,
            "y": 20,
            "width": 400,
            "max_height": 380,
            "bg_color": "#2a1f1a",
            "text_color": "#fff5e8",
            "accent_color": HudColor.ACCENT_ORANGE.value,
            "opacity": 0.90,
            "border_radius": 14,
            "font_size": 16,
            "typewriter_effect": True,
            "fade_delay": 8.0,
            "z_order": 10,
        },
        # Private persistent panel - right side
        "private_persistent": {
            "layout_mode": LayoutMode.MANUAL.value,
            "x": 1520,
            "y": 420,
            "width": 340,
            "max_height": 280,
            "bg_color": "#2a1f1a",
            "text_color": "#fff5e8",
            "accent_color": HudColor.WARNING.value,
            "opacity": 0.82,
            "border_radius": 10,
            "font_size": 13,
            "typewriter_effect": False,
            "z_order": 5,
        },
    },
    "charlie": {
        "display_name": "Charlie",
        # Private HUD - bottom-left corner (purple theme)
        "private_hud": {
            "layout_mode": LayoutMode.MANUAL.value,
            "x": 20,
            "y": 720,
            "width": 420,
            "max_height": 320,
            "bg_color": "#1f1a2a",
            "text_color": "#f0e8ff",
            "accent_color": HudColor.ACCENT_PURPLE.value,
            "opacity": 0.88,
            "border_radius": 16,
            "font_size": 15,
            "typewriter_effect": False,  # Charlie prefers instant text
            "fade_delay": 12.0,
            "z_order": 10,
        },
        # Private persistent panel - bottom area
        "private_persistent": {
            "layout_mode": LayoutMode.MANUAL.value,
            "x": 460,
            "y": 800,
            "width": 350,
            "max_height": 220,
            "bg_color": "#1f1a2a",
            "text_color": "#f0e8ff",
            "accent_color": "#8e44ad",
            "opacity": 0.80,
            "border_radius": 12,
            "font_size": 14,
            "typewriter_effect": False,
            "z_order": 5,
        },
    },
}

# Shared group configurations
SHARED_CONFIGS = {
    "team_notifications": {
        "name": "Team Notifications",
        "layout_mode": LayoutMode.MANUAL.value,
        "x": 800,
        "y": 20,
        "width": 450,
        "max_height": 400,
        "bg_color": "#1a1a2e",
        "text_color": HudColor.WHITE.value,
        "accent_color": HudColor.ERROR.value,
        "opacity": 0.95,
        "border_radius": 12,
        "font_size": 16,
        "typewriter_effect": True,
        "z_order": 20,  # Highest priority
    },
    "team_chat": {
        "name": "Team Chat",
        "layout_mode": LayoutMode.MANUAL.value,
        "x": 800,
        "y": 440,
        "width": 480,
        "max_height": 450,
        "bg_color": "#16213e",
        "text_color": "#e8e8e8",
        "accent_color": HudColor.INFO.value,
        "opacity": 0.90,
        "border_radius": 10,
        "font_size": 14,
        "is_chat_window": True,
        "auto_hide": False,
        "max_messages": 100,
        "fade_old_messages": True,
        "sender_colors": {
            "Alice": HudColor.ACCENT_BLUE.value,
            "Bob": HudColor.ACCENT_ORANGE.value,
            "Charlie": HudColor.ACCENT_PURPLE.value,
            "System": HudColor.GRAY.value,
        },
        "z_order": 15,
    },
    "shared_status": {
        "name": "Shared Status",
        "layout_mode": LayoutMode.MANUAL.value,
        "x": 1300,
        "y": 720,
        "width": 360,
        "max_height": 300,
        "bg_color": "#0d1b2a",
        "text_color": "#d0d0d0",
        "accent_color": HudColor.SUCCESS.value,
        "opacity": 0.85,
        "border_radius": 8,
        "font_size": 14,
        "typewriter_effect": False,
        "z_order": 12,
    },
}


# =============================================================================
# USER CLIENT CLASS
# =============================================================================

@dataclass
class UserClient:
    """Represents a single user with their own HUD groups."""

    user_id: str
    config: dict[str, Any]
    base_url: str = "http://127.0.0.1:7862"
    _client: Optional[HudHttpClient] = field(default=None, repr=False)
    connected: bool = False
    saved_states: dict[str, dict] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return self.config.get("display_name", self.user_id.title())

    @property
    def private_hud_group(self) -> str:
        return f"user_{self.user_id}_hud"

    @property
    def private_persistent_group(self) -> str:
        return f"user_{self.user_id}_persistent"

    async def connect(self, timeout: float = 5.0) -> bool:
        """Connect to the HUD server."""
        try:
            self._client = HudHttpClient(self.base_url)
            if await self._client.connect(timeout=timeout):
                self.connected = True
                print(f"[{self.display_name}] Connected to HUD server")
                return True
            print(f"[{self.display_name}] Failed to connect")
            return False
        except Exception as e:
            print(f"[{self.display_name}] Connection error: {e}")
            return False

    async def disconnect(self):
        """Disconnect from the HUD server."""
        if self._client:
            await self._client.disconnect()
        self.connected = False
        print(f"[{self.display_name}] Disconnected")

    def _config_to_props(self, config: dict) -> MessageProps:
        """Convert a config dict to MessageProps."""
        return MessageProps(
            layout_mode=config.get("layout_mode"),
            x=config.get("x"),
            y=config.get("y"),
            width=config.get("width"),
            max_height=config.get("max_height"),
            bg_color=config.get("bg_color"),
            text_color=config.get("text_color"),
            accent_color=config.get("accent_color"),
            opacity=config.get("opacity"),
            border_radius=config.get("border_radius"),
            font_size=config.get("font_size"),
            typewriter_effect=config.get("typewriter_effect"),
            fade_delay=config.get("fade_delay"),
            z_order=config.get("z_order"),
        )

    async def setup_private_groups(self):
        """Create the user's private HUD groups."""
        if not self._client:
            return

        # Create private HUD
        await self._client.create_group(
            self.private_hud_group,
            WindowType.MESSAGE,
            props=self._config_to_props(self.config["private_hud"])
        )
        print(f"[{self.display_name}] Created private HUD group")

        # Create private persistent panel
        await self._client.create_group(
            self.private_persistent_group,
            WindowType.PERSISTENT,
            props=self._config_to_props(self.config["private_persistent"])
        )
        print(f"[{self.display_name}] Created private persistent group")

    async def cleanup_private_groups(self):
        """Delete the user's private HUD groups."""
        if not self._client:
            return

        await self._client.delete_group(self.private_hud_group)
        await self._client.delete_group(self.private_persistent_group)
        print(f"[{self.display_name}] Cleaned up private groups")

    # State persistence methods
    async def save_state(self, group_name: str) -> bool:
        """Save the current state of a group for later restore."""
        if not self._client:
            return False

        result = await self._client.get_state(group_name)
        if result and "state" in result:
            self.saved_states[group_name] = result["state"]
            print(f"[{self.display_name}] Saved state for '{group_name}'")
            return True
        return False

    async def restore_state(self, group_name: str) -> bool:
        """Restore a previously saved group state."""
        if not self._client:
            return False

        if group_name not in self.saved_states:
            print(f"[{self.display_name}] No saved state for '{group_name}'")
            return False

        result = await self._client.restore_state(
            group_name,
            self.saved_states[group_name]
        )
        if result:
            print(f"[{self.display_name}] Restored state for '{group_name}'")
            return True
        return False

    def clear_saved_states(self):
        """Clear all saved states (simulating no persistence)."""
        self.saved_states.clear()
        print(f"[{self.display_name}] Cleared all saved states")

    # Private HUD operations
    async def show_private_message(self, title: str, content: str,
                                   color: Optional[str] = None):
        """Show a message in the user's private HUD."""
        if not self._client:
            return
        await self._client.show_message(
            self.private_hud_group,
            WindowType.MESSAGE,
            title=title,
            content=content,
            color=color or self.config["private_hud"]["accent_color"],
        )

    async def show_private_loader(self, show: bool = True):
        """Show/hide loader in private HUD."""
        if not self._client:
            return
        await self._client.show_loader(self.private_hud_group, WindowType.MESSAGE, show)

    async def add_private_item(self, title: str, description: str,
                               duration: Optional[float] = None):
        """Add a persistent item to private panel."""
        if not self._client:
            return
        await self._client.add_item(
            self.private_persistent_group,
            WindowType.PERSISTENT,
            title=title,
            description=description,
            duration=duration,
        )

    async def update_private_item(self, title: str, description: str):
        """Update a persistent item in private panel."""
        if not self._client:
            return
        await self._client.update_item(
            self.private_persistent_group,
            WindowType.PERSISTENT,
            title=title,
            description=description,
        )

    async def remove_private_item(self, title: str):
        """Remove a persistent item from private panel."""
        if not self._client:
            return
        await self._client.remove_item(self.private_persistent_group, WindowType.PERSISTENT, title)

    async def show_private_progress(self, title: str, current: float,
                                    maximum: float = 100, description: str = ""):
        """Show a progress bar in private panel."""
        if not self._client:
            return
        await self._client.show_progress(
            self.private_persistent_group,
            WindowType.PERSISTENT,
            title=title,
            current=current,
            maximum=maximum,
            description=description,
        )

    async def show_private_timer(self, title: str, duration: float,
                                 description: str = "", auto_close: bool = True):
        """Show a timer in private panel."""
        if not self._client:
            return
        await self._client.show_timer(
            self.private_persistent_group,
            WindowType.PERSISTENT,
            title=title,
            duration=duration,
            description=description,
            auto_close=auto_close,
        )


# =============================================================================
# SHARED GROUP MANAGER
# =============================================================================

class SharedGroupManager:
    """Manages shared groups accessible by multiple users."""

    def __init__(self, base_url: str = "http://127.0.0.1:7862"):
        self.base_url = base_url
        self._client: Optional[HudHttpClient] = None
        self.connected = False

    async def connect(self) -> bool:
        """Connect to the HUD server."""
        self._client = HudHttpClient(self.base_url)
        if await self._client.connect():
            self.connected = True
            print("[SharedGroupManager] Connected")
            return True
        return False

    async def disconnect(self):
        """Disconnect from the HUD server."""
        if self._client:
            await self._client.disconnect()
        self.connected = False

    async def setup_shared_groups(self):
        """Create all shared groups."""
        if not self._client:
            return

        for group_id, config in SHARED_CONFIGS.items():
            if config.get("is_chat_window"):
                await self._client.create_chat_window(
                    name=group_id,
                    x=config["x"],
                    y=config["y"],
                    width=config["width"],
                    max_height=config["max_height"],
                    auto_hide=config.get("auto_hide", False),
                    max_messages=config.get("max_messages", 50),
                    sender_colors=config.get("sender_colors"),
                    fade_old_messages=config.get("fade_old_messages", True),
                )
            else:
                # Convert config dict to MessageProps
                props = MessageProps(
                    layout_mode=config.get("layout_mode"),
                    x=config.get("x"),
                    y=config.get("y"),
                    width=config.get("width"),
                    max_height=config.get("max_height"),
                    bg_color=config.get("bg_color"),
                    text_color=config.get("text_color"),
                    accent_color=config.get("accent_color"),
                    opacity=config.get("opacity"),
                    border_radius=config.get("border_radius"),
                    font_size=config.get("font_size"),
                    typewriter_effect=config.get("typewriter_effect"),
                    z_order=config.get("z_order"),
                )
                await self._client.create_group(group_id, WindowType.MESSAGE, props=props)
            print(f"[SharedGroupManager] Created shared group: {config['name']}")

    async def cleanup_shared_groups(self):
        """Delete all shared groups."""
        if not self._client:
            return

        for group_id, config in SHARED_CONFIGS.items():
            if config.get("is_chat_window"):
                await self._client.delete_chat_window(group_id)
            else:
                await self._client.delete_group(group_id)
        print("[SharedGroupManager] Cleaned up all shared groups")

    async def send_team_notification(self, title: str, content: str,
                                     color: Optional[str] = None):
        """Send a notification to the team notifications panel."""
        if not self._client:
            return
        await self._client.show_message(
            "team_notifications",
            WindowType.MESSAGE,
            title=title,
            content=content,
            color=color,
        )

    async def send_team_chat(self, sender: str, text: str,
                             color: Optional[str] = None):
        """Send a message to the team chat."""
        if not self._client:
            return
        await self._client.send_chat_message(
            "team_chat",
            WindowType.CHAT,
            sender=sender,
            text=text,
            color=color,
        )

    async def update_shared_status(self, title: str, description: str):
        """Update an item in the shared status panel."""
        if not self._client:
            return
        await self._client.add_item(
            "shared_status",
            WindowType.PERSISTENT,
            title=title,
            description=description,
        )


# =============================================================================
# TEST SCENARIOS
# =============================================================================

async def test_multiuser_basic_setup(users: dict[str, UserClient],
                                     shared: SharedGroupManager,
                                     delay: float = 1.5):
    """Test basic multi-user setup with private and shared groups."""
    print("\n" + "="*60)
    print("TEST: Basic Multi-User Setup")
    print("="*60)

    # Each user sets up their private groups
    for user in users.values():
        await user.setup_private_groups()
    await asyncio.sleep(delay)

    # Setup shared groups
    await shared.setup_shared_groups()
    await asyncio.sleep(delay)

    # Each user sends a message to their private HUD
    for user_id, user in users.items():
        await user.show_private_message(
            f"Welcome, {user.display_name}!",
            f"""This is your **private HUD**.

- Only you can see this
- Positioned at `x={user.config['private_hud']['x']}, y={user.config['private_hud']['y']}`
- Theme color: `{user.config['private_hud']['accent_color']}`
"""
        )
        await asyncio.sleep(0.5)

    await asyncio.sleep(delay)

    # Team notification
    await shared.send_team_notification(
        "Session Started",
        """All team members connected!

**Active Users:**
- Alice *(Top-Left)*
- Bob *(Top-Right)*  
- Charlie *(Bottom-Left)*

> Team communication is ready.
"""
    )
    await asyncio.sleep(delay)

    # Each user adds private persistent items
    await users["alice"].add_private_item("Task", "Complete report")
    await users["bob"].add_private_item("Objective", "Review pull requests")
    await users["charlie"].add_private_item("Note", "Prepare presentation")

    await asyncio.sleep(delay)
    print("Basic setup test complete")


async def test_multiuser_shared_interaction(users: dict[str, UserClient],
                                            shared: SharedGroupManager,
                                            delay: float = 1.0):
    """Test multiple users interacting with shared groups."""
    print("\n" + "="*60)
    print("TEST: Shared Group Interaction")
    print("="*60)

    # Simulate team chat conversation
    conversation = [
        ("Alice", "Hey team! Ready to start?"),
        ("Bob", "Ready here!"),
        ("Charlie", "Just finishing up something, give me a sec..."),
        ("System", "Meeting starting in **2 minutes**"),
        ("Alice", "No rush Charlie, we can wait"),
        ("Charlie", "Okay I'm good now! Let's go"),
        ("Bob", "Perfect, let's do this!"),
    ]

    for sender, text in conversation:
        await shared.send_team_chat(sender, text)
        await asyncio.sleep(delay)

    # Shared status updates
    await shared.update_shared_status("Team Status", "All members **online**")
    await asyncio.sleep(delay * 0.5)

    await shared.update_shared_status("Current Task", "Sprint Planning")
    await asyncio.sleep(delay * 0.5)

    await shared.update_shared_status("Time Remaining", "`45 minutes`")

    await asyncio.sleep(delay)
    print("Shared interaction test complete")


async def test_disconnect_reconnect_with_save(users: dict[str, UserClient],
                                              shared: SharedGroupManager,
                                              delay: float = 2.0):
    """Test disconnect and reconnect WITH state persistence."""
    print("\n" + "="*60)
    print("TEST: Disconnect/Reconnect WITH State Save")
    print("="*60)

    # Alice adds content to her private panels
    await users["alice"].show_private_message(
        "Important Data",
        """This message should **persist** after reconnect!

- Item 1: Saved
- Item 2: Saved
- State will be restored
"""
    )
    await users["alice"].add_private_item("Saved Item 1", "This will persist")
    await users["alice"].add_private_item("Saved Item 2", "This too!")
    await asyncio.sleep(delay)

    # Bob shows a progress bar
    await users["bob"].show_private_progress("Download", 65, 100, "65% complete")
    await users["bob"].add_private_item("Pinned", "Important bookmark")
    await asyncio.sleep(delay)

    # Save states before disconnect
    print("\n--- Saving states before disconnect ---")
    await users["alice"].save_state(users["alice"].private_hud_group)
    await users["alice"].save_state(users["alice"].private_persistent_group)
    await users["bob"].save_state(users["bob"].private_hud_group)
    await users["bob"].save_state(users["bob"].private_persistent_group)

    await asyncio.sleep(delay)

    # Disconnect both users
    print("\n--- Disconnecting users ---")
    await users["alice"].disconnect()
    await users["bob"].disconnect()
    await asyncio.sleep(delay)

    # Reconnect
    print("\n--- Reconnecting users ---")
    await users["alice"].connect()
    await users["bob"].connect()
    await asyncio.sleep(delay)

    # Restore saved states
    print("\n--- Restoring saved states ---")
    await users["alice"].restore_state(users["alice"].private_hud_group)
    await users["alice"].restore_state(users["alice"].private_persistent_group)
    await users["bob"].restore_state(users["bob"].private_hud_group)
    await users["bob"].restore_state(users["bob"].private_persistent_group)

    await asyncio.sleep(delay)

    # Verify restoration by showing confirmation
    await users["alice"].show_private_message(
        "State Restored!",
        "Previous content should be visible above."
    )

    await asyncio.sleep(delay)
    print("Disconnect/reconnect WITH save test complete")


async def test_disconnect_reconnect_without_save(users: dict[str, UserClient],
                                                  delay: float = 2.0):
    """Test disconnect and reconnect WITHOUT state persistence."""
    print("\n" + "="*60)
    print("TEST: Disconnect/Reconnect WITHOUT State Save (Clean Start)")
    print("="*60)

    # Charlie adds content
    await users["charlie"].show_private_message(
        "Temporary Content",
        """This message will be **lost** after reconnect!

- No state save
- Fresh start on reconnect
- Content will disappear
"""
    )
    await users["charlie"].add_private_item("Temp Item", "Will not persist")
    await users["charlie"].show_private_timer("Session Timer", 30.0, "Running...")

    await asyncio.sleep(delay)

    # Clear any saved states to simulate no persistence
    users["charlie"].clear_saved_states()

    # Disconnect
    print("\n--- Disconnecting Charlie (no state save) ---")
    await users["charlie"].disconnect()
    await asyncio.sleep(delay)

    # Reconnect
    print("\n--- Reconnecting Charlie ---")
    await users["charlie"].connect()
    await asyncio.sleep(delay)

    # Setup fresh groups (previous content is lost)
    await users["charlie"].setup_private_groups()
    await asyncio.sleep(delay)

    # Show that this is a fresh start
    await users["charlie"].show_private_message(
        "Fresh Start",
        """Previous content is **gone**!

This is a clean slate:
- No messages restored
- No items restored
- Starting fresh
"""
    )
    await users["charlie"].add_private_item("New Item", "Created after reconnect")

    await asyncio.sleep(delay)
    print("Disconnect/reconnect WITHOUT save test complete")


async def test_mixed_hud_configs(users: dict[str, UserClient],
                                  shared: SharedGroupManager,
                                  delay: float = 1.5):
    """Test HUDs with different configurations across the screen."""
    print("\n" + "="*60)
    print("TEST: Mixed HUD Configurations Across Screen")
    print("="*60)

    # Show each user's unique configuration
    config_info = {
        "alice": ("Top-Left", "Blue theme, typewriter ON"),
        "bob": ("Top-Right", "Orange theme, typewriter ON, larger font"),
        "charlie": ("Bottom-Left", "Purple theme, typewriter OFF (instant)"),
    }

    # Demonstrate different configurations simultaneously
    for user_id, user in users.items():
        pos, desc = config_info[user_id]
        hud_cfg = user.config["private_hud"]

        await user.show_private_message(
            f"{user.display_name}'s Config",
            f"""**Position:** {pos}

**Style:**
- {desc}
- Border radius: `{hud_cfg['border_radius']}px`
- Font size: `{hud_cfg['font_size']}px`
- Opacity: `{hud_cfg['opacity']}`
- Accent: `{hud_cfg['accent_color']}`
"""
        )
        await asyncio.sleep(0.3)

    await asyncio.sleep(delay)

    # Demonstrate progress bars with different colors in each user's panel
    await users["alice"].show_private_progress("Blue Progress", 75, 100)
    await users["bob"].show_private_progress("Orange Progress", 45, 100)
    await users["charlie"].show_private_progress("Purple Progress", 90, 100)

    await asyncio.sleep(delay)

    # Timers with different durations
    await users["alice"].show_private_timer("Short Timer", 5.0, "5 seconds")
    await users["bob"].show_private_timer("Medium Timer", 10.0, "10 seconds")
    await users["charlie"].show_private_timer("Long Timer", 15.0, "15 seconds")

    await asyncio.sleep(delay)

    # Team notification about the test
    await shared.send_team_notification(
        "Layout Test",
        """HUDs displayed across screen:

| User | Position | Theme |
|------|----------|-------|
| Alice | Top-Left | Blue |
| Bob | Top-Right | Orange |
| Charlie | Bottom-Left | Purple |
| Shared | Center | Dark |

All HUDs running with unique configurations!
"""
    )

    await asyncio.sleep(delay * 2)
    print("Mixed HUD configurations test complete")


async def test_concurrent_operations(users: dict[str, UserClient],
                                      shared: SharedGroupManager,
                                      delay: float = 0.5):
    """Test concurrent operations from multiple users."""
    print("\n" + "="*60)
    print("TEST: Concurrent Operations")
    print("="*60)

    async def user_activity(user: UserClient, iteration: int):
        """Simulate user activity."""
        await user.show_private_message(
            f"Activity #{iteration}",
            f"User **{user.display_name}** is active!\n\nIteration: `{iteration}`"
        )
        await asyncio.sleep(0.2)
        await user.add_private_item(
            f"Item {iteration}",
            f"Added at iteration {iteration}"
        )

    # Run concurrent operations from all users
    for i in range(1, 4):
        print(f"  Iteration {i}...")
        await asyncio.gather(
            user_activity(users["alice"], i),
            user_activity(users["bob"], i),
            user_activity(users["charlie"], i),
            shared.send_team_chat("System", f"Round {i} complete"),
        )
        await asyncio.sleep(delay)

    # Rapid-fire team chat
    messages = [
        ("Alice", "Quick message 1"),
        ("Bob", "Quick message 2"),
        ("Charlie", "Quick message 3"),
        ("Alice", "Quick message 4"),
        ("Bob", "Quick message 5"),
    ]

    for sender, text in messages:
        await shared.send_team_chat(sender, text)
        await asyncio.sleep(0.1)

    await asyncio.sleep(delay)
    print("Concurrent operations test complete")


# =============================================================================
# MAIN TEST RUNNER
# =============================================================================

async def run_all_multiuser_tests(base_url: str = "http://127.0.0.1:7862",
                                   delay_multiplier: float = 1.0):
    """Run all multi-user tests."""
    print("\n" + "="*70)
    print("  MULTIUSER HUD TEST SUITE")
    print("  Testing multiple users, shared groups, disconnect/reconnect")
    print("="*70)

    # Create users
    users: dict[str, UserClient] = {}
    for user_id, config in USER_CONFIGS.items():
        users[user_id] = UserClient(
            user_id=user_id,
            config=config,
            base_url=base_url
        )

    # Create shared group manager
    shared = SharedGroupManager(base_url)

    try:
        # Connect all users
        print("\n--- Connecting Users ---")
        for user in users.values():
            await user.connect()
        await shared.connect()

        # Run tests
        await test_multiuser_basic_setup(users, shared, 1.5 * delay_multiplier)
        await asyncio.sleep(2)

        await test_multiuser_shared_interaction(users, shared, 1.0 * delay_multiplier)
        await asyncio.sleep(2)

        await test_disconnect_reconnect_with_save(users, shared, 2.0 * delay_multiplier)
        await asyncio.sleep(2)

        await test_disconnect_reconnect_without_save(users, 2.0 * delay_multiplier)
        await asyncio.sleep(2)

        await test_mixed_hud_configs(users, shared, 1.5 * delay_multiplier)
        await asyncio.sleep(2)

        await test_concurrent_operations(users, shared, 0.5 * delay_multiplier)
        await asyncio.sleep(2)

        print("\n" + "="*70)
        print("  ALL MULTIUSER TESTS COMPLETE")
        print("="*70)

    except Exception as e:
        print(f"\nTest error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Cleanup
        print("\n--- Cleanup ---")
        for user in users.values():
            if user.connected:
                await user.cleanup_private_groups()
                await user.disconnect()

        if shared.connected:
            await shared.cleanup_shared_groups()
            await shared.disconnect()

        print("Cleanup complete")


async def run_with_server():
    """Run tests with automatic server management."""
    from hud_server import HudServer

    server = HudServer()
    if not server.start(host="127.0.0.1", port=7862):
        print("Failed to start HUD server")
        return

    try:
        await asyncio.sleep(1)  # Wait for server to be ready
        await run_all_multiuser_tests()
    finally:
        await server.stop()


if __name__ == "__main__":
    import sys

    if "--with-server" in sys.argv:
        # Run with automatic server management
        asyncio.run(run_with_server())
    else:
        # Assume server is already running
        print("Connecting to existing HUD server...")
        print("(Run with --with-server to auto-start the server)")
        asyncio.run(run_all_multiuser_tests())
