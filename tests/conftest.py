"""Shared fixtures.

`toon_binary` provides the Rust TOON serializer, building it on first use via
scripts/build_toon_rs.sh when `rustc` is available (GitHub's ubuntu runners
ship it). Where rustc is genuinely absent, binary-dependent tests skip — the
serializer is the only compiled artifact in an otherwise Python-tested repo.

Under `pytest-xdist` the build has already happened on the controller (see the
repository-root `conftest.py`, which owns execution policy), so the branch below
is the serial path and the no-rustc path only.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOON_BIN = REPO_ROOT / "rust" / "toon" / "bin" / "graph_to_toon"


@pytest.fixture(scope="session")
def toon_binary() -> Path:
    if not TOON_BIN.is_file():
        if shutil.which("rustc") is None:
            pytest.skip("rustc unavailable and Rust TOON binary not built")
        build = subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "build_toon_rs.sh")],
            capture_output=True, text=True, timeout=300,
        )
        if build.returncode != 0:
            pytest.fail(f"build_toon_rs.sh failed:\n{build.stderr}")
    return TOON_BIN
