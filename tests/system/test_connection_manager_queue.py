"""Without a client, events wait for the next one; state updates do not, or
an old state arrives after it changed."""

import asyncio
import threading
import time

from api.commands import ScGameLogStateChangedCommand, ToastCommand
from api.enums import ToastType
from api.interface import ScGameLogStatus
from services.connection_manager import ConnectionManager


def _manager() -> ConnectionManager:
    manager = ConnectionManager()
    manager.active_connections = []
    manager.message_queue = []
    return manager


def test_a_log_reader_status_is_not_queued_without_a_client():
    manager = _manager()
    status = ScGameLogStatus.model_construct(running=True, game_path="C:\\x", game_path_found=False)
    asyncio.run(manager.broadcast(ScGameLogStateChangedCommand.model_construct(status=status)))
    assert manager.message_queue == []


def test_a_toast_is_queued_without_a_client():
    manager = _manager()
    toast = ToastCommand.model_construct(text="hi", toast_type=ToastType.NORMAL)
    asyncio.run(manager.broadcast(toast))
    assert manager.message_queue == [toast]


class _Socket:
    def __init__(self):
        self.sent_on = []
        self.closed = False

    async def send_text(self, text):
        await asyncio.sleep(0.05)
        self.sent_on.append(threading.current_thread())

    async def close(self):
        self.closed = True


def test_a_turn_sends_on_the_main_loop_while_the_main_loop_holds_the_socket():
    # Each turn has its own loop on its own thread. Waiting for a send lock
    # the main loop holds raised RuntimeError there, and the client's socket
    # was closed from the turn's thread.
    manager = _manager()
    socket = _Socket()
    main_loop = asyncio.new_event_loop()
    main_thread = threading.Thread(target=main_loop.run_forever, daemon=True)
    main_thread.start()
    try:
        async def connect():
            manager.active_connections = [socket]
            manager._send_locks = {id(socket): asyncio.Lock()}

        asyncio.run_coroutine_threadsafe(connect(), main_loop).result(1)
        manager.set_main_loop(main_loop)
        toast = ToastCommand.model_construct(text="hi", toast_type=ToastType.NORMAL)
        on_main = asyncio.run_coroutine_threadsafe(manager.broadcast(toast), main_loop)

        def turn():
            asyncio.run(manager.broadcast(toast))

        turn_thread = threading.Thread(target=turn, daemon=True)
        turn_thread.start()
        turn_thread.join(2)
        on_main.result(2)
        # The turn hands its message over and goes on; the main loop sends it.
        deadline = time.monotonic() + 2
        while len(socket.sent_on) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)

        assert socket.sent_on == [main_thread, main_thread]
        assert not socket.closed
        assert manager.active_connections == [socket]
    finally:
        manager.set_main_loop(None)
        main_loop.call_soon_threadsafe(main_loop.stop)
        main_thread.join(1)
        main_loop.close()


def test_a_handed_over_message_that_fails_is_logged(monkeypatch):
    from services.printr import Printr

    logged = []
    monkeypatch.setattr(Printr, "print", lambda self, text, **kwargs: logged.append(text))
    manager = ConnectionManager()
    main_loop = asyncio.new_event_loop()
    main_thread = threading.Thread(target=main_loop.run_forever, daemon=True)
    main_thread.start()

    async def fails():
        raise ValueError("not serializable")

    try:
        manager.set_main_loop(main_loop)
        asyncio.run(manager._on_main_loop(fails()))
        deadline = time.monotonic() + 1
        while not logged and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        manager.set_main_loop(None)
        main_loop.call_soon_threadsafe(main_loop.stop)
        main_thread.join(1)
        main_loop.close()

    assert logged and "not serializable" in logged[0]
