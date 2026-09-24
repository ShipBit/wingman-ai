#!/usr/bin/env python3
"""Leave the venv with exactly one ONNX Runtime: the GPU build requirements.txt asks for.

    python scripts/ensure_onnxruntime_gpu.py

Run after `pip install -r requirements.txt` on Windows and Linux; the release
workflows do. On macOS it does nothing.

elevenlabslib depends on the CPU package `onnxruntime`. It and `onnxruntime-gpu`
install into the same `onnxruntime/` directory, so the one pip installs last
owns the files, and with different versions the directory ends up mixed. A CPU
`onnxruntime_pybind11_state` next to the GPU build's CUDA provider means Parakeet
runs on the CPU with nothing in the log saying so.

The script removes both and installs `onnxruntime-gpu` alone, with the version
range from requirements.txt. Then it checks that the CUDA provider is there and
that onnxruntime was built for the CUDA major the nvidia-cuda-runtime package
brings. A mismatch fails nowhere else: the provider is listed, cannot load its
libraries and Parakeet runs on the CPU.
"""

import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements.txt"


def gpu_requirement() -> str:
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if re.match(r"onnxruntime-gpu\b", line):
            return line.split(";")[0].strip()
    raise SystemExit("requirements.txt has no onnxruntime-gpu line.")


def pip(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "pip", *args], check=True)


def main() -> None:
    if sys.platform == "darwin":
        return

    requirement = gpu_requirement()
    pip("uninstall", "-y", "onnxruntime", "onnxruntime-gpu")
    pip("install", "--no-deps", requirement)

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
