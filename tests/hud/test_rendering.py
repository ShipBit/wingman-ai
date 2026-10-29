"""What a HUD window renders: only what is in view, and only what changed."""

import io
import threading
import time

import pytest
from PIL import Image, ImageDraw, ImageFont

import hud_server.rendering.markdown as markdown
from hud_server.constants import GROUP_CHAT
from hud_server.hud_manager import HudManager
from hud_server.rendering.glass import SHADOW
from hud_server.rendering.layers import Piece, PieceCache, lay_out, render_piece
from hud_server.rendering.markdown import MarkdownRenderer
from tests.support import FakeHudBackend, make_overlay, overlay_errors, run_frames

LONG = "\n\n".join(f"Paragraph {i}: the quick brown fox jumps over the lazy dog." for i in range(40))


@pytest.fixture
def clock(monkeypatch):
    """The overlay's time, moved by hand: typewriter and loader follow it."""
    now = [1000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    return now


@pytest.fixture
def rendered_blocks(monkeypatch):
    """The start of every markdown block rendered, in order."""
    starts = []
    original = MarkdownRenderer.render

    def render(self, draw, canvas, text, x, y, width, max_chars=None, pre_parsed_blocks=None):
        for block in pre_parsed_blocks or []:
            starts.append(block.get("start"))
        return original(self, draw, canvas, text, x, y, width, max_chars, pre_parsed_blocks)

    monkeypatch.setattr(MarkdownRenderer, "render", render)
    return starts


def show(overlay, content, **props):
    overlay._handle_message({
        "type": "show_message", "group": "atc", "element": "message", "title": "ATC",
        "content": content, "props": {"typewriter_effect": False, "width": 400, **props},
    })


def chat(**style):
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    manager = HudManager()
    manager.register_command_callback(overlay._handle_message)
    area = {"layout_mode": "manual", "x": 0, "y": 0, "width": 400, "max_height": 300, "align": "top"}
    manager.set_defaults({"typewriter_effect": False, **style}, {GROUP_CHAT: area})
    manager.create_group(GROUP_CHAT, "chat")
    return backend, overlay, manager


def light_pixels(image, box):
    return sum(1 for p in image.crop(box).getdata() if p[0] > 200 and p[3] > 200)


def test_a_message_longer_than_its_window_shows_its_end():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)

    show(overlay, LONG + "\n\nTHE END", max_height=400)
    run_frames(overlay)

    image = backend.window("HUD_message_atc").image
    assert image.height == SHADOW.top + 400 + SHADOW.bottom
    assert light_pixels(image, (SHADOW.left, SHADOW.top + 200, SHADOW.left + 400, SHADOW.top + 400)) > 100
    assert overlay_errors(overlay) == []


def test_text_above_the_window_is_not_rendered(rendered_blocks):
    backend = FakeHudBackend()
    overlay = make_overlay(backend)

    show(overlay, LONG, max_height=300)
    run_frames(overlay)

    # 79 blocks (paragraphs and the empty lines between them); a few fill 300 px
    assert 0 < len(rendered_blocks) < 20
    assert 0 not in rendered_blocks


def test_a_loader_frame_renders_nothing_but_the_loader(clock, rendered_blocks):
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    show(overlay, "Checking the hangar.\n\nStand by.")
    overlay._handle_message({"type": "set_loader", "group": "atc", "show": True})
    run_frames(overlay)
    before = len(rendered_blocks)
    first = backend.window("HUD_message_atc").image.tobytes()

    for _ in range(10):
        clock[0] += 0.05
        run_frames(overlay, 1)

    assert len(rendered_blocks) == before
    assert backend.window("HUD_message_atc").image.tobytes() != first  # the loader moved


def test_a_typed_block_is_not_rendered_again_while_the_next_one_types(clock, rendered_blocks):
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    show(overlay, "Short first line.\n\n" + "A much longer second paragraph. " * 6, typewriter_effect=True)

    for _ in range(30):
        clock[0] += 0.02  # 4 characters a frame
        run_frames(overlay, 1)

    first_block = [s for s in rendered_blocks if s == 0]
    # Typed in about 5 frames, then kept
    assert len(first_block) <= 6
    assert rendered_blocks[-1] != 0


