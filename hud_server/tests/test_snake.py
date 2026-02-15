# -*- coding: utf-8 -*-
"""
Test Snake - Interactive Snake game using the HUD Server.

An advanced Snake game implementation featuring:
- Each grid cell is its own HUD window positioned across the screen
- HUDs are created on-demand (only for snake and food, not empty cells)
- Manual window placement to create a full-screen grid
- Keyboard controls (arrow keys)
- HUD messages for start/game over screens and stats

Features:
- 🌈 Snake body gradient (head to tail color fade)
- ∞ Endless mode (no time limit)
- 🔥 Combo system for eating quickly (2s window)
- 🍎 Multiple foods on screen simultaneously
- 🌟 Rare golden apples worth +5 points
- 🎨 Animated border colors that change with score
- 📊 Real-time stats with combo display

Usage:
    python -m hud_server.tests.test_snake
"""

import asyncio
import time
import random
from enum import Enum
from hud_server.tests.test_session import TestSession
from hud_server.types import Anchor, LayoutMode, HudColor, MessageProps, WindowType

try:
    import keyboard.keyboard as keyboard
except ImportError:
    import keyboard


# =============================================================================
# Game Constants
# =============================================================================

# Screen configuration (assumed 1920x1080, adjust if needed)
SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080

# Cell configuration
CELL_SIZE = 32  # Size of each HUD window in pixels
CELL_PADDING = 2  # Padding between cells

# Calculate grid size to fit screen (leaving margins for stats panel)
MARGIN_TOP = 80  # Space for stats
MARGIN_BOTTOM = 50
MARGIN_LEFT = 50
MARGIN_RIGHT = 200  # Space for stats panel on right

# Calculate playable area
PLAYABLE_WIDTH = SCREEN_WIDTH - MARGIN_LEFT - MARGIN_RIGHT
PLAYABLE_HEIGHT = SCREEN_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM

# Grid dimensions (auto-calculated)
GRID_WIDTH = PLAYABLE_WIDTH // (CELL_SIZE + CELL_PADDING)
GRID_HEIGHT = PLAYABLE_HEIGHT // (CELL_SIZE + CELL_PADDING)

# Screen offset (top-left of play area)
SCREEN_OFFSET_X = MARGIN_LEFT
SCREEN_OFFSET_Y = MARGIN_TOP

# Game timing
GAME_DURATION = None  # None = endless mode, no time limit
INITIAL_SPEED = 0.125  # seconds between moves
SPEED_INCREMENT = 0.0025  # speed increase per food eaten
MIN_SPEED = 0.035  # fastest possible speed (faster for endless mode)

# Multi-food system
MAX_FOODS = 1  # Maximum number of regular foods on screen
GOLDEN_APPLE_CHANCE = 0.15  # 15% chance for golden apple
GOLDEN_APPLE_POINTS = 5
GOLDEN_APPLE_DURATION = 10  # seconds before it disappears

# Combo system
COMBO_TIME_WINDOW = 2.0  # seconds to maintain combo
COMBO_MULTIPLIER = 0.5  # bonus points per combo level

# Cell types for display
CELL_EMPTY = "empty"
CELL_SNAKE_HEAD = "snake_head"
CELL_SNAKE_BODY = "snake_body"
CELL_FOOD = "food"
CELL_GOLDEN_FOOD = "golden_food"
CELL_BORDER = "border"

# Colors for different cell types
COLORS = {
    CELL_EMPTY: "#1a1a2e",
    CELL_SNAKE_HEAD: "#00ff00",
    CELL_SNAKE_BODY: "#00aa00",
    CELL_FOOD: "#ff3333",
    CELL_GOLDEN_FOOD: "#ffd700",  # Gold
    CELL_BORDER: "#0066cc",
}

