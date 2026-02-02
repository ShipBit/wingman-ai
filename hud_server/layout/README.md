# HUD Layout Manager

The Layout Manager provides automatic positioning and stacking for HUD elements to prevent overlapping windows.

## Overview

When multiple HUD groups are active (e.g., messages from different wingmen, persistent info panels, chat windows), they can overlap if positioned at similar coordinates. The Layout Manager solves this by:

1. **Anchor-based positioning**: Windows anchor to screen corners (top-left, top-right, bottom-left, bottom-right)
2. **Automatic stacking**: Windows at the same anchor stack vertically with configurable spacing
3. **Priority ordering**: Higher priority windows are positioned closer to the anchor point
4. **Dynamic reflow**: When window heights change, other windows reposition automatically
5. **Visibility awareness**: Hidden windows don't take up space in the layout

## Configuration

### Layout Properties

These properties can be set when creating or updating a HUD group:

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `layout_mode` | string | `"auto"` | `"auto"`, `"manual"`, or `"hybrid"` |
| `anchor` | string | `"top_left"` | `"top_left"`, `"top_right"`, `"bottom_left"`, `"bottom_right"`, `"center"` |
| `priority` | int | `10` | Stacking priority (higher = closer to anchor) |
| `margin` | int | `20` | Margin from screen edge (pixels) |
| `spacing` | int | `10` | Space between stacked windows (pixels) |

### Layout Modes

- **`auto`** (default): Windows are automatically positioned and stacked based on anchor and priority
- **`manual`**: Windows use the `x` and `y` properties directly (no auto-stacking)
- **`hybrid`**: Not yet implemented; reserved for future use with offset adjustments

### Anchor Points

```
 ┌───────────────────────────────────────────────────────────┐
 │                                                           │
 │  TOP_LEFT         TOP_CENTER          TOP_RIGHT           │
 │     ↓                 ↓                   ↓               │
 │  ┌─────┐          ┌─────┐            ┌─────┐              │
 │  │     │          │     │            │     │              │
 │  └─────┘          └─────┘            └─────┘              │
 │     ↓                 ↓                   ↓               │
 │  ┌─────┐          ┌─────┐            ┌─────┐              │
 │  │     │          │     │            │     │              │
 │  └─────┘          └─────┘            └─────┘              │
 │                                                           │
 │  LEFT_CENTER                          RIGHT_CENTER        │
 │  (vertically                          (vertically         │
 │   centered)       ┌─────┐              centered)          │
 │  ┌─────┐          │  C  │            ┌─────┐              │
 │  │     │          └─────┘            │     │              │
 │  └─────┘                             └─────┘              │
 │  ┌─────┐                             ┌─────┐              │
 │  │     │                             │     │              │
 │  └─────┘                             └─────┘              │
 │                                                           │
 │  ┌─────┐          ┌─────┐            ┌─────┐              │
 │  │     │          │     │            │     │              │
 │  └─────┘          └─────┘            └─────┘              │
 │     ↑                 ↑                   ↑               │
 │  ┌─────┐          ┌─────┐            ┌─────┐              │
 │  │     │          │     │            │     │              │
 │  └─────┘          └─────┘            └─────┘              │
 │     ↑                 ↑                   ↑               │
 │  BOTTOM_LEFT     BOTTOM_CENTER      BOTTOM_RIGHT          │
 │                                                           │
 └───────────────────────────────────────────────────────────┘
```

**9 Anchor Points:**

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

## Usage Examples

### API Example: Create groups with auto-layout

```python
import httpx

# Create a high-priority wingman group (messages appear at top)
httpx.post("http://127.0.0.1:7862/group", json={
    "group_name": "ATC",
    "props": {
        "anchor": "top_left",
        "priority": 20,
        "margin": 20,
        "spacing": 10,
        "layout_mode": "auto"
    }
})

# Create a lower-priority group (stacks below ATC)
httpx.post("http://127.0.0.1:7862/group", json={
    "group_name": "Navigation",
    "props": {
        "anchor": "top_left",
        "priority": 10,
        "margin": 20,
        "spacing": 10,
        "layout_mode": "auto"
    }
})

# Create a group on the right side of the screen
httpx.post("http://127.0.0.1:7862/group", json={
    "group_name": "System",
    "props": {
        "anchor": "top_right",
        "priority": 15,
        "width": 350
    }
})
```

### Skill Configuration Example

In a Wingman's config, you can set layout properties:

```yaml
wingmen:
  atc:
    name: "ATC"
    hud:
      anchor: "top_left"
      priority: 20
      margin: 20
      spacing: 10
      
  computer:
    name: "Computer"  
    hud:
      anchor: "top_left"
      priority: 15
      margin: 20
      spacing: 10
      
  status:
    name: "Status Display"
    hud:
      anchor: "bottom_right"
      priority: 10
      width: 300
```

## Behavior Details

### Priority-based Stacking

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

### Dynamic Height Adjustment

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

### Visibility and Layout

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

## Fallback Behavior

If the layout manager cannot determine a position (edge cases), the system falls back to using the `x` and `y` properties directly from the group props.

## Testing

Run layout manager tests:

```bash
python -m hud_server.tests.run_tests --layout
```

This runs unit tests that verify:
- Basic vertical stacking
- Multiple anchor support
- Visibility handling
- Dynamic height updates
- Manual mode positioning
- Collision detection
