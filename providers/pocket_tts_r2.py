"""Redirect PocketTTS model downloads from HuggingFace to our Cloudflare R2 mirror.

The upstream ``pocket_tts`` library resolves its weights from ``hf://`` URIs baked
into the per-language YAML configs it ships (see ``pocket_tts/config/*.yaml``). The
voice-cloning weights live in the *gated* ``kyutai/pocket-tts`` repo, which requires
an HF account that accepted the terms plus a token - something our end users don't
have. On first start the download therefore fails, the library silently falls back
to the non-cloning weights, and any clone attempt raises ``VOICE_CLONING_UNSUPPORTED``.

We mirror the required files (unmodified) to our own R2 bucket - permitted by the
model's CC-BY-4.0 license - and rewrite the configs at load time so every ``hf://``
URI points at ``release.wingman-ai.com`` instead. ``pocket_tts``'s own
``download_if_necessary`` already understands plain ``https://`` URLs, so no library
patching is needed.

Both this module (runtime rewrite) and ``scripts/mirror_pocket_tts_r2.py`` (upload)
derive R2 URLs through :func:`hf_uri_to_r2_url`, so the paths are guaranteed to match.
"""

import hashlib
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import requests

# Public base URL of the R2 ``wingman-releases`` bucket (custom domain), plus the
# top-level ``models/`` prefix. This prefix is NOT touched by the release-cleanup
# job in wingman-client, which only prunes ``vX.Y.Z/`` semver folders.
POCKET_TTS_R2_BASE = "https://release.wingman-ai.com/models"

# We only mirror files from the *gated* repo - that is the sole thing users can't
# download without an HF token, and thus the entire cause of the bug. The tokenizer
# and non-cloning weights live in a public repo and are fetched straight from HF (no
# token needed), which also keeps our R2 storage/footprint to the minimum and leaves
# a genuine cross-host fallback if R2 is ever unreachable.
GATED_REPO_PREFIX = "hf://kyutai/pocket-tts/"

# Escape hatch for developers: set to ``hf`` to bypass the R2 mirror and let the
# library download straight from HuggingFace (requires a local HF token for the
# gated cloning weights). Any other value (or unset) uses the R2 mirror.
_SOURCE_ENV = "WINGMAN_POCKET_TTS_SOURCE"

_HF_URI_RE = re.compile(r"hf://\S+")


def use_r2_mirror() -> bool:
    """Whether builtin models should load from the R2 mirror (default) or HF."""
    return os.environ.get(_SOURCE_ENV, "").strip().lower() != "hf"


def hf_uri_to_r2_url(hf_uri: str) -> str:
    """Map a single ``hf://owner/repo/path/file.ext@revision`` URI to its R2 URL.

    The revision is preserved as a path segment right before the filename so that a
    future ``pocket_tts`` bump (new revisions) fails loudly with a 404 against the
    stale mirror instead of silently serving weights that no longer match the config.

    ``hf://kyutai/pocket-tts/languages/english_2026-04/model.safetensors@19f95fe``
    -> ``<base>/kyutai/pocket-tts/languages/english_2026-04/19f95fe/model.safetensors``
    """
    if not hf_uri.startswith("hf://"):
        return hf_uri
    body = hf_uri[len("hf://") :]
    revision = None
    if "@" in body:
        body, revision = body.rsplit("@", 1)
    if revision:
        head, _, filename = body.rpartition("/")
        body = f"{head}/{revision}/{filename}" if head else f"{revision}/{filename}"
    return f"{POCKET_TTS_R2_BASE.rstrip('/')}/{body}"


