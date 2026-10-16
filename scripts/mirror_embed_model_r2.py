#!/usr/bin/env python3
"""One-off / maintenance tool: mirror the local embedding model to R2.

WHY
    Core downloads the embedding model (`EMBED_MODELS` in
    services/local_model_manager.py) on first start. It tries our Cloudflare R2
    bucket first and Hugging Face second: the mirror is ours to keep up, HF has
    been slow or rate-limited at exactly that moment. The file is mirrored
    unmodified, with the model's Apache 2.0 LICENSE and a NOTICE next to it.

WHAT IT DOES
    For every model in `EMBED_MODELS` that has a mirror `url`, downloads the
    GGUF from its Hugging Face repo, uploads it to R2 at the key the `url`
    expects, and uploads LICENSE and NOTICE into the same folder. Idempotent:
    objects already present are skipped unless ``--force`` is given.

PREREQUISITES (what YOU need before running)
    1. The AWS CLI installed (`pip install awscli`) - same tool our release CI uses.
    2. The R2 credentials (the same GitHub secrets the release workflow uses):
           export R2_ACCOUNT_ID=...
           export R2_ACCESS_KEY_ID=...
           export R2_SECRET_ACCESS_KEY=...
       Optionally override the bucket (defaults to the releases bucket):
           export R2_BUCKET=wingman-releases

USAGE
    python scripts/mirror_embed_model_r2.py              # mirror every embed model
    python scripts/mirror_embed_model_r2.py --force      # re-upload even if present
    python scripts/mirror_embed_model_r2.py --dry-run    # show what would happen
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Ensure the repo root is importable when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from huggingface_hub import hf_hub_download  # noqa: E402

from services.local_model_manager import EMBED_MODELS, MODELS_R2_BASE  # noqa: E402

R2_BUCKET = os.environ.get("R2_BUCKET", "wingman-releases")
# The custom domain serves the bucket root, so the S3 key is the URL path after the host.
_R2_HOST_PREFIX = MODELS_R2_BASE.split("/models", 1)[0].rstrip("/") + "/"

# Who made each model and where it comes from, for the NOTICE next to it.
ORIGINS = {
    "nomic-embed-text-v1.5.f16.gguf": (
        "Nomic Embed Text v1.5",
        "Nomic AI",
        "https://huggingface.co/nomic-ai/nomic-embed-text-v1.5",
    ),
    "embeddinggemma-2-Q8_0.gguf": (
        "EmbeddingGemma 2",
        "Google LLC",
        "https://huggingface.co/google/embeddinggemma-2",
    ),
}

NOTICE = """{name}
Copyright {owner}

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. A copy of the License
is in the LICENSE file next to this one.

This folder holds an unmodified copy of {filename} from
https://huggingface.co/{repo}, a GGUF conversion of
{origin}, mirrored by ShipBit for Wingman AI so that the model downloads
from one place.
"""


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


def _license_text() -> str:
    """The Apache 2.0 text from its canonical URL (the GGUF repo carries
    none of its own)."""
    import urllib.request

    with urllib.request.urlopen("https://www.apache.org/licenses/LICENSE-2.0.txt", timeout=30) as r:
        return r.read().decode("utf-8")


def main() -> int:
    args = sys.argv[1:]
    force = "--force" in args
    dry_run = "--dry-run" in args

    if shutil.which("aws") is None and not dry_run:
        sys.exit("ERROR: the AWS CLI is not installed. Run: pip install awscli")

    endpoint = _r2_endpoint() if not dry_run else "(dry run)"
    env = _aws_env() if not dry_run else {}

    print(f"Mirroring embedding models -> s3://{R2_BUCKET}/ ({endpoint})\n")
    uploaded = skipped = 0
    for filename, model in EMBED_MODELS.items():
        url = model.get("url")
        if not url:
            print(f"  [{filename}] no mirror url, skip")
            continue
        key = r2_url_to_key(url)
        folder = key.rsplit("/", 1)[0]
        files = {key: ("hf", model["repo"], filename)}
        files[f"{folder}/LICENSE"] = ("text", _license_text if not dry_run else None, None)
        name, owner, origin = ORIGINS[filename]
        files[f"{folder}/NOTICE"] = (
            "text",
            # Bound now: the loop below reuses `name` for its own tuples.
            lambda name=name, owner=owner, origin=origin, filename=filename, repo=model["repo"]: NOTICE.format(
                name=name, owner=owner, origin=origin, filename=filename, repo=repo
            ),
            None,
        )
        for object_key, (kind, source, name) in files.items():
            if dry_run:
                print(f"  would upload: {object_key}")
                continue
            if not force and _object_exists(object_key, endpoint, env):
                print(f"  exists, skip: {object_key}")
                skipped += 1
                continue
            if kind == "hf":
                print(f"  downloading {source}/{name} ...")
                local = hf_hub_download(repo_id=source, filename=name)
                print(f"  uploading -> {object_key}")
                _upload(local, object_key, endpoint, env)
            else:
                with tempfile.NamedTemporaryFile("w", suffix=object_key.rsplit("/", 1)[-1], delete=False) as handle:
                    handle.write(source())
                    local = handle.name
                print(f"  uploading -> {object_key}")
                _upload(local, object_key, endpoint, env)
                os.remove(local)
            uploaded += 1

    print(f"\nDone. uploaded={uploaded} skipped={skipped}" + (" (dry run)" if dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
