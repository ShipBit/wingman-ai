"""Without a client, events wait for the next one; state updates do not, or
an old state arrives after it changed."""

import asyncio

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
