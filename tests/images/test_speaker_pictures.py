"""The picture of someone a skill voices, as it travels with their lines."""

import base64
import io

import pytest
from PIL import Image

from services.image_generation import PICTURE_SIZE, picture_data_url


def _decoded(data_url: str) -> Image.Image:
    assert data_url.startswith("data:image/jpeg;base64,")
    return Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1])))


def test_a_picture_is_a_small_jpeg_with_transparency_on_white(tmp_path):
    file = tmp_path / "lena.png"
    Image.new("RGBA", (1024, 1024), (0, 0, 0, 0)).save(file)

    picture = _decoded(picture_data_url(str(file)))

    assert picture.size == (PICTURE_SIZE, PICTURE_SIZE) and picture.mode == "RGB"
    assert picture.getpixel((5, 5)) == (255, 255, 255)


def test_a_small_or_wide_picture_keeps_its_proportion(tmp_path):
    file = tmp_path / "wide.jpg"
    Image.new("RGB", (640, 320), "blue").save(file)
    assert _decoded(picture_data_url(str(file))).size == (128, 64)

    small = tmp_path / "small.png"
    Image.new("RGB", (40, 40), "red").save(small)
    assert _decoded(picture_data_url(str(small))).size == (40, 40), "never enlarged"


def test_a_file_that_is_no_picture_raises(tmp_path):
    file = tmp_path / "notes.png"
    file.write_text("not an image", encoding="utf-8")
    with pytest.raises(Exception):
        picture_data_url(str(file))
    with pytest.raises(Exception):
        picture_data_url(str(tmp_path / "missing.png"))
