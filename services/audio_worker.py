"""Private stdio audio worker. Only this process loads the hardware driver.

Stdout is a bounded JSON transport, never a logging stream. There is no network
listener and no deserialization of executable objects. EOF terminates the worker.
"""

import base64
import json
import os
import sys
import threading


def watch_parent():
    """A client terminating Core must not leave microphone workers behind."""
    parent = os.getppid()
    def watch():
        if os.name == "nt":
            import ctypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel32.OpenProcess(0x00100000, False, parent)
            if handle:
                try:
                    if kernel32.WaitForSingleObject(handle, 0xFFFFFFFF) == 0:
                        os._exit(0)
                finally:
                    kernel32.CloseHandle(handle)
        else:
            import time
            while os.getppid() == parent:
                time.sleep(1)
            os._exit(0)
    threading.Thread(target=watch, name="audio-parent-watch", daemon=True).start()

MAX_MESSAGE = 1024 * 1024


def inventory(sd):
    devices = [dict(device) for device in sd.query_devices()]
    hosts = sd.query_hostapis()
    for device in devices:
        device["hostapi_name"] = hosts[device["hostapi"]]["name"]
    return {"devices": devices, "defaults": list(sd.default.device)}


def resolve(devices, defaults, preference, direction):
    """Preference is an identity, never an index from another enumeration."""
    key = "max_input_channels" if direction == "input" else "max_output_channels"
    candidates = [d for d in devices if d[key] > 0]
    if preference:
        matching = [d for d in candidates if d["name"] == preference.get("name")]
        exact = [d for d in matching if (
            d.get("hostapi_name") == preference.get("hostapi_name")
            if preference.get("hostapi_name") else d["hostapi"] == preference.get("hostapi"))]
        if len(exact) == 1:
            return exact[0], False
        if len(matching) == 1:
            return matching[0], False
    index = defaults[0 if direction == "input" else 1]
    return next((d for d in candidates if d["index"] == index), None), bool(preference)


def open_stream(sd, request):
    direction = request["direction"]
    snapshot = inventory(sd)
    selected, fallback = resolve(snapshot["devices"], snapshot["defaults"], request.get("preference"), direction)
    default, _ = resolve(snapshot["devices"], snapshot["defaults"], None, direction)
    candidates = [(selected, fallback)] if selected else []
    if default and default != selected:
        candidates.append((default, True))
    rate, channels = int(request["samplerate"]), int(request["channels"])
    if not 8000 <= rate <= 192000 or not 1 <= channels <= 8:
        raise ValueError("Unsupported stream format")
    key = "max_input_channels" if direction == "input" else "max_output_channels"
    check = sd.check_input_settings if direction == "input" else sd.check_output_settings
    factory = sd.RawInputStream if direction == "input" else sd.RawOutputStream
    last_error = RuntimeError("No usable system default " + direction + " device")
    for device, fallback in candidates:
        stream = None
        native_channels = min(channels, device[key])
        native_rate = rate
        try:
            try:
                check(device=device["index"], channels=native_channels, dtype="int16", samplerate=rate)
            except sd.PortAudioError:
                native_rate = int(device["default_samplerate"])
                check(device=device["index"], channels=native_channels, dtype="int16", samplerate=native_rate)
            stream = factory(device=device["index"], samplerate=native_rate, channels=native_channels, dtype="int16")
            # Some Windows backends accept construction but fail at start
            # (including the original MME -9999 failure). Probe both stages.
            stream.start()
            stream.stop()
            return stream, native_rate, native_channels, device, fallback
        except Exception as exc:
            last_error = exc
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
    raise last_error


def serve():
    watch_parent()
    # Keep heavyweight Core/provider imports out of this process.
    import audioop
    import numpy as np
    import sounddevice as sd

    stream = None
    state = None
    pending = b""
    rate = native_rate = channels = native_channels = 0
    direction = ""
    while True:
        line = sys.stdin.buffer.readline(MAX_MESSAGE + 1)
        if not line or len(line) > MAX_MESSAGE:
            break
        try:
            request = json.loads(line)
            operation = request["op"]
            result = None
            if operation == "inventory":
                result = inventory(sd)
            elif operation == "open":
                direction = request["direction"]
                rate = int(request["samplerate"])
                channels = int(request["channels"])
                stream, native_rate, native_channels, device, fallback = open_stream(sd, request)
                result = {"device": device, "fallback": fallback}
            elif operation == "start":
                stream.start()
            elif operation == "stop":
                stream.stop()
                state, pending = None, b""
            elif operation == "write":
                data = base64.b64decode(request["data"], validate=True)
                samples = np.frombuffer(data, dtype="<i2").reshape(-1, channels)
                if native_channels != channels:
                    samples = samples.mean(axis=1, keepdims=True).astype("<i2")
                    samples = np.repeat(samples, native_channels, axis=1)
                data = samples.tobytes()
                if rate != native_rate:
                    data, state = audioop.ratecv(data, 2, native_channels, rate, native_rate, state)
                underflow = stream.write(data)
                result = bool(underflow)
            elif operation == "read":
                frames = int(request["frames"])
                if not 1 <= frames <= 16384:
                    raise ValueError("Invalid capture block")
                needed = frames * channels * 2
                while len(pending) < needed:
                    native_frames = max(1, int(frames * native_rate / rate))
                    data, overflow = stream.read(native_frames)
                    if overflow:
                        raise RuntimeError("Capture overflow; interrupted recording discarded")
                    data = bytes(data)
                    if native_channels != channels:
                        values = np.frombuffer(data, dtype="<i2").reshape(-1, native_channels)
                        data = np.repeat(values.mean(axis=1, keepdims=True), channels, axis=1).astype("<i2").tobytes()
                    if native_rate != rate:
                        data, state = audioop.ratecv(data, 2, channels, native_rate, rate, state)
                    pending += data
                result = base64.b64encode(pending[:needed]).decode("ascii")
                pending = pending[needed:]
            elif operation == "close":
                if stream is not None:
                    stream.close()
                break
            else:
                raise ValueError("Unknown audio operation")
            reply = {"ok": True, "result": result}
        except Exception as exc:
            reply = {"ok": False, "error": str(exc)[:500]}
        sys.stdout.buffer.write(json.dumps(reply).encode("utf-8") + b"\n")
        sys.stdout.buffer.flush()
    if stream is not None:
        stream.close()


if __name__ == "__main__":
    serve()
