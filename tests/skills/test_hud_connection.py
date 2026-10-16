"""The HUD skill is called from the main loop and from the loop of every
turn. Switching between them must not reconnect and rebuild the groups."""

import asyncio
import threading
from types import SimpleNamespace

import skills.hud.main as hud_main
from skills.hud.main import HUD


class FakeClient:
    made = []

    def __init__(self, base_url):
        self.connected = False
        self.groups = 0
        FakeClient.made.append(self)

    async def connect(self, timeout=None):
        self.connected = True
        return True

    async def create_group(self, *args, **kwargs):
        self.groups += 1
        return {}


def make_hud(monkeypatch):
    FakeClient.made = []
    monkeypatch.setattr(hud_main, "HudHttpClient", FakeClient)
    hud = HUD.__new__(HUD)
    hud._unloading = False
    hud.settings = SimpleNamespace(hud_server=SimpleNamespace(enabled=True))
    hud._clients = {}
    hud._groups_ready = False
    # A monitor that is already running, so the test starts none.
    hud._monitor_task = SimpleNamespace(done=lambda: False)
    hud._group_name = "KAT"
    hud._get_hud_props = lambda: None
    hud._get_persistent_props = lambda: None
    hud.active = False
    return hud


def run_on_new_loop(coro_factory):
    """Like a turn: a fresh loop on its own thread, closed afterwards."""
    result = {}

    def run():
        loop = asyncio.new_event_loop()
        try:
            result["value"] = loop.run_until_complete(coro_factory())
        finally:
            loop.close()

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    return result["value"]


def test_turns_on_their_own_loops_create_the_groups_once(monkeypatch):
    hud = make_hud(monkeypatch)
    for _ in range(3):
        assert run_on_new_loop(hud._ensure_connected)
    assert sum(client.groups for client in FakeClient.made) == 2
    # The closed loops' clients are dropped on the next call.
    run_on_new_loop(hud._ensure_connected)
    assert len(hud._clients) == 1


def test_a_failed_connection_rebuilds_the_groups(monkeypatch):
    hud = make_hud(monkeypatch)
    run_on_new_loop(hud._ensure_connected)

    async def refuse(self, timeout=None):
        return False

    monkeypatch.setattr(FakeClient, "connect", refuse)
    assert not run_on_new_loop(hud._ensure_connected)
    monkeypatch.undo()
    monkeypatch.setattr(hud_main, "HudHttpClient", FakeClient)
    assert run_on_new_loop(hud._ensure_connected)
    assert sum(client.groups for client in FakeClient.made) == 4


def test_a_lost_server_gets_the_groups_again(monkeypatch):
    """A failed request marks the client disconnected; the server may have
    restarted without this wingman's groups."""
    hud = make_hud(monkeypatch)

    async def turn():
        assert await hud._ensure_connected()
        hud._client.connected = False  # The next request failed.
        assert await hud._ensure_connected()

    run_on_new_loop(turn)
    assert sum(client.groups for client in FakeClient.made) == 4


def test_groups_that_failed_to_be_made_are_tried_again(monkeypatch):
    hud = make_hud(monkeypatch)

    async def refused(self, *args, **kwargs):
        self.groups += 1
        return None

    monkeypatch.setattr(FakeClient, "create_group", refused)
    run_on_new_loop(hud._ensure_connected)
    assert hud._groups_ready is False