def test_a_chat_renders_only_the_messages_in_view():
    backend, overlay, manager = chat()
    for i in range(40):
        manager.send_chat_message(GROUP_CHAT, "chat", "Jay" if i % 2 else "Orionis", f"Line {i}. " * 8, own=bool(i % 2))
    run_frames(overlay)

    pieces = overlay._windows[f"chat_{GROUP_CHAT}"]["pieces"]
    assert 0 < len(pieces) < 12
    assert pieces.renders < 15


def test_the_info_panel_keeps_its_newest_items_in_view():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    overlay._handle_message({"type": "create_group", "group": "info", "element": "persistent",
                             "props": {"max_height": 200}})
    for i in range(12):
        overlay._handle_message({
            "type": "add_item", "group": "info", "element": "persistent", "title": f"Item {i}",
            "description": "Some details",
        })
        overlay._windows["persistent_info"]["items"][f"Item {i}"]["added_at"] = i
    run_frames(overlay)

    titles = {key[1][1] for key in overlay._windows["persistent_info"]["pieces"]._images}
    assert "Item 11" in titles
    assert "Item 0" not in titles


def test_an_info_item_shows_its_picture_small_and_round_beside_the_title(tmp_path):
    picture = tmp_path / "lena.png"
    Image.new("RGB", (512, 512), (255, 0, 0)).save(picture)
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    overlay._handle_message({"type": "create_group", "group": "npc", "element": "persistent",
                             "props": {"width": 320, "font_size": 16, "bg_color": "#000000"}})
    overlay._handle_message({"type": "add_item", "group": "npc", "element": "persistent",
                             "title": "Lena Varga", "description": "Tammany and Sons · Lorville"})
    run_frames(overlay)
    without = backend.window("HUD_persistent_npc").image.copy()

    overlay._handle_message({"type": "add_item", "group": "npc", "element": "persistent",
                             "title": "Lena Varga", "description": "Tammany and Sons · Lorville",
                             "icon": str(picture)})
    run_frames(overlay)
    image = backend.window("HUD_persistent_npc").image

    red = [(x, y) for x in range(image.width) for y in range(image.height)
           if (p := image.getpixel((x, y)))[0] > 200 and p[1] < 60 and p[2] < 60]
    assert red, "the picture is drawn"
    xs, ys = [x for x, _ in red], [y for _, y in red]
    assert max(xs) - min(xs) <= 40 and max(ys) - min(ys) <= 40, "small: a picture in a ring, not a block"
    assert min(ys) < image.height / 2 and min(xs) < image.width / 3, "beside the title, at the top left"
    assert image.height > without.height - 1 and image.tobytes() != without.tobytes()


def test_in_the_chat_a_reply_has_its_picture_and_the_users_own_message_is_a_bubble_on_the_right(tmp_path):
    avatar = tmp_path / "orionis.png"
    Image.new("RGB", (64, 64), (255, 0, 0)).save(avatar)
    backend, overlay, manager = chat(accent_color="#00ff00", bg_color="#000000")

    manager.send_chat_message(GROUP_CHAT, "chat", "Jay", "Status?", own=True)
    manager.send_chat_message(GROUP_CHAT, "chat", "Orionis", "All green.", icon=str(avatar))
    run_frames(overlay)

    image = backend.window(f"HUD_chat_{GROUP_CHAT}").image
    red = lambda p: p[0] > 200 and p[1] < 60 and p[2] < 60
    tinted = lambda p: p[1] > p[0] + 40 and p[1] > p[2] + 40
    left, right = image.crop((0, 0, 200, image.height)), image.crop((200, 0, 400, image.height))
    assert any(red(p) for p in left.getdata())
    assert not any(red(p) for p in right.getdata())
    assert sum(1 for p in right.getdata() if tinted(p)) > 300


def test_a_chat_reply_types_itself_out(clock):
    backend, overlay, manager = chat(typewriter_effect=True)
    manager.send_chat_message(GROUP_CHAT, "chat", "Orionis", "All systems online and standing by. " * 3)

    clock[0] += 0.05
    run_frames(overlay, 1)
    typing = light_pixels(backend.window(f"HUD_chat_{GROUP_CHAT}").image, (0, 0, 400, 300))
    for _ in range(20):
        clock[0] += 0.1
        run_frames(overlay, 1)
    done = light_pixels(backend.window(f"HUD_chat_{GROUP_CHAT}").image, (0, 0, 400, 300))

    assert 0 < typing < done