# Border color progression based on speed/score (extended for endless mode)
BORDER_COLORS = [
    "#0066cc",  # 0 - Initial blue
    "#0088ff",  # 2 - Light blue
    "#00aaff",  # 4 - Cyan
    "#00cccc",  # 6 - Turquoise
    "#00cc88",  # 8 - Teal
    "#00cc44",  # 10 - Green-blue
    "#44cc00",  # 12 - Green
    "#88cc00",  # 14 - Yellow-green
    "#cccc00",  # 16 - Yellow
    "#cc8800",  # 18 - Orange
    "#cc4400",  # 20 - Red-orange
    "#cc0000",  # 22 - Red
    "#cc0044",  # 24 - Pink-red
    "#cc0088",  # 26 - Magenta
    "#8800cc",  # 28 - Purple
    "#4400cc",  # 30 - Blue-purple
    "#0044cc",  # 32 - Deep blue
    "#00ccaa",  # 34 - Aqua
    "#ccaa00",  # 36 - Gold
    "#cc00cc",  # 38 - Fuchsia
    "#00ffff",  # 40 - Bright cyan
    "#ff00ff",  # 42 - Bright magenta
    "#ffff00",  # 44 - Bright yellow
    "#ff6600",  # 46 - Bright orange
    "#ff0066",  # 48 - Hot pink
    "#6600ff",  # 50+ - Electric purple
]

# Snake body gradient colors (head to tail)
def get_snake_body_color(index: int, total_length: int) -> str:
    """Calculate gradient color for snake body segment."""
    if index == 0:
        return COLORS[CELL_SNAKE_HEAD]  # Head is always bright green

    # Gradient from bright to dark green
    ratio = index / max(total_length - 1, 1)
    # Start: #00ff00 (bright green), End: #003300 (dark green)
    r = 0
    g = int(255 * (1 - ratio * 0.8))  # 255 -> 51
    b = 0
    return f"#{r:02x}{g:02x}{b:02x}"

# Colors
COLOR_GAME = "#00ff00"
COLOR_GAME_OVER = "#ff0000"

# Current border color index
_current_border_color_index = 0


def _menu_props(priority: int, accent_color: str = COLOR_GAME, bg_color: str = "#0a0e14",
                width: int = 600, font_size: int = 14) -> MessageProps:
    """Create MessageProps for menu screens."""
    return MessageProps(
        anchor=Anchor.TOP_LEFT.value,
        priority=priority,
        layout_mode=LayoutMode.AUTO.value,
        width=width,
        bg_color=bg_color,
        text_color="#f0f0f0",
        accent_color=accent_color,
        opacity=0.98,
        border_radius=12,
        font_size=font_size,
        content_padding=20,
        typewriter_effect=False,
    )


def _stats_props() -> MessageProps:
    """Create MessageProps for stats display."""
    return MessageProps(
        anchor=Anchor.TOP_RIGHT.value,
        priority=100,
        layout_mode=LayoutMode.AUTO.value,
        width=350,
        bg_color="#0a0e14",
        text_color="#f0f0f0",
        accent_color=COLOR_GAME,
        opacity=0.95,
        border_radius=8,
        font_size=14,
        content_padding=12,
        typewriter_effect=False,
    )


# =============================================================================
# Game Logic
# =============================================================================

class Direction(Enum):
    UP = (0, -1)
    DOWN = (0, 1)
    LEFT = (-1, 0)
    RIGHT = (1, 0)


