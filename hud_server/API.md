# HUD Server API Reference

Complete API reference for the Wingman AI HUD Server REST API.

**Base URL**: `http://127.0.0.1:7862`

**Content-Type**: `application/json`

---

## Table of Contents

- [Health & Status](#health--status)
- [Groups](#groups)
- [Messages](#messages)
- [Loader](#loader)
- [Persistent Items](#persistent-items)
- [Progress & Timers](#progress--timers)
- [Chat Windows](#chat-windows)
- [State Management](#state-management)
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

```json
{
  "group_name": "my_wingman",
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

### PATCH /groups/{group_name}

Update properties of an existing group (real-time updates).

**URL Parameters**:
- `group_name` (string): Name of the group to update

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

### DELETE /groups/{group_name}

Delete a HUD group.

**URL Parameters**:
- `group_name` (string): Name of the group to delete

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

### POST /message/hide/{group_name}

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
  "show": true,
  "color": "#00aaff"
}
```

**Fields**:
- `group_name` (string, required): Target group name
- `show` (boolean, required): Show (true) or hide (false)
- `color` (string, optional): Hex color for loader (#RRGGBB)

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
  "duration": 30.0
}
```

**Fields**:
- `group_name` (string, required): Target group name
- `title` (string, required): Item title/identifier (unique within group)
- `description` (string, optional): Item description
- `color` (string, optional): Hex color (#RRGGBB)
- `duration` (number, optional): Auto-remove after N seconds

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

### DELETE /items/{group_name}/{title}

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

### DELETE /items/{group_name}

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
  "window_name": "team_chat",
  "sender": "Alice",
  "text": "Hello everyone!",
  "color": "#ff6b6b"
}
```

**Fields**:
- `window_name` (string, required): Target chat window name
- `sender` (string, required): Sender name
- `text` (string, required): Message text
- `color` (string, optional): Sender color override (#RRGGBB)

**Response**: `200 OK`

```json
{
  "status": "ok"
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

## State Management

### GET /state/{group_name}

Get the current state of a group for persistence.

**URL Parameters**:
- `group_name` (string): Target group name

**Response**: `200 OK`

```json
{
  "group_name": "my_wingman",
  "state": {
    "props": { ... },
    "current_message": { ... },
    "items": { ... },
    "chat_messages": [ ... ],
    "loader_visible": false,
    "is_chat_window": false,
    "visible": true
  }
}
```

### POST /state/restore

Restore a group's state from a previous snapshot.

**Request Body**:

```json
{
  "group_name": "my_wingman",
  "state": {
    "props": { ... },
    "items": { ... }
  }
}
```

**Response**: `200 OK`

```json
{
  "status": "ok",
  "message": "State restored for 'my_wingman'"
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
- Storing more than 10MB of state per group

---

## Interactive API Documentation

When the server is running, visit `http://127.0.0.1:7862/docs` for interactive Swagger UI documentation with request/response examples and a "Try it out" feature.
