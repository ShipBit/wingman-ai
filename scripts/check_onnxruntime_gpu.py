#!/usr/bin/env python3
"""Fails the build when Parakeet would silently run on the CPU.

    python scripts/check_onnxruntime_gpu.py

Run after `pip install -r requirements.txt` on Windows and Linux; the release
workflows do. On macOS it does nothing.

It checks that the installed onnxruntime has the CUDA provider and that it was
built for the CUDA major the nvidia-cuda-runtime package brings. A mismatch
fails nowhere else: the provider is listed, cannot load its libraries and
Parakeet runs on the CPU.
"""

import subprocess
import sys
from importlib import metadata


def main() -> None:
    if sys.platform == "darwin":
        return

    check = subprocess.run(
        [
            sys.executable,
            "-c",
            "import onnxruntime as o; from onnxruntime.capi import build_and_package_info as b; "
            "print(o.__version__); print(','.join(o.get_available_providers())); print(b.cuda_version)",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    version, providers, ort_cuda = check.stdout.strip().splitlines()
    runtime_cuda = metadata.version("nvidia-cuda-runtime")
    print(f"onnxruntime {version} (CUDA {ort_cuda}), nvidia-cuda-runtime {runtime_cuda}, providers: {providers}")
    if "CUDAExecutionProvider" not in providers.split(","):
        raise SystemExit("The installed onnxruntime has no CUDA provider.")
    if ort_cuda.split(".")[0] != runtime_cuda.split(".")[0]:
        raise SystemExit(
            f"onnxruntime-gpu {version} is built for CUDA {ort_cuda}, the bundled CUDA "
            f"runtime is {runtime_cuda}. Move the nvidia packages in requirements.txt."
        )


if __name__ == "__main__":
    main()