def test_a_web_image_loads_beside_the_hud_and_shows_once_it_arrived(monkeypatch):
    release = threading.Event()
    png = io.BytesIO()
    Image.new("RGB", (40, 40), (255, 0, 0)).save(png, "PNG")

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout=None):
        release.wait(5)
        return Response(png.getvalue())

    monkeypatch.setattr(markdown.urllib.request, "urlopen", urlopen)
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    show(overlay, "Look: ![ship](https://example.invalid/ship.png)")

    started = time.monotonic()
    run_frames(overlay)
    assert time.monotonic() - started < 2  # the download does not hold the HUD

    release.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run_frames(overlay, 1)
        image = backend.window("HUD_message_atc").image
        if any(p[0] > 200 and p[1] < 60 and p[2] < 60 for p in image.getdata()):
            break
    else:
        pytest.fail("the downloaded image never showed")


def test_each_web_image_downloads_once_however_many_show(monkeypatch):
    png = io.BytesIO()
    Image.new("RGB", (40, 40), (0, 0, 255)).save(png, "PNG")
    requested = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout=None):
        requested.append(request.full_url)
        return Response(png.getvalue())

    monkeypatch.setattr(markdown.urllib.request, "urlopen", urlopen)
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    images = "\n\n".join(f"![{i}](https://example.invalid/many/{i}.png)" for i in range(30))
    show(overlay, images, max_height=4000)

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and len(set(requested)) < 30:
        run_frames(overlay, 1)
    run_frames(overlay, 20)

    assert len(requested) == len(set(requested)) == 30


def test_a_growing_typed_block_renders_once_a_frame(clock, rendered_blocks):
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    show(overlay, "word " * 900, typewriter_effect=True, max_height=2000)
    for _ in range(60):  # well past 256 px of typed text
        clock[0] += 0.1
        run_frames(overlay, 1)
    before = len(rendered_blocks)

    for _ in range(10):
        clock[0] += 0.02
        run_frames(overlay, 1)

    assert len(rendered_blocks) - before <= 10


def test_text_appended_to_a_message_renders_only_the_block_it_changes(rendered_blocks):
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    first = "One.\n\nTwo.\n\nThree"
    show(overlay, first)
    run_frames(overlay)
    rendered_blocks.clear()

    show(overlay, first + " and more.")
    run_frames(overlay)

    assert rendered_blocks == [first.rindex("Three")]


def test_a_block_taller_than_a_piece_can_be_shows_its_end():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    code = "\n".join(f"line {i}" for i in range(1200))

    show(overlay, f"```\n{code}\n```\n\nTHE END", max_height=400)
    run_frames(overlay)

    image = backend.window("HUD_message_atc").image
    assert light_pixels(image, (0, 300, 400, 400)) > 50
    assert overlay_errors(overlay) == []


def test_the_users_bubble_fits_bold_text_emoji_and_links_on_one_line():
    backend, overlay, manager = chat()
    manager.send_chat_message(GROUP_CHAT, "chat", "Jay", "Hi", own=True)
    run_frames(overlay)
    one_line = overlay._windows[f"chat_{GROUP_CHAT}"]["static_canvas"].height

    for text in (
        "**Status report please, commander**",
        "Emoji \U0001F680\U0001F680\U0001F680 launch now \U0001F600",
        "[the map](https://example.invalid/a/very/long/path/to/the/map/of/stanton)",
    ):
        manager.clear_chat_window(GROUP_CHAT, "chat")
        manager.send_chat_message(GROUP_CHAT, "chat", "Jay", text, own=True)
        run_frames(overlay)
        # An emoji may stand a little taller than letters; a second line would add a whole line
        assert overlay._windows[f"chat_{GROUP_CHAT}"]["static_canvas"].height - one_line < 10, text


def test_long_names_are_cut_to_the_window():
    backend, overlay, manager = chat(accent_color="#00ff00")
    manager.send_chat_message(GROUP_CHAT, "chat", "\U0001F680 Rocket [happy] " + "Commander " * 10, "Ready.")
    run_frames(overlay)

    image = backend.window(f"HUD_chat_{GROUP_CHAT}").image
    green = [
        i % image.width for i, p in enumerate(image.getdata()) if p[1] > 200 and p[0] < 100 and p[3] > 200
    ]
    assert green and max(green) < image.width - 8
    assert overlay_errors(overlay) == []


