import base64
import io
from PIL import Image

MAX_DIMENSION = 1024
JPEG_QUALITY = 85
ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def validate_image_mime(content_type: str) -> bool:
    return content_type.lower() in ALLOWED_MIME_TYPES


def process_image(image_bytes: bytes) -> tuple[str, str]:
    """Downscale and encode an image for LLM consumption.

    Args:
        image_bytes: Raw image file bytes.

    Returns:
        Tuple of (base64_encoded_string, mime_type).
        mime_type is "image/png" if alpha channel, otherwise "image/jpeg".
    """
    img = Image.open(io.BytesIO(image_bytes))

    # Downscale if needed
    width, height = img.size
    longest = max(width, height)
    if longest > MAX_DIMENSION:
        scale = MAX_DIMENSION / longest
        new_width = int(width * scale)
        new_height = int(height * scale)
        img = img.resize((new_width, new_height), Image.LANCZOS)

    # Encode
    has_alpha = img.mode in ("RGBA", "LA", "PA") or (
        img.mode == "P" and "transparency" in img.info
    )

    buf = io.BytesIO()
    if has_alpha:
        img.save(buf, format="PNG")
        mime = "image/png"
    else:
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=JPEG_QUALITY)
        mime = "image/jpeg"

    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return b64, mime
