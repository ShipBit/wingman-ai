# HUD Server

Production-ready HTTP API server for controlling HUD (Heads-Up Display) overlays in Wingman AI.

## Overview

The HUD Server provides a REST API to control HUD overlays from any client. It runs in its own thread with its own event loop, supporting:

- **Multiple HUD Groups**: Independent overlay groups for different wingmen
- **Message Display**: Show messages with Markdown formatting, typewriter effects, and animations
- **Persistent Items**: Progress bars, timers, and status indicators
- **Chat Windows**: Multi-user chat overlays with auto-hide and message history
- **State Management**: Persist and restore HUD state across sessions
- **Overlay Integration**: PIL-based overlay rendering, put on screen by a platform backend (Windows for now, see [Platforms](#platforms))

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Wingman AI Core                          │
│                                                             │
│  ┌────────────┐      ┌──────────────┐      ┌────────────┐   │
│  │  Wingman   │─────▶│  HUD Server  │◀─────│  HTTP      │   │
│  │  Skills    │      │  (FastAPI)   │      │  Client    │   │
│  └────────────┘      └──────┬───────┘      └────────────┘   │
│                             │                               │
└─────────────────────────────┼───────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │   HUD Manager    │
                    │  (State Storage) │
                    └─────────┬────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  HeadsUpOverlay  │
                    │  (PIL Renderer)  │
                    └─────────┬────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │ Platform backend │
                    │ (OS windows)     │
                    └──────────────────┘
```

### Core Components

- **`server.py`**: FastAPI-based HTTP server with REST endpoints
- **`hud_manager.py`**: Thread-safe state management for all HUD groups
- **`http_client.py`**: Async/sync HTTP client for interacting with the server
- **`models.py`**: Pydantic models for API requests/responses with validation
- **`overlay/overlay.py`**: PIL-based overlay renderer (any OS; draws through the platform backend)
- **`layout/manager.py`**: Automatic positioning and stacking system
- **`rendering/markdown.py`**: Sophisticated Markdown renderer
- **`rendering/layers.py`**: Windows drawn as a stack of cached pieces (see [Rendering](#rendering))
- **`platform/`**: The bridge to the operating system, one backend per OS (see [Platforms](#platforms))

## Rendering

Every window (message, info panel, chat) is a stack of pieces: a title, each
Markdown block, each chat message, each info item. A piece is rendered once,
at its full height, and kept while the window shows it. A frame lays out only
the pieces that reach into the window, newest at the bottom, so:

- content scrolled out of view is neither rendered nor kept; when there is
  more above, the newest part shows and the top fades,
- the typewriter redraws only the block it is typing,
- a frame where only the loader moves draws only the loader; a running timer
  redraws its own item once a second, a moving progress bar once a pixel,
- images from the web download in the background and show once they arrived.

## Platforms

The overlay renders every HUD window into a PIL image, on every OS. Only the
platform backend touches the OS: it shows those images in transparent,
always-on-top, click-through windows, moves and hides them, routes the mouse
for the preview, lists the monitors and finds the font files.

`hud_server/platform/` is the bridge:

| File | Role |
| --- | --- |
| `__init__.py` | Picks the backend for the OS Core runs on: `create_backend()`, `hud_supported()`, `unsupported_reason()`. |
| `base.py` | `HudBackend`, the interface every backend implements, and its types (`Monitor`, `FontSet`, `Cursor`, `Pointer`). |
| `windows.py` | The Windows backend: layered Win32 windows with per-pixel alpha. |
| `win32.py` | The ctypes bindings `windows.py` uses. |
| `linux.py`, `macos.py` | Registered, not written yet: they report the HUD as unsupported and say why. |

Core starts the HUD server only where `hud_supported()` is true. Elsewhere it
logs the reason, and skills see `self.wingman.hud.available == False`.

To add an OS, implement `HudBackend` in its module and set `supported = True`.
The overlay, layout, preview and Core stay as they are. The backend's window
calls run on the overlay thread. Tests drive the overlay through a backend
without an OS (`FakeHudBackend` in `tests/support.py`), so they run on every OS.

## Quick Start

### Starting the Server

```python
from hud_server.server import HudServer

server = HudServer()
server.start(host="127.0.0.1", port=7862, framerate=60)

# Server runs in background thread
# API available at http://127.0.0.1:7862
# Docs at http://127.0.0.1:7862/docs
```

### Using the Client (Async)

```python
from hud_server.http_client import HudHttpClient
from hud_server.types import WindowType

async with HudHttpClient() as client:
    # Create a message HUD group (for temporary messages)
    await client.create_group("my_wingman", WindowType.MESSAGE, {
        "anchor": "top_left",
        "priority": 20,
        "width": 400,
        "bg_color": "#1e212b",
        "accent_color": "#00aaff"
    })

    # Create a persistent HUD group (for info panels)
    await client.create_group("my_wingman", WindowType.PERSISTENT, {
        "anchor": "bottom_left",
        "priority": 10,
        "width": 400
    })

    # Show a message
    await client.show_message(
        group_name="my_wingman",
        element=WindowType.MESSAGE,
        title="Hello!",
        content="This is a **Markdown** message with `code`.",
        duration=10.0
    )

    # Add a progress bar (to persistent group)
    await client.show_progress(
        group_name="my_wingman",
        element=WindowType.PERSISTENT,
        title="Loading",
        current=50,
        maximum=100
    )
```

### Using the Client (Sync)

```python
from hud_server.http_client import HudHttpClientSync
from hud_server.types import WindowType

with HudHttpClientSync() as client:
    client.create_group("my_wingman", WindowType.MESSAGE)
    client.create_group("my_wingman", WindowType.PERSISTENT)
    client.show_message("my_wingman", WindowType.MESSAGE, "Title", "Content")
    client.show_progress("my_wingman", WindowType.PERSISTENT, "Loading", 50, 100)
```

## API Endpoints

### Health & Status

- `GET /health` - Health check and list of active groups
- `GET /` - Same as `/health`

### Groups

- `POST /groups` - Create or update a HUD group
- `PUT /groups/{group_name}/{element}` - Create or update a specific element type
- `PATCH /groups/{group_name}/{element}` - Update group properties
- `DELETE /groups/{group_name}/{element}` - Delete a group element
- `GET /groups` - List all groups

> **Note:** Groups require an `element` parameter to specify the window type (`message`, `persistent`, or `chat`).

### Defaults

- `GET /defaults` - The values groups use for props their own calls leave out
- `PUT /defaults` - Replace them: `props` for every group, `groups` per group name

Every window resolves its props as: built-in values, then `defaults.props`,
then `defaults.groups[group_name]`, then the group's own props, then the props
sent with a call. A change to the defaults restyles and moves existing windows
right away. Wingman AI Core sets them from the active HUD profile, so a skill
that creates a group with only a position gets the user's look.

### Shared Containers

Core writes every Wingman's conversation to the group `wingman_chat`
(element `message`) and the info panels to `wingman_info` (element
`persistent`). Their area and look come from the defaults.

### Preview

- `PUT /preview` (or `POST`) - Show the chat and info containers as preview panels that fill their whole area, in their real style
- `GET /preview` - The preview and its current areas
- `DELETE /preview` - End it

With `"interactive": true` the mouse moves a panel (drag the middle) and
resizes it (drag an edge or corner). In-process listeners registered with
`HudServer.add_event_listener()` get a `preview_changed` event with the new
area (`x1`, `y1`, `x2`, `y2`, `final` on mouse-up). Coordinates are pixels on
the HUD screen; the process is DPI-unaware, so on a scaled display both the
windows and the mouse use the same virtualized pixels.

### Element Visibility

- `POST /element/show` - Show a hidden element (message, persistent, or chat)
- `POST /element/hide` - Hide an element without removing it

This allows you to temporarily hide HUD elements while preserving their state and continuing to receive updates in the background.

### Settings

- `POST /settings/update` - Update server settings at runtime (framerate, layout_margin, layout_spacing, screen)

### Messages

- `POST /message` - Show a message in a group
- `POST /message/append` - Append content to current message (streaming)
- `POST /message/hide/{group_name}/{element}` - Hide the current message

### Persistent Items

- `POST /items` - Add a persistent item
- `PUT /items` - Update an existing item
- `DELETE /items/{group_name}/{element}/{title}` - Remove an item
- `DELETE /items/{group_name}/{element}` - Clear all items

### Progress & Timers

- `POST /progress` - Show/update a progress bar
- `POST /timer` - Show a countdown timer

### Chat Windows

- `POST /chat/window` - Create a chat window
- `DELETE /chat/window/{name}` - Delete a chat window
- `POST /chat/message` - Send a chat message (returns `message_id`)
- `PUT /chat/message` - Update an existing message by ID
- `DELETE /chat/messages/{name}` - Clear chat history
- `POST /chat/show/{name}` - Show a hidden chat window
- `POST /chat/hide/{name}` - Hide a chat window

#### Message Updates

When sending a chat message via `POST /chat/message`, the response includes a `message_id` that uniquely identifies the message. This ID can be used to update the message content later via `PUT /chat/message`.

If consecutive messages are sent by the same sender, they are automatically merged into a single message. In this case, `POST /chat/message` returns the existing merged message's ID, so updates will apply to the combined message.

**Send a message:**
```python
response = await client.send_chat_message(
    window_name="my_chat",
    sender="Assistant",
    text="Processing your request..."
)
message_id = response["message_id"]
```

**Update the message later:**
```python
await client.update_chat_message(
    window_name="my_chat",
    message_id=message_id,
    text="Done! Here are your results: ..."
)
```

This works for both the most recent message and any past message still in the chat history.

## Configuration

### Server Settings

Core keeps them in `settings.yaml` under `hud_server` (`HudServerSettings` in
`api/interface.py`):

```yaml
hud_server:
  enabled: true          # Start with Core
  host: 127.0.0.1        # Local only; 0.0.0.0 for the LAN
  port: 7862
  framerate: 60          # Overlay FPS
  layout_margin: 20      # Screen edge margin
  layout_spacing: 15     # Space between stacked windows
  screen: 1              # Monitor (1 = primary, 2+ = more monitors)
```

### Dynamic Settings Update

The server supports runtime configuration changes without restart via the `/settings/update` endpoint:

| Parameter | Type | Description |
|-----------|------|-------------|
| `framerate` | int | Overlay FPS (1-240) |
| `layout_margin` | int | Screen edge margin in pixels |
| `layout_spacing` | int | Window spacing in pixels |
| `screen` | int | Monitor index (1=primary, 2+=additional monitors) |

**Note:** Screen changes take effect on next overlay render cycle. The server must be restarted for host/port changes to take effect.

### Group Properties

```python
props = {
    # Position & Size
    "x": 20, "y": 20, "width": 400, "max_height": 600,
    
    # Colors (hex format)
    "bg_color": "#1e212b",
    "text_color": "#f0f0f0",
    "accent_color": "#00aaff",
    
    # Visual
    "opacity": 0.85,
    "border_radius": 12,
    "font_size": 16,
    "font_family": "Segoe UI",
    
    # Behavior
    "typewriter_effect": True,
    "typewriter_speed": 200,    # chars per second
    "auto_fade": True,
    "fade_delay": 8.0,          # seconds
    
    # Layout (automatic positioning)
    "layout_mode": "auto",      # auto | manual | hybrid
    "anchor": "top_left",       # top_left | top_right | bottom_left | bottom_right | center
    "priority": 10,             # stacking order (0-100)
    "align": "top",             # manual mode: top | center | bottom of the area
}
```

## Layout System

The HUD Server includes an intelligent layout system to prevent overlapping windows when multiple HUD groups are active (e.g., messages from different wingmen, persistent info panels, chat windows).

### Features

1. **Anchor-based positioning**: Windows anchor to screen corners and edges
2. **Automatic stacking**: Windows at the same anchor stack vertically with configurable spacing
3. **Priority ordering**: Higher priority windows are positioned closer to the anchor point
4. **Dynamic reflow**: When window heights change, other windows reposition automatically
5. **Visibility awareness**: Hidden windows don't take up space in the layout

### Layout Properties

These properties can be set when creating or updating a HUD group:

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `layout_mode` | string | `"auto"` | `"auto"`, `"manual"`, or `"hybrid"` |
| `anchor` | string | `"top_left"` | Screen anchor point (see below) |
| `priority` | int | `10` | Stacking priority (higher = closer to anchor) |
| `align` | string | `"top"` | Manual mode: `"top"` sticks to `y` and grows down, `"center"` stays in the middle of the area and grows both ways, `"bottom"` sticks to `y + max_height` and grows up |

### Layout Modes

- **`auto`** (default): Windows are automatically positioned and stacked based on anchor and priority
- **`manual`**: Windows live in the area `x`, `y`, `width`, `max_height` (no auto-stacking). They take no place in an anchor's stack and are kept on the screen.
- **`hybrid`**: Reserved for future use with offset adjustments

### Anchor Points

The layout system supports 9 anchor points:

```
 ┌─────────────────────────────────────────────────────┐
 │                                                     │
 │  TOP_LEFT          TOP_CENTER         TOP_RIGHT     │
 │     ↓                  ↓                  ↓         │
 │  ┌─────┐            ┌─────┐            ┌─────┐      │
 │  │     │            │     │            │     │      │
 │  └─────┘            └─────┘            └─────┘      │
 │     ↓                  ↓                  ↓         │
 │  ┌─────┐            ┌─────┐            ┌─────┐      │
 │  │     │            │     │            │     │      │
 │  └─────┘            └─────┘            └─────┘      │
 │                                                     │
 │  LEFT_CENTER                          RIGHT_CENTER  │
 │  (vertically                          (vertically   │
 │   centered)         ┌─────┐            centered)    │
 │  ┌─────┐            │  C  │            ┌─────┐      │
 │  │     │            └─────┘            │     │      │
 │  └─────┘                               └─────┘      │
 │  ┌─────┐                               ┌─────┐      │
 │  │     │                               │     │      │
 │  └─────┘                               └─────┘      │
 │                                                     │
 │  ┌─────┐            ┌─────┐            ┌─────┐      │
 │  │     │            │     │            │     │      │
 │  └─────┘            └─────┘            └─────┘      │
 │     ↑                  ↑                  ↑         │
 │  ┌─────┐            ┌─────┐            ┌─────┐      │
 │  │     │            │     │            │     │      │
 │  └─────┘            └─────┘            └─────┘      │
 │     ↑                  ↑                  ↑         │
 │  BOTTOM_LEFT      BOTTOM_CENTER     BOTTOM_RIGHT    │
 │                                                     │
 └─────────────────────────────────────────────────────┘
```

**Anchor Points Reference:**

| Anchor | Position | Stacking Direction |
|--------|----------|-------------------|
| `top_left` | Top-left corner | Downward |
| `top_center` | Top edge, centered | Downward |
| `top_right` | Top-right corner | Downward |
| `left_center` | Left edge, vertically centered | Downward (centered) |
| `center` | Screen center | No stacking |
| `right_center` | Right edge, vertically centered | Downward (centered) |
| `bottom_left` | Bottom-left corner | Upward |
| `bottom_center` | Bottom edge, centered | Upward |
| `bottom_right` | Bottom-right corner | Upward |

### Priority-Based Stacking

Windows with higher priority values are positioned closer to the anchor point:

```
Anchor: TOP_LEFT

Priority 20: ┌─────────────┐  ← Closest to corner (y=20)
             │ ATC Message │
             └─────────────┘
Priority 15: ┌─────────────┐  ← Stacks below (y=130)
             │ Navigation  │
             └─────────────┘
Priority 10: ┌─────────────┐  ← Stacks below (y=240)
             │ Persistent  │
             └─────────────┘
```

### Layout Examples

#### Multiple Groups at Same Anchor

```python
# High priority - appears at top
await client.create_group("critical_alerts", {
    "anchor": "top_right",
    "priority": 100,
    "layout_mode": "auto"
})

# Lower priority - stacks below critical alerts
await client.create_group("info_messages", {
    "anchor": "top_right",
    "priority": 50,
    "layout_mode": "auto"
})
```

#### Different Anchors for Different Types

```python
# Main wingman messages on left
await client.create_group("atc", {
    "anchor": "top_left",
    "priority": 20,
    "width": 400
})

# Status info on right
await client.create_group("system_status", {
    "anchor": "top_right",
    "priority": 15,
    "width": 350
})

# Persistent data at bottom
await client.create_group("navigation", {
    "anchor": "bottom_left",
    "priority": 10,
    "width": 450
})
```

#### Wingman Configuration Example

In a Wingman's YAML config:

```yaml
wingmen:
  atc:
    name: "ATC"
    hud:
      anchor: "top_left"
      priority: 20
      layout_mode: "auto"
      
  computer:
    name: "Computer"  
    hud:
      anchor: "top_left"
      priority: 15
      layout_mode: "auto"
      
  status:
    name: "Status Display"
    hud:
      anchor: "bottom_right"
      priority: 10
      width: 300
      layout_mode: "auto"
```

### Dynamic Behavior

#### Height Adjustment

When a window's content changes and its height increases/decreases, windows below it automatically reposition:

```
Before (ATC height=100):          After (ATC height=200):
┌─────────────┐ y=20              ┌─────────────┐ y=20
│ ATC Message │                   │             │
└─────────────┘                   │ ATC Message │
┌─────────────┐ y=130             │             │
│ Navigation  │                   └─────────────┘
└─────────────┘                   ┌─────────────┐ y=230  ← Moved down
                                  │ Navigation  │
                                  └─────────────┘
```

#### Visibility Awareness

Hidden windows (faded out, no content) don't occupy space:

```
All visible:                      Navigation hidden:
┌─────────────┐ y=20              ┌─────────────┐ y=20
│ ATC         │                   │ ATC         │
└─────────────┘                   └─────────────┘
┌─────────────┐ y=130             ┌─────────────┐ y=130  ← Moved up!
│ Navigation  │                   │ Status      │
└─────────────┘                   └─────────────┘
┌─────────────┐ y=240
│ Status      │
└─────────────┘
```

### Fallback Behavior

If the layout manager cannot determine a position, the system falls back to using the `x` and `y` properties directly from the group props.

## Markdown Support

Messages support rich Markdown formatting:

- **Bold**: `**text**` or `__text__`
- **Italic**: `*text*` or `_text_`
- **Code**: `` `inline` `` or ` ```block``` `
- **Links**: `[text](url)`
- **Images**: `![alt](url)`
- **Headers**: `# H1`, `## H2`, etc.
- **Lists**: `- item` or `1. item`
- **Blockquotes**: `> quote`
- **Tables**: Standard Markdown table syntax

## Error Handling

The server provides detailed error responses:

```json
{
  "status": "error",
  "message": "Group 'unknown' not found",
  "detail": "..."
}
```

HTTP Status Codes:
- `200` - Success
- `404` - Resource not found
- `422` - Validation error (invalid request data)
- `500` - Internal server error

### Logging

All components use `Printr` for consistent logging:

```python
from services.printr import Printr
from api.enums import LogType

printr = Printr()
printr.print("HUD Server started", color=LogType.INFO, server_only=True)
```

## Testing

Run the test suite:

```powershell
python -m hud_server.tests.run_tests
```

Individual tests:
```powershell
python -m hud_server.tests.run_tests                    # Run quick integration test
python -m hud_server.tests.run_tests --all              # Run all test suites
python -m hud_server.tests.run_tests --messages         # Run message tests
python -m hud_server.tests.run_tests --progress         # Run progress tests
python -m hud_server.tests.run_tests --persistent       # Run persistent info tests
python -m hud_server.tests.run_tests --chat             # Run chat tests
python -m hud_server.tests.run_tests --unicode          # Run Unicode/emoji stress tests
python -m hud_server.tests.run_tests --layout           # Run layout manager unit tests (no server needed)
python -m hud_server.tests.run_tests --layout-visual    # Run visual layout tests with actual HUD windows
python -m hud_server.tests.run_tests --snake            # You know this one ...
```

## Troubleshooting

### Server won't start

Check if port is already in use:
```powershell
netstat -ano | findstr :7862
```

Try a different port:
```python
server.start(port=7863)
```

### Overlay not showing

1. Check PIL is installed: `pip install Pillow`
2. Only Windows has a platform backend so far; on macOS/Linux the log says `[HUD] The HUD does not run on ... yet.`
3. Check logs for overlay errors

### Connection failures

1. Verify server is running: `http://127.0.0.1:7862/health`
2. Check firewall settings
3. Use correct host/port in client

### Multi-monitor Issues

1. Verify the correct screen index: Screen 1 is primary, Screen 2 is secondary, etc.
2. Check Windows display settings to confirm monitor order
3. Try restarting the HUD server after changing screen settings