def test_an_empty_own_message_draws_nothing():
    backend, overlay, manager = chat()

    manager.send_chat_message(GROUP_CHAT, "chat", "Jay", "  [happy]  ", own=True)
    run_frames(overlay)

    assert len(overlay._windows[f"chat_{GROUP_CHAT}"].get("pieces") or []) == 0


# Every style its own size, so a test can tell from the font which style drew a word (on any OS)
STYLE_SIZES = {"normal": 16, "bold": 17, "italic": 18, "bold_italic": 19, "code": 15}


def sized_renderer():
    fonts = {style: ImageFont.load_default(size=size) for style, size in STYLE_SIZES.items()}
    for level in range(1, 7):
        fonts[f"h{level}"] = fonts["bold"]
    fonts.update(header=fonts["bold"], emoji=fonts["normal"], _font_size=16)
    return MarkdownRenderer(fonts, {"text": (220, 220, 220), "accent": (0, 170, 255)}, color_emojis=False)


def styles_drawn(renderer, monkeypatch, text: str) -> dict:
    """Which style drew each word of `text`."""
    sizes = {size: style for style, size in STYLE_SIZES.items()}
    drawn = {}

    def record(draw, pos, word, fill, font, embedded_color=False):
        drawn[word.strip()] = sizes.get(font.size)

    monkeypatch.setattr(renderer, "_draw_text_with_spacing", record)
    image = Image.new("RGBA", (400, 300))
    renderer.render(ImageDraw.Draw(image), image, text, 0, 0, 380)
    return drawn


def test_bold_keeps_its_weight_in_a_blockquote(monkeypatch):
    drawn = styles_drawn(sized_renderer(), monkeypatch, "> plain **strong** words")

    assert (drawn["plain"], drawn["strong"], drawn["words"]) == ("italic", "bold_italic", "italic")