class SnakeGame:
    """Snake game logic."""

    def __init__(self, width: int = GRID_WIDTH, height: int = GRID_HEIGHT):
        self.width = width
        self.height = height
        self.reset()

    def reset(self):
        """Reset the game state."""
        start_x = self.width // 2
        start_y = self.height // 2
        self.snake = [(start_x, start_y), (start_x - 1, start_y), (start_x - 2, start_y)]
        self.direction = Direction.RIGHT
        self.next_direction = Direction.RIGHT

        # Multi-food system
        self.foods = []  # List of regular food positions
        self.golden_food = None  # Golden apple position (if any)
        self.golden_food_spawn_time = None  # When golden apple spawned

        # Spawn initial foods
        for _ in range(MAX_FOODS):
            self.foods.append(self._spawn_food())

        # Combo system
        self.combo = 0
        self.combo_last_time = None

        self.score = 0
        self.game_over = False
        self.game_over_reason = ""

    def _spawn_food(self, force_golden: bool = False) -> tuple[int, int]:
        """Spawn food at a random empty location."""
        while True:
            x = random.randint(0, self.width - 1)
            y = random.randint(0, self.height - 1)
            # Check if position is empty (not snake, not other food, not golden food)
            if (x, y) not in self.snake and \
               (x, y) not in self.foods and \
               (x, y) != self.golden_food:
                return (x, y)

    def _spawn_golden_food(self):
        """Try to spawn a golden apple."""
        if self.golden_food is None and random.random() < GOLDEN_APPLE_CHANCE:
            self.golden_food = self._spawn_food(force_golden=True)
            self.golden_food_spawn_time = time.time()

    def _check_golden_food_timeout(self):
        """Remove golden food if it's been too long."""
        if self.golden_food and self.golden_food_spawn_time:
            if time.time() - self.golden_food_spawn_time > GOLDEN_APPLE_DURATION:
                self.golden_food = None
                self.golden_food_spawn_time = None

    def _update_combo(self):
        """Update combo counter."""
        current_time = time.time()
        if self.combo_last_time and current_time - self.combo_last_time <= COMBO_TIME_WINDOW:
            self.combo += 1
        else:
            self.combo = 1
        self.combo_last_time = current_time

    def _reset_combo(self):
        """Reset combo when window expires."""
        if self.combo_last_time:
            if time.time() - self.combo_last_time > COMBO_TIME_WINDOW:
                self.combo = 0
                self.combo_last_time = None

    def set_direction(self, direction: Direction):
        """Set the next direction (will be applied on next update)."""
        current = self.direction
        if (direction == Direction.UP and current != Direction.DOWN) or \
           (direction == Direction.DOWN and current != Direction.UP) or \
           (direction == Direction.LEFT and current != Direction.RIGHT) or \
           (direction == Direction.RIGHT and current != Direction.LEFT):
            self.next_direction = direction

    def update(self):
        """Update the game state (move snake, check collisions, etc.)."""
        if self.game_over:
            return

        # Check combo timeout
        self._reset_combo()

        # Check golden food timeout
        self._check_golden_food_timeout()

        self.direction = self.next_direction
        head_x, head_y = self.snake[0]
        dx, dy = self.direction.value
        new_head = (head_x + dx, head_y + dy)

        # Check wall collision
        if new_head[0] < 0 or new_head[0] >= self.width or \
           new_head[1] < 0 or new_head[1] >= self.height:
            self.game_over = True
            self.game_over_reason = "Hit the wall!"
            return

        # Check self collision
        if new_head in self.snake:
            self.game_over = True
            self.game_over_reason = "Bit yourself!"
            return

        self.snake.insert(0, new_head)

        ate_food = False

        # Check golden food collision
        if new_head == self.golden_food:
            ate_food = True
            self._update_combo()
            bonus = GOLDEN_APPLE_POINTS + int(self.combo * COMBO_MULTIPLIER)
            self.score += bonus
            self.golden_food = None
            self.golden_food_spawn_time = None
            # Keep snake growing for all points
            for _ in range(GOLDEN_APPLE_POINTS - 1):
                pass  # Snake will grow by not popping tail
        # Check regular food collision
        elif new_head in self.foods:
            ate_food = True
            self._update_combo()
            bonus = 1 + int(self.combo * COMBO_MULTIPLIER)
            self.score += bonus
            self.foods.remove(new_head)
            # Spawn new food
            self.foods.append(self._spawn_food())
            # Try to spawn golden apple
            self._spawn_golden_food()

        if not ate_food:
            self.snake.pop()

        return ate_food  # Return whether food was eaten


# =============================================================================
# HUD Cell Management - On-demand creation
# =============================================================================

def get_cell_position(x: int, y: int) -> tuple[int, int]:
    """Calculate screen position for a grid cell. Supports negative coords for borders."""
    screen_x = SCREEN_OFFSET_X + (x * (CELL_SIZE + CELL_PADDING))
    screen_y = SCREEN_OFFSET_Y + (y * (CELL_SIZE + CELL_PADDING))
    return (screen_x, screen_y)


def get_cell_group_name(x: int, y: int) -> str:
    """Get the HUD group name for a cell. Handles negative coords for borders."""
    # Use 'n' prefix for negative numbers to avoid invalid group names
    x_str = f"n{abs(x)}" if x < 0 else str(x)
    y_str = f"n{abs(y)}" if y < 0 else str(y)
    return f"snake_cell_{x_str}_{y_str}"


# Track which cells currently have HUDs
_active_cell_huds: set = set()

# Track border positions for color animation
_border_positions: list = []


def get_border_positions(game: SnakeGame) -> list[tuple[int, int]]:
    """Get all border cell positions in clockwise order starting from top-left."""
    positions = []

    # Top border (left to right, including both corners)
    for x in range(-1, game.width + 1):
        positions.append((x, -1))

    # Right border (top to bottom, skip top corner but include bottom corner)
    for y in range(0, game.height + 1):
        positions.append((game.width, y))

    # Bottom border (right to left, skip right corner but include left corner)
    for x in range(game.width - 1, -2, -1):
        positions.append((x, game.height))

    # Left border (bottom to top, skip bottom corner but include top)
    for y in range(game.height - 1, -1, -1):
        positions.append((-1, y))

    return positions


