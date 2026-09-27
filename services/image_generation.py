"""Shared pieces of image generation: style presets, reference images and
storing what the model returns.

Used by the Image Generation skill and the avatar studio. The images come from
seedream through the Wingman Pro backend. seedream reads natural sentences
best. Concise and concrete beats a pile of keywords, and it has no negative
prompt, so the style blocks below mostly say what to do, not what to avoid.
"""

import base64
import datetime
import io
import re
from os import listdir, path, remove

import requests
from PIL import Image

from api.enums import ImageStyle

STYLE_PROMPTS: dict[ImageStyle, str] = {
    ImageStyle.NONE: "",
    ImageStyle.CINEMATIC: "Digital concept art painting like the key art of a science fiction film: visible painterly brushwork, dramatic volumetric light, teal and orange color grading, epic mood.",
    ImageStyle.PHOTO: "Ultra-realistic photograph taken with a professional full-frame camera, sharp focus, natural skin and material textures, true-to-life colors, realistic lighting.",
    ImageStyle.ANIME: "Modern anime illustration, clean line art, cel shading, vibrant colors, expressive eyes, like a key visual of a high-budget anime series.",
    ImageStyle.GHIBLI: "Studio Ghibli hand-drawn animation style, soft watercolor backgrounds, gentle pastel colors, warm natural light, whimsical and nostalgic mood.",
    ImageStyle.PIXAR: "Pixar-style 3D animation, stylized proportions, soft global illumination, smooth subsurface shading, expressive friendly features, polished render.",
    ImageStyle.CARTOON: "Flat 2D cartoon, bold clean outlines, simple shapes, bright solid colors, minimal shading, playful look.",
    ImageStyle.COMIC: "American comic book art, bold black ink lines, halftone dot shading, strong contrast, saturated colors, graphic novel look.",
    ImageStyle.OIL_PAINTING: "Traditional oil painting on canvas, clearly painted by hand with thick visible impasto brushstrokes and canvas texture, loose painterly edges, rich warm colors, in the manner of an old master portrait.",
    ImageStyle.PIXEL_ART: "Retro 16-bit pixel art like a 1990s console game: a low-resolution image made of large, clearly visible square pixels, limited color palette, hard edges without anti-aliasing, no smooth gradients.",
    ImageStyle.SYNTHWAVE: "Neon synthwave style, glowing magenta and cyan light, dark background, chrome reflections, 1980s retro-futuristic mood.",
    ImageStyle.RETRO_SCIFI: "Vintage 1970s science fiction paperback cover illustration, airbrushed gouache painting, warm faded print colors, visible print grain, bold heroic pulp art.",
    ImageStyle.CLAYMATION: "Claymation, handmade plasticine figures with soft rounded shapes and visible fingerprints, miniature set, soft studio lighting, stop-motion look.",
    ImageStyle.SKETCH: "Detailed graphite pencil sketch on textured paper, fine hatching and cross-hatching, monochrome.",
}

# seedream paints a decorative frame around "digital painting" portraits unless
# told otherwise (seen 2026-09-25), and a frame ruins a round avatar crop.
AVATAR_FRAMING = (
    "Square head-and-shoulders portrait, face centered in the upper half of the image, "
    "looking at the viewer, simple uncluttered background, full-bleed image without any "
    "border, frame, text or logo."
)

# With a reference the background comes from the reference. "Simple
# uncluttered background" made seedream swap a cockpit for plain white.
AVATAR_FRAMING_REFINE = (
    "Square head-and-shoulders portrait, face centered in the upper half of the image, "
    "full-bleed image without any border, frame, text or logo."
)

# The backend accepts at most four and each one has to be small: a Vercel
# function takes 4.5 MB per request.
MAX_REFERENCE_IMAGES = 4
REFERENCE_MAX_DIMENSION = 1024

DATA_URL_PATTERN = re.compile(
    r"^data:(?P<mime>image/[a-zA-Z0-9.+-]+);base64,(?P<data>.+)$", re.DOTALL
)

