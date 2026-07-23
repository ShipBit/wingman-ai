import platform
import subprocess
import shutil
import sys
from typing import Optional
from fastapi import APIRouter
from api.enums import LogType
from api.interface import SystemCore, SystemInfo

LOCAL_VERSION = "3.1.6"


class SystemManager:
    def __init__(self):
        self.router = APIRouter()
        self.router.add_api_route(
            methods=["GET"],
            path="/system-info",
            endpoint=self.get_system_info,
            response_model=SystemInfo,
            tags=["system"],
        )

        self._cuda_available: bool | None = None  # Cached CUDA availability
        self._gpu_name: str | None = None  # Cached GPU name
        self._gpu_checked: bool = False  # Whether GPU detection has been attempted

    def _detect_gpu(self) -> None:
        """
        Detect NVIDIA GPU and cache both availability and GPU name.

        This checks for:
        1. nvidia-smi command availability (indicates NVIDIA driver is installed)
        2. Successfully running nvidia-smi (indicates a working NVIDIA GPU)
        """
        if self._gpu_checked:
            return

        self._gpu_checked = True
        self._cuda_available = False
        self._gpu_name = None

        # CUDA is not available on macOS
        if platform.system() == "Darwin":
            return

        try:
            # Check if nvidia-smi exists
            nvidia_smi = shutil.which("nvidia-smi")
            if nvidia_smi is None:
                return

            # Try to run nvidia-smi to verify GPU is accessible
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,  # Don't raise exception on non-zero return code
                creationflags=(
                    subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
                ),
            )

            # If nvidia-smi runs successfully and returns GPU info, CUDA is available
            if result.returncode == 0 and len(result.stdout.strip()) > 0:
                self._cuda_available = True
                # Get the first GPU name (in case of multi-GPU setup)
                self._gpu_name = result.stdout.strip().split("\n")[0].strip()

        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

        # Log GPU detection results (lazy import to avoid circular dependency)
        from services.printr import Printr

        printr = Printr()
        if self._gpu_name:
            printr.print(
                f"GPU detected: {self._gpu_name}",
                color=LogType.STARTUP,
                server_only=True,
            )
        else:
            printr.print(
                "No NVIDIA GPU detected - CUDA acceleration disabled",
                color=LogType.STARTUP,
                server_only=True,
            )

    def is_cuda_available(self) -> bool:
        """
        Check if NVIDIA CUDA is available on the system.
        """
        self._detect_gpu()
        return self._cuda_available

    def get_gpu_name(self) -> Optional[str]:
        """
        Get the name of the NVIDIA GPU if available.

        Returns:
            GPU name string (e.g., "NVIDIA GeForce RTX 4070") or None if not available.
        """
        self._detect_gpu()
        return self._gpu_name

    # GET /system-info
    def get_system_info(self):
        return SystemInfo(
            os=platform.system(),
            core=SystemCore(
                version=LOCAL_VERSION,
                cuda_available=self.is_cuda_available(),
                gpu_name=self.get_gpu_name(),
                is_dev=not getattr(sys, "frozen", False),
            ),
        )
