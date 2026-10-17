"""The HUD's look: anti-aliased shapes, a window's glass body and its shadow.

Rounded corners are cut from a circle drawn four times larger and scaled down,
so every edge is smooth. What does not depend on a window's content (its body,
edges and shadow) is made once per size and reused while the content changes.
"""

import math
from collections import OrderedDict
from functools import lru_cache
from typing import NamedTuple, Optional, Sequence, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SCALE = 4


class Margins(NamedTuple):
    left: int
    top: int
    right: int
    bottom: int


SHADOW = Margins(16, 10, 16, 22)
"""Room around a window's body for its shadow: the body sits this far in."""
SHADOW_OFFSET = 6
SHADOW_BLUR = 7
SHADOW_STRENGTH = 0.4

TOP_LIGHT = 0.06
"""How much lighter a body is at its top than at its bottom."""
EDGE = 0.07
HIGHLIGHT = 0.1

_LUTS: dict = {}


def _lut(alpha: int) -> list:
    lut = _LUTS.get(alpha)
    if lut is None:
        lut = _LUTS[alpha] = [v * alpha // 255 for v in range(256)]
    return lut


def scaled(mask: Image.Image, alpha: int) -> Image.Image:
    """The mask at `alpha`/255 of its strength."""
    alpha = max(0, min(255, int(alpha)))
    return mask if alpha == 255 else mask.point(_lut(alpha))


def is_dark(rgb: Sequence[int]) -> bool:
    r, g, b = rgb[:3]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b < 128


def edge_color(bg: Sequence[int]) -> Tuple[int, int, int]:
    """Light lines on a dark panel, dark ones on a light panel."""
    return (255, 255, 255) if is_dark(bg) else (0, 0, 0)


def mix(a: Sequence[int], b: Sequence[int], amount: float) -> Tuple[int, int, int]:
    return tuple(round(x + (y - x) * amount) for x, y in zip(a[:3], b[:3]))


def lighter(rgb: Sequence[int], amount: float) -> Tuple[int, int, int]:
    return mix(rgb, (255, 255, 255), amount)


# ─────────────────────────────── shapes ─────────────────────────────── #


@lru_cache(maxsize=256)
def _corner(radius: int, corner: int) -> Image.Image:
    """One corner of a disc `radius` wide: 0 top left, 1 top right, 2 bottom right, 3 bottom left."""
    big = Image.new("L", (radius * 2 * SCALE, radius * 2 * SCALE), 0)
    ImageDraw.Draw(big).ellipse([0, 0, big.width - 1, big.height - 1], fill=255)
    disc = big.resize((radius * 2, radius * 2), Image.Resampling.BOX)
    x = radius if corner in (1, 2) else 0
    y = radius if corner in (2, 3) else 0
    return disc.crop((x, y, x + radius, y + radius))


def rounded_mask(width: int, height: int, radius: float, corners: Optional[Sequence[float]] = None) -> Image.Image:
    """A rounded rectangle as an alpha mask. `corners` gives each corner its
    own radius: top left, top right, bottom right, bottom left."""
    width, height = max(1, int(width)), max(1, int(height))
    mask = Image.new("L", (width, height), 255)
    limit = min(width, height) // 2
    for i, r in enumerate(corners or (radius,) * 4):
        r = max(0, min(int(round(r)), limit))
        if r:
            x = width - r if i in (1, 2) else 0
            y = height - r if i in (2, 3) else 0
            mask.paste(_corner(r, i), (x, y))
    return mask


def ring_mask(width: int, height: int, radius: float, thickness: int = 1,
              corners: Optional[Sequence[float]] = None) -> Image.Image:
    """The outline of a rounded rectangle, `thickness` wide, inside its edge."""
    outer = rounded_mask(width, height, radius, corners)
    inner = Image.new("L", outer.size, 0)
    if width > 2 * thickness and height > 2 * thickness:
        radii = [max(0, r - thickness) for r in (corners or (radius,) * 4)]
        inner.paste(rounded_mask(width - 2 * thickness, height - 2 * thickness, 0, radii), (thickness, thickness))
    return ImageChops.subtract(outer, inner)


def top_edge(mask: Image.Image) -> Image.Image:
    """The top row of a shape, following its corners: where light catches it."""
    below = Image.new("L", mask.size, 0)
    below.paste(mask.crop((0, 0, mask.width, mask.height - 1)), (0, 1))
    return ImageChops.subtract(mask, below)


def paint(image: Image.Image, mask: Image.Image, color: Sequence[int], at: Tuple[int, int] = (0, 0)) -> None:
    """Lay `color` over the image through the mask, as see-through as the colour."""
    alpha = color[3] if len(color) > 3 else 255
    if alpha <= 0:
        return
    layer = Image.new("RGBA", mask.size, tuple(color[:3]) + (0,))
    layer.putalpha(scaled(mask, alpha))
    put(image, layer, at)


def put(image: Image.Image, layer: Image.Image, at: Tuple[int, int]) -> None:
    """alpha_composite that takes a layer reaching past the image's edges."""
    x, y = int(at[0]), int(at[1])
    left, top = max(0, -x), max(0, -y)
    right = min(layer.width, image.width - x)
    bottom = min(layer.height, image.height - y)
    if right <= left or bottom <= top:
        return
    if (left, top, right, bottom) != (0, 0, layer.width, layer.height):
        layer = layer.crop((left, top, right, bottom))
    image.alpha_composite(layer, (x + left, y + top))


def vertical_gradient(width: int, height: int, top: Sequence[int], bottom: Sequence[int]) -> Image.Image:
    ramp = Image.linear_gradient("L").resize((1, max(1, height)), Image.Resampling.BILINEAR)
    column = Image.composite(
        Image.new("RGBA", (1, max(1, height)), tuple(bottom)),
        Image.new("RGBA", (1, max(1, height)), tuple(top)),
        ramp,
    )
    return column.resize((max(1, width), max(1, height)), Image.Resampling.NEAREST)


def horizontal_gradient(width: int, height: int, left: Sequence[int], right: Sequence[int]) -> Image.Image:
    return vertical_gradient(height, width, left, right).transpose(Image.Transpose.TRANSPOSE)


def hairline(width: int, color: Sequence[int], peak: float = 0.5, fade_in: bool = True) -> Image.Image:
    """A 1 px line that fades out towards its end (and in from its start)."""
    ramp = []
    for i in range(max(1, width)):
        t = i / max(1, width - 1)
        if t <= peak:
            level = t / peak if fade_in and peak > 0 else 1.0
        else:
            level = 1 - (t - peak) / (1 - peak)
        ramp.append(round(255 * max(0.0, min(1.0, level))))
    mask = Image.new("L", (len(ramp), 1))
    mask.putdata(ramp)
    line = Image.new("RGBA", mask.size, tuple(color[:3]) + (0,))
    line.putalpha(scaled(mask, color[3] if len(color) > 3 else 255))
    return line


# ─────────────────────────────── windows ─────────────────────────────── #


class Body(NamedTuple):
    fill: Image.Image
    """The background, to draw the content on."""
    edges: Image.Image
    """The outline and top light, laid over the content."""
    top_color: Tuple[int, int, int]


_bodies: "OrderedDict[tuple, Body]" = OrderedDict()
_shadows: "OrderedDict[tuple, Image.Image]" = OrderedDict()
_CACHED = 8


def _remember(cache: OrderedDict, key, value):
    cache[key] = value
    while len(cache) > _CACHED:
        cache.popitem(last=False)
    return value


def body(width: int, height: int, radius: int, bg: Sequence[int]) -> Body:
    """A window's glass at this size: lighter at the top, a fine outline,
    a line of light along its top edge."""
    key = (width, height, radius, tuple(bg))
    cached = _bodies.get(key)
    if cached is not None:
        _bodies.move_to_end(key)
        return cached
    alpha = bg[3] if len(bg) > 3 else 255
    top = lighter(bg, TOP_LIGHT)
    mask = rounded_mask(width, height, radius)
    fill = vertical_gradient(width, height, top + (255,), tuple(bg[:3]) + (255,))
    fill.putalpha(scaled(mask, alpha))
    edges = Image.new("RGBA", (width, height), edge_color(bg) + (0,))
    edges.putalpha(scaled(ring_mask(width, height, radius), round(EDGE * alpha)))
    paint(edges, top_edge(mask), (255, 255, 255, round(HIGHLIGHT * alpha)))
    return _remember(_bodies, key, Body(fill, edges, top))


def shadow(width: int, height: int, radius: int, alpha: int) -> Image.Image:
    """The soft shadow around a body of this size, on a canvas with SHADOW's
    room around the body. Only outside the body: a see-through body keeps its
    own colour. Blurred at a quarter of the size: it is all soft."""
    key = (width, height, radius, alpha)
    cached = _shadows.get(key)
    if cached is not None:
        _shadows.move_to_end(key)
        return cached
    q = 4
    full = (width + SHADOW.left + SHADOW.right, height + SHADOW.top + SHADOW.bottom)
    small = Image.new("L", (math.ceil(full[0] / q), math.ceil(full[1] / q)), 0)
    strength = round(255 * SHADOW_STRENGTH * alpha / 255)
    if strength > 0:
        left, top = SHADOW.left / q, (SHADOW.top + SHADOW_OFFSET) / q
        ImageDraw.Draw(small).rounded_rectangle(
            [left, top, left + width / q, top + height / q], radius=radius / q, fill=strength
        )
        small = small.filter(ImageFilter.GaussianBlur(SHADOW_BLUR / q))
    mask = small.resize((small.width * q, small.height * q), Image.Resampling.BILINEAR).crop((0, 0, *full))
    outside = Image.new("L", full, 255)
    outside.paste(ImageChops.invert(rounded_mask(width, height, radius)), (SHADOW.left, SHADOW.top))
    mask = ImageChops.multiply(mask, outside)
    image = Image.new("RGBA", full, (0, 0, 0, 0))
    image.putalpha(mask)
    return _remember(_shadows, key, image)


def framed(content: Image.Image, radius: int, alpha: int) -> Image.Image:
    """The body on its shadow."""
    canvas = shadow(content.width, content.height, radius, alpha).copy()
    canvas.alpha_composite(content, (SHADOW.left, SHADOW.top))
    return canvas


# ─────────────────────────────── details ─────────────────────────────── #


@lru_cache(maxsize=128)
def disc(diameter: float, color: Tuple[int, int, int]) -> Image.Image:
    """A smooth dot, on a square of whole pixels around it."""
    size = math.ceil(diameter) + 2
    big = Image.new("L", (size * SCALE, size * SCALE), 0)
    offset = (size - diameter) / 2 * SCALE
    ImageDraw.Draw(big).ellipse([offset, offset, offset + diameter * SCALE - 1, offset + diameter * SCALE - 1], fill=255)
    image = Image.new("RGBA", (size, size), color + (0,))
    image.putalpha(big.resize((size, size), Image.Resampling.BOX))
    return image


# ─────────────────────────────── the loader ─────────────────────────────── #

GLOW = 0.6
"""How strong the loader's glow is at its brightest."""
GLOW_HEIGHT = 64
"""How far the glow rises into the window from its bottom edge."""
GLOW_PERIOD = 2.8
"""One breath, in seconds."""
LINE_PAD = 6
"""Room above and below the edge's line for its halo."""


def breath(now: float) -> tuple:
    """How bright the glow is (0.35 to 0.9) and how wide its line (0.7 to 1)
    at this moment: one slow, even breath every GLOW_PERIOD seconds."""
    phase = 0.5 - 0.5 * math.cos(2 * math.pi * now / GLOW_PERIOD)
    return 0.35 + 0.55 * phase, 0.7 + 0.3 * phase


def _glow_alpha(distance: float) -> float:
    """The glow's strength by distance from the middle of the bottom edge
    (0) to the edge of its ellipse (1)."""
    if distance <= 0.45:
        return 0.3 - 0.18 * distance / 0.45
    if distance <= 0.85:
        return 0.12 * (1 - (distance - 0.45) / 0.4)
    return 0.0


_GLOW_LUT = [round(255 * GLOW * _glow_alpha(v / 255)) for v in range(256)]


@lru_cache(maxsize=32)
def bleed(width: int, height: int, radius: int, color: Tuple[int, int, int]) -> Image.Image:
    """The light rising from the bottom edge into the window, `height` tall:
    an ellipse three quarters of the width wide, centred on the edge, inside
    the window's rounded bottom corners. At full strength; `scaled` dims it."""
    rx, ry = max(1, round(width * 0.75)), max(1, height)
    distance = Image.radial_gradient("L").resize((2 * rx, 2 * ry), Image.Resampling.BILINEAR)
    left = rx - width // 2
    alpha = distance.crop((left, ry - height, left + width, ry)).point(_GLOW_LUT)
    corners = rounded_mask(width, height + radius + 1, radius).crop((0, radius + 1, width, height + radius + 1))
    image = Image.new("RGBA", (width, height), color + (0,))
    image.putalpha(ImageChops.multiply(alpha, corners))
    return image


@lru_cache(maxsize=32)
def edge_line(width: int, color: Tuple[int, int, int]) -> Image.Image:
    """The bottom edge's line: brightest in the middle, fading out to both
    ends, with a soft halo; LINE_PAD of room for it above and below."""
    width = max(2, width)
    half = (width - 1) / 2
    row = [round(255 * 0.9 * GLOW * (1 - abs(x - half) / half)) for x in range(width)]
    line = Image.new("L", (width, 1 + 2 * LINE_PAD), 0)
    line.paste(Image.frombytes("L", (width, 1), bytes(row)), (0, LINE_PAD))
    halo = line.filter(ImageFilter.GaussianBlur(3)).point(lambda v: min(255, round(v * 3.3)))
    image = Image.new("RGBA", line.size, color + (0,))
    image.putalpha(ImageChops.lighter(line, halo))
    return image


@lru_cache(maxsize=64)
def avatar_halo(size: int, color: Tuple[int, int, int], margin: int) -> Image.Image:
    """A ring in the sender's colour around a round picture `size` wide, with a soft glow."""
    full = size + 2 * margin
    glow = Image.new("L", (full, full), 0)
    ImageDraw.Draw(glow).ellipse([margin - 2, margin - 2, margin + size + 1, margin + size + 1], fill=60)
    glow = glow.filter(ImageFilter.GaussianBlur(max(1, margin // 2)))
    image = Image.new("RGBA", (full, full), color + (0,))
    image.putalpha(glow)
    ring = Image.new("L", (full, full), 0)
    ring.paste(ring_mask(size + 4, size + 4, (size + 4) / 2, 2), (margin - 2, margin - 2))
    paint(image, ring, color + (120,))
    return image


@lru_cache(maxsize=64)
def initial_disc(size: int, color: Tuple[int, int, int], bg: Tuple[int, int, int]) -> Image.Image:
    """The round picture of a sender without one: a disc in a dark shade of
    their colour, lit from above."""
    image = vertical_gradient(size, size, mix(bg, color, 0.42) + (255,), mix(bg, color, 0.16) + (255,))
    image.putalpha(rounded_mask(size, size, size / 2))
    return image


@lru_cache(maxsize=64)
def icon(kind: str, size: int, color: Tuple[int, int, int]) -> Image.Image:
    """A small line icon for an info panel item: "timer", "progress" or "note"."""
    s = size * SCALE / 16  # drawn on a 16 grid
    big = Image.new("L", (size * SCALE, size * SCALE), 0)
    d = ImageDraw.Draw(big)
    w = max(1, round(1.6 * s))

    def line(*points):
        d.line([(x * s, y * s) for x, y in points], fill=255, width=w, joint="curve")
        for x, y in (points[0], points[-1]):
            d.ellipse([x * s - w / 2, y * s - w / 2, x * s + w / 2, y * s + w / 2], fill=255)

    if kind == "timer":
        d.ellipse([2.2 * s, 3.2 * s, 13.8 * s, 14.8 * s], outline=255, width=w)
        line((8, 6.4), (8, 9), (10, 10.6))
        line((6.4, 1.2), (9.6, 1.2))
    elif kind == "progress":
        line((1.5, 14), (14.5, 14))
        line((4, 11), (4, 8.5))
        line((8, 11), (8, 4))
        line((12, 11), (12, 6.5))
    else:
        d.rounded_rectangle([2.2 * s, 1.8 * s, 13.8 * s, 14.2 * s], radius=2.4 * s, outline=255, width=w)
        line((5.2, 6), (10.8, 6))
        line((5.2, 9), (10.8, 9))
        line((5.2, 12), (8.6, 12))
    image = Image.new("RGBA", (size, size), color + (0,))
    image.putalpha(big.resize((size, size), Image.Resampling.BOX))
    return image


def progress_bar(width: int, height: int, filled: int, color: Sequence[int], track: Sequence[int],
                 glow: int = 4) -> Image.Image:
    """A slim bar: the track, and the filled part brightening towards its
    end with a soft glow, on a strip with `glow` room around it."""
    strip = Image.new("RGBA", (width + 2 * glow, height + 2 * glow), (0, 0, 0, 0))
    radius = height / 2
    paint(strip, rounded_mask(width, height, radius), track, (glow, glow))
    filled = max(0, min(width, filled))
    if filled >= height:
        mask = rounded_mask(filled, height, radius)
        halo = Image.new("L", strip.size, 0)
        halo.paste(mask, (glow, glow))
        paint(strip, halo.filter(ImageFilter.GaussianBlur(glow / 2)), tuple(color[:3]) + (110,))
        bar = horizontal_gradient(filled, height, tuple(color[:3]) + (140,), tuple(color[:3]) + (255,))
        bar.putalpha(ImageChops.multiply(bar.getchannel("A"), mask))
        light = Image.new("RGBA", (filled, height), (255, 255, 255, 0))
        light.putalpha(scaled(top_edge(mask), 70))
        bar.alpha_composite(light)
        strip.alpha_composite(bar, (glow, glow))
    return strip