# Characters Windows refuses in file names
FILENAME_UNSAFE_PATTERN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

MIME_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def compose_prompt(prompt: str, style: ImageStyle, framing: str = "") -> str:
    """The prompt as seedream gets it: the style, then the description, then
    the framing. Core adds style and framing so they are never lost to a model
    that shortens or rewords them.

    The style goes first: at the end, a realistic description ("warm light
    from the side, a hangar") won over it, and oil painting, retro sci-fi and
    pixel art came out as photos (seedream-4.5, 2026-09-25)."""
    parts = [STYLE_PROMPTS.get(style, ""), prompt.strip().rstrip(".") + ".", framing]
    return " ".join(part for part in parts if part)


def reference_data_url(image_bytes: bytes) -> str:
    """An image as a reference for the backend: JPEG, at most 1024 pixels on
    the long side, about 150 to 300 KB. Transparency goes onto white, because
    a PNG with alpha can be several megabytes."""
    image = Image.open(io.BytesIO(image_bytes))
    image.thumbnail((REFERENCE_MAX_DIMENSION, REFERENCE_MAX_DIMENSION), Image.LANCZOS)
    if image.mode in ("RGBA", "LA", "PA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.getchannel("A"))
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def reference_from_data_url(data_url: str) -> str:
    """A data URL from the client or the chat history, shrunk the same way."""
    match = DATA_URL_PATTERN.match(data_url)
    if not match:
        raise ValueError("Not an image data URL")
    return reference_data_url(base64.b64decode(match.group("data")))


def safe_file_in(directory: str, filename: str) -> str | None:
    """The path of `filename` inside `directory`, or None if the name tries to
    leave it or the file does not exist."""
    if not filename or path.basename(filename) != filename:
        return None
    root = path.realpath(directory)
    file_path = path.realpath(path.join(root, filename))
    if path.commonpath([root, file_path]) != root or not path.isfile(file_path):
        return None
    return file_path


def store_image(image: str, directory: str, name_hint: str) -> str:
    """Write a generated image into `directory`.

    Providers either return an http(s) URL or an inline data URL, both are
    handled. Returns the path, or raises when the image could not be stored."""
    data_url = DATA_URL_PATTERN.match(image)

    if data_url:
        extension = MIME_EXTENSIONS.get(data_url.group("mime").lower(), "png")
        content = base64.b64decode(data_url.group("data"))
    else:
        response = requests.get(image, timeout=30)
        response.raise_for_status()
        mime = response.headers.get("content-type", "")
        extension = MIME_EXTENSIONS.get(mime.split(";")[0].strip().lower(), "png")
        content = response.content

    # No spaces: the skill hands the name to the model, which has to repeat it
    # exactly to use the image as a reference later.
    name = "_".join(FILENAME_UNSAFE_PATTERN.sub("_", name_hint[:40]).split()) or "image"
    stem = f"{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{name}"
    image_path = path.join(directory, f"{stem}.{extension}")
    # The timestamp only resolves to seconds - two images from the same second
    # must not overwrite each other, the client links to the file.
    counter = 1
    while path.exists(image_path):
        image_path = path.join(directory, f"{stem}_{counter}.{extension}")
        counter += 1

    with open(image_path, "wb") as file:
        file.write(content)

    return image_path


def list_images(directory: str) -> list[str]:
    """Image files in `directory`, newest first."""
    if not path.isdir(directory):
        return []
    files = [
        path.join(directory, name)
        for name in listdir(directory)
        if path.splitext(name)[1].lower() in IMAGE_EXTENSIONS
    ]
    files = [entry for entry in files if path.isfile(entry)]
    files.sort(key=path.getmtime, reverse=True)
    return files


def prune_images(directory: str, keep: int) -> None:
    """Keep only the newest `keep` images in `directory`."""
    for stale in list_images(directory)[keep:]:
        remove(stale)
