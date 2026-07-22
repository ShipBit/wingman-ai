import asyncio
import os
import threading
from os import path
from typing import Callable, Optional

import requests

from api.enums import LogType
from services.printr import Printr

printr = Printr()

# Transient network failures (blips, resets, mid-download aborts) were the most
# frequent failure source in the field — always retry with backoff before
# surfacing an error.
MAX_DOWNLOAD_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 2


class ModelDownloader:
    """Generic model download service with progress reporting.

    Manages the unified models/ directory and handles downloads from
    HuggingFace Hub and direct URLs with consistent progress callbacks.
    """

    def __init__(self, models_root: str):
        self.models_root = models_root
        if not path.exists(models_root):
            os.makedirs(models_root)

    def get_model_dir(self, category: str) -> str:
        """Return the subdirectory for a model category, creating it if needed.

        Args:
            category: Subdirectory name (e.g., "parakeet", "faster-whisper", "local-ai")
        """
        category_dir = path.join(self.models_root, category)
        if not path.exists(category_dir):
            os.makedirs(category_dir)
        return category_dir

    def models_exist(self, category: str, expected_files: list[str]) -> bool:
        """Check if all expected model files exist in the category directory."""
        category_dir = self.get_model_dir(category)
        return all(path.exists(path.join(category_dir, f)) for f in expected_files)

    async def download_huggingface(
        self,
        repo_id: str,
        category: str,
        allow_patterns: list[str] | None = None,
    ) -> str:
        """Download model from HuggingFace Hub.

        Args:
            repo_id: HuggingFace repository ID (e.g., "istupakov/parakeet-tdt-0.6b-v3-onnx")
            category: Subdirectory name under models/
            allow_patterns: File patterns to download (None = all)

        Returns:
            Local directory path where files were downloaded.
        """
        local_dir = self.get_model_dir(category)
        loop = asyncio.get_event_loop()

        def _download():
            try:
                from huggingface_hub import snapshot_download
            except ImportError as e:
                raise ImportError(
                    "huggingface_hub is required for HuggingFace downloads. "
                    "Install it with: pip install huggingface_hub"
                ) from e

            return snapshot_download(
                repo_id,
                local_dir=local_dir,
                allow_patterns=allow_patterns,
            )

        printr.print(
            f"Downloading model from {repo_id}...",
            color=LogType.INFO,
            server_only=True,
        )

        # snapshot_download retries and resumes individual files internally, but
        # its initial repo-info call and unlucky streaks still fail on flaky
        # connections — retry the whole snapshot (completed files are skipped,
        # partial files resume, so retries are cheap).
        delay = RETRY_BASE_DELAY_SECONDS
        last_error: Optional[Exception] = None
        for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
            try:
                result_path = await loop.run_in_executor(None, _download)
                printr.print(
                    f"Download complete: {repo_id}",
                    color=LogType.POSITIVE,
                    server_only=True,
                )
                return result_path
            except Exception as e:
                last_error = e
                if not self._is_retryable(e) or attempt >= MAX_DOWNLOAD_ATTEMPTS:
                    break
                printr.print(
                    f"Download of {repo_id} failed (attempt {attempt}/{MAX_DOWNLOAD_ATTEMPTS}): {e} — retrying in {delay}s...",
                    color=LogType.WARNING,
                    server_only=True,
                )
                await asyncio.sleep(delay)
                delay *= 2

        printr.print(
            f"Failed to download {repo_id}: {last_error}",
            color=LogType.ERROR,
            server_only=True,
        )
        raise last_error

    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        """Whether a download error is transient. Auth/gating/404 never heal on retry."""
        try:
            from huggingface_hub.errors import (
                GatedRepoError,
                RepositoryNotFoundError,
                RevisionNotFoundError,
            )

            if isinstance(
                error,
                (GatedRepoError, RepositoryNotFoundError, RevisionNotFoundError),
            ):
                return False
        except ImportError:
            pass
        status = getattr(getattr(error, "response", None), "status_code", None)
        if status is not None and 400 <= status < 500 and status != 429:
            return False
        return True

    async def download_file(
        self,
        url: str,
        category: str,
        filename: str,
        on_progress: Optional[Callable[[str, float, float, float], None]] = None,
    ) -> str:
        """Download a single file via HTTP with progress tracking.

        Args:
            url: Direct download URL
            category: Subdirectory name under models/
            filename: Target filename
            on_progress: Callback (filename, percent, downloaded_mb, total_mb)

        Returns:
            Local file path.
        """
        category_dir = self.get_model_dir(category)
        target_path = path.join(category_dir, filename)

        if path.exists(target_path):
            printr.print(
                f"Model already exists: {filename}",
                color=LogType.INFO,
                server_only=True,
            )
            return target_path

        loop = asyncio.get_event_loop()

        def _download():
            # Unique temp name: if two triggers race the same file, they never
            # interleave writes into the same .part; the atomic replace below
            # makes the last writer win with a complete file either way.
            temp_path = f"{target_path}.{os.getpid()}-{threading.get_ident()}.part"
            try:
                response = requests.get(url, stream=True, timeout=30)
                response.raise_for_status()

                total_size = int(response.headers.get("content-length", 0))
                downloaded = 0
                last_callback_pct = -2
                total_mb = total_size // (1024 * 1024) if total_size > 0 else 0

                with open(temp_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            pct = int(downloaded / total_size * 100)
                            downloaded_mb = downloaded // (1024 * 1024)
                            if on_progress and pct - last_callback_pct >= 2:
                                on_progress(filename, pct, downloaded_mb, total_mb)
                                last_callback_pct = pct

                # Never promote a truncated body to the final filename.
                if downloaded == 0 or (total_size > 0 and downloaded != total_size):
                    raise IOError(
                        f"Incomplete download: got {downloaded} of {total_size} bytes"
                    )

                os.replace(temp_path, target_path)
                return target_path

            except Exception:
                if path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
                raise

        printr.print(
            f"Downloading {filename}...",
            color=LogType.INFO,
            server_only=True,
        )

        delay = RETRY_BASE_DELAY_SECONDS
        last_error: Optional[Exception] = None
        for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
            try:
                result = await loop.run_in_executor(None, _download)
                printr.print(
                    f"Download complete: {filename}",
                    color=LogType.POSITIVE,
                    server_only=True,
                )
                return result
            except Exception as e:
                last_error = e
                if not self._is_retryable(e) or attempt >= MAX_DOWNLOAD_ATTEMPTS:
                    break
                printr.print(
                    f"Download of {filename} failed (attempt {attempt}/{MAX_DOWNLOAD_ATTEMPTS}): {e} — retrying in {delay}s...",
                    color=LogType.WARNING,
                    server_only=True,
                )
                await asyncio.sleep(delay)
                delay *= 2

        printr.print(
            f"Failed to download {filename}: {last_error}",
            color=LogType.ERROR,
            server_only=True,
        )
        raise last_error
