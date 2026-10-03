"""Supervised audio transport with disposable drivers and stable preferences.

The sounddevice-shaped stream facade keeps DSP and provider integrations in
Core. All physical streams and fresh enumerations run in disposable children.
"""

import atexit
import base64
from concurrent.futures import Future, TimeoutError
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import weakref

from services.audio_worker import MAX_MESSAGE, resolve


class AudioUnavailable(RuntimeError):
    pass


class CallbackStop(Exception):
    pass


class Worker:
    """One bounded request at a time; even a blocked pipe has a deadline."""
    def __init__(self):
        command = ([sys.executable, "--audio-worker"] if getattr(sys, "frozen", False)
                   else [sys.executable, "-u", str(Path(__file__).with_name("audio_worker.py"))])
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.requests = queue.Queue(maxsize=1)
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self._transport, daemon=True, name="audio-transport")
        self.thread.start()

    def _transport(self):
        try:
            while not self.closed.is_set():
                try:
                    request, future = self.requests.get(timeout=0.2)
                except queue.Empty:
                    continue
                try:
                    data = json.dumps(request).encode("utf-8") + b"\n"
                    if len(data) > MAX_MESSAGE:
                        raise AudioUnavailable("Audio transport block too large")
                    self.process.stdin.write(data)
                    self.process.stdin.flush()
                    line = self.process.stdout.readline(MAX_MESSAGE + 1)
                    if not line or len(line) > MAX_MESSAGE:
                        raise AudioUnavailable("Audio worker exited")
                    reply = json.loads(line)
                    if not reply.get("ok"):
                        raise AudioUnavailable(reply.get("error", "Audio worker failed"))
                    future.set_result(reply["result"])
                except Exception as exc:
                    future.set_exception(AudioUnavailable(str(exc)))
        finally:
            for pipe in (self.process.stdin, self.process.stdout):
                try:
                    pipe.close()
                except OSError:
                    pass

    def call(self, op, timeout=3, **values):
        if self.closed.is_set():
            raise AudioUnavailable("Audio worker replaced")
        future = Future()
        try:
            self.requests.put(({"op": op, **values}, future), timeout=timeout)
            return future.result(timeout=timeout)
        except (queue.Full, TimeoutError) as exc:
            self.close()
            raise AudioUnavailable("Audio driver did not respond; recovering") from exc

    def close(self):
        if self.closed.is_set():
            return
        self.closed.set()
        if self.process.poll() is None:
            self.process.kill()
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass


def fresh_inventory():
    worker = Worker()
    try:
        return worker.call("inventory", timeout=5)
    finally:
        worker.close()


def identity(device):
    return {key: device[key] for key in ("name", "hostapi", "hostapi_name") if key in device}


