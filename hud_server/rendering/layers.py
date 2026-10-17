"""A HUD window drawn as a stack of pieces.

A piece is one part of a window's content: a message's title, a markdown
block, a chat message, an info item. It is rendered once, at its full height,
and kept while frames show it. A frame lays out only the pieces that reach
into the window, newest at the bottom, so content scrolled out of view is
neither rendered nor kept, and a frame in which only the loader moves draws
nothing but the loader.
"""

from dataclasses import dataclass
from typing import Callable, Hashable, Iterable, Optional

from PIL import Image, ImageChops, ImageDraw

from hud_server.rendering import glass

MAX_PIECE_HEIGHT = 16384

DrawPiece = Callable[[ImageDraw.ImageDraw, Image.Image, int], int]
"""Draws a piece from y=0 down and returns the y where it ends. The third
argument is how many pixels to leave off at the top: draw everything that
much higher. Only a piece taller than MAX_PIECE_HEIGHT gets more than 0."""


def render_piece(width: int, draw: DrawPiece, height_hint: int = 256) -> Image.Image:
    """The piece at its full height, however tall it turns out. Taller than
    MAX_PIECE_HEIGHT, it keeps its end: that is what a window shows of it."""
    height = max(1, min(height_hint, MAX_PIECE_HEIGHT))
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    end = int(draw(ImageDraw.Draw(image), image, 0))
    if end <= height:
        return image.crop((0, 0, width, max(1, end)))
    top = max(0, end - MAX_PIECE_HEIGHT)
    image = Image.new("RGBA", (width, end - top), (0, 0, 0, 0))
    draw(ImageDraw.Draw(image), image, top)
    return image


@dataclass
class Piece:
    key: Hashable
    """Everything the piece's pixels depend on: same key, same image."""
    draw: DrawPiece
    gap: int = 0
    """Space below the piece."""
    alpha: float = 1.0
    """Faded when the window is put together, so fading renders nothing."""
    slot: Optional[Hashable] = None
    """Pieces that replace one another, like a block while it is typed, share
    a slot: the last one's height sizes the next, so it renders once."""


class PieceCache:
    """The rendered pieces of one window."""

    def __init__(self) -> None:
        self._images: dict = {}
        self._used: set = set()
        self._heights: dict = {}
        self._used_slots: set = set()
        self.renders = 0
        """Pieces rendered so far. A frame that only reuses pieces adds none."""

    def image(self, piece: Piece, width: int) -> Image.Image:
        key = (width, piece.key)
        slot = (width, piece.slot) if piece.slot is not None else None
        image = self._images.get(key)
        if image is None:
            hint = self._heights.get(slot, 128) + 128 if slot else 256
            image = render_piece(width, piece.draw, hint)
            self._images[key] = image
            self.renders += 1
        self._used.add(key)
        if slot:
            self._heights[slot] = image.height
            self._used_slots.add(slot)
        return image

    def end_frame(self) -> None:
        """Forget the pieces this frame did not show."""
        for key in [k for k in self._images if k not in self._used]:
            del self._images[key]
        for slot in [s for s in self._heights if s not in self._used_slots]:
            del self._heights[slot]
        self._used = set()
        self._used_slots = set()

    def __len__(self) -> int:
        return len(self._images)


@dataclass
class Layout:
    height: int
    clipped: bool
    """More content above the window: the newest part shows, the top fades."""
    placed: list
    """(image, y, alpha) of every piece in view."""
    tail_y: int
    """Where the space reserved below the pieces (the loader's) starts."""
    signature: tuple
    """Same signature, same picture."""


def lay_out(
    cache: PieceCache,
    newest_first: Iterable[Piece],
    width: int,
    max_height: int,
    *,
    top: int = 0,
    bottom: int = 0,
    tail: int = 0,
    min_height: int = 0,
    fixed_height: Optional[int] = None,
) -> Layout:
    """Stack the pieces under `top` padding, with `tail` and `bottom` below
    them. `newest_first` is read only until the window is full: the pieces
    above it are not rendered, and a generator does not even make them."""
    limit = fixed_height if fixed_height is not None else max_height
    below = bottom + tail
    used = below
    chosen = []  # newest first
    pieces = iter(newest_first)
    for piece in pieces:
        image = cache.image(piece, width)
        chosen.append((piece, image))
        used += image.height + piece.gap
        if used >= limit:
            break
    more_above = next(pieces, None) is not None

    total = used + top
    if fixed_height is not None:
        height = fixed_height
    elif more_above:
        height = max_height
    else:
        height = min(max(min_height, total), max_height)
    clipped = more_above or total > height

    placed = []
    if clipped:
        y = height - below
        tail_y = y
        for piece, image in chosen:
            y -= piece.gap + image.height
            placed.append((piece, image, y))
        placed.reverse()
    else:
        y = top
        for piece, image in reversed(chosen):
            placed.append((piece, image, y))
            y += image.height + piece.gap
        tail_y = y

    signature = (height, clipped, tail_y, tuple((p.key, y, p.alpha) for p, _, y in placed))
    return Layout(
        height=height,
        clipped=clipped,
        placed=[(image, y, piece.alpha) for piece, image, y in placed],
        tail_y=tail_y,
        signature=signature,
    )


def compose(
    layout: Layout,
    width: int,
    background: tuple,
    radius: int,
    fade_height: int = 0,
    under: Optional[Image.Image] = None,
) -> Image.Image:
    """The window: its glass body with the pieces in view, a fade at the top
    when there is more above, on its shadow (glass.SHADOW's room around it).
    `under` (the loader's glow) lies on the body's bottom, below the pieces."""
    radius = max(0, min(radius, layout.height // 2, width // 2))
    body = glass.body(width, layout.height, radius, background)
    canvas = body.fill.copy()
    if under is not None:
        glass.put(canvas, under, (0, layout.height - under.height))
    for image, y, alpha in layout.placed:
        top = max(0, -y)
        bottom = min(image.height, layout.height - y)
        if bottom <= top:
            continue
        part = image.crop((0, top, image.width, bottom))
        if alpha < 1.0:
            faded = part.getchannel("A").point(lambda a: int(a * alpha))
            part.putalpha(faded)
        canvas.alpha_composite(part, (0, y + top))
    if layout.clipped and fade_height > 0:
        fade_top(canvas, body.top_color, fade_height)
    canvas.alpha_composite(body.edges)
    return glass.framed(canvas, radius, background[3] if len(background) > 3 else 255)


def fade_top(canvas: Image.Image, background: tuple, fade_height: int) -> None:
    """Fade the content at the top into the background: there is more above."""
    fade_height = min(fade_height, canvas.height)
    if fade_height <= 0:
        return
    width = canvas.width
    top_region = canvas.crop((0, 0, width, fade_height))
    # 255 (all background) at the top row, 0 at the bottom row
    gradient = ImageChops.invert(Image.linear_gradient("L")).resize((width, fade_height))
    # Only where the panel is opaque already: never over the transparent
    # rounded corners or past a see-through background
    gradient = ImageChops.multiply(gradient, top_region.getchannel("A"))
    layer = Image.new("RGBA", (width, fade_height), tuple(background) + (255,))
    layer.putalpha(gradient)
    canvas.paste(Image.alpha_composite(top_region, layer), (0, 0))
