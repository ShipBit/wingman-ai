"""Saving a new global push-to-talk, shut up or mute key failed with a
TypeError: the event has no data, and a subscriber that takes an argument was
called without one. The save stopped there, so the new key had no hook and the
settings after it were not written until the next save."""

import asyncio

from services.pub_sub import PubSub


def test_a_subscriber_with_an_argument_gets_none():
    received = []

    class Core:
        async def on_input_bindings_changed(self, _):
            received.append(_)

    events = PubSub()
    events.subscribe("input_bindings_changed", Core().on_input_bindings_changed)

    asyncio.run(events.publish("input_bindings_changed", None))

    assert received == [None]


def test_a_subscriber_without_an_argument_still_gets_none_passed():
    calls = []
    events = PubSub()
    events.subscribe("changed", lambda: calls.append("called"))

    asyncio.run(events.publish("changed", "data"))

    assert calls == ["called"]