class AudioSupervisor:
    def __init__(self, probe=fresh_inventory):
        self.probe = probe
        self.lock = threading.RLock()
        self.snapshot = {"devices": [], "defaults": [-1, -1]}
        self.preferences = {"input": None, "output": None}
        self.streams = weakref.WeakSet()
        self.wake = threading.Event()
        self.closed = threading.Event()
        self.thread = None
        self.revision = 0
        self.last_error = {}
        self.listeners = []
        self.notification_stop = None

    def report(self, direction, message):
        if self.last_error.get(direction) == message:
            return
        self.last_error[direction] = message
        if self.listeners:
            for listener in tuple(self.listeners):
                listener(direction, message)
        else:
            from api.enums import LogType
            from services.printr import Printr
            Printr().print(f"Audio {direction}: {message}", color=LogType.INFO, server_only=True)

    def start(self):
        if self.thread is not None:
            return
        self.thread = threading.Thread(target=self._monitor, daemon=True, name="audio-supervisor")
        self.thread.start()
        if os.name == "nt":
            from services.audio_windows import watch_devices
            self.notification_stop = watch_devices(self.wake.set)

    def configure(self, audio):
        if hasattr(audio, "model_dump"):
            audio = audio.model_dump()
        audio = audio or {}
        with self.lock:
            for direction in self.preferences:
                preference = audio.get(direction)
                if isinstance(preference, int):
                    device = next((d for d in self.snapshot["devices"] if d["index"] == preference), None)
                    # Do not turn an unavailable saved index into an unrelated device.
                    preference = identity(device) if device else None
                if isinstance(preference, dict):
                    matches = [d for d in self.snapshot["devices"] if
                               d["name"] == preference.get("name") and d["hostapi"] == preference.get("hostapi")]
                    if len(matches) == 1:
                        preference = identity(matches[0])
                if preference != self.preferences[direction]:
                    self.preferences[direction] = preference
                    self.revision += 1
                    self._invalidate(direction)
        self.wake.set()

    def _invalidate(self, direction):
        for stream in list(self.streams):
            if stream.direction == direction:
                stream.invalidate()

    def reconcile(self):
        snapshot = self.probe()
        with self.lock:
            for direction in self.preferences:
                before, _ = resolve(self.snapshot["devices"], self.snapshot["defaults"], self.preferences[direction], direction)
                after, fallback = resolve(snapshot["devices"], snapshot["defaults"], self.preferences[direction], direction)
                if before != after:
                    self._invalidate(direction)
                if not any(s.direction == direction and not s.closed for s in self.streams):
                    message = ("unavailable; waiting for a usable device" if after is None else
                               ("system fallback available: " if fallback else "available: ") + after["name"])
                    self.report(direction, message)
            self.snapshot = snapshot

    def _monitor(self):
        attempts = 0
        while not self.closed.is_set():
            try:
                self.reconcile()
                attempts = 0
                delay = 5
            except Exception as exc:
                self.report("devices", f"recovering ({exc})")
                delay = (1, 2, 5, 10)[min(attempts, 3)]
                attempts += 1
            if self.wake.wait(delay):
                self.wake.clear()
                self.closed.wait(1)  # coalesce reconnect storms

    def close(self):
        self.closed.set()
        self.wake.set()
        if self.notification_stop:
            self.notification_stop()
        for stream in list(self.streams):
            stream.close()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=6)


supervisor = AudioSupervisor()
atexit.register(supervisor.close)


def query_devices(device=None):
    with supervisor.lock:
        devices = [dict(d) for d in supervisor.snapshot["devices"]]
    # Keep the existing public /audio-devices response shape.
    for entry in devices:
        entry.pop("hostapi_name", None)
    if device is None:
        return devices
    for entry in devices:
        if entry["index"] == device:
            return entry
    raise AudioUnavailable("Selected audio device is no longer available")


def sleep(milliseconds):
    time.sleep(milliseconds / 1000)


