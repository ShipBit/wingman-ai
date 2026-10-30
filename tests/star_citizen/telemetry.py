"""Helpers for the Star Citizen telemetry tests: recorded moments, a replay and a fake game.

The moments in sc_telemetry_fixtures/ were cut from live field tests (Star Citizen 4.10.2, 2026-10-26 to
2026-10-28): one line per frame, {"t": unix time, "frame": the frame as JSON}. They hold ship and weapon instance
ids, seat names and a UEC balance, no player names.
"""

import gzip
import json
import threading
from concurrent import futures
from os import path

import grpc
from google.protobuf.json_format import ParseDict

from services.sc_telemetry.handler import Handler
from services.sc_telemetry.schema import SERVICE, message_classes

FIXTURES = path.join(path.dirname(__file__), "sc_telemetry_fixtures")
FLOAT_MAX = 3.4028234663852886e38
"""The game sends 3.4028235e38 for "no planet altitude", a hair above what ParseDict takes for a float."""


def load_frames(name: str) -> list[tuple[float, dict]]:
    with gzip.open(path.join(FIXTURES, f"{name}.gz"), "rt", encoding="utf-8") as handle:
        return [(row["t"], row["frame"]) for row in map(json.loads, handle)]


def replay(frames: list):
    handler = Handler()
    events, states = [], []
    for t, frame in frames:
        events.extend(handler.update(frame, t))
        states.append((t, handler.state))
    return handler, events, states


def ids(events) -> list[str]:
    return [event.type for event in events]


def _clamped(value):
    if isinstance(value, dict):
        return {key: _clamped(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clamped(item) for item in value]
    if isinstance(value, float) and value > FLOAT_MAX:
        return FLOAT_MAX
    return value


def to_message(frame: dict):
    return ParseDict(_clamped(frame), message_classes()[1]())


class FakeGame:
    """A game on a free local port. It streams what `send` gets to every caller and keeps the stream open in
    between, like the game in its menus, until `close_stream` or `stop`. With `telemetry=False` it answers like a
    game without the service (a patch that renamed it)."""

    def __init__(self, telemetry: bool = True) -> None:
        self._frames: list[dict] = []
        self._new = threading.Condition()
        self._closed = False
        self.calls = 0
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
        if telemetry:
            request_cls, _ = message_classes()
            handler = grpc.method_handlers_generic_handler(SERVICE, {
                "TelemetryStream": grpc.unary_stream_rpc_method_handler(
                    self._stream, request_deserializer=request_cls.FromString,
                    response_serializer=lambda message: message.SerializeToString())})
            self.server.add_generic_rpc_handlers((handler,))
        self.port = self.server.add_insecure_port("127.0.0.1:0")
        self.address = f"127.0.0.1:{self.port}"
        self.server.start()

    def send(self, *frames: dict) -> None:
        with self._new:
            self._frames.extend(frames)
            self._new.notify_all()

    def close_stream(self) -> None:
        with self._new:
            self._closed = True
            self._new.notify_all()

    def stop(self) -> None:
        self.close_stream()
        self.server.stop(0)

    def _stream(self, request, context):
        self.calls += 1
        with self._new:
            sent = len(self._frames)  # a new caller gets what comes from now on
        while context.is_active():
            with self._new:
                while sent >= len(self._frames) and not self._closed and context.is_active():
                    self._new.wait(0.1)
                if self._closed or not context.is_active():
                    return
                frames = self._frames[sent:]
                sent = len(self._frames)
            for frame in frames:
                yield to_message(frame)
