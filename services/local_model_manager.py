import asyncio
import os
import platform
import stat
import tarfile
import zipfile
from os import path
from typing import Optional

import requests

from api.enums import LogType
from api.interface import LlamaCppSettings
from services.file import get_local_models_dir
from services.printr import Printr

printr = Printr()

# Available summarize models — keyed by GGUF filename
SUMMARIZE_MODELS: dict[str, dict] = {
    "Qwen3.5-2B-Q4_K_M.gguf": {
        "repo": "unsloth/Qwen3.5-2B-GGUF",
        "filename": "Qwen3.5-2B-Q4_K_M.gguf",
        "expected_size_mb": 1280,
        "label": "Qwen 3.5 2B (recommended)",
    },
    "Qwen3.5-0.8B-Q4_K_M.gguf": {
        "repo": "unsloth/Qwen3.5-0.8B-GGUF",
        "filename": "Qwen3.5-0.8B-Q4_K_M.gguf",
        "expected_size_mb": 500,
        "label": "Qwen 3.5 0.8B (lightweight)",
    },
}

DEFAULT_SUMMARIZE_MODEL = SUMMARIZE_MODELS["Qwen3.5-2B-Q4_K_M.gguf"]

DEFAULT_EMBED_MODEL = {
    "repo": "nomic-ai/nomic-embed-text-v1.5-GGUF",
    "filename": "nomic-embed-text-v1.5.f16.gguf",
    "expected_size_mb": 250,
}

# llama-server binary release — update this to get newer llama.cpp features
LLAMA_SERVER_VERSION = "b8400"

# Platform + backend → release asset name
# On Windows, multiple backends are available; macOS/Linux use one universal build.
LLAMA_SERVER_ASSETS: dict[str, dict[str, str]] = {
    "Darwin_arm64": {
        "default": f"llama-{LLAMA_SERVER_VERSION}-bin-macos-arm64.tar.gz",
    },
    "Darwin_x86_64": {
        "default": f"llama-{LLAMA_SERVER_VERSION}-bin-macos-x64.tar.gz",
    },
    "Windows_AMD64": {
        "vulkan": f"llama-{LLAMA_SERVER_VERSION}-bin-win-vulkan-x64.zip",
        "cuda": f"llama-{LLAMA_SERVER_VERSION}-bin-win-cuda-12.4-x64.zip",
        "cpu": f"llama-{LLAMA_SERVER_VERSION}-bin-win-cpu-x64.zip",
    },
    "Linux_x86_64": {
        "default": f"llama-{LLAMA_SERVER_VERSION}-bin-ubuntu-x64.tar.gz",
    },
}

# CUDA runtime DLLs asset (needed alongside the CUDA llama-server binary on Windows)
LLAMA_SERVER_CUDA_RUNTIME = f"cudart-llama-bin-win-cuda-12.4-x64.zip"