def hf_uri_to_https_url(hf_uri: str) -> str:
    """Map ``hf://owner/repo/path/file.ext@revision`` to a direct
    ``https://huggingface.co/owner/repo/resolve/<revision>/path/file.ext`` URL.

    Unlike :func:`hf_uri_to_r2_url` this keeps the file on HuggingFace — used for
    public (non-gated) files we deliberately don't mirror, so they can be fetched
    with :func:`download_url_to_path` instead of the library's fragile downloader.
    """
    if not hf_uri.startswith("hf://"):
        return hf_uri
    body = hf_uri[len("hf://") :]
    revision = "main"
    if "@" in body:
        body, revision = body.rsplit("@", 1)
    parts = body.split("/")
    repo = "/".join(parts[:2])
    file_path = "/".join(parts[2:])
    return f"https://huggingface.co/{repo}/resolve/{revision}/{file_path}"


def is_gated_uri(hf_uri: str) -> bool:
    """Whether a URI points at the gated ``kyutai/pocket-tts`` repo.

    The trailing slash is required to avoid matching the *public*
    ``kyutai/pocket-tts-without-voice-cloning`` repo, which we deliberately leave on HF.
    """
    return hf_uri.startswith(GATED_REPO_PREFIX)


def rewrite_config_text(text: str) -> str:
    """Rewrite gated ``hf://`` URIs in a raw YAML config to their R2 equivalent.

    Only URIs from the gated repo are redirected to R2; public URIs (tokenizer,
    non-cloning weights) are left untouched so they keep downloading straight from HF.

    Operates on the raw text (not a parsed tree) so comments and formatting are kept
    verbatim. ``hf://`` URIs are unquoted YAML scalars with no whitespace, so the
    ``\\S+`` match cleanly captures exactly one URI.
    """

    def _sub(m: "re.Match") -> str:
        uri = m.group(0)
        return hf_uri_to_r2_url(uri) if is_gated_uri(uri) else uri

    return _HF_URI_RE.sub(_sub, text)


def iter_gated_uris(text: str):
    """Yield every gated ``hf://`` URI in a raw YAML config (used by the mirror)."""
    return [u for u in _HF_URI_RE.findall(text) if is_gated_uri(u)]


def library_config_path(model_id: str) -> Path:
    """Absolute path to the ``pocket_tts`` library's bundled config for a language."""
    from pocket_tts.utils.config import CONFIGS_DIR

    return Path(CONFIGS_DIR) / f"{model_id}.yaml"


def build_r2_config(model_id: str, cache_dir: str) -> str:
    """Write an R2-rewritten copy of a builtin language config and return its path.

    Args:
        model_id: A builtin language id (e.g. ``english_2026-04``, ``german_24l``).
        cache_dir: Directory to write the rewritten config into (created if needed).

    Returns:
        The absolute path to the rewritten YAML, ready to pass to
        ``TTSModel.load_model(config=...)``.
    """
    src = library_config_path(model_id)
    if not src.exists():
        raise FileNotFoundError(f"No bundled pocket_tts config for '{model_id}' at {src}")

    out_dir = Path(cache_dir) / ".r2-configs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{model_id}.yaml"
    # Atomic write: a settings-change reload (daemon thread) may race the initial
    # deferred load; never let the library read a half-written config.
    tmp_path = out_dir / f".{model_id}.yaml.{os.getpid()}.tmp"
    tmp_path.write_text(rewrite_config_text(src.read_text()))
    os.replace(tmp_path, out_path)
    return str(out_path)


# ── Robust prefetch into pocket_tts's download cache ────────────────────────
#
# ``pocket_tts.download_if_necessary`` handles plain https URLs with a bare
# ``requests.get`` — no timeout (startup can hang forever on a stalled
# connection), no retry, no size check and a non-atomic cache write, so a kill
# mid-write leaves a truncated file that is treated as valid forever. To keep
# that fragile path from ever running for our (hundreds-of-MB) R2 weights, we
# pre-populate the exact cache entry the library will look up, with retries,
# timeouts, size validation and an atomic rename.

_PREFETCH_LOCK = threading.Lock()
_PREFETCH_TIMEOUT = (10, 120)  # (connect, per-read) seconds
_PREFETCH_ATTEMPTS = 3


