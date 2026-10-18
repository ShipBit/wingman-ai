"""The Windows proactor must not lose its loop to a stale socket read.

The proactor itself only exists on Windows, so the tolerance is tested on a
stand-in with the same ``select``/``_results`` contract as ``IocpProactor``.
"""

import asyncio

from services.event_loop import StaleCompletionTolerance


class FakeProactor:
    """``IocpProactor.select``: poll, then hand over what the poll collected.
    The poll raises the way ``_poll`` does when another thread cancelled a
    read's future while it was being finished."""

    def __init__(self, polls):
        self._results = []
        self._polls = list(polls)

    def select(self, timeout=None):
        if not self._results:
            collected, raises = self._polls.pop(0)
            self._results.extend(collected)
            if raises:
                raise asyncio.InvalidStateError("invalid state")
        tmp = self._results
        self._results = []
        return tmp


class TolerantFake(StaleCompletionTolerance, FakeProactor):
    pass


def test_stale_completion_keeps_what_was_collected_before_it():
    proactor = TolerantFake([(["read-a", "read-b"], True)])

    assert proactor.select() == ["read-a", "read-b"]
    assert proactor._results == []


def test_polling_goes_on_after_a_stale_completion():
    proactor = TolerantFake([([], True), (["read-c"], False)])

    assert proactor.select() == []
    assert proactor.select() == ["read-c"]
