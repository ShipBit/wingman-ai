"""What the Linux backend hands X: no display needed."""

from PIL import Image

from hud_server.platform.linux import _premultiplied_bgra


def test_pixels_go_to_x_premultiplied_in_bgra_order():
    image = Image.new("RGBA", (1, 1), (200, 100, 50, 128))

    b, g, r, a = _premultiplied_bgra(image, 255)

    assert a == 128
    assert (r, g, b) == (200 * 128 // 255, 100 * 128 // 255, 50 * 128 // 255)


def test_the_window_opacity_is_baked_into_the_alpha():
    image = Image.new("RGBA", (1, 1), (255, 255, 255, 255))

    b, g, r, a = _premultiplied_bgra(image, 128)

    assert a == 128
    assert r == g == b == 128