def _library_cache_path(url: str) -> Path:
    """The cache file ``pocket_tts.download_if_necessary`` uses for an https URL.

    Must mirror the library's logic exactly:
    ``~/.cache/pocket_tts/<sha256(url)>.<last-dot-suffix>``. If the library ever
    changes its layout, the worst case is a redundant download on its side —
    never a broken load.
    """
    from pocket_tts.utils.utils import make_cache_directory

    suffix = url.split(".")[-1]
    return make_cache_directory() / (hashlib.sha256(url.encode()).hexdigest() + "." + suffix)


def r2_urls_for_model(model_id: str) -> list[str]:
    """The R2 URLs a rewritten config for ``model_id`` will reference."""
    src = library_config_path(model_id)
    if not src.exists():
        return []
    return [hf_uri_to_r2_url(u) for u in iter_gated_uris(src.read_text())]


def _download_to_cache(url: str, cache_path: Path, log: Optional[Callable[[str], None]]) -> None:
    """Stream ``url`` to ``cache_path`` with retries, size check and atomic rename."""
    temp_path = cache_path.with_name(f"{cache_path.name}.{os.getpid()}.part")
    last_error: Optional[Exception] = None
    delay = 2
    for attempt in range(1, _PREFETCH_ATTEMPTS + 1):
        try:
            with requests.get(url, stream=True, timeout=_PREFETCH_TIMEOUT) as response:
                response.raise_for_status()
                total_size = int(response.headers.get("content-length", 0))
                written = 0
                with open(temp_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                        f.write(chunk)
                        written += len(chunk)
            if written == 0 or (total_size > 0 and written != total_size):
                raise IOError(
                    f"Incomplete download: got {written} of {total_size} bytes"
                )
            os.replace(temp_path, cache_path)
            return
        except Exception as e:
            last_error = e
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            # Client errors (404 = stale mirror, 403, ...) won't heal on retry.
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status is not None and 400 <= status < 500 and status != 429:
                break
            if attempt < _PREFETCH_ATTEMPTS:
                if log:
                    log(
                        f"Download of {url} failed (attempt {attempt}/{_PREFETCH_ATTEMPTS}): {e} — retrying in {delay}s..."
                    )
                time.sleep(delay)
                delay *= 2
    raise RuntimeError(f"Could not download {url}: {last_error}") from last_error


def download_url_to_path(
    url: str, dest_path: "str | Path", log: Optional[Callable[[str], None]] = None
) -> None:
    """Robustly download ``url`` to an exact destination path.

    Same guarantees as the R2 weight prefetch (retries, timeouts, size check,
    atomic rename) — shared with ``providers.pocket_tts`` for the per-language
    built-in voice embeddings, which live in a public HF repo and are therefore
    not mirrored to R2.
    """
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _download_to_cache(url, dest, log)


def prefetch_gated_weights(
    model_id: str, log: Optional[Callable[[str], None]] = None
) -> None:
    """Ensure the R2-mirrored weights for ``model_id`` are in pocket_tts's cache.

    Called before ``TTSModel.load_model`` so the library finds the weights
    already cached and never exercises its own fragile download path. No-op
    (and no network access) when the cache is already warm, so offline starts
    with a warm cache keep working. Raises on failure — callers decide whether
    to surface a warning and continue (the library then falls back to the
    public non-cloning weights).
    """
    for url in r2_urls_for_model(model_id):
        cache_path = _library_cache_path(url)
        if cache_path.exists() and cache_path.stat().st_size > 0:
            continue
        # One download at a time: two concurrent loads of the same model must
        # not write the same cache entry on top of each other.
        with _PREFETCH_LOCK:
            if cache_path.exists() and cache_path.stat().st_size > 0:
                continue
            if log:
                log(f"Downloading PocketTTS voice-cloning weights from R2 mirror: {url}")
            _download_to_cache(url, cache_path, log)
