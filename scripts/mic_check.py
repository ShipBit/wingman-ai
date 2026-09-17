#!/usr/bin/env python3
"""Where does the microphone signal go? Run this from the same place Core runs
(the VS Code terminal, or the packaged app's environment), speak for three
seconds, and read the numbers.

    python scripts/mic_check.py

For the default input device it records twice: once at the device's native
rate on every channel, once the way Core opens it (16 kHz, one channel, 512
sample blocks). A peak of exactly 0.0000 everywhere means no audio reaches this
process at all: a permission (macOS Privacy > Microphone) or a device that has
nothing connected. A peak on channel 2 only means the mic hangs on the second
input. A peak at native rate but 0.0000 at 16 kHz means the driver refuses the
resampled stream.
"""

import sys
import time
from os import path

import numpy as np
import sounddevice as sd

sys.path.insert(0, path.dirname(path.dirname(path.abspath(__file__))))


def main() -> None:
    print("Input devices:")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            mark = " (default)" if i == sd.default.device[0] else ""
            print(f"  [{i}] {d['name']}  channels={d['max_input_channels']}  rate={d['default_samplerate']:.0f}{mark}")

    device = sd.query_devices(kind="input")
    channels = int(device["max_input_channels"])
    rate = float(device["default_samplerate"])
    print(f"\nDefault: {device['name']}. Speak now, three seconds...")

    native = sd.rec(int(3 * rate), samplerate=rate, channels=channels, dtype="float32")
    sd.wait()
    peaks = [float(np.max(np.abs(native[:, c]))) for c in range(channels)]
    print("native rate, per channel peak:", [f"{p:.4f}" for p in peaks])

    print("Again, three seconds, the way Core opens it (16 kHz mono, 512-sample blocks)...")
    frames: list[np.ndarray] = []

    def callback(indata, _frames, _time, status):
        if status:
            print("  status:", status)
        frames.append(indata[:, 0].copy())

    with sd.InputStream(samplerate=16000, channels=1, dtype="float32", blocksize=512,
                        device=sd.default.device[0], callback=callback):
        time.sleep(3.0)
    mono = np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32)
    print(f"16 kHz mono: {len(frames)} blocks, peak {float(np.max(np.abs(mono))) if mono.size else 0.0:.4f}")

    if mono.size:
        rms = float(np.sqrt(np.mean(mono ** 2)))
        dc = float(np.mean(mono))
        crossings = int(np.sum(np.abs(np.diff(np.sign(mono - dc))) > 0))
        print(f"  rms {rms:.4f}, dc offset {dc:.4f}, zero crossings/s {crossings / 3:.0f} "
              f"(speech: a few hundred to a few thousand; a constant or a hum: far fewer)")
        clipped = int(np.sum(np.abs(mono) >= 0.999))
        print(f"  samples at full scale: {clipped} of {mono.size}")
        import soundfile
        out = path.join(path.dirname(path.abspath(__file__)), "mic_check.wav")
        soundfile.write(out, mono, 16000, subtype="PCM_16")
        print(f"  saved to {out}")

    root = path.dirname(path.dirname(path.abspath(__file__)))
    try:
        from services.audio.vad import SileroVad

        vad = SileroVad(root)
        scores = [vad(f) for f in frames if f.shape[0] == 512]
        print(f"Silero: best speech score {max(scores) if scores else 0.0:.2f} over {len(scores)} frames")
    except Exception as e:
        print("Silero could not run:", e)

    print("Once more, three seconds, through Core's own AudioInput class...")
    try:
        from services.audio.input import AudioInput

        peaks: list[float] = []
        audio_input = AudioInput(lambda f: peaks.append(float(np.max(np.abs(f)))))
        print("  start:", audio_input.start())
        time.sleep(3.0)
        audio_input.stop()
        print(f"  AudioInput at {audio_input.device_rate} Hz: {len(peaks)} frames, peak {max(peaks) if peaks else 0.0:.4f}")
    except Exception as e:
        print("AudioInput could not run:", e)


if __name__ == "__main__":
    main()
