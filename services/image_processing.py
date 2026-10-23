import io

from PIL import Image

from services.image_generation import VISION_MAX_CHARS, vision_base64

ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def validate_image_mime(content_type: str) -> bool:
    return content_type.lower() in ALLOWED_MIME_TYPES


def process_images(images: list[bytes]) -> list[tuple[str, str]]:
    """Images the user attached to a chat message, as (base64, mime) for the
    LLM. JPEG like a Vision AI screenshot; together they fit into one Wingman
    Pro request, so each gets its share of the limit."""
    max_chars = VISION_MAX_CHARS // max(1, len(images))
    return [
        (vision_base64(Image.open(io.BytesIO(data)), max_chars), "image/jpeg")
        for data in images
    ]
