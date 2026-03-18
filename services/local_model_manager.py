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

# Default model definitions used for auto-download
DEFAULT_SUMMARIZE_MODEL = {
    "repo": "unsloth/Qwen3.5-0.8B-GGUF",
    "filename": "Qwen3.5-0.8B-Q4_K_M.gguf",
    "expected_size_mb": 500,
}

DEFAULT_EMBED_MODEL = {
    "repo": "nomic-ai/nomic-embed-text-v1.5-GGUF",
    "filename": "nomic-embed-text-v1.5.f16.gguf",
    "expected_size_mb": 250,
}

# llama-server binary release — update this to get newer llama.cpp features
LLAMA_SERVER_VERSION = "b8400"
LLAMA_SERVER_ASSETS = {
    "Darwin_arm64": f"llama-{LLAMA_SERVER_VERSION}-bin-macos-arm64.tar.gz",
    "Darwin_x86_64": f"llama-{LLAMA_SERVER_VERSION}-bin-macos-x64.tar.gz",
    "Windows_AMD64": f"llama-{LLAMA_SERVER_VERSION}-bin-win-vulkan-x64.zip",
    "Linux_x86_64": f"llama-{LLAMA_SERVER_VERSION}-bin-ubuntu-x64.tar.gz",
}


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

    async def download_models(self) -> bool:
        """Download both models and llama-server binary asynchronously. Returns True if all succeed."""
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
            summarize_ok = await loop.run_in_executor(
                None, self._download_model, DEFAULT_SUMMARIZE_MODEL
            )
            embed_ok = await loop.run_in_executor(
                None, self._download_model, DEFAULT_EMBED_MODEL
            )
            server_ok = await loop.run_in_executor(None, self._download_llama_server)
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
            "is_downloading": self._downloading,
            "models_dir": self.models_dir,
        }

    # ── llama-server binary management ──────────────────────────────────

    def get_llama_server_dir(self) -> str:
        """Return the directory containing the extracted llama-server binary."""
        return path.join(self.models_dir, f"llama-server-{LLAMA_SERVER_VERSION}")

    def get_llama_server_path(self) -> str:
        """Return the full path to the llama-server binary, searching recursively."""
        server_dir = self.get_llama_server_dir()
        binary_name = (
            "llama-server.exe" if platform.system() == "Windows" else "llama-server"
        )
        # Search recursively (archive may have nested dirs like llama-b8400/)
        for root, _dirs, files in os.walk(server_dir):
            if binary_name in files:
                return path.join(root, binary_name)
        # Fallback — will fail the exists() check, triggering download
        return path.join(server_dir, binary_name)

    def llama_server_available(self) -> bool:
        """Check if the llama-server binary exists."""
        return path.exists(self.get_llama_server_path())

    def _get_platform_asset_name(self) -> Optional[str]:
        """Get the platform-specific release asset filename."""
        system = platform.system()
        machine = platform.machine()
        key = f"{system}_{machine}"
        return LLAMA_SERVER_ASSETS.get(key)

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

    def _download_llama_server(self) -> bool:
        """Download and extract the llama-server binary for the current platform."""
        if self.llama_server_available():
            return True

        asset_name = self._get_platform_asset_name()
        if not asset_name:
            printr.print(
                f"No llama-server binary available for {platform.system()} {platform.machine()}",
                color=LogType.ERROR,
                server_only=True,
            )
            return False

        url = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_SERVER_VERSION}/{asset_name}"
        server_dir = self.get_llama_server_dir()
        temp_path = path.join(self.models_dir, asset_name + ".part")

        printr.print(
            f"Downloading llama-server {LLAMA_SERVER_VERSION} for {platform.system()} {platform.machine()}...",
            color=LogType.INFO,
            server_only=True,
        )

        try:
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
                                f"  llama-server: {pct}% ({downloaded // (1024*1024)} MB / {total_size // (1024*1024)} MB)",
                                color=LogType.INFO,
                                server_only=True,
                            )
                            last_logged_pct = pct

            # Extract archive
            os.makedirs(server_dir, exist_ok=True)
            if asset_name.endswith(".tar.gz"):
                self._safe_extract_tar(temp_path, server_dir)
            elif asset_name.endswith(".zip"):
                self._safe_extract_zip(temp_path, server_dir)

            # Make binary executable on Unix
            binary_path = self.get_llama_server_path()
            if platform.system() != "Windows" and path.exists(binary_path):
                os.chmod(
                    binary_path,
                    os.stat(binary_path).st_mode
                    | stat.S_IEXEC
                    | stat.S_IXGRP
                    | stat.S_IXOTH,
                )

            # Clean up archive
            os.remove(temp_path)

            printr.print(
                f"llama-server {LLAMA_SERVER_VERSION} ready.",
                color=LogType.INFO,
                server_only=True,
            )
            return True

        except Exception as e:
            printr.print(
                f"Failed to download llama-server: {e}",
                color=LogType.ERROR,
                server_only=True,
            )
            if path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            return False

    def download_llama_server_sync(self) -> bool:
        """Synchronous wrapper for downloading the llama-server binary."""
        return self._download_llama_server()