async def animate_border_color_change(session: TestSession, game: SnakeGame, new_color_index: int):
    """Animate the border color change by updating cells one by one in a wave."""
    global _current_border_color_index

    if new_color_index >= len(BORDER_COLORS):
        new_color_index = len(BORDER_COLORS) - 1

    new_color = BORDER_COLORS[new_color_index]
    _current_border_color_index = new_color_index

    # Update COLORS dict for future border cells
    COLORS[CELL_BORDER] = new_color

    # Get all border positions if not already cached
    global _border_positions
    if not _border_positions:
        _border_positions = get_border_positions(game)

    # Animate border with pulsating effect
    # Update each border cell with a small delay to create wave effect
    delay_per_cell = 0.003  # 3ms delay between each cell update

    # For higher scores, add rotation effect by starting from different positions
    start_offset = (new_color_index * 5) % len(_border_positions)

    for i in range(len(_border_positions)):
        idx = (i + start_offset) % len(_border_positions)
        x, y = _border_positions[idx]
        await show_cell(session, x, y, CELL_BORDER, color_override=new_color)
        if i % 5 == 0:  # Every 5 cells, add a small delay
            await asyncio.sleep(delay_per_cell)


async def show_cell(session: TestSession, x: int, y: int, cell_type: str, color_override: str = None, pulsate: bool = False):
    """Show or update a cell HUD. Creates it if it doesn't exist."""
    if not session._client:
        return

    group_name = get_cell_group_name(x, y)
    screen_x, screen_y = get_cell_position(x, y)

    # Use override color if provided, otherwise use default color for cell type
    cell_color = color_override if color_override else COLORS[cell_type]

    # Special properties for golden food (pulsating effect)
    props = MessageProps(
        layout_mode=LayoutMode.MANUAL.value,
        x=screen_x,
        y=screen_y,
        width=CELL_SIZE,
        max_height=CELL_SIZE,
        bg_color=cell_color,
        opacity=1.0,
        border_radius=4,
        font_size=1,
        content_padding=0,
    )

    await session._client.show_message(
        group_name=group_name,
        element=WindowType.MESSAGE,
        title=" ",
        content=" ",  # Need non-empty content to keep HUD visible
        color=cell_color,
        props=props,
        duration=3600  # Max allowed duration
    )
    _active_cell_huds.add((x, y))


async def hide_cell(session: TestSession, x: int, y: int):
    """Hide/delete a cell HUD."""
    if not session._client:
        return

    if (x, y) in _active_cell_huds:
        group_name = get_cell_group_name(x, y)
        await session._client.delete_group(group_name, WindowType.MESSAGE)
        _active_cell_huds.discard((x, y))


async def cleanup_all_cells(session: TestSession):
    """Remove all active cell HUDs."""
    if not session._client:
        return

    for (x, y) in list(_active_cell_huds):
        group_name = get_cell_group_name(x, y)
        await session._client.delete_group(group_name, WindowType.MESSAGE)

    _active_cell_huds.clear()

    # Also clean up stats
    await session._client.delete_group("snake_stats", WindowType.MESSAGE)


async def render_initial_state(session: TestSession, game: SnakeGame):
    """Render the initial game state - borders, snake and food."""
    # Show borders first
    await render_borders(session, game)

    # Show snake with gradient
    for i, pos in enumerate(game.snake):
        if i == 0:
            await show_cell(session, pos[0], pos[1], CELL_SNAKE_HEAD)
        else:
            color = get_snake_body_color(i, len(game.snake))
            await show_cell(session, pos[0], pos[1], CELL_SNAKE_BODY, color_override=color)

    # Show all regular foods
    for food_pos in game.foods:
        await show_cell(session, food_pos[0], food_pos[1], CELL_FOOD)

    # Show golden food if exists
    if game.golden_food:
        await show_cell(session, game.golden_food[0], game.golden_food[1], CELL_GOLDEN_FOOD, pulsate=True)


