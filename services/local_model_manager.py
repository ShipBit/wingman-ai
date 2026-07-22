import asyncio
import os
import platform
import shutil
import stat
import tarfile
import threading
import time
import zipfile
from os import path
from typing import Optional

import requests

from api.enums import LogType
from api.interface import LlamaCppSettings
from services.printr import Printr

printr = Printr()

# Retry policy for all downloads in this module — transient network failures
# (blips, resets, mid-download aborts) must not leave the user without local AI.
MAX_DOWNLOAD_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 2


def _is_retryable_download_error(error: Exception) -> bool:
    """Whether a download error is transient. 4xx (except 429) never heals on retry."""
    status = getattr(getattr(error, "response", None), "status_code", None)
    if status is not None and 400 <= status < 500 and status != 429:
        return False
    return True

# Available support models — keyed by GGUF filename
SUPPORT_MODELS: dict[str, dict] = {
    "Qwen3.5-4B-Q4_K_M.gguf": {
        "repo": "unsloth/Qwen3.5-4B-GGUF",
        "filename": "Qwen3.5-4B-Q4_K_M.gguf",
        "expected_size_mb": 2740,
        "label": "Qwen 3.5 4B",
    },
    "gemma-4-E2B-it-Q3_K_M.gguf": {
        "repo": "unsloth/gemma-4-E2B-it-GGUF",
        "filename": "gemma-4-E2B-it-Q3_K_M.gguf",
        "expected_size_mb": 2540,
        "label": "Gemma 4 E2B",
    },
    "Qwen3.5-2B-Q4_K_M.gguf": {
        "repo": "unsloth/Qwen3.5-2B-GGUF",
        "filename": "Qwen3.5-2B-Q4_K_M.gguf",
        "expected_size_mb": 1280,
        "label": "Qwen 3.5 2B (recommended)",
    },
}

DEFAULT_SUPPORT_MODEL = SUPPORT_MODELS["Qwen3.5-2B-Q4_K_M.gguf"]

EMBED_MODELS: dict[str, dict] = {
    "nomic-embed-text-v1.5.f16.gguf": {
        "repo": "nomic-ai/nomic-embed-text-v1.5-GGUF",
        "filename": "nomic-embed-text-v1.5.f16.gguf",
        "expected_size_mb": 250,
        "label": "Nomic Embed Text v1.5 (recommended)",
    },
}

DEFAULT_EMBED_MODEL = EMBED_MODELS["nomic-embed-text-v1.5.f16.gguf"]

