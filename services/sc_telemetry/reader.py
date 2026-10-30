"""The connection to the game: one TelemetryStream call in its own thread, reconnecting until stopped.

No interpretation here. Every message goes to `on_message(message)` and every change of the connection to
`on_state(state, detail)`. States: `waiting` (nothing listens on the port: the game is not running or runs without
telemetry), `connected` (the stream is open, no frames yet: menus or loading), `live`, `incompatible` (the game
answers, but not in the shape the schema knows: a game patch changed it), `stopped`.

Read-only and loopback only: the request is empty and nothing else is ever sent to the game.
"""
from __future__ import annotations

import threading
from collections.abc import Callable

import grpc

from services.sc_telemetry.schema import STREAM_METHOD, message_classes

ADDRESS = "127.0.0.1:2942"
CONNECT_TIMEOUT_S = 2.0
RETRY_S = (1.0, 2.0, 3.0, 5.0)
"""Waits between attempts. Loopback connects are cheap, and the user asks about the ship right after spawning."""
JOIN_TIMEOUT_S = 5.0

WAITING = "waiting"
CONNECTED = "connected"
LIVE = "live"
INCOMPATIBLE = "incompatible"
STOPPED = "stopped"

# The game answered, but the call does not fit: a renamed service or method, or messages that do not decode.
INCOMPATIBLE_CODES = frozenset({
    grpc.StatusCode.UNIMPLEMENTED,
    grpc.StatusCode.INTERNAL,
    grpc.StatusCode.UNKNOWN,
    grpc.StatusCode.DATA_LOSS,
    grpc.StatusCode.INVALID_ARGUMENT,
    grpc.StatusCode.FAILED_PRECONDITION,
})


class TelemetryReader:
    def __init__(
        self,
        on_message: Callable[[object], None],
        on_state: Callable[[str, str | None], None],
        on_error: Callable[[Exception], None],
        address: str = ADDRESS,
    ) -> None:
        host, _, port = address.rpartition(":")
        if host != "127.0.0.1" or not port.isdigit():
            raise ValueError("telemetry is read from loopback only")
        self._on_message, self._on_state, self._on_error = on_message, on_state, on_error
        self._address = address
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._channel: grpc.Channel | None = None
        self._thread: threading.Thread | None = None
        self._state = ""

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sc-telemetry", daemon=True)
        self._thread.start()

    def stop(self) -> bool:
        """Stop and wait for the thread. True when it ended in time."""
        self._stop.set()
        with self._lock:
            channel = self._channel
        if channel is not None:
            # Ends the open call at once, also while the game sends nothing (menus): the frame loop would
            # otherwise wait for the next frame. Channel.close() may be called from any thread.
            channel.close()
        if self._thread is None:
            return True
        self._thread.join(JOIN_TIMEOUT_S)
        return not self._thread.is_alive()

    def _to(self, state: str, detail: str | None = None) -> None:
        if state != self._state or state == INCOMPATIBLE:
            self._state = state
            self._on_state(state, detail)

    def _run(self) -> None:
        request_cls, response_cls = message_classes()
        attempt = 0
        while not self._stop.is_set():
            channel = grpc.insecure_channel(self._address)
            with self._lock:
                self._channel = channel
            try:
                if self._stop.is_set():
                    break
                if self._connect(channel):
                    attempt = 0
                    self._stream(channel, request_cls, response_cls)
            except grpc.RpcError as error:
                if self._stop.is_set():
                    break
                code = error.code()
                if code in INCOMPATIBLE_CODES:
                    self._to(INCOMPATIBLE, f"{code.name}: {error.details()}")
                else:
                    self._to(WAITING)
            except Exception as error:  # noqa: BLE001 - the reader outlives anything and reconnects
                if self._stop.is_set():
                    break
                self._to(INCOMPATIBLE, f"{type(error).__name__}: {error}")
            finally:
                with self._lock:
                    self._channel = None
                channel.close()
            self._stop.wait(RETRY_S[min(attempt, len(RETRY_S) - 1)])
            attempt += 1
        self._to(STOPPED)

    def _connect(self, channel: grpc.Channel) -> bool:
        """A call is lazy: only a ready channel proves the game listens."""
        try:
            grpc.channel_ready_future(channel).result(timeout=CONNECT_TIMEOUT_S)
        except grpc.FutureTimeoutError:
            if not self._stop.is_set():
                self._to(WAITING)
            return False
        return not self._stop.is_set()

    def _stream(self, channel: grpc.Channel, request_cls: type, response_cls: type) -> None:
        stream = channel.unary_stream(
            STREAM_METHOD,
            request_serializer=lambda request: request.SerializeToString(),
            response_deserializer=response_cls.FromString,
        )
        call = stream(request_cls(), wait_for_ready=False)
        if self._stop.is_set():  # stop() may have run before the channel had the call
            call.cancel()
            return
        self._to(CONNECTED)
        for message in call:
            if self._stop.is_set():
                return
            self._to(LIVE)
            try:
                self._on_message(message)
            except Exception as error:  # noqa: BLE001 - one bad frame, not a lost stream
                self._on_error(error)
        if not self._stop.is_set():
            self._to(WAITING)  # the game closed the stream: it quit or went back to the menu
