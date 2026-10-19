"""A screenshot for a vision model fits into one Wingman Pro request."""

import base64
import io

from PIL import Image

from services.image_generation import (
    SCREENSHOT_MAX_CHARS,
    SCREENSHOT_MAX_DIMENSION,
    screenshot_base64,
)


def _decode(encoded: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(encoded)))


def test_screen_becomes_a_small_jpeg():
    screen = Image.new("RGBA", (2560, 1440), (30, 40, 60, 255))

    image = _decode(screenshot_base64(screen))

    assert image.format == "JPEG"
    assert image.size == (SCREENSHOT_MAX_DIMENSION, 720)


def test_busy_screen_still_fits_the_request_limit():
    # Noise compresses worst of all: far over the limit at full size and quality
    screen = Image.effect_noise((2560, 1440), 100).convert("RGB")

    encoded = screenshot_base64(screen)

    assert len(encoded) <= SCREENSHOT_MAX_CHARS
    assert _decode(encoded).format == "JPEG"