# llama-server binary release — update this to get newer llama.cpp features.
# NOTE on disabling Qwen3.5 thinking: older builds (b8400) honored the
# `--reasoning-budget 0` launch flag, but newer builds (verified b9488) ignore
# it for this model and require `chat_template_kwargs={"enable_thinking": false}`
# in the request body instead (see llama_cpp_provider.support / llama_cpp_remote).
# Both mechanisms are now sent, so this is safe to keep current.
LLAMA_SERVER_VERSION = "b9488"

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
        self.models_dir = self._get_models_dir()
        self._downloading = False
        self._download_progress: dict = {}  # {file, pct, downloaded_mb, total_mb}
        # Serializes llama-server binary installs: download_models (executor)
        # and _ensure_binary from load_support_model (another thread) can race
        # for the same backend and must not extract into the same dir at once.
        self._server_download_lock = threading.Lock()

    @staticmethod
    def _get_models_dir() -> str:
        from services.file import get_models_dir
        models_root = get_models_dir()
        local_ai_dir = os.path.join(models_root, "local-ai")
        if not os.path.exists(local_ai_dir):
            os.makedirs(local_ai_dir)
        return local_ai_dir

    def update_settings(self, new_settings: LlamaCppSettings):
        self.settings = new_settings

    def get_support_model_path(self) -> str:
        """Return the full path to the support model GGUF file."""
        filename = self.settings.support_model
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
        return self.support_model_available() and self.embed_model_available()

    def support_model_available(self) -> bool:
        return path.exists(self.get_support_model_path())

    def embed_model_available(self) -> bool:
        return path.exists(self.get_embed_model_path())

    @property
    def is_downloading(self) -> bool:
        return self._downloading

    def _download_model(self, model_def: dict, on_progress: callable = None) -> bool:
        """Download a single GGUF model from HuggingFace. Returns True on success."""
        repo = model_def["repo"]
        filename = model_def["filename"]
        target_path = path.join(self.models_dir, filename)
        expected_size_mb = model_def.get("expected_size_mb")

        if path.exists(target_path):
            # Guard against a truncated file left behind by an earlier failed
            # run: it would block re-downloading forever and only surface later
            # as a cryptic llama-server startup failure.
            actual_mb = os.path.getsize(target_path) // (1024 * 1024)
            if expected_size_mb and actual_mb < expected_size_mb * 0.9:
                printr.print(
                    f"Existing model file looks incomplete ({actual_mb} MB, expected ~{expected_size_mb} MB) — re-downloading {filename}...",
                    color=LogType.WARNING,
                    server_only=True,
                )
                try:
                    os.remove(target_path)
                except OSError as e:
                    printr.print(
                        f"Could not remove incomplete model file {target_path}: {e}",
                        color=LogType.ERROR,
                        server_only=True,
                    )
                    return False
            else:
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

        delay = RETRY_BASE_DELAY_SECONDS
        last_error: Optional[Exception] = None
        for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
            try:
                response = requests.get(url, stream=True, timeout=30)
                response.raise_for_status()

                total_size = int(response.headers.get("content-length", 0))
                downloaded = 0
                last_logged_pct = -10
                last_callback_pct = -2
                total_mb = total_size // (1024 * 1024) if total_size > 0 else 0
                self._download_progress = {
                    "file": filename,
                    "pct": 0,
                    "downloaded_mb": 0,
                    "total_mb": total_mb,
                }

                with open(temp_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            pct = int(downloaded / total_size * 100)
                            downloaded_mb = downloaded // (1024 * 1024)
                            self._download_progress = {
                                "file": filename,
                                "pct": pct,
                                "downloaded_mb": downloaded_mb,
                                "total_mb": total_mb,
                            }
                            if pct - last_logged_pct >= 10:
                                printr.print(
                                    f"  {filename}: {pct}% ({downloaded_mb} MB / {total_mb} MB)",
                                    color=LogType.INFO,
                                    server_only=True,
                                )
                                last_logged_pct = pct
                            if on_progress and pct - last_callback_pct >= 2:
                                on_progress(filename, pct, downloaded_mb, total_mb)
                                last_callback_pct = pct

                # Never promote a truncated body to the final filename.
                if downloaded == 0 or (total_size > 0 and downloaded != total_size):
                    raise IOError(
                        f"Incomplete download: got {downloaded} of {total_size} bytes"
                    )

                # Atomic rename: readers either see the old state or the
                # complete new file, never a partial one.
                os.replace(temp_path, target_path)

                self._download_progress = {}
                printr.print(
                    f"Download complete: {filename}",
                    color=LogType.INFO,
                    server_only=True,
                )
                return True

            except Exception as e:
                last_error = e
                # Clean up partial download
                if path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
                if not _is_retryable_download_error(e) or attempt >= MAX_DOWNLOAD_ATTEMPTS:
                    break
                printr.print(
                    f"Download of {filename} failed (attempt {attempt}/{MAX_DOWNLOAD_ATTEMPTS}): {e} — retrying in {delay}s...",
                    color=LogType.WARNING,
                    server_only=True,
                )
                time.sleep(delay)
                delay *= 2

        self._download_progress = {}
        printr.print(
            f"Failed to download {filename}: {last_error}",
            color=LogType.ERROR,
            server_only=True,
        )
        return False

    async def download_models(
        self, cuda_available: bool = False, on_progress: callable = None
    ) -> bool:
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
            # Download the support model matching the current settings selection
            active_model = SUPPORT_MODELS.get(
                self.settings.support_model, DEFAULT_SUPPORT_MODEL
            )
            support_ok = await loop.run_in_executor(
                None, self._download_model, active_model, on_progress
            )
            active_embed = EMBED_MODELS.get(
                self.settings.embed_model, DEFAULT_EMBED_MODEL
            )
            embed_ok = await loop.run_in_executor(
                None, self._download_model, active_embed, on_progress
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

            return support_ok and embed_ok and server_ok
        finally:
            self._downloading = False
            self._download_progress = {}

    def get_status(self) -> dict:
        """Return current model status for the API."""
        status = {
            "models_available": self.models_available(),
            "support_available": self.support_model_available(),
            "embed_available": self.embed_model_available(),
            "llama_server_available": self.llama_server_available(),
            "gpu_backend": self._get_active_backend(),
            "available_backends": self.get_available_backends(),
            "is_downloading": self._downloading,
            "models_dir": self.models_dir,
        }
        if self._downloading and self._download_progress:
            status["download_progress"] = self._download_progress
        return status

    def _scan_custom_gguf(self, exclude: set[str]) -> list[dict]:
        """Scan models_dir for .gguf files not in the given exclude set."""
        custom = []
        if not path.isdir(self.models_dir):
            return custom
        for entry in sorted(os.listdir(self.models_dir)):
            if not entry.lower().endswith(".gguf"):
                continue
            if entry in exclude:
                continue
            full = path.join(self.models_dir, entry)
            if not path.isfile(full):
                continue
            size_mb = os.path.getsize(full) // (1024 * 1024)
            custom.append(
                {
                    "filename": entry,
                    "label": entry,
                    "size_mb": size_mb,
                    "downloaded": True,
                }
            )
        return custom

    def get_support_models(self) -> list[dict]:
        """Return the list of available support models for the UI dropdown."""
        result = []
        for filename, model_def in SUPPORT_MODELS.items():
            result.append(
                {
                    "filename": filename,
                    "label": model_def["label"],
                    "size_mb": model_def["expected_size_mb"],
                    "downloaded": path.exists(path.join(self.models_dir, filename)),
                }
            )
        known = set(SUPPORT_MODELS.keys()) | set(EMBED_MODELS.keys())
        result.extend(self._scan_custom_gguf(known))
        return result

    def get_embed_models(self) -> list[dict]:
        """Return the list of available embed models for the UI dropdown."""
        result = []
        for filename, model_def in EMBED_MODELS.items():
            result.append(
                {
                    "filename": filename,
                    "label": model_def["label"],
                    "size_mb": model_def["expected_size_mb"],
                    "downloaded": path.exists(path.join(self.models_dir, filename)),
                }
            )
        known = set(SUPPORT_MODELS.keys()) | set(EMBED_MODELS.keys())
        result.extend(self._scan_custom_gguf(known))
        return result

    # ── llama-server binary management ──────────────────────────────────

    def _get_active_backend(self) -> str:
        """Return the effective backend name for the current platform."""
        system = platform.system()
        if system != "Windows":
            return "default"
        return self.settings.gpu_backend or "cpu"

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
        with self._server_download_lock:
            # Re-check inside the lock: another thread may have finished the
            # install while we were waiting.
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
            # Stage into a sibling dir and swap it in only once everything
            # (binary + CUDA runtime DLLs) is extracted — a failure or crash
            # mid-way can't leave a half-installed server_dir that
            # llama_server_available() mistakes for a working install.
            staging_dir = server_dir + ".staging"
            temp_path = path.join(self.models_dir, asset_name + ".part")

            printr.print(
                f"Downloading llama-server {LLAMA_SERVER_VERSION} ({bk}) for {platform.system()} {platform.machine()}...",
                color=LogType.INFO,
                server_only=True,
            )

            try:
                if path.isdir(staging_dir):
                    shutil.rmtree(staging_dir)

                self._download_and_extract(
                    url, temp_path, staging_dir, f"llama-server ({bk})"
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
                        cudart_url, cudart_temp, staging_dir, "CUDA runtime"
                    )

                # Everything extracted — swap the staged install into place.
                if path.isdir(server_dir):
                    shutil.rmtree(server_dir)
                os.rename(staging_dir, server_dir)

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
                if path.isdir(staging_dir):
                    try:
                        shutil.rmtree(staging_dir)
                    except OSError:
                        pass
                return False

    def _download_and_extract(
        self, url: str, temp_path: str, target_dir: str, label: str
    ):
        """Download a file (with retries) and extract it into target_dir."""
        delay = RETRY_BASE_DELAY_SECONDS
        for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
            try:
                self._stream_download_archive(url, temp_path, label)
                break
            except Exception as e:
                if path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
                if (
                    not _is_retryable_download_error(e)
                    or attempt >= MAX_DOWNLOAD_ATTEMPTS
                ):
                    raise
                printr.print(
                    f"Download of {label} failed (attempt {attempt}/{MAX_DOWNLOAD_ATTEMPTS}): {e} — retrying in {delay}s...",
                    color=LogType.WARNING,
                    server_only=True,
                )
                time.sleep(delay)
                delay *= 2

        try:
            # Extract archive
            os.makedirs(target_dir, exist_ok=True)
            archive_name = temp_path.removesuffix(".part")
            if archive_name.endswith(".tar.gz"):
                self._safe_extract_tar(temp_path, target_dir)
            elif archive_name.endswith(".zip"):
                self._safe_extract_zip(temp_path, target_dir)
        finally:
            # Clean up archive (also on a failed extraction — it's corrupt then)
            if path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def _stream_download_archive(self, url: str, temp_path: str, label: str):
        """Stream a single archive download to temp_path with size validation."""
        response = requests.get(url, stream=True, timeout=30, allow_redirects=True)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0
        last_logged_pct = -10
        total_mb = total_size // (1024 * 1024) if total_size > 0 else 0
        self._download_progress = {
            "file": label,
            "pct": 0,
            "downloaded_mb": 0,
            "total_mb": total_mb,
        }

        with open(temp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    pct = int(downloaded / total_size * 100)
                    self._download_progress = {
                        "file": label,
                        "pct": pct,
                        "downloaded_mb": downloaded // (1024 * 1024),
                        "total_mb": total_mb,
                    }
                    if pct - last_logged_pct >= 10:
                        printr.print(
                            f"  {label}: {pct}% ({downloaded // (1024*1024)} MB / {total_mb} MB)",
                            color=LogType.INFO,
                            server_only=True,
                        )
                        last_logged_pct = pct

        # Never extract a truncated archive.
        if downloaded == 0 or (total_size > 0 and downloaded != total_size):
            raise IOError(
                f"Incomplete download: got {downloaded} of {total_size} bytes"
            )

    def download_llama_server_sync(self, backend: Optional[str] = None) -> bool:
        """Synchronous wrapper for downloading a llama-server binary."""
        return self._download_llama_server(backend)
