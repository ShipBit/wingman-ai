"""Images for a vision model, from Vision AI or attached to a chat message,
are JPEGs that fit into one Wingman Pro request."""

import base64
import io

from PIL import Image

from services.image_generation import (
    VISION_MAX_CHARS,
    VISION_MAX_PIXELS,
    vision_base64,
)
from services.image_processing import process_images


def _decode(encoded: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(encoded)))


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _noise() -> Image.Image:
    # Noise compresses worst of all: far over the limit at full size and quality
    return Image.effect_noise((2560, 1440), 100).convert("RGB")


def test_screen_becomes_a_small_jpeg():
    screen = Image.new("RGBA", (2560, 1440), (30, 40, 60, 255))

    image = _decode(vision_base64(screen))

    assert image.format == "JPEG"
    assert image.width * image.height <= VISION_MAX_PIXELS
    assert abs(image.width / image.height - 16 / 9) < 0.01


def test_ultrawide_screen_keeps_its_height():
    # At 1280 pixels wide a 32:9 screen was 360 high: its text was unreadable
    screen = Image.new("RGB", (5120, 1440), (30, 40, 60))

    image = _decode(vision_base64(screen))

    assert image.height > 500


def test_busy_screen_still_fits_the_request_limit():
    encoded = vision_base64(_noise())

    assert len(encoded) <= VISION_MAX_CHARS
    assert _decode(encoded).format == "JPEG"


def test_attached_png_with_transparency_becomes_jpeg_on_white():
    transparent = Image.new("RGBA", (200, 100), (0, 0, 0, 0))

    [(encoded, mime)] = process_images([_png(transparent)])

    image = _decode(encoded)
    assert mime == "image/jpeg"
    assert image.format == "JPEG"
    assert image.getpixel((100, 50)) == (255, 255, 255)


def test_attached_images_fit_into_one_request_together():
    attached = [_png(_noise()) for _ in range(3)]

    processed = process_images(attached)

    assert sum(len(encoded) for encoded, _mime in processed) <= VISION_MAX_CHARS