class LocalModelManager:
    """Manages downloading and verifying local GGUF models for summarization and embedding."""

    def __init__(self, settings: LlamaCppSettings):
        self.settings = settings
        self.models_dir = get_local_models_dir()
        self._downloading = False

    def update_settings(self, new_settings: LlamaCppSettings):
        self.settings = new_settings

    def get_summarize_model_path(self) -> str:
        """Return the full path to the summarize model GGUF file."""
        filename = self.settings.summarize_model
        if path.isabs(filename):
            return filename
        return path.join(self.models_dir, filename)

    def get_embed_model_path(self) -> str:
        """Return the full path to the embed model GGUF file."""
        filename = self.settings.embed_model
        if path.isabs(filename):
            return filename
        return path.join(self.models_dir, filename)

    def models_available(self) -> bool:
        return self.summarize_model_available() and self.embed_model_available()

    def summarize_model_available(self) -> bool:
        return path.exists(self.get_summarize_model_path())

    def embed_model_available(self) -> bool:
        return path.exists(self.get_embed_model_path())

    @property
    def is_downloading(self) -> bool:
        return self._downloading

    def _download_model(self, model_def: dict) -> bool:
        """Download a single GGUF model from HuggingFace. Returns True on success."""
        repo = model_def["repo"]
        filename = model_def["filename"]
        target_path = path.join(self.models_dir, filename)

        if path.exists(target_path):
            printr.print(
                f"Model already exists: {filename}",
                color=LogType.INFO,
                server_only=True,
            )
            return True

        url = f"https://huggingface.co/{repo}/resolve/main/{filename}"
        temp_path = target_path + ".part"

        printr.print(
            f"Downloading {filename} from {repo}...",
            color=LogType.INFO,
            server_only=True,
        )

        try:
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0
            last_logged_pct = -10

            with open(temp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = int(downloaded / total_size * 100)
                        if pct - last_logged_pct >= 10:
                            printr.print(
                                f"  {filename}: {pct}% ({downloaded // (1024*1024)} MB / {total_size // (1024*1024)} MB)",
                                color=LogType.INFO,
                                server_only=True,
                            )
                            last_logged_pct = pct

            # Rename temp to final
            if path.exists(target_path):
                os.remove(target_path)
            os.rename(temp_path, target_path)

            printr.print(
                f"Download complete: {filename}",
                color=LogType.INFO,
                server_only=True,
            )
            return True

        except Exception as e:
            printr.print(
                f"Failed to download {filename}: {e}",
                color=LogType.ERROR,
                server_only=True,
            )
            # Clean up partial download
            if path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            return False

    async def download_models(self, cuda_available: bool = False) -> bool:
        """Download models and llama-server binaries asynchronously.

        Downloads the active backend binary plus CUDA if cuda_available is True.
        Returns True if all succeed.
        """
        if self._downloading:
            printr.print(
                "Model download already in progress.",
                color=LogType.WARNING,
                server_only=True,
            )
            return False

        self._downloading = True
        try:
            loop = asyncio.get_event_loop()
            # Download the summarize model matching the current settings selection
            active_model = SUMMARIZE_MODELS.get(
                self.settings.summarize_model, DEFAULT_SUMMARIZE_MODEL
            )
            summarize_ok = await loop.run_in_executor(
                None, self._download_model, active_model
            )
            embed_ok = await loop.run_in_executor(
                None, self._download_model, DEFAULT_EMBED_MODEL
            )

            # Determine which backends to download
            backends_to_download: set[str] = set()
            available = self.get_available_backends()
            if "default" in available:
                # macOS / Linux — single universal build
                backends_to_download.add("default")
            else:
                # Windows — always download vulkan + cpu; add cuda if available
                backends_to_download.add("vulkan")
                backends_to_download.add("cpu")
                if cuda_available:
                    backends_to_download.add("cuda")

            server_ok = True
            for bk in backends_to_download:
                ok = await loop.run_in_executor(None, self._download_llama_server, bk)
                if not ok:
                    server_ok = False

            return summarize_ok and embed_ok and server_ok
        finally:
            self._downloading = False

    def get_status(self) -> dict:
        """Return current model status for the API."""
        return {
            "models_available": self.models_available(),
            "summarize_available": self.summarize_model_available(),
            "embed_available": self.embed_model_available(),
            "llama_server_available": self.llama_server_available(),
            "gpu_backend": self._get_active_backend(),
            "available_backends": self.get_available_backends(),
            "is_downloading": self._downloading,
            "models_dir": self.models_dir,
        }

    def get_summarize_models(self) -> list[dict]:
        """Return the list of available summarize models for the UI dropdown."""
        result = []
        for filename, model_def in SUMMARIZE_MODELS.items():
            result.append(
                {
                    "filename": filename,
                    "label": model_def["label"],
                    "size_mb": model_def["expected_size_mb"],
                    "downloaded": path.exists(path.join(self.models_dir, filename)),
                }
            )
        return result

    # ── llama-server binary management ──────────────────────────────────

    def _get_active_backend(self) -> str:
        """Return the effective backend name for the current platform."""
        system = platform.system()
        if system != "Windows":
            return "default"
        return self.settings.gpu_backend or "vulkan"

    def get_llama_server_dir(self, backend: Optional[str] = None) -> str:
        """Return the directory containing the extracted llama-server binary for a backend."""
        bk = backend or self._get_active_backend()
        return path.join(self.models_dir, f"llama-server-{LLAMA_SERVER_VERSION}-{bk}")

    def get_llama_server_path(self, backend: Optional[str] = None) -> str:
        """Return the full path to the llama-server binary, searching recursively."""
        server_dir = self.get_llama_server_dir(backend)
        binary_name = (
            "llama-server.exe" if platform.system() == "Windows" else "llama-server"
        )
        # Search recursively (archive may have nested dirs like llama-b8400/)
        for root, _dirs, files in os.walk(server_dir):
            if binary_name in files:
                return path.join(root, binary_name)
        # Fallback — will fail the exists() check, triggering download
        return path.join(server_dir, binary_name)

    def llama_server_available(self, backend: Optional[str] = None) -> bool:
        """Check if the llama-server binary exists for the given (or active) backend."""
        return path.exists(self.get_llama_server_path(backend))

    def _get_platform_asset_name(self, backend: Optional[str] = None) -> Optional[str]:
        """Get the platform-specific release asset filename."""
        system = platform.system()
        machine = platform.machine()
        platform_key = f"{system}_{machine}"
        backends = LLAMA_SERVER_ASSETS.get(platform_key)
        if not backends:
            return None
        bk = backend or self._get_active_backend()
        return backends.get(bk)

    def get_available_backends(self) -> list[str]:
        """Return the list of backends available for the current platform.

        On macOS/Linux there's only 'default'. On Windows: vulkan, cuda, cpu.
        """
        system = platform.system()
        machine = platform.machine()
        platform_key = f"{system}_{machine}"
        backends = LLAMA_SERVER_ASSETS.get(platform_key, {})
        return list(backends.keys())

    @staticmethod
    def _safe_extract_tar(tar_path: str, target_dir: str):
        """Extract a tar.gz archive with path traversal protection."""
        abs_target = path.abspath(target_dir) + os.sep
        with tarfile.open(tar_path, "r:gz") as tar:
            for member in tar.getmembers():
                abs_member = path.abspath(path.join(target_dir, member.name))
                if not abs_member.startswith(
                    abs_target
                ) and abs_member != abs_target.rstrip(os.sep):
                    raise ValueError(
                        f"Path traversal detected in archive: {member.name}"
                    )
            tar.extractall(target_dir)

    @staticmethod
    def _safe_extract_zip(zip_path: str, target_dir: str):
        """Extract a zip archive with path traversal protection."""
        abs_target = path.abspath(target_dir) + os.sep
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                abs_member = path.abspath(path.join(target_dir, info.filename))
                if not abs_member.startswith(
                    abs_target
                ) and abs_member != abs_target.rstrip(os.sep):
                    raise ValueError(
                        f"Path traversal detected in archive: {info.filename}"
                    )
            zf.extractall(target_dir)

    def _download_llama_server(self, backend: Optional[str] = None) -> bool:
        """Download and extract the llama-server binary for a specific backend."""
        bk = backend or self._get_active_backend()
        if self.llama_server_available(bk):
            return True

        asset_name = self._get_platform_asset_name(bk)
        if not asset_name:
            printr.print(
                f"No llama-server binary available for {platform.system()} {platform.machine()} ({bk})",
                color=LogType.ERROR,
                server_only=True,
            )
            return False

        url = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_SERVER_VERSION}/{asset_name}"
        server_dir = self.get_llama_server_dir(bk)
        temp_path = path.join(self.models_dir, asset_name + ".part")

        printr.print(
            f"Downloading llama-server {LLAMA_SERVER_VERSION} ({bk}) for {platform.system()} {platform.machine()}...",
            color=LogType.INFO,
            server_only=True,
        )

        try:
            self._download_and_extract(
                url, temp_path, server_dir, f"llama-server ({bk})"
            )

            # CUDA backend on Windows also needs the CUDA runtime DLLs
            if bk == "cuda" and platform.system() == "Windows":
                cudart_url = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_SERVER_VERSION}/{LLAMA_SERVER_CUDA_RUNTIME}"
                cudart_temp = path.join(
                    self.models_dir, LLAMA_SERVER_CUDA_RUNTIME + ".part"
                )
                printr.print(
                    "Downloading CUDA runtime libraries...",
                    color=LogType.INFO,
                    server_only=True,
                )
                self._download_and_extract(
                    cudart_url, cudart_temp, server_dir, "CUDA runtime"
                )

            # Make binary executable on Unix
            binary_path = self.get_llama_server_path(bk)
            if platform.system() != "Windows" and path.exists(binary_path):
                os.chmod(
                    binary_path,
                    os.stat(binary_path).st_mode
                    | stat.S_IEXEC
                    | stat.S_IXGRP
                    | stat.S_IXOTH,
                )

            printr.print(
                f"llama-server {LLAMA_SERVER_VERSION} ({bk}) ready.",
                color=LogType.INFO,
                server_only=True,
            )
            return True

        except Exception as e:
            printr.print(
                f"Failed to download llama-server ({bk}): {e}",
                color=LogType.ERROR,
                server_only=True,
            )
            if path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            return False

    def _download_and_extract(
        self, url: str, temp_path: str, target_dir: str, label: str
    ):
        """Download a file and extract it into target_dir."""
        response = requests.get(url, stream=True, timeout=30, allow_redirects=True)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0
        last_logged_pct = -10

        with open(temp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    pct = int(downloaded / total_size * 100)
                    if pct - last_logged_pct >= 10:
                        printr.print(
                            f"  {label}: {pct}% ({downloaded // (1024*1024)} MB / {total_size // (1024*1024)} MB)",
                            color=LogType.INFO,
                            server_only=True,
                        )
                        last_logged_pct = pct

        # Extract archive
        os.makedirs(target_dir, exist_ok=True)
        archive_name = temp_path.removesuffix(".part")
        if archive_name.endswith(".tar.gz"):
            self._safe_extract_tar(temp_path, target_dir)
        elif archive_name.endswith(".zip"):
            self._safe_extract_zip(temp_path, target_dir)

        # Clean up archive
        os.remove(temp_path)

    def download_llama_server_sync(self, backend: Optional[str] = None) -> bool:
        """Synchronous wrapper for downloading a llama-server binary."""
        return self._download_llama_server(backend)
