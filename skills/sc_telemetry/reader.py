"""The Reader: one TelemetryStream call to the game, in its own thread, reconnecting until stopped.

No interpretation here: every frame goes to `on_frame(frame_dict, unix_time)` and every connection change to
`on_status(status)`. Statuses: `no_grpc` (this Wingman has no gRPC library), `waiting` (port closed: game not
running or telemetry off), `connected` (stream open, no frames yet: menus / loading), `live`, `stopped`.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

from skills.sc_telemetry.schema import STREAM_METHOD, message_classes, to_dict

try:
    import grpc
except ImportError:  # reported as status "no_grpc" instead of failing the skill
    grpc = None

DEFAULT_ADDRESS = "127.0.0.1:2942"
RETRY_FIRST_S = 2.0
RETRY_MAX_S = 15.0
CONNECT_TIMEOUT_S = 2.0


class _NotListening(Exception):
    """Nothing answers on the port (game not running, or telemetry off)."""


class TelemetryReader:
    def __init__(self, on_frame: Callable[[dict, float], None], on_status: Callable[[str], None],
                 address: str = DEFAULT_ADDRESS, on_error: Callable[[str], None] | None = None) -> None:
        if not address.startswith("127.0.0.1:"):
            raise ValueError("telemetry is read from loopback only")
        self._on_frame, self._on_status, self._address = on_frame, on_status, address
        self._on_error = on_error or (lambda message: None)
        self._stop = threading.Event()
        self._call = None
        self._thread: threading.Thread | None = None
        self._status = ""

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sc_telemetry_reader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        call = self._call
        if call is not None:
            call.cancel()  # unblocks the frame iterator
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _status_to(self, status: str) -> None:
        if status != self._status:
            self._status = status
            self._on_status(status)

    def _run(self) -> None:
        if grpc is None:
            self._status_to("no_grpc")
            return
        try:
            request_cls, response_cls = message_classes()
        except ImportError:  # no protobuf runtime
            self._status_to("no_grpc")
            return
        delay = RETRY_FIRST_S
        while not self._stop.is_set():
            try:
                with grpc.insecure_channel(self._address) as channel:
                    try:  # a call is lazy: only a ready channel proves the game is listening
                        grpc.channel_ready_future(channel).result(timeout=CONNECT_TIMEOUT_S)
                    except grpc.FutureTimeoutError:
                        self._status_to("waiting")
                        raise _NotListening from None
                    stream = channel.unary_stream(STREAM_METHOD, request_serializer=lambda r: r.SerializeToString(),
                                                  response_deserializer=response_cls.FromString)
                    self._call = stream(request_cls(), wait_for_ready=False)
                    self._status_to("connected")
                    for message in self._call:
                        self._status_to("live")
                        delay = RETRY_FIRST_S
                        try:
                            self._on_frame(to_dict(message), time.time())
                        except Exception as error:  # noqa: BLE001 - skip one bad frame, keep the stream
                            self._on_error(f"frame skipped: {type(error).__name__}: {error}")
                        if self._stop.is_set():
                            break
            except _NotListening:
                pass
            except grpc.RpcError as error:
                if self._stop.is_set():
                    break
                self._status_to("waiting" if error.code() == grpc.StatusCode.UNAVAILABLE else "connected")
            except Exception as error:  # noqa: BLE001 - the reader must outlive anything; it reconnects
                if self._stop.is_set():
                    break
                self._on_error(f"stream error, reconnecting: {type(error).__name__}: {error}")
            finally:
                self._call = None
            self._stop.wait(delay)
            delay = min(delay * 2, RETRY_MAX_S)
        self._status_to("stopped")
