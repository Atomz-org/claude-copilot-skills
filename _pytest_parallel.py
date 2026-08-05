"""Opt-in-by-availability parallel execution, loaded as a pytest plugin.

Why a plugin module and not `conftest.py`
-----------------------------------------
`pytest_load_initial_conftests` is the only hook early enough to add `-n` before
xdist reads its options, and pytest fires it *while* loading the initial
conftests — so a conftest implementing it registers after its own call has
already been made. Measured: the suite stayed at 97s with the hook in a rootdir
`conftest.py`, silently, with nothing in the output to explain it.

A plugin named in `pytest.ini`'s `addopts` via `-p` is registered during preparse,
before conftest loading, so its hook does fire. `pytest.ini` therefore carries
`-p _pytest_parallel` and never `-n auto` — naming the plugin is safe whether or
not `pytest-xdist` is installed, while a bare `-n auto` would make `pytest` fail
with "unrecognized arguments" wherever it is not.

That keeps the property `tests/test_wren_context_sync.py` pins: bare
`python -m pytest -q`, which all six CI call sites run, works on any machine —
serially where xdist is absent, across cores where it is present.
"""
from __future__ import annotations

import os
from typing import List


def _distribution_already_chosen(args: List[str]) -> bool:
    """True when the caller already decided how the run is distributed."""
    for arg in args:
        if arg.startswith("-n") or arg.startswith("--numprocesses"):
            return True
        if arg.startswith("--dist") or arg == "no:xdist":
            return True
    return False


def pytest_load_initial_conftests(early_config, parser, args: List[str]) -> None:
    """Spread the suite over the machine's cores when xdist happens to be installed.

    `loadgroup` rather than `loadfile` because the repository-root `conftest.py`
    merges three files that share the committed enhanza-analytics tree into one
    group; see its docstring for why they cannot run on separate workers.
    """
    if os.environ.get("CODE_SKILLS_NO_XDIST"):
        return
    if _distribution_already_chosen(args):
        return
    try:  # optional accelerator — absence is a supported configuration
        import xdist  # noqa: F401
    except ImportError:
        return
    args[:] = ["-n", "auto", "--dist", "loadgroup", *args]
