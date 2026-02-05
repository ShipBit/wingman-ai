# -*- coding: utf-8 -*-
"""
Test Snake - Interactive Snake game using the HUD Server.

A fun Snake game implementation that uses:
- Each grid cell is its own HUD window positioned across the screen
- HUDs are created on-demand (only for snake and food, not empty cells)
- Manual window placement to create a full-screen grid
- Keyboard controls (arrow keys)
- HUD messages for start/game over screens and stats
- Auto-ends after 2 minutes

Usage:
    python -m hud_server.tests.test_snake
"""

import asyncio
import time
import random
from enum import Enum
from hud_server.tests.test_session import TestSession

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
GAME_DURATION = 120  # 2 minutes
INITIAL_SPEED = 0.15  # seconds between moves
SPEED_INCREMENT = 0.005  # speed increase per food eaten
MIN_SPEED = 0.05  # fastest possible speed

# Cell types for display
CELL_EMPTY = "empty"
CELL_SNAKE_HEAD = "snake_head"
CELL_SNAKE_BODY = "snake_body"
CELL_FOOD = "food"
CELL_BORDER = "border"

# Colors for different cell types
COLORS = {
    CELL_EMPTY: "#1a1a2e",
    CELL_SNAKE_HEAD: "#00ff00",
    CELL_SNAKE_BODY: "#00aa00",
    CELL_FOOD: "#ff3333",
    CELL_BORDER: "#0066cc",
}

# Colors
COLOR_GAME = "#00ff00"
COLOR_GAME_OVER = "#ff0000"


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
        self.food = self._spawn_food()
        self.score = 0
        self.game_over = False
        self.game_over_reason = ""

    def _spawn_food(self) -> tuple[int, int]:
        """Spawn food at a random empty location."""
        while True:
            x = random.randint(0, self.width - 1)
            y = random.randint(0, self.height - 1)
            if (x, y) not in self.snake:
                return (x, y)

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

        if new_head == self.food:
            self.score += 1
            self.food = self._spawn_food()
        else:
            self.snake.pop()


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


async def show_cell(session: TestSession, x: int, y: int, cell_type: str):
    """Show or update a cell HUD. Creates it if it doesn't exist."""
    if not session._client:
        return

    group_name = get_cell_group_name(x, y)
    screen_x, screen_y = get_cell_position(x, y)

    await session._client.show_message(
        group_name=group_name,
        title=" ",
        content=" ",  # Need non-empty content to keep HUD visible
        color=COLORS[cell_type],
        props={
            "layout_mode": "manual",
            "x": screen_x,
            "y": screen_y,
            "width": CELL_SIZE,
            "height": CELL_SIZE,
            "bg_color": COLORS[cell_type],
            "opacity": 1.0,
            "border_radius": 4,
            "font_size": 1,
            "content_padding": 0,
            "disable_animations": True,
            "disable_transitions": True,
            "duration": 120,  # 2 minutes - same as game duration
        }
    )
    _active_cell_huds.add((x, y))


async def hide_cell(session: TestSession, x: int, y: int):
    """Hide/delete a cell HUD."""
    if not session._client:
        return

    if (x, y) in _active_cell_huds:
        group_name = get_cell_group_name(x, y)
        await session._client.delete_group(group_name)
        _active_cell_huds.discard((x, y))


async def cleanup_all_cells(session: TestSession):
    """Remove all active cell HUDs."""
    if not session._client:
        return

    for (x, y) in list(_active_cell_huds):
        group_name = get_cell_group_name(x, y)
        await session._client.delete_group(group_name)

    _active_cell_huds.clear()

    # Also clean up stats
    await session._client.delete_group("snake_stats")


async def render_initial_state(session: TestSession, game: SnakeGame):
    """Render the initial game state - borders, snake and food."""
    # Show borders first
    await render_borders(session, game)

    # Show snake head
    await show_cell(session, game.snake[0][0], game.snake[0][1], CELL_SNAKE_HEAD)

    # Show snake body
    for pos in game.snake[1:]:
        await show_cell(session, pos[0], pos[1], CELL_SNAKE_BODY)

    # Show food
    await show_cell(session, game.food[0], game.food[1], CELL_FOOD)


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


async def update_display(session: TestSession, old_states: dict, new_states: dict):
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
                await show_cell(session, pos[0], pos[1], new_type)


def get_game_state(game: SnakeGame) -> dict:
    """Get current state of all non-empty cells."""
    states = {}
    if game.snake:
        states[game.snake[0]] = CELL_SNAKE_HEAD
        for pos in game.snake[1:]:
            states[pos] = CELL_SNAKE_BODY
    states[game.food] = CELL_FOOD
    return states


# =============================================================================
# Game Screens
# =============================================================================