async def render_borders(session: TestSession, game: SnakeGame):
    """Render the border cells around the playable area."""
    # Top border (row -1)
    for x in range(-1, game.width + 1):
        await show_cell(session, x, -1, CELL_BORDER)

    # Bottom border (row height)
    for x in range(-1, game.width + 1):
        await show_cell(session, x, game.height, CELL_BORDER)

    # Left border (column -1)
    for y in range(game.height):
        await show_cell(session, -1, y, CELL_BORDER)

    # Right border (column width)
    for y in range(game.height):
        await show_cell(session, game.width, y, CELL_BORDER)


async def update_display(session: TestSession, game: SnakeGame, old_states: dict, new_states: dict):
    """Update only the cells that changed."""
    all_positions = set(old_states.keys()) | set(new_states.keys())

    for pos in all_positions:
        old_type = old_states.get(pos)
        new_type = new_states.get(pos)

        if old_type != new_type:
            if new_type is None:
                # Cell became empty - hide it
                await hide_cell(session, pos[0], pos[1])
            else:
                # Cell has content - show/update it
                cell_type, extra_data = new_type if isinstance(new_type, tuple) else (new_type, None)

                if cell_type == CELL_SNAKE_BODY and extra_data:
                    # Use gradient color for snake body
                    await show_cell(session, pos[0], pos[1], cell_type, color_override=extra_data)
                elif cell_type == CELL_GOLDEN_FOOD:
                    # Golden food with pulsating effect
                    await show_cell(session, pos[0], pos[1], cell_type, pulsate=True)
                else:
                    await show_cell(session, pos[0], pos[1], cell_type)


def get_game_state(game: SnakeGame) -> dict:
    """Get current state of all non-empty cells."""
    states = {}

    # Snake with gradient
    if game.snake:
        states[game.snake[0]] = CELL_SNAKE_HEAD
        for i, pos in enumerate(game.snake[1:], start=1):
            color = get_snake_body_color(i, len(game.snake))
            states[pos] = (CELL_SNAKE_BODY, color)  # Store type and color

    # Regular foods
    for food_pos in game.foods:
        states[food_pos] = CELL_FOOD

    # Golden food
    if game.golden_food:
        states[game.golden_food] = CELL_GOLDEN_FOOD

    return states


# =============================================================================
# Combo Display
# =============================================================================

async def show_combo_flash(session: TestSession, combo: int):
    """Show a flashy combo notification in the center of the screen."""
    if not session._client or combo < 2:
        return

    # Different messages for different combo levels
    if combo >= 10:
        emoji = "🔥💥"
        message = f"**INSANE COMBO x{combo}!**"
        color = "#ff0066"
    elif combo >= 5:
        emoji = "🔥"
        message = f"**MEGA COMBO x{combo}!**"
        color = "#ff6600"
    elif combo >= 3:
        emoji = "⚡"
        message = f"**COMBO x{combo}!**"
        color = "#ffaa00"
    else:
        emoji = "✨"
        message = f"**x{combo} Combo**"
        color = "#00ff00"

    combo_text = f"{emoji} {message} {emoji}"

    props = MessageProps(
        anchor=Anchor.CENTER.value,
        priority=150,
        layout_mode=LayoutMode.AUTO.value,
        width=400,
        bg_color=HudColor.BLACK.value,
        text_color=color,
        accent_color=color,
        opacity=0.95,
        border_radius=20,
        font_size=24,
        content_padding=20,
        typewriter_effect=False,
    )
    await session._client.show_message(
        group_name="snake_combo_flash",
        element=WindowType.MESSAGE,
        title=" ",
        content=combo_text,
        color=color,
        props=props,
        duration=1.5  # Show for 1.5 seconds
    )


# =============================================================================
# Game Screens
# =============================================================================

