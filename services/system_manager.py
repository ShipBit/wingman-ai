import platform
import subprocess
import shutil
from typing import Optional
from fastapi import APIRouter
import requests
from packaging import version
from api.enums import LogType
from api.interface import SystemCore, SystemInfo

LOCAL_VERSION = "2.1.1"
VERSION_ENDPOINT = "https://wingman-ai.com/api/version"


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

        self.latest_version = version.parse("0.0.0")
        self.local_version = version.parse(LOCAL_VERSION)
        self._cuda_available: bool | None = None  # Cached CUDA availability
        self._gpu_name: str | None = None  # Cached GPU name
        self._gpu_checked: bool = False  # Whether GPU detection has been attempted
        self.check_version()

    def check_version(self):
        try:
            response = requests.get(VERSION_ENDPOINT, timeout=10)
            response.raise_for_status()

            remote_version_str = response.json().get("version", None)
            remote_version = version.parse(remote_version_str)

            self.latest_version = remote_version

            return self.local_version >= remote_version

        except requests.RequestException:
            return False
        except ValueError:
            return False

    def current_version_is_latest(self):
        return self.local_version >= self.latest_version

    def get_local_version(self, as_string=True) -> str | version.Version:
        return LOCAL_VERSION if as_string else self.local_version

    def get_latest_version(self, as_string=True) -> str | version.Version:
        return str(self.latest_version) if as_string else self.latest_version

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

        # Only check on Windows - CUDA is not supported on other platforms
        if platform.system() != "Windows":
            # No logging needed - CUDA is simply not available on non-Windows
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
        is_latest = self.check_version()

        return SystemInfo(
            os=platform.system(),
            core=SystemCore(
                version=str(LOCAL_VERSION),
                latest_version=str(self.latest_version),
                is_latest=is_latest,
                cuda_available=self.is_cuda_available(),
                gpu_name=self.get_gpu_name(),
            ),
        )
