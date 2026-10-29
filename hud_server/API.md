# HUD Server API Reference

Complete API reference for the Wingman AI HUD Server REST API.

**Base URL**: `http://127.0.0.1:7862`

**Content-Type**: `application/json`

---

## Table of Contents

- [Health & Status](#health--status)
- [Groups](#groups)
- [Defaults](#defaults)
- [Shared Containers](#shared-containers)
- [Preview](#preview)
- [Messages](#messages)
- [Loader](#loader)
- [Persistent Items](#persistent-items)
- [Progress & Timers](#progress--timers)
- [Chat Windows](#chat-windows)
- [OBS Studio & Web Streaming](#obs-studio--web-streaming)
- [Error Responses](#error-responses)

---

## Health & Status

### GET /health

Check server health and get list of active groups.

**Response**: `200 OK`

```json
{
  "status": "healthy",
  "groups": ["wingman1", "wingman2"],
  "version": "1.0.0"
}
```

### GET /

Root endpoint - same as `/health`.

---

## Groups

### POST /groups

Create or update a HUD group.

**Request Body**:

A group is a name plus an element: `message` (one message at a time),
`persistent` (items, progress bars, timers) or `chat`. The same name can have
one group per element.

```json
{
  "group_name": "my_wingman",
  "element": "message",
  "props": {
    "x": 20,
    "y": 20,
    "width": 400,
    "max_height": 600,
    "bg_color": "#1e212b",
    "text_color": "#f0f0f0",
    "accent_color": "#00aaff",
    "opacity": 0.85,
    "border_radius": 12,
    "font_size": 16,
    "font_family": "Segoe UI",
    "typewriter_effect": true,
    "typewriter_speed": 200,
    "auto_fade": true,
    "fade_delay": 8.0,
    "layout_mode": "auto",
    "anchor": "top_left",
    "priority": 10
  }
}
```

**Response**: `200 OK`

```json
{
  "status": "ok",
  "message": "Group 'my_wingman' created"
}
```

### PUT /groups/{group_name}/{element}

Update properties of an existing group (real-time updates). `PATCH` works the
same. Windows follow right away, position and layout mode included.

**URL Parameters**:
- `group_name` (string): Name of the group to update
- `element` (string): `message`, `persistent` or `chat`

**Request Body**:

```json
{
  "props": {
    "opacity": 0.9,
    "font_size": 18
  }
}
```

**Response**: `200 OK`

```json
{
  "status": "ok",
  "message": "Group 'my_wingman' updated"
}
```

### DELETE /groups/{group_name}/{element}

Delete a HUD group. Only that element's window goes.

**URL Parameters**:
- `group_name` (string): Name of the group to delete
- `element` (string): `message`, `persistent` or `chat`

**Response**: `200 OK`

```json
{
  "status": "ok",
  "message": "Group 'my_wingman' deleted"
}
```

### GET /groups

Get list of all group names.

**Response**: `200 OK`

```json
{
  "groups": ["wingman1", "wingman2", "alerts"]
}
```

### Placement props

| Prop | Meaning |
|---|---|
| `layout_mode` | `auto`: stack at `anchor` with other windows there. `manual`: a free area at `x`/`y`, `width` wide and up to `max_height` high. A manual window takes no place in an anchor's stack. |
| `anchor`, `priority` | Auto mode: the screen corner or edge, and the order there (higher = closer to it). |
| `x`, `y`, `width`, `max_height` | Manual mode: the area, in pixels on the HUD screen. |
| `align` | Manual mode: `top` (default) sticks to `y` and grows down, `center` stays in the middle of the area and grows both ways, `bottom` sticks to `y + max_height` and grows up. |

---

## Defaults

Props a group's own calls leave out come from the server's defaults. The
resolution order for every window is:

1. built-in values,
2. `props` of the defaults (for every group),
3. `groups[group_name]` of the defaults,
4. the group's own props (`POST /groups`, `PUT /groups/...`),
5. the props sent with a call (`POST /message` ...).

Changing the defaults restyles and moves existing windows right away. Wingman
AI Core sets them from the active HUD profile.

### GET /defaults

**Response**: `200 OK`

```json
{
  "props": {"font_size": 16, "accent_color": "#00aaff", "opacity": 0.85},
  "groups": {
    "wingman_chat": {"layout_mode": "manual", "x": 20, "y": 20, "width": 400, "max_height": 500, "align": "top"}
  }
}
```

### PUT /defaults

Replace the defaults. Same body as the response above.

---

## Shared Containers

Wingman AI Core writes the conversation of every Wingman to one chat container
and their info panels to one info panel:

| Group | Element | Content |
|---|---|---|
| `wingman_chat` | `message` | The conversation, one message at a time |
| `wingman_info` | `persistent` | Info panels, progress bars, timers |

Their place and look come from the defaults (`groups.wingman_chat`,
`groups.wingman_info`). Other programs can write to them like to any group.

---

## Preview

Shows the shared containers as preview panels: sample content in their real
style, always filling the whole area. While a preview runs, the real
containers are hidden.

### PUT /preview

`POST` works the same.

```json
{
  "containers": {
    "chat": {"x": 20, "y": 20, "width": 400, "max_height": 500, "font_size": 16, "accent_color": "#00aaff"},
    "info": {"x": 20, "y": 540, "width": 400, "max_height": 500}
  },
  "interactive": true
}
```

With `interactive`, the mouse moves a panel (drag the middle) and resizes it
(drag an edge or corner). The new area is reported to in-process listeners
(`HudServer.add_event_listener`) as a `preview_changed` event and shows in
`GET /preview`.

### GET /preview

```json
{
  "active": true,
  "interactive": true,
  "containers": {"chat": {"x": 120, "y": 80, "width": 600, "max_height": 400}}
}
```

### DELETE /preview

End the preview; the real containers come back.

---

## Messages

### POST /message

Show a message in a HUD group.

**Request Body**:

```json
{
  "group_name": "my_wingman",
  "title": "Hello!",
  "content": "This is a **Markdown** message with `code` and [links](https://example.com).",
  "color": "#00ff00",
  "tools": [
    {
      "name": "search",
      "status": "active"
    }
  ],
  "props": {
    "typewriter_effect": false
  },
  "duration": 10.0
}
```

**Fields**:
- `group_name` (string, required): Target group name
- `title` (string, required): Message title (1-200 chars)
- `content` (string, required): Message content with Markdown support (max 50000 chars)
- `color` (string, optional): Hex color for title/accent (#RRGGBB)
- `tools` (array, optional): Tool information for display
- `props` (object, optional): Property overrides for this message
- `duration` (number, optional): Auto-hide after N seconds (0.1-3600)

**Response**: `200 OK`

```json
{
  "status": "ok"
}
```

### POST /message/append

Append content to the current message (for streaming).

**Request Body**:

```json
{
  "group_name": "my_wingman",
  "content": " Additional text..."
}
```

**Response**: `200 OK`

```json
{
  "status": "ok"
}
```

### POST /message/hide/{group_name}/{element}

Hide the current message in a group.

**URL Parameters**:
- `group_name` (string): Target group name

**Response**: `200 OK`

```json
{
  "status": "ok"
}
```

---

## Loader

### POST /loader

Show or hide the loader animation.

**Request Body**:

```json
{
  "group_name": "my_wingman",
  "element": "message",
  "show": true,
  "color": "#00aaff"
}
```

**Fields**:
- `group_name` (string, required): Target group name
- `element` (string, required): `message`, or `chat` for the group's chat window
- `show` (boolean, required): Show (true) or hide (false)
- `color` (string, optional): Hex color for loader (#RRGGBB). Without it, the loader uses the group's `accent_color`.

**Response**: `200 OK`

```json
{
  "status": "ok"
}
```

---

## Persistent Items

### POST /items

Add a persistent item to a group.

**Request Body**:

```json
{
  "group_name": "my_wingman",
  "title": "Status",
  "description": "System operational",
  "color": "#00ff00",
  "duration": 30.0,
  "added_by": "Computer"
}
```

**Fields**:
- `group_name` (string, required): Target group name
- `title` (string, required): Item title/identifier (unique within group)
- `description` (string, optional): Item description
- `color` (string, optional): Hex color (#RRGGBB)
- `duration` (number, optional): Auto-remove after N seconds
- `added_by` (string, optional): Who adds it, e.g. a Wingman's name. Not drawn; kept for whoever reads the panel. `POST /progress` and `POST /timer` take it too.

**Response**: `200 OK`

```json
{
  "status": "ok"
}
```

### PUT /items

Update an existing item.

**Request Body**:

```json
{
  "group_name": "my_wingman",
  "title": "Status",
  "description": "Updated description",
  "color": "#ffaa00"
}
```

**Response**: `200 OK`

```json
{
  "status": "ok"
}
```

### DELETE /items/{group_name}/{element}/{title}

Remove an item from a group.

**URL Parameters**:
- `group_name` (string): Target group name
- `title` (string): Item title to remove

**Response**: `200 OK`

```json
{
  "status": "ok"
}
```

### DELETE /items/{group_name}/{element}

Clear all items from a group.

**URL Parameters**:
- `group_name` (string): Target group name

**Response**: `200 OK`

```json
{
  "status": "ok"
}
```

---

## Progress & Timers

### POST /progress

Show or update a progress bar.

**Request Body**:

```json
{
  "group_name": "my_wingman",
  "title": "Loading",
  "current": 50,
  "maximum": 100,
  "description": "Processing files...",
  "color": "#00aaff",
  "auto_close": false,
  "props": {}
}
```

**Fields**:
- `group_name` (string, required): Target group name
- `title` (string, required): Progress bar title
- `current` (number, required): Current value
- `maximum` (number, optional): Maximum value (default: 100)
- `description` (string, optional): Progress description
- `color` (string, optional): Hex color for progress bar (#RRGGBB)
- `auto_close` (boolean, optional): Auto-close when complete (default: false)
- `props` (object, optional): Property overrides

**Response**: `200 OK`

```json
{
  "status": "ok"
}
```

### POST /timer

Show a countdown timer.

**Request Body**:

```json
{
  "group_name": "my_wingman",
  "title": "Cooldown",
  "duration": 60.0,
  "description": "Ability recharging...",
  "color": "#ff9900",
  "auto_close": true,
  "initial_progress": 10.0,
  "props": {}
}
```

**Fields**:
- `group_name` (string, required): Target group name
- `title` (string, required): Timer title
- `duration` (number, required): Total duration in seconds
- `description` (string, optional): Timer description
- `color` (string, optional): Hex color (#RRGGBB)
- `auto_close` (boolean, optional): Auto-close when complete (default: true)
- `initial_progress` (number, optional): Start at N seconds (for resume)
- `props` (object, optional): Property overrides

**Response**: `200 OK`

```json
{
  "status": "ok"
}
```

---

## Chat Windows

### POST /chat/window

Create a new chat window.

**Request Body**:

```json
{
  "name": "team_chat",
  "x": 20,
  "y": 20,
  "width": 400,
  "max_height": 400,
  "auto_hide": false,
  "auto_hide_delay": 10.0,
  "max_messages": 50,
  "sender_colors": {
    "Alice": "#ff6b6b",
    "Bob": "#4ecdc4"
  },
  "fade_old_messages": true,
  "props": {}
}
```

**Fields**:
- `name` (string, required): Unique chat window name
- `x` (integer, optional): X position (default: 20)
- `y` (integer, optional): Y position (default: 20)
- `width` (integer, optional): Width in pixels (default: 400)
- `max_height` (integer, optional): Max height (default: 400)
- `auto_hide` (boolean, optional): Auto-hide when inactive (default: false)
- `auto_hide_delay` (number, optional): Delay before auto-hide in seconds (default: 10.0)
- `max_messages` (integer, optional): Max message history (default: 50)
- `sender_colors` (object, optional): Per-sender color overrides
- `fade_old_messages` (boolean, optional): Fade older messages (default: true)
- `props` (object, optional): Additional properties

**Response**: `200 OK`

```json
{
  "status": "ok",
  "message": "Chat window 'team_chat' created"
}
```

### POST /chat/message

Send a message to a chat window.

**Request Body**:

```json
{
  "group_name": "team_chat",
  "element": "chat",
  "sender": "Alice",
  "text": "Hello everyone!",
  "color": "#ff6b6b",
  "icon": "C:/avatars/alice.png"
}
```

**Fields**:
- `group_name` (string, required): The chat window's group. The window appears with its first message.
- `element` (string, required): `chat`
- `sender` (string, required): Sender name
- `text` (string, required): Message text (Markdown)
- `color` (string, optional): Sender color override (#RRGGBB)
- `icon` (string, optional): Path of the sender's picture, shown round next to the message. Without one, a circle with the sender's initial.
- `own` (boolean, optional): Written by the user: a bubble on the right, like in a messenger
- `tools` (list, optional): Tool chips under the message, as for a message window

Every message is an entry of its own. Only `tools` without `text` join the
sender's last entry, shown under what it said before calling them; the
response then carries that entry's ID.

**Response**: `200 OK`

```json
{
  "status": "ok",
  "message_id": "6f1c..."
}
```

### DELETE /chat/messages/{window_name}

Clear all messages from a chat window.

**URL Parameters**:
- `window_name` (string): Target chat window name

**Response**: `200 OK`

```json
{
  "status": "ok"
}
```

### POST /chat/show/{name}

Show a hidden chat window.

**URL Parameters**:
- `name` (string): Chat window name

**Response**: `200 OK`

```json
{
  "status": "ok"
}
```

### POST /chat/hide/{name}

Hide a chat window.

**URL Parameters**:
- `name` (string): Chat window name

**Response**: `200 OK`

```json
{
  "status": "ok"
}
```

### DELETE /chat/window/{name}

Delete a chat window.

**URL Parameters**:
- `name` (string): Chat window name

**Response**: `200 OK`

```json
{
  "status": "ok"
}
```

---

## OBS Studio & Web Streaming

### GET /obs

The page to add as an OBS Browser Source: the HUD on a transparent background,
the size of the HUD's screen, fixed to its pixel size.

**Response**: `200 OK` (`text/html`)

### GET /obs/chat

Dedicated Browser Source page for only the Chat panel, sized to its container
pixel dimensions with transparent background.

**Response**: `200 OK` (`text/html`)

### GET /obs/info

Dedicated Browser Source page for only the Info panel, sized to its container
pixel dimensions with transparent background.

**Response**: `200 OK` (`text/html`)

### WS /obs/ws

The HUD windows for the `/obs` pages, each sent on its own whenever it changes.
Accepts an optional `channel` query parameter (`?channel=all|chat|info`, defaults to `all`),
or path `/obs/{channel}/ws`. Clients on `chat` or `info` channels only receive windows
belonging to their container, with coordinates translated relative to the container canvas.
Pictures, `state`, `hide` and `clear` carry a sequence number `seq` that rises
with each change. They can arrive out of order, and a client that falls behind
gets only the newest of each per window: a client ignores anything older than
what it shows, and after a `clear` anything at or below its `seq`. Only pages
of this server may connect: a handshake with another `Origin`, or with a `Host`
that is not an IP address or `localhost`, is refused.

Text messages (JSON):
- `{"type": "init", "width": <w>, "height": <h>, "fps": <fps>, "channel": <chan>}` on connect;
  every visible matching window follows as a picture.
- `{"type": "resize", "width": <w>, "height": <h>, "channel": <chan>}` when the screen or container changes size.
- `{"type": "state", "id": <window>, "seq": <n>, "x": <x>, "y": <y>, "opacity": <0..1>}`
  when a window moves or fades.
- `{"type": "hide", "id": <window>, "seq": <n>}` when a window has faded out or is gone.
- `{"type": "clear", "seq": <n>}` when the overlay stops.

Binary messages carry a window's new picture: a 4-byte big-endian header length,
a JSON header `{"id", "seq", "state", "x", "y", "opacity"}` and a PNG. `seq` is
the picture's sequence number, `state` that of the position and opacity in the
header.

### GET /obs/frame.png

The HUD as it is now, as one transparent PNG the size of its screen.

**Response**: `200 OK` (`image/png`), or `403` for a request from another site's page or
to a `Host` that is not an IP address or `localhost`

### GET /obs/chat/frame.png

The chat container as one transparent PNG the size of its canvas.

**Response**: `200 OK` (`image/png`)

### GET /obs/info/frame.png

The info container as one transparent PNG the size of its canvas.

**Response**: `200 OK` (`image/png`)

### GET /obs/status

Connected Browser Sources, the HUD screen's size, container sizes, and the number of windows shown.
`width` and `height` are in the HUD's pixels (scaled on Windows), the size to
give the Browser Source.

**Response**: `200 OK`
```json
{
  "subscribers": 1,
  "width": 1920,
  "height": 1080,
  "fps": 60,
  "windows": 2,
  "chat": {"width": 432, "height": 532},
  "info": {"width": 432, "height": 532}
}
```

---

## Error Responses

All errors follow this format:

### 404 Not Found

```json
{
  "status": "error",
  "message": "Group 'unknown' not found"
}
```

### 422 Validation Error

```json
{
  "status": "error",
  "message": "Validation error",
  "detail": [
    {
      "loc": ["body", "title"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

### 500 Internal Server Error

```json
{
  "status": "error",
  "message": "Internal server error",
  "detail": "Exception details..."
}
```

---

## Color Format

All color fields accept hex format: `#RRGGBB`

Examples:
- `#ff0000` - Red
- `#00ff00` - Green
- `#0000ff` - Blue
- `#ffffff` - White
- `#000000` - Black
- `#1e212b` - Dark gray (default background)

---

## Markdown Support

Message content supports the following Markdown features:

- **Bold**: `**text**` or `__text__`
- **Italic**: `*text*` or `_text_`
- **Code**: `` `inline` `` or ` ```block``` `
- **Links**: `[text](url)`
- **Images**: `![alt](url)`
- **Headers**: `# H1`, `## H2`, `### H3`, etc.
- **Lists**: `- item` or `1. item`
- **Blockquotes**: `> quote`
- **Horizontal Rules**: `---` or `***`
- **Tables**: Standard Markdown table syntax

---

## Rate Limits

No rate limits are currently enforced, but avoid:
- Sending more than 100 requests/second per group
- Creating more than 1000 groups

---

## Interactive API Documentation

When the server is running, visit `http://127.0.0.1:7862/docs` for interactive Swagger UI documentation with request/response examples and a "Try it out" feature.
