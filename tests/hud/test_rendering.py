"""What a HUD window renders: only what is in view, and only what changed."""

import io
import threading
import time

import pytest
from PIL import Image

import hud_server.rendering.markdown as markdown
from hud_server.constants import GROUP_CHAT
from hud_server.hud_manager import HudManager
from hud_server.rendering.layers import MAX_PIECE_HEIGHT, render_piece
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
    assert image.height == 400
    assert light_pixels(image, (0, 200, 400, 400)) > 100
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


def test_a_piece_taller_than_a_piece_may_be_keeps_its_end():
    def draw(d, image, top):
        end = MAX_PIECE_HEIGHT + 5000
        d.line([(0, end - 1 - top), (10, end - 1 - top)], fill=(255, 0, 0, 255))
        return end

    piece = render_piece(20, draw)

    assert piece.height == MAX_PIECE_HEIGHT
    assert piece.getpixel((5, piece.height - 1)) == (255, 0, 0, 255)


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


def test_the_users_bubble_is_as_wide_as_what_it_shows():
    backend, overlay, manager = chat(accent_color="#00ff00", bg_color="#000000")

    for text in ("[map](https://example.invalid/a/very/long/path/to/the/map/of/stanton)", "line one\nline two"):
        manager.clear_chat_window(GROUP_CHAT, "chat")
        manager.send_chat_message(GROUP_CHAT, "chat", "Jay", text, own=True)
        run_frames(overlay)

        image = backend.window(f"HUD_chat_{GROUP_CHAT}").image
        bubble = [i % image.width for i, p in enumerate(image.getdata()) if p[1] > 60 and p[0] < 40 and p[2] < 40]
        assert image.width - min(bubble) < image.width / 2, text


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


def test_a_window_without_height_draws_without_errors():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)

    show(overlay, "Hold short.", max_height=0)
    run_frames(overlay)

    assert overlay_errors(overlay) == []
