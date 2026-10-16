"""A message draws its loader in the profile's accent color, and its tables
in a shade of the panel's background, as see-through as the background."""

from PIL import Image

from tests.support import FakeHudBackend, make_overlay, overlay_errors, run_frames

RED = "#ff0000"
TABLE = "| Ship | Fuel |\n|---|---|\n| Cutlass | 80 % |\n| Prospector | 45 % |\n| Vulture | 12 % |"


def show(overlay, content, **props):
    overlay._handle_message({
        "type": "show_message", "group": "atc", "element": "message", "title": " ",
        "content": content, "props": {"typewriter_effect": False, **props},
    })


def drawn(backend, overlay):
    run_frames(overlay)
    assert overlay_errors(overlay) == []
    return list(backend.window("HUD_message_atc").image.getdata())


def table_pixels(pixels, panel, lighter):
    """Neutral pixels a little lighter (or darker) than the panel, at about its opacity."""
    def shaded(p):
        neutral = max(p[:3]) - min(p[:3]) <= max(panel) - min(panel) + 6
        moved = all(c > b for c, b in zip(p[:3], panel)) if lighter else all(c < b for c, b in zip(p[:3], panel))
        return neutral and moved and 128 <= p[3] <= 150
    return [p for p in pixels if shaded(p)]


def test_a_table_is_a_lighter_shade_of_a_dark_background_and_as_see_through():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    show(overlay, TABLE, accent_color=RED, bg_color="#1e212b80")

    pixels = drawn(backend, overlay)

    assert len(table_pixels(pixels, (30, 33, 43), lighter=True)) > 10_000
    # Not the accent: only the red header text leans red
    assert sum(1 for p in pixels if p[0] > p[1] + 5 and p[3] < 250) < 2_000


def test_on_a_light_background_a_table_is_a_darker_shade():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    show(overlay, TABLE, accent_color=RED, bg_color="#f0f0f080", text_color="#202020")

    assert len(table_pixels(drawn(backend, overlay), (240, 240, 240), lighter=False)) > 10_000


def test_the_loader_runs_in_the_accent_color():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    show(overlay, "Checking the hangar", accent_color=RED)

    overlay._handle_message({"type": "set_loader", "group": "atc", "show": True})

    assert (255, 0, 0, 255) in drawn(backend, overlay)


def test_a_loader_color_given_by_the_call_wins():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    show(overlay, "Checking the hangar", accent_color=RED)

    overlay._handle_message({"type": "set_loader", "group": "atc", "show": True, "color": "#00ff00"})

    pixels = drawn(backend, overlay)
    assert (0, 255, 0, 255) in pixels
    assert (255, 0, 0, 255) not in pixels


def test_the_table_text_has_no_light_rim_on_a_see_through_row():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    show(overlay, TABLE, accent_color="#d84f4f", bg_color="#202227d9", text_color="#cccccc")
    run_frames(overlay)
    image = backend.window("HUD_message_atc").image
    scene = Image.new("RGBA", image.size, (120, 70, 40, 255))
    scene.alpha_composite(image)
    pixels = scene.load()

    header = [y for y in range(scene.height) for x in range(scene.width)
              if pixels[x, y][0] > 180 and pixels[x, y][1] < 110]
    top, bottom = min(header) - 3, max(header) + 3
    row = pixels[30, top + 1]
    # Text edges laid over the row, not mixed into its light shade
    rim = [
        (x, y) for y in range(top, bottom) for x in range(20, scene.width - 20)
        if all(c > r + 25 for c, r in zip(pixels[x, y][:3], row[:3])) and pixels[x, y][1] > 90
    ]
    assert rim == []
