import asyncio
import os
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
    "repo": "Qwen/Qwen3.5-0.8B-GGUF",
    "filename": "qwen3.5-0.8b-q4_k_m.gguf",
    "expected_size_mb": 500,
}

DEFAULT_EMBED_MODEL = {
    "repo": "nomic-ai/nomic-embed-text-v1.5-GGUF",
    "filename": "nomic-embed-text-v1.5.f16.gguf",
    "expected_size_mb": 250,
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
        """Download both models asynchronously. Returns True if both succeed."""
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
            return summarize_ok and embed_ok
        finally:
            self._downloading = False

    def get_status(self) -> dict:
        """Return current model status for the API."""
        return {
            "models_available": self.models_available(),
            "summarize_available": self.summarize_model_available(),
            "embed_available": self.embed_model_available(),
            "is_downloading": self._downloading,
            "models_dir": self.models_dir,
        }