async def show_start_screen(session: TestSession):
    """Display the game start screen as individual HUD elements."""
    if not session._client:
        return

    # Title HUD - Highest priority
    await session._client.show_message(
        group_name="snake_menu_title",
        element=WindowType.MESSAGE,
        title=" ",  # Space to pass validation
        content="# 🐍 ENDLESS SNAKE GAME 🐍",
        color=COLOR_GAME,
        props=_menu_props(250, font_size=16),
        duration=3600,
    )

    # How to Play HUD
    await session._client.show_message(
        group_name="snake_menu_howto",
        element=WindowType.MESSAGE,
        title=" ",
        content="""## How to Play
- Use **Arrow Keys** to control the snake
- Eat 🍎 red apples to grow and score **+1 point**
- Eat 🌟 **GOLDEN APPLES** for **+5 points** (rare!)
- Build **COMBOS** by eating quickly (2s window)
- Avoid hitting the borders and yourself
- **ENDLESS MODE** - No time limit, play until you lose!""",
        color=COLOR_GAME,
        props=_menu_props(240),
        duration=3600,
    )

    # Features HUD
    await session._client.show_message(
        group_name="snake_menu_features",
        element=WindowType.MESSAGE,
        title=" ",
        content="""## Features
- 🌈 Snake body gradient (head to tail)
- 🎨 Border colors change with your score
- 🔥 Combo system for bonus points
- ⚡ Multiple foods on screen
- 🌟 Golden apples (disappear after 10s)""",
        color=COLOR_GAME,
        props=_menu_props(230),
        duration=3600,
    )

    # Controls HUD
    await session._client.show_message(
        group_name="snake_menu_controls",
        element=WindowType.MESSAGE,
        title=" ",
        content=f"""## Controls
- **↑ ↓ ← →** : Move snake
- **Grid Size:** {GRID_WIDTH} x {GRID_HEIGHT}""",
        color=COLOR_GAME,
        props=_menu_props(220),
        duration=3600,
    )

    # Start Button HUD
    await session._client.show_message(
        group_name="snake_menu_start",
        element=WindowType.MESSAGE,
        title=" ",
        content="🎮 **Press SPACE to begin your endless journey!** 🎮",
        color=COLOR_GAME,
        props=_menu_props(210, bg_color="#1a4d1a", font_size=16),
        duration=3600,
    )


async def show_stats(session: TestSession, game: SnakeGame, elapsed: float, speed: float, force: bool = False):
    """Display stats overlay - only updates if changed."""
    if not session._client:
        return

    # Format elapsed time (endless mode)
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    time_str = f"{minutes}:{seconds:02d}"

    # Combo display
    combo_str = ""
    if game.combo > 1:
        combo_str = f"\n🔥 **COMBO x{game.combo}** 🔥"

    stats_message = f"""**Score:** {game.score}  |  **Length:** {len(game.snake)}
**Time:** {time_str}  |  **Speed:** {1/speed:.1f}/s{combo_str}"""

    await session._client.show_message(
        group_name="snake_stats",
        element=WindowType.MESSAGE,
        title="🎮 Endless Snake",
        content=stats_message,
        color=COLOR_GAME,
        props=_stats_props(),
        duration=3600,  # Max allowed duration
    )


async def show_game_over_screen(session: TestSession, game: SnakeGame, elapsed: float):
    """Display the game over screen as individual HUD elements."""
    if not session._client:
        return

    # Better score ratings for endless mode
    if game.score >= 100:
        result_emoji, rating = "👑", "GODLIKE!"
    elif game.score >= 75:
        result_emoji, rating = "🏆", "LEGENDARY!"
    elif game.score >= 50:
        result_emoji, rating = "💎", "MASTER!"
    elif game.score >= 30:
        result_emoji, rating = "🌟", "AMAZING!"
    elif game.score >= 20:
        result_emoji, rating = "🎉", "GREAT!"
    elif game.score >= 10:
        result_emoji, rating = "👍", "GOOD!"
    elif game.score >= 5:
        result_emoji, rating = "😊", "NICE!"
    else:
        result_emoji, rating = "😅", "KEEP TRYING!"

    # Format time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    time_str = f"{minutes}:{seconds:02d}"

    # Game Over Title HUD
    await session._client.show_message(
        group_name="snake_gameover_title",
        element=WindowType.MESSAGE,
        title=" ",
        content=f"# {result_emoji} GAME OVER {result_emoji}",
        color=COLOR_GAME_OVER,
        props=_menu_props(250, accent_color=COLOR_GAME_OVER, bg_color="#1a0a0a", width=500, font_size=18),
        duration=3600,
    )

    # Rating HUD
    await session._client.show_message(
        group_name="snake_gameover_rating",
        element=WindowType.MESSAGE,
        title=" ",
        content=f"## {rating}",
        color=COLOR_GAME_OVER,
        props=_menu_props(240, accent_color=COLOR_GAME_OVER, width=500, font_size=16),
        duration=3600,
    )

    # Stats HUD
    await session._client.show_message(
        group_name="snake_gameover_stats",
        element=WindowType.MESSAGE,
        title=" ",
        content=f"""### Final Stats
- **Score:** {game.score}
- **Final Length:** {len(game.snake)}
- **Survival Time:** {time_str}
- **Reason:** {game.game_over_reason}""",
        color=COLOR_GAME_OVER,
        props=_menu_props(230, accent_color=COLOR_GAME_OVER, width=500),
        duration=3600,
    )

    # Play Again Button HUD
    await session._client.show_message(
        group_name="snake_gameover_playagain",
        element=WindowType.MESSAGE,
        title=" ",
        content="🔄 **Press SPACE to play again**",
        color=COLOR_GAME,
        props=_menu_props(220, bg_color="#1a4d1a", width=500, font_size=15),
        duration=3600,
    )

    # Exit Button HUD
    await session._client.show_message(
        group_name="snake_gameover_exit",
        element=WindowType.MESSAGE,
        title=" ",
        content="👋 **Press ESC to exit**",
        color="#888888",
        props=_menu_props(210, accent_color="#888888", bg_color="#1a1a1a", width=500, font_size=15),
        duration=3600,
    )


