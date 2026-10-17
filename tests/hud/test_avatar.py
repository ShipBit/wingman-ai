"""A Wingman's picture in the chat is a circle cut from the picture's middle."""

from PIL import Image

from hud_server.overlay.overlay import round_avatar


def test_the_corners_are_cut_away_and_the_middle_stays():
    avatar = round_avatar(Image.new("RGB", (128, 128), (200, 40, 40)), 40)

    assert avatar.size == (40, 40)
    assert avatar.getpixel((0, 0))[3] == 0
    assert avatar.getpixel((20, 20)) == (200, 40, 40, 255)


def test_a_wide_picture_shows_its_middle_instead_of_being_squeezed():
    picture = Image.new("RGB", (300, 100), (255, 0, 0))
    picture.paste((0, 255, 0), (100, 0, 200, 100))

    avatar = round_avatar(picture, 40)

    assert avatar.getpixel((4, 20))[:3] == (0, 255, 0)
    assert avatar.getpixel((35, 20))[:3] == (0, 255, 0)
