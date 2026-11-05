import asyncio
import hashlib
import os
import time
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
# A resumed download may need many attempts on a connection that keeps breaking;
# only attempts without new bytes count against MAX_DOWNLOAD_ATTEMPTS.
MAX_RESUMED_ATTEMPTS = 20


class ChecksumError(IOError):
    """A download came in whole but is not the file we expected. A retry
    would fetch the same bytes again."""


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
        size: Optional[int] = None,
        sha256: Optional[str] = None,
    ) -> str:
        """Download a single file via HTTP with progress tracking.

        A file already there is kept when it has `size` bytes (any file when
        `size` is None). A broken connection keeps what came so far and asks
        for the rest (HTTP Range); attempts that bring new bytes do not count
        against the limit. A new file must match `sha256`, if given, before it
        gets its name.

        Args:
            url: Direct download URL
            category: Subdirectory name under models/
            filename: Target filename
            on_progress: Callback (filename, percent, downloaded_mb, total_mb),
                called from a worker thread
            size: Expected size in bytes
            sha256: Expected SHA256 (hex)

        Returns:
            Local file path.
        """
        category_dir = self.get_model_dir(category)
        target_path = path.join(category_dir, filename)

        if path.exists(target_path):
            if size is None or path.getsize(target_path) == size:
                return target_path
            printr.print(
                f"{filename} has {path.getsize(target_path)} bytes instead of {size}, downloading it again.",
                color=LogType.WARNING,
                server_only=True,
            )
            os.remove(target_path)

        printr.print(f"Downloading {filename}...", color=LogType.INFO, server_only=True)
        await asyncio.get_event_loop().run_in_executor(
            None, self._download_resumable, url, target_path, size, sha256, on_progress
        )
        printr.print(f"Download complete: {filename}", color=LogType.POSITIVE, server_only=True)
        return target_path

    def _download_resumable(
        self,
        url: str,
        target_path: str,
        size: Optional[int],
        sha256: Optional[str],
        on_progress: Optional[Callable[[str, float, float, float], None]],
    ):
        filename = path.basename(target_path)
        temp_path = f"{target_path}.part"
        delay = RETRY_BASE_DELAY_SECONDS
        failures_without_progress = 0
        for attempt in range(1, MAX_RESUMED_ATTEMPTS + 1):
            have = path.getsize(temp_path) if path.exists(temp_path) else 0
            try:
                headers = {"Range": f"bytes={have}-"} if have else {}
                response = requests.get(url, stream=True, timeout=30, headers=headers)
                if have and response.status_code == 416:
                    # The part file is whole already, or wrong: start over
                    os.remove(temp_path)
                    have = 0
                    response = requests.get(url, stream=True, timeout=30)
                response.raise_for_status()
                if response.status_code != 206:
                    have = 0  # The server sent the whole file
                total = int(response.headers.get("content-length", 0)) + have
                downloaded = have
                last_pct = -2
                with open(temp_path, "ab" if have else "wb") as f:
                    for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        pct = int(downloaded / total * 100) if total else 0
                        if on_progress and pct - last_pct >= 2:
                            on_progress(filename, pct, downloaded // (1024 * 1024), total // (1024 * 1024))
                            last_pct = pct

                # Never promote a truncated or foreign body to the final name
                if downloaded == 0 or (total and downloaded != total) or (size and downloaded != size):
                    raise IOError(f"Incomplete download: got {downloaded} of {size or total} bytes")
                if sha256 and _sha256(temp_path) != sha256:
                    os.remove(temp_path)
                    raise ChecksumError(f"{filename} does not match its checksum")
                os.replace(temp_path, target_path)
                return
            except ChecksumError:
                raise
            except Exception as e:
                now_have = path.getsize(temp_path) if path.exists(temp_path) else 0
                if not self._is_retryable(e):
                    raise
                if now_have > have:
                    failures_without_progress = 0
                    delay = RETRY_BASE_DELAY_SECONDS
                else:
                    failures_without_progress += 1
                if failures_without_progress >= MAX_DOWNLOAD_ATTEMPTS or attempt == MAX_RESUMED_ATTEMPTS:
                    raise
                printr.print(
                    f"Download of {filename} interrupted at {now_have // (1024 * 1024)} MB "
                    f"(attempt {attempt}): {e} - continuing in {delay}s...",
                    color=LogType.WARNING,
                    server_only=True,
                )
                time.sleep(delay)
                delay *= 2


def _sha256(file_path: str) -> str:
    digest = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