# =============================================================================
# Main Game Loop
# =============================================================================

async def test_snake_game(session: TestSession):
    """Run the interactive Snake game."""
    global _current_border_color_index, _border_positions, _active_cell_huds

    # Reset global state for new game
    _current_border_color_index = 0
    _border_positions = []
    _active_cell_huds = set()

    print(f"[{session.name}] Starting Full-Screen Snake Game...")

    game = SnakeGame()

    # Show start screen and wait for SPACE
    await show_start_screen(session)
    print(f"[{session.name}] Press SPACE to start...")

    while not keyboard.is_pressed('space'):
        await asyncio.sleep(0.1)

    # Wait for key release to avoid double-triggering
    await asyncio.sleep(0.2)

    # Hide start menu before game starts
    if session._client:
        await session._client.delete_group("snake_menu_title", WindowType.MESSAGE)
        await session._client.delete_group("snake_menu_howto", WindowType.MESSAGE)
        await session._client.delete_group("snake_menu_features", WindowType.MESSAGE)
        await session._client.delete_group("snake_menu_controls", WindowType.MESSAGE)
        await session._client.delete_group("snake_menu_start", WindowType.MESSAGE)

    print(f"[{session.name}] Game started!")


    # Render initial game state (just snake + food)
    await render_initial_state(session, game)

    # Show initial stats
    await show_stats(session, game, 0, INITIAL_SPEED)

    # Set up keyboard handlers
    game_running = True

    def on_arrow_up(e):
        if game_running:
            game.set_direction(Direction.UP)

    def on_arrow_down(e):
        if game_running:
            game.set_direction(Direction.DOWN)

    def on_arrow_left(e):
        if game_running:
            game.set_direction(Direction.LEFT)

    def on_arrow_right(e):
        if game_running:
            game.set_direction(Direction.RIGHT)

    keyboard.on_press_key('up', on_arrow_up)
    keyboard.on_press_key('down', on_arrow_down)
    keyboard.on_press_key('left', on_arrow_left)
    keyboard.on_press_key('right', on_arrow_right)

    start_time = time.time()
    current_speed = INITIAL_SPEED
    last_update = start_time
    last_stats = {"score": -1, "time": -1, "combo": -1}
    elapsed = 0.0
    last_combo_shown = 0

    try:
        while game_running:
            current_time = time.time()
            elapsed = current_time - start_time

            # Update game at current speed
            if current_time - last_update >= current_speed:
                old_states = get_game_state(game)
                old_score = game.score
                old_combo = game.combo

                ate_food = game.update()
                last_update = current_time

                if game.game_over:
                    game_running = False
                    break

                new_states = get_game_state(game)

                # Speed up on food eaten and animate border color change
                if game.score > old_score:
                    current_speed = max(MIN_SPEED, INITIAL_SPEED - (game.score * SPEED_INCREMENT))

                    # Trigger border color animation based on score
                    # Change color every 2 points to make it more visible
                    new_color_index = min(game.score // 2, len(BORDER_COLORS) - 1)
                    if new_color_index != _current_border_color_index:
                        # Start animation in background (non-blocking)
                        asyncio.create_task(animate_border_color_change(session, game, new_color_index))

                    # Show combo flash when reaching combo milestones
                    if game.combo >= 2 and game.combo != old_combo:
                        asyncio.create_task(show_combo_flash(session, game.combo))

                # Update only changed cells
                await update_display(session, game, old_states, new_states)

            # Update stats when score, time, or combo changes
            current_minute = int(elapsed // 60)
            current_stats = {"score": game.score, "time": current_minute, "combo": game.combo}
            if current_stats != last_stats:
                await show_stats(session, game, elapsed, current_speed)
                last_stats = current_stats.copy()

            await asyncio.sleep(0.01)

        # Cleanup and show game over
        await cleanup_all_cells(session)
        await show_game_over_screen(session, game, elapsed)

        # Wait for player decision: SPACE to play again, ESC to exit
        print(f"[{session.name}] Game Over! Press SPACE to play again or ESC to exit...")
        play_again = False

        while True:
            if keyboard.is_pressed('space'):
                play_again = True
                print(f"[{session.name}] Restarting game...")
                break
            elif keyboard.is_pressed('esc'):
                play_again = False
                print(f"[{session.name}] Exiting game...")
                break
            await asyncio.sleep(0.1)

        # Wait for key release before continuing
        await asyncio.sleep(0.3)

        # Hide game over menu
        if session._client:
            await session._client.delete_group("snake_gameover_title", WindowType.MESSAGE)
            await session._client.delete_group("snake_gameover_rating", WindowType.MESSAGE)
            await session._client.delete_group("snake_gameover_stats", WindowType.MESSAGE)
            await session._client.delete_group("snake_gameover_playagain", WindowType.MESSAGE)
            await session._client.delete_group("snake_gameover_exit", WindowType.MESSAGE)

        # Cleanup keyboard hooks before returning
        keyboard.unhook_all()

        return play_again

    except Exception as e:
        print(f"[{session.name}] Error in game: {e}")
        keyboard.unhook_all()
        # Cleanup all menu HUDs
        if session._client:
            # Start menu
            await session._client.delete_group("snake_menu_title", WindowType.MESSAGE)
            await session._client.delete_group("snake_menu_howto", WindowType.MESSAGE)
            await session._client.delete_group("snake_menu_features", WindowType.MESSAGE)
            await session._client.delete_group("snake_menu_controls", WindowType.MESSAGE)
            await session._client.delete_group("snake_menu_start", WindowType.MESSAGE)
            # Game over menu
            await session._client.delete_group("snake_gameover_title", WindowType.MESSAGE)
            await session._client.delete_group("snake_gameover_rating", WindowType.MESSAGE)
            await session._client.delete_group("snake_gameover_stats", WindowType.MESSAGE)
            await session._client.delete_group("snake_gameover_playagain", WindowType.MESSAGE)
            await session._client.delete_group("snake_gameover_exit", WindowType.MESSAGE)
        return False


# =============================================================================
# Main Entry Point
# =============================================================================

async def run_snake_test():
    """Run the enhanced endless Snake game test with advanced features."""
    from hud_server.tests.test_runner import TestContext

    print("=" * 60)
    print("ENDLESS SNAKE GAME - ENHANCED EDITION")
    print("=" * 60)
    print("Features: Gradient Snake | Combos | Golden Apples | Animated Borders")
    print("=" * 60)

    session_config = {
        "name": "Snake",
        "anchor": "top_left",
        "priority": 50,
        "persistent_anchor": "top_left",
        "persistent_priority": 40,
        "layout_mode": "auto",
        "hud_width": 500,
        "persistent_width": 500,
        "hud_max_height": 900,
        "bg_color": "#0a0e14",
        "text_color": "#f0f0f0",
        "accent_color": COLOR_GAME,
        "user_color": "#4cd964",
        "opacity": 0.95,
        "border_radius": 16,
        "font_size": 14,
        "content_padding": 20,
        "typewriter_effect": False,
    }

    async with TestContext(session_ids=[1]) as ctx:
        session = ctx.sessions[0]
        session.config = session_config
        session.name = "Snake"

        print("HUD Server started. Get ready for ENDLESS Snake! 🐍✨\n")
        print("🌈 Gradient Snake | 🔥 Combos | 🌟 Golden Apples | 🎨 Animated Borders\n")

        # Play again loop
        while True:
            play_again = await test_snake_game(session)
            if not play_again:
                print("Thanks for playing! 🐍✨")
                break
            else:
                print("\n" + "=" * 60)
                print("Starting new game...")
                print("=" * 60 + "\n")
                await asyncio.sleep(0.5)  # Small delay before restart


if __name__ == "__main__":
    asyncio.run(run_snake_test())