class Stream:
    def __init__(self, direction, samplerate=16000, channels=1, dtype="float32",
                 callback=None, finished_callback=None, raw=False, **kwargs):
        self.direction, self.samplerate, self.channels = direction, samplerate, channels
        self.dtype, self.callback, self.finished_callback = dtype, callback, finished_callback
        self.raw = raw
        self.active = False
        self.failed = False
        self.closed = False
        self.worker = None
        self.thread = None
        self.finished = threading.Event()
        self._io_lock = threading.RLock()
        self.paused = threading.Event()
        self.paused.set()
        with supervisor.lock:
            if supervisor.closed.is_set():
                raise AudioUnavailable("Core audio is shutting down")
            if sum(not s.closed for s in supervisor.streams) >= 16:
                raise AudioUnavailable("Too many simultaneous audio streams")
            self.preference = supervisor.preferences[direction]
            supervisor.streams.add(self)
        try:
            self.worker = Worker()
            opened = self.worker.call("open", direction=direction, preference=self.preference,
                                      samplerate=samplerate, channels=channels)
            if isinstance(opened, dict):
                supervisor.report(direction, ("using system fallback: " if opened["fallback"] else "ready: ") + opened["device"]["name"])
        except Exception:
            self.invalidate()
            raise

    def start(self):
        self._check()
        try:
            with self._io_lock:
                self.worker.call("start")
        except Exception:
            self.invalidate()
            raise
        self.active = True
        self.paused.set()
        if self.callback and self.thread is None:
            self.thread = threading.Thread(target=self._pump, daemon=True, name="audio-stream")
            self.thread.start()
        return self

    def _check(self):
        if self.closed or self.failed:
            raise AudioUnavailable("Audio stream interrupted; request fresh audio")

    def _pump(self):
        import numpy as np
        try:
            while not self.closed:
                self.paused.wait(0.1)
                if not self.active:
                    continue
                if self.direction == "input":
                    data, _ = self.read(1024)
                    self.callback(data, 1024, None, False)
                else:
                    data = bytearray(1024 * self.channels * np.dtype(self.dtype).itemsize) if self.raw else np.zeros((1024, self.channels), dtype=self.dtype)
                    try:
                        self.callback(data, 1024, None, False)
                    except CallbackStop:
                        # A final partially filled block still has to reach the device.
                        self.write(data)
                        with self._io_lock:
                            self.worker.call("stop")  # drain the final device buffer
                        break
                    self.write(data)
        except Exception as exc:
            if not self.closed:
                self.failed = True
                supervisor.report(self.direction, f"recovering ({exc})")
                supervisor.wake.set()
        finally:
            self.active = False
            self.close()
            self._finish()

    def _finish(self):
        if not self.finished.is_set():
            self.finished.set()
            if self.finished_callback:
                self.finished_callback()

    def write(self, data):
        import numpy as np
        self._check()
        values = np.frombuffer(data, dtype=self.dtype) if self.raw else np.asarray(data)
        if np.issubdtype(values.dtype, np.floating):
            values = (np.clip(values, -1, 1) * 32767).astype("<i2")
        else:
            values = values.astype("<i2")
        # Bounded messages also keep cancellation latency short.
        raw = values.tobytes()
        block = max(self.channels * 2, int(self.samplerate / 20) * self.channels * 2)
        try:
            for start in range(0, len(raw), block):
                while True:
                    self._check()
                    if not self.paused.wait(0.1):
                        continue
                    with self._io_lock:
                        if not self.active:
                            continue
                        self._check()
                        self.worker.call("write", data=base64.b64encode(raw[start:start + block]).decode("ascii"))
                        break
        except Exception as exc:
            if not self.closed:
                supervisor.report(self.direction, f"recovering ({exc})")
                self.invalidate()
            raise
        return False

    def read(self, frames):
        import numpy as np
        self._check()
        try:
            data = base64.b64decode(self.worker.call("read", frames=frames))
        except Exception as exc:
            if not self.closed:
                supervisor.report(self.direction, f"recovering ({exc})")
                self.invalidate()
            raise
        if self.raw:
            return data, False
        return np.frombuffer(data, dtype="<i2").reshape(-1, self.channels).astype("float32") / 32768, False

    def stop(self):
        if self.closed:
            return
        self.active = False
        self.paused.clear()
        try:
            with self._io_lock:
                self.worker.call("stop")
        except AudioUnavailable:
            self.invalidate()

    def close(self):
        self.closed = True
        self.active = False
        self.paused.set()
        if self.worker:
            self.worker.close()

    def invalidate(self):
        self.failed = True
        self.close()
        supervisor.wake.set()

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.close()


def InputStream(**kwargs):
    return Stream("input", **kwargs)


def OutputStream(**kwargs):
    return Stream("output", **kwargs)


def RawOutputStream(**kwargs):
    return Stream("output", raw=True, **kwargs)


def RawInputStream(**kwargs):
    return Stream("input", raw=True, **kwargs)