def test_a_task_item_has_its_checkbox_and_no_bullet(monkeypatch):
    bullets = []
    original = ImageDraw.ImageDraw.text

    def text(self, xy, content, *args, **kwargs):
        if content == "•":
            bullets.append(xy)
        return original(self, xy, content, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", text)
    image = Image.new("RGBA", (400, 200))
    sized_renderer().render(ImageDraw.Draw(image), image, "- [ ] buy cargo\n- [x] sell cargo\n- plain item", 0, 0, 380)

    assert len(bullets) == 1  # only the plain item


def test_a_blockquote_box_fits_its_text():
    renderer = sized_renderer()

    def height(text):
        image = Image.new("RGBA", (400, 300))
        return renderer.render(ImageDraw.Draw(image), image, text, 0, 0, 380)

    one_line = height("> **Taranite**: 22 SCU, only 22 in stock here.")
    two_lines = height("> " + "word " * 40)
    # Used to be estimated in the widest font: a short bold line got a box a line too tall
    assert one_line < renderer.line_height * 2
    assert two_lines - one_line >= renderer.line_height * 0.5


def test_strikethrough_in_a_table_cell_crosses_the_word(monkeypatch):
    renderer = sized_renderer()
    words, lines = {}, []
    original_text, original_line = ImageDraw.ImageDraw.text, ImageDraw.ImageDraw.line

    def text(self, xy, content, *args, **kwargs):
        words[content] = (xy, kwargs.get("font"))
        return original_text(self, xy, content, *args, **kwargs)

    def line(self, points, *args, **kwargs):
        lines.append(points)
        return original_line(self, points, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", text)
    monkeypatch.setattr(ImageDraw.ImageDraw, "line", line)
    image = Image.new("RGBA", (400, 200))
    renderer.render(ImageDraw.Draw(image), image, "| Sell | SCU |\n|---|---|\n| ~~Astatine~~ | 618 |", 0, 0, 380)

    (x, y), font = words["Astatine"]
    left, top, right, bottom = font.getbbox("Astatine")
    strike_y = [points[0][1] for points in lines if points[0][0] == x]
    # Through the letters, not along their top (it used to ignore the font's offset to the ink)
    assert strike_y and y + top < strike_y[0] < y + bottom


def drawn_texts(renderer, monkeypatch, text: str, width: int = 380) -> dict:
    """Where (x, y) and in which colour each piece of `text` was drawn."""
    drawn = {}

    def record(draw, pos, word, fill, font, embedded_color=False):
        drawn[word.strip()] = (pos, fill)

    monkeypatch.setattr(renderer, "_draw_text_with_spacing", record)
    image = Image.new("RGBA", (400, 400))
    renderer.render(ImageDraw.Draw(image), image, text, 0, 0, width)
    return drawn


def test_a_right_aligned_table_column_puts_its_values_at_the_right_edge(monkeypatch):
    renderer = sized_renderer()
    cells = []
    original = renderer._render_cell_content_with_pos

    def record(draw, text, x, *args):
        cells.append((text, x))
        return original(draw, text, x, *args)

    monkeypatch.setattr(renderer, "_render_cell_content_with_pos", record)
    image = Image.new("RGBA", (400, 200))
    renderer.render(ImageDraw.Draw(image), image, "| Buy | SCU |\n|---|---:|\n| Tin | 9 |\n| Gold | 1,234 |", 0, 0, 380)

    x = dict(cells)
    assert x["9"] > x["1,234"]  # both end at the right edge, the shorter starts further right
    assert x["Tin"] == x["Gold"]  # the left column stays left


def test_a_bar_block_draws_its_segments_to_scale_in_the_profiles_colours(monkeypatch):
    renderer = sized_renderer()
    renderer.set_colors((220, 220, 220), (0, 170, 255), (20, 20, 30), 255)
    painted = []
    original = markdown.glass.paint

    def paint(image, mask, color, at=(0, 0)):
        painted.append((mask.size, tuple(color[:3])))
        return original(image, mask, color, at)

    monkeypatch.setattr(markdown.glass, "paint", paint)
    image = Image.new("RGBA", (400, 200))
    renderer.render(ImageDraw.Draw(image), image, "```bar\nmax: 100\nHold | 50 accent | 25 text\n```", 0, 0, 380)

    accent = [size for size, color in painted if color == (0, 170, 255)]
    text = [size for size, color in painted if color == (220, 220, 220)]
    track = max(size[0] for size, _ in painted)  # the track is the full bar
    assert accent and text
    assert abs(accent[0][0] - track / 2) <= 3 and abs(text[0][0] - track / 4) <= 3


def test_a_steps_block_puts_the_route_in_one_row_even_when_it_is_too_wide(monkeypatch):
    short = drawn_texts(sized_renderer(), monkeypatch, "```steps\ndone | A\ncurrent | B\njump | Jump\nnext | C\n```")
    rows = [short[stop][0][1] for stop in ("A", "B", "C")]
    assert max(rows) - min(rows) <= 2  # one row (the current stop is bold, centred a pixel apart)
    assert short["A"][0][0] < short["B"][0][0] < short["C"][0][0]
    assert "JUMP" not in short and "Jump" not in short  # a symbol, not a word

    long_names = "```steps\ndone | " + "Long Station Name " * 2 + "\ncurrent | " + "Another Long Name " * 2 + "\n```"
    wide = drawn_texts(sized_renderer(), monkeypatch, long_names)
    ys = [pos[1] for pos, _ in wide.values()]
    assert max(ys) - min(ys) <= 2


def test_a_gap_separates_pieces_and_leaves_none_under_the_bottom_one():
    pieces = [Piece(("piece", i), lambda d, image, top: 20, gap=10) for i in range(2)]
    layout = lay_out(PieceCache(), pieces, 100, 600, top=16, bottom=12)

    assert layout.height == 16 + 20 + 10 + 20 + 12
    assert [y for _, y, _ in layout.placed] == [16, 46]


def test_a_tall_piece_that_ends_higher_once_drawn_whole_keeps_that_end():
    # As an info item does: it can only trim to its ink when the whole of it fits the image
    piece = render_piece(100, lambda d, image, top: 280 if image.height >= 300 else 300)
    assert piece.height == 280


def info_item(description: str) -> Image.Image:
    overlay = make_overlay(FakeHudBackend())
    props = {"width": 400, "content_padding": 16, "font_size": 16}
    text, accent, bg = (240, 240, 240), (0, 170, 255), (30, 33, 43, 255)
    overlay._window_renderer(props, text, accent, bg)
    piece = overlay._info_item_piece("Trade run", {"title": "Trade run", "description": description}, None, 0.0,
                                     props, overlay._style_key(props), text, accent, bg, separator=False)
    return render_piece(400, piece.draw)


@pytest.mark.parametrize("last_block", ["| Sell | SCU |\n|---|---:|\n| Gold | 4 |"])
def test_an_info_item_ending_in_a_table_or_card_ends_close_under_it(last_block):
    image = info_item("Stop 1 of 2\n\n" + last_block)
    assert image.height - image.getchannel("A").getbbox()[3] == 6  # 4 under the ink, as text gets, and 2


def test_route_legs_show_progress_and_a_jump_puts_a_gate_on_its_leg(monkeypatch):
    renderer = sized_renderer()
    renderer.set_colors((220, 220, 220), (0, 170, 255), (20, 20, 30), 255)
    legs, gates = [], []
    monkeypatch.setattr(renderer, "_draw_chevrons", lambda strip, start, end, center, leg: legs.append((start, leg)))
    monkeypatch.setattr(renderer, "_draw_jump_gate", lambda strip, x, center, color: gates.append((x, color)))
    drawn = drawn_texts(renderer, monkeypatch, "```steps\ndone | A\ncurrent | B\njump | Jump\nnext | C\nnext | D\n```")

    assert [leg for _, leg in sorted(legs)] == ["flown", "next", "next", "ahead"]  # the jump leg in two halves
    assert len(gates) == 1 and drawn["B"][0][0] < gates[0][0] < drawn["C"][0][0]
    assert gates[0][1] == (0, 170, 255)  # on the leg to the next stop: the accent


@pytest.mark.parametrize("current, left_faded, right_faded", [(0, False, True), (4, True, True)])
def test_a_route_too_wide_for_its_row_shows_the_current_stop_and_fades_where_it_goes_on(current, left_faded, right_faded):
    stops = [("done" if i < current else "current" if i == current else "next") + f" | Station Number {i}"
             for i in range(8)]
    image = Image.new("RGBA", (380, 60))
    sized_renderer().render(ImageDraw.Draw(image), image, "```steps\n" + "\n".join(stops) + "\n```", 0, 0, 380)
    alpha = image.getchannel("A")

    def edge(left: int) -> int:
        return max(alpha.crop((left, 0, left + 8, 60)).getdata())

    assert (edge(0) < 100) == left_faded and (edge(372) < 100) == right_faded
    ring = [pixel for pixel in image.getdata() if pixel[3] > 200 and pixel[2] > 200 and pixel[0] < 60]
    assert ring  # the current stop's accent icon, unfaded


def test_a_stats_block_shows_values_under_their_labels_and_colours_accent_ones(monkeypatch):
    renderer = sized_renderer()
    renderer.set_colors((220, 220, 220), (0, 170, 255), (20, 20, 30), 255)
    drawn = drawn_texts(renderer, monkeypatch, "```stats\nPaid | 5,000\nProfit | 2,000 | accent\n```")

    assert drawn["5,000"][0][1] > drawn["Paid"][0][1]  # value below its label
    assert drawn["Profit"][0][0] > drawn["Paid"][0][0]  # side by side
    assert tuple(drawn["2,000"][1][:3]) == (0, 170, 255) and tuple(drawn["5,000"][1][:3]) == (220, 220, 220)


def test_table_columns_follow_their_content():
    renderer = sized_renderer()
    normal, bold = renderer.fonts["normal"], renderer.fonts["bold"]
    rows = [["Commodity", "SCU", "aUEC"], ["Recycled Material Composite", "640", "5,696,000"]]

    widths = renderer._table_column_widths(rows, 3, normal, bold, 400, 6)
    assert sum(widths) == 400
    assert widths[0] > widths[1]  # the long name gets the room, the short column stays narrow
    assert widths[0] >= renderer._get_text_size("Recycled Material Composite", normal)[0] + 12  # no wrap

    # Too narrow for the content: still exactly the table's width, no column below the minimum
    tight = renderer._table_column_widths(rows, 3, normal, bold, 160, 6)
    assert sum(tight) == 160 and min(tight) >= renderer.TABLE_MIN_COLUMN
