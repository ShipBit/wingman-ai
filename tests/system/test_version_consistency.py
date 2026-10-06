"""The version has to read the same everywhere it is written down.

3.2.0 shipped with `src-tauri/Cargo.toml` and `Cargo.lock` still on 3.1.6,
because a bump means editing seven files across two repositories by hand and two
of them are Rust. Nothing noticed. This is what notices.

Core is checked always. The client is checked when a checkout sits next to this
one, which is the normal local layout; in CI, where only one repository is
present, those places are skipped rather than failed.
"""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CLIENT = REPO.parent / "wingman-client"


def _versions():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/bump_version.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    return result


def test_every_place_agrees():
    result = _versions()
    assert result.returncode == 0, (
        "The version does not read the same everywhere:\n\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_the_checker_finds_the_client_when_it_is_there():
    """Guards the guard: a broken path would make the check silently pass."""
    if not (CLIENT / "package.json").is_file():
        pytest.skip("no client checkout next to this one")

    assert "client: Cargo.lock" in _versions().stdout, (
        "The client checkout is there but the check did not look at it — "
        "so a client-only mismatch would go unnoticed."
    )
