#!/usr/bin/env python3
"""Maintenance tool: mirror the Parakeet model Core runs to our R2 bucket.

WHY
    Core downloads Parakeet from release.wingman-ai.com instead of Hugging Face:
    the upstream repo rebuilds its files in place, and we want one source that
    only changes when we change providers/parakeet_r2.py.

WHAT IT DOES
    Downloads every file of providers/parakeet_r2.py at its pinned revision from
    Hugging Face, checks size and SHA256, and uploads it to the key Core expects,
    with a NOTICE (attribution, as CC-BY-4.0 asks) and the license text.
    Idempotent: files already in R2 are skipped unless --force is given.

PREREQUISITES
    The AWS CLI (`pip install awscli`, or run it through `uvx --from awscli`), and
    either the R2 credentials our release CI uses:
        export R2_ACCOUNT_ID=... R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=...
    or an AWS profile whose config has the R2 `endpoint_url`:
        export AWS_PROFILE=r2
    Optionally the bucket: export R2_BUCKET=wingman-releases

USAGE
    python scripts/mirror_parakeet_r2.py             # mirror
    python scripts/mirror_parakeet_r2.py --dry-run   # show what would happen
    python scripts/mirror_parakeet_r2.py --force     # re-upload even if present
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402
from huggingface_hub import hf_hub_download  # noqa: E402

from providers.parakeet_r2 import (  # noqa: E402
    FILES,
    PARAKEET_R2_BASE,
    REVISION,
    SOURCE_REPO,
    file_url,
)

R2_BUCKET = os.environ.get("R2_BUCKET", "wingman-releases")
_R2_HOST_PREFIX = PARAKEET_R2_BASE.split("/models", 1)[0].rstrip("/") + "/"
AWS = os.environ.get("AWS_CLI", "aws").split()
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/legalcode.txt"

NOTICE = f"""Parakeet Ultra, ONNX int8
Copyright NVIDIA Corporation (parakeet-tdt-0.6b-v3), moondream (parakeet-ultra),
Olicorne (ONNX export)

Licensed under the Creative Commons Attribution 4.0 International License
(CC-BY-4.0). A copy of the license is in the LICENSE file next to this one.

This folder holds unmodified copies of int8/encoder-model.int8.onnx,
int8/decoder_joint-model.int8.onnx, vocab.txt and config.json from
https://huggingface.co/{SOURCE_REPO} at revision {REVISION},
an ONNX export of https://huggingface.co/moondream/parakeet-ultra, which is a
post-trained version of https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3,
mirrored by ShipBit for Wingman AI so that the model downloads from one place.
"""


def _key(url: str) -> str:
    return url[len(_R2_HOST_PREFIX):]


def _aws(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if os.environ.get("R2_ACCESS_KEY_ID"):
        env["AWS_ACCESS_KEY_ID"] = os.environ["R2_ACCESS_KEY_ID"]
        env["AWS_SECRET_ACCESS_KEY"] = os.environ.get("R2_SECRET_ACCESS_KEY", "")
    env.setdefault("AWS_DEFAULT_REGION", "auto")
    endpoint = []
    if os.environ.get("R2_ACCOUNT_ID"):
        endpoint = ["--endpoint-url", f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"]
    return subprocess.run([*AWS, *args, *endpoint], env=env, check=check, capture_output=not check, text=True)


def _exists(key: str) -> bool:
    return _aws("s3api", "head-object", "--bucket", R2_BUCKET, "--key", key, check=False).returncode == 0


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    force = "--force" in sys.argv
    dry_run = "--dry-run" in sys.argv
    if shutil.which(AWS[0]) is None:
        sys.exit(f"ERROR: '{AWS[0]}' not found. Install the AWS CLI or set AWS_CLI.")

    with tempfile.TemporaryDirectory() as tmp:
        notice = os.path.join(tmp, "NOTICE")
        Path(notice).write_text(NOTICE, encoding="utf-8")
        license_path = os.path.join(tmp, "LICENSE")
        response = requests.get(LICENSE_URL, headers={"User-Agent": "wingman-ai-mirror"}, timeout=30)
        response.raise_for_status()
        Path(license_path).write_text(response.text, encoding="utf-8")

        for name, (source, size, sha256) in FILES.items():
            key = _key(file_url(name))
            if not force and not dry_run and _exists(key):
                print(f"exists, skip: {key}")
                continue
            if dry_run:
                print(f"would upload {SOURCE_REPO}/{source} -> {key}")
                continue
            local = hf_hub_download(SOURCE_REPO, source, revision=REVISION)
            if os.path.getsize(local) != size or _sha256(local) != sha256:
                sys.exit(f"ERROR: {source} at {REVISION[:8]} is not the file providers/parakeet_r2.py names.")
            print(f"uploading {key}")
            _aws("s3", "cp", local, f"s3://{R2_BUCKET}/{key}")

        for local, name in ((notice, "NOTICE"), (license_path, "LICENSE")):
            key = _key(file_url(name))
            if dry_run:
                print(f"would upload {name} -> {key}")
                continue
            print(f"uploading {key}")
            _aws("s3", "cp", local, f"s3://{R2_BUCKET}/{key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
