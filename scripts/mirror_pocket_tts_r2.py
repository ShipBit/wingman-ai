#!/usr/bin/env python3
"""One-off / maintenance tool: mirror the gated PocketTTS voice-cloning weights to R2.

WHY
    The voice-cloning weights live in the *gated* ``kyutai/pocket-tts`` HF repo, which
    needs an account that accepted the terms plus a token. End users have neither, so
    on first start the download fails and voice cloning breaks. We host these weights
    (unmodified) on our own Cloudflare R2 bucket - permitted by the model's CC-BY-4.0
    license - and Wingman rewrites the configs at runtime to load them from there
    (see providers/pocket_tts_r2.py).

    Only the *gated* files are mirrored. The tokenizer and non-cloning weights are in a
    public repo and keep downloading straight from HF, so this stays minimal.

WHAT IT DOES
    For every builtin language it reads the ``pocket_tts`` library config, finds the
    gated ``hf://kyutai/pocket-tts/...`` URIs, downloads each from HF (using your token),
    and uploads it to R2 at the exact key Wingman expects. Idempotent: files already
    present in R2 are skipped unless ``--force`` is given.

PREREQUISITES (what YOU need before running)
    1. Accept the terms once at https://huggingface.co/kyutai/pocket-tts (auto-approved),
       then authenticate locally so downloads work:
           export HF_TOKEN=hf_xxx            # or: uvx hf auth login  /  huggingface-cli login
    2. The AWS CLI installed (`pip install awscli`) - same tool our release CI uses.
    3. The R2 credentials (the same GitHub secrets the release workflow uses) exported:
           export R2_ACCOUNT_ID=...
           export R2_ACCESS_KEY_ID=...
           export R2_SECRET_ACCESS_KEY=...
       Optionally override the bucket (defaults to the releases bucket):
           export R2_BUCKET=wingman-releases

USAGE
    python scripts/mirror_pocket_tts_r2.py                 # mirror all builtin languages
    python scripts/mirror_pocket_tts_r2.py english_2026-04 german_24l   # only these
    python scripts/mirror_pocket_tts_r2.py --force         # re-upload even if present
    python scripts/mirror_pocket_tts_r2.py --dry-run       # show what would happen
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

# Ensure the repo root is importable when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from huggingface_hub import hf_hub_download  # noqa: E402

from providers.pocket_tts_r2 import (  # noqa: E402
    POCKET_TTS_R2_BASE,
    hf_uri_to_r2_url,
    iter_gated_uris,
    library_config_path,
)

# Keep in sync with BUILTIN_MODELS in providers/pocket_tts.py. Hardcoded here so the
# mirror script doesn't have to import the heavyweight provider (torch/torchaudio).
BUILTIN_LANGUAGES = [
    "english_2026-04",
    "german",
    "german_24l",
    "french_24l",
    "spanish",
    "spanish_24l",
    "italian",
    "italian_24l",
    "portuguese",
    "portuguese_24l",
]

R2_BUCKET = os.environ.get("R2_BUCKET", "wingman-releases")
# The custom domain serves the bucket root, so the S3 key is the URL path after the host.
_R2_HOST_PREFIX = POCKET_TTS_R2_BASE.split("/models", 1)[0].rstrip("/") + "/"


def r2_url_to_key(url: str) -> str:
    """Turn a public R2 URL into the S3 object key inside the bucket."""
    return url[len(_R2_HOST_PREFIX) :]


def _r2_endpoint() -> str:
    account = os.environ.get("R2_ACCOUNT_ID")
    if not account:
        sys.exit("ERROR: R2_ACCOUNT_ID is not set (see the header of this script).")
    return f"https://{account}.r2.cloudflarestorage.com"


def _aws_env() -> dict:
    env = dict(os.environ)
    # Map the R2_* names our CI uses onto what the AWS CLI expects.
    key = os.environ.get("R2_ACCESS_KEY_ID")
    secret = os.environ.get("R2_SECRET_ACCESS_KEY")
    if not key or not secret:
        sys.exit("ERROR: R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY are not set.")
    env["AWS_ACCESS_KEY_ID"] = key
    env["AWS_SECRET_ACCESS_KEY"] = secret
    env["AWS_DEFAULT_REGION"] = "auto"
    return env


def _object_exists(key: str, endpoint: str, env: dict) -> bool:
    result = subprocess.run(
        ["aws", "s3api", "head-object", "--bucket", R2_BUCKET, "--key", key,
         "--endpoint-url", endpoint],
        env=env, capture_output=True, text=True,
    )
    return result.returncode == 0


def _upload(local: str, key: str, endpoint: str, env: dict) -> None:
    subprocess.run(
        ["aws", "s3", "cp", local, f"s3://{R2_BUCKET}/{key}", "--endpoint-url", endpoint],
        env=env, check=True,
    )


def main() -> int:
    args = sys.argv[1:]
    force = "--force" in args
    dry_run = "--dry-run" in args
    languages = [a for a in args if not a.startswith("--")] or BUILTIN_LANGUAGES

    if shutil.which("aws") is None:
        sys.exit("ERROR: the AWS CLI is not installed. Run: pip install awscli")

    endpoint = _r2_endpoint()
    env = _aws_env()

    print(f"Mirroring PocketTTS gated weights -> s3://{R2_BUCKET}/ ({endpoint})")
    print(f"Languages: {', '.join(languages)}\n")

    uploaded = skipped = 0
    for lang in languages:
        cfg = library_config_path(lang)
        if not cfg.exists():
            print(f"  [{lang}] SKIP - no bundled config at {cfg}")
            continue
        gated = iter_gated_uris(cfg.read_text())
        if not gated:
            print(f"  [{lang}] no gated files (nothing to mirror)")
            continue

        for hf_uri in gated:
            key = r2_url_to_key(hf_uri_to_r2_url(hf_uri))
            if not force and not dry_run and _object_exists(key, endpoint, env):
                print(f"  [{lang}] exists, skip: {key}")
                skipped += 1
                continue
            if dry_run:
                print(f"  [{lang}] would upload: {key}\n              from: {hf_uri}")
                continue

            # hf://owner/repo/path@rev  ->  repo_id=owner/repo, filename=path, revision=rev
            body = hf_uri[len("hf://") :]
            body, _, revision = body.partition("@")
            owner, repo, filename = body.split("/", 2)
            repo_id = f"{owner}/{repo}"
            print(f"  [{lang}] downloading {repo_id}/{filename} @ {revision[:8]} ...")
            local = hf_hub_download(
                repo_id=repo_id, filename=filename, revision=revision or None
            )
            print(f"  [{lang}] uploading -> {key}")
            _upload(local, key, endpoint, env)
            uploaded += 1

    print(f"\nDone. uploaded={uploaded} skipped={skipped}"
          + (" (dry run)" if dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