async def show_start_screen(session: TestSession):
    """Display the game start screen."""
    start_message = f"""# 🐍 FULL-SCREEN SNAKE GAME 🐍

## How to Play
- Use **Arrow Keys** to control the snake
- Eat 🍎 to grow longer and score points
- Avoid hitting the blue borders and yourself
- Game lasts **2 minutes**

## Controls
- **↑ ↓ ← →** : Move snake
- **SPACE** : Start game

## Grid Size: {GRID_WIDTH} x {GRID_HEIGHT}

**Press SPACE to begin!**"""

    await session.draw_assistant_message(start_message)


async def show_stats(session: TestSession, game: SnakeGame, elapsed: float, speed: float, force: bool = False):
    """Display stats overlay - only updates if changed."""
    if not session._client:
        return

    time_left = int(GAME_DURATION - elapsed)

    stats_message = f"""**Score:** {game.score}  |  **Length:** {len(game.snake)}  |  **Time:** {time_left}s"""

    await session._client.show_message(
        group_name="snake_stats",
        title="🎮 Snake",
        content=stats_message,
        color=COLOR_GAME,
        props={
            "anchor": "top_right",
            "priority": 100,
            "layout_mode": "auto",
            "width": 350,
            "bg_color": "#0a0e14",
            "text_color": "#f0f0f0",
            "accent_color": COLOR_GAME,
            "opacity": 0.95,
            "border_radius": 8,
            "font_size": 14,
            "content_padding": 12,
            "typewriter_effect": False,
            "disable_animations": True,
            "disable_transitions": True,
            "duration": 120,  # 2 minutes - same as game duration
        }
    )


async def show_game_over_screen(session: TestSession, game: SnakeGame, elapsed: float):
    """Display the game over screen."""
    if game.score >= 30:
        result_emoji, rating = "🏆", "LEGENDARY!"
    elif game.score >= 20:
        result_emoji, rating = "🌟", "AMAZING!"
    elif game.score >= 10:
        result_emoji, rating = "🎉", "GREAT!"
    elif game.score >= 5:
        result_emoji, rating = "👍", "GOOD!"
    else:
        result_emoji, rating = "😅", "NICE TRY!"

    game_over_message = f"""# {result_emoji} GAME OVER {result_emoji}

## {rating}

### Final Stats
- **Score:** {game.score}
- **Final Length:** {len(game.snake)}
- **Time Played:** {int(elapsed)}s / {GAME_DURATION}s
- **Reason:** {game.game_over_reason}

---

*Press any key to exit*"""

    await session.draw_assistant_message(game_over_message)


# =============================================================================
# Main Game Loop
# =============================================================================

async def test_snake_game(session: TestSession):
    """Run the interactive Snake game."""
    print(f"[{session.name}] Starting Full-Screen Snake Game...")

    game = SnakeGame()

    # Show start screen and wait for SPACE
    await show_start_screen(session)
    print(f"[{session.name}] Press SPACE to start...")

    while not keyboard.is_pressed('space'):
        await asyncio.sleep(0.1)

    print(f"[{session.name}] Game started!")

    # Hide start screen
    await session.hide()

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
    last_stats = {"score": -1, "time": -1}
    elapsed = 0.0

    try:
        while game_running:
            current_time = time.time()
            elapsed = current_time - start_time

            # Check time limit
            if elapsed >= GAME_DURATION:
                game.game_over = True
                game.game_over_reason = "Time's up!"
                break

            # Update game at current speed
            if current_time - last_update >= current_speed:
                old_states = get_game_state(game)
                old_score = game.score

                game.update()
                last_update = current_time

                if game.game_over:
                    game_running = False
                    break

                new_states = get_game_state(game)

                # Speed up on food eaten
                if game.score > old_score:
                    current_speed = max(MIN_SPEED, INITIAL_SPEED - (game.score * SPEED_INCREMENT))

                # Update only changed cells
                await update_display(session, old_states, new_states)

            # Update stats only when changed
            current_stats = {"score": game.score, "time": int(GAME_DURATION - elapsed)}
            if current_stats != last_stats:
                await show_stats(session, game, elapsed, current_speed)
                last_stats = current_stats.copy()

            await asyncio.sleep(0.01)

        # Cleanup and show game over
        await cleanup_all_cells(session)
        await show_game_over_screen(session, game, elapsed)
        await asyncio.sleep(5)

    finally:
        keyboard.unhook_all()
        await session.hide()
        print(f"[{session.name}] Snake game ended. Final score: {game.score}")


# =============================================================================
# Main Entry Point
# =============================================================================

async def run_snake_test():
    """Run the Snake game test."""
    from hud_server.tests.test_runner import TestContext

    print("=" * 60)
    print("SNAKE GAME TEST")
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

        print("HUD Server started. Get ready to play Snake! 🐍\n")
        await test_snake_game(session)


if __name__ == "__main__":
    asyncio.run(run_snake_test())
