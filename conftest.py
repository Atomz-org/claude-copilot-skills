"""Test-worker assignment and controller-side setup.

Turning parallelism *on* lives in `_pytest_parallel.py`, which `pytest.ini` loads
with `-p`; that hook has to run before conftests exist. What lives here is the
part that needs the collected tests: which worker each one may run on. Fixtures
live in `tests/conftest.py`.

This suite is dominated by subprocess spawns — nearly every test shells out to a
script in `scripts/`, so it spends most of its wall time waiting rather than
computing. Measured on a 10-core machine: 97s at 70% CPU, a third of the machine
idle.

Distribution is `loadgroup`, with every test assigned a group named after its own
file. That reproduces `loadfile`'s guarantee — a file's tests stay on one worker,
in order, so module-scoped fixtures build once and any intra-file ordering the
suite was written under still holds — while allowing the one exception below.

The exception: `_SHARED_REAL_TREE` share a single group
--------------------------------------------------------
Three files drive the *committed* enhanza-analytics tree rather than a `tmp_path`
copy. Two of them append a probe comment to a real `.sql`, run the rebuild hook,
assert the artifact went current again, and restore the file in a `finally`:

    tests/test_dbt_column_memory.py::test_the_hook_rebuilds_the_store_...
    tests/test_dbt_column_memory_watch.py::test_the_hook_rebuilds_the_store_...

Those are two different files defining the same end-to-end claim, so plain
`loadfile` puts them on two workers and they mutate one `.sql` and one
`column-memory.json` concurrently. Measured: 2 failures, reproducibly.
`tests/test_use_case_sync.py` joins them because its `columns` stage runs
`--check` against that same artifact and would observe the mutation window.

Merging the three into one group serialises exactly the tests that share global
state and nothing else. It costs no wall time: their combined runtime is ~16s,
below the ~23s of `tests/test_dbt_sample_build.py`, which bounds the run anyway.

This is a property of the suite, not of xdist — those tests were always
order-dependent, and running serially was hiding it.

Escape hatches, in precedence order: an explicit `-n`/`--numprocesses`/`--dist` on
the command line wins, `-p no:xdist` disables the plugin outright, and
`CODE_SKILLS_NO_XDIST=1` forces serial execution for bisecting a flake or reading
un-interleaved output.
"""
from __future__ import annotations


import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent
TOON_BIN = REPO_ROOT / "rust" / "toon" / "bin" / "graph_to_toon"

#: Files that read or write the committed enhanza-analytics tree rather than a
#: tmp_path copy. They must land on one worker; see the module docstring.
_SHARED_REAL_TREE = frozenset({
    "test_dbt_column_memory.py",
    "test_dbt_column_memory_watch.py",
    "test_use_case_sync.py",
})

_SHARED_GROUP = "enhanza_committed_tree"


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items) -> None:
    """Assign every test an xdist group: its filename, or the shared-tree group.

    Done here rather than as a `pytestmark` in each test module so that adding a
    test to one of the `_SHARED_REAL_TREE` files inherits the constraint instead
    of relying on someone remembering the marker. A no-op without xdist, since
    nothing else reads the marker.

    `tryfirst` is load-bearing. xdist reads the `xdist_group` marker in its *own*
    `pytest_collection_modifyitems` and encodes it as an `@group` suffix on the
    nodeid, which is what the scheduler actually groups by. A marker added after
    that hook has run is never seen: measured, every file was spread across all
    ten workers and the shared-tree tests still collided.
    """
    for item in items:
        filename = Path(str(getattr(item, "path", "") or getattr(item, "fspath", ""))).name
        group = _SHARED_GROUP if filename in _SHARED_REAL_TREE else filename
        item.add_marker(pytest.mark.xdist_group(group))


def pytest_configure(config) -> None:
    """Register the group marker, then build the TOON serializer on the controller.

    The marker is declared unconditionally because the grouping hook above applies
    it unconditionally: with `-p no:xdist`, or on a machine without xdist at all,
    nothing would otherwise own the name and every test raises an unknown-mark
    warning. Registering it twice when xdist *is* loaded is harmless.

    Building the serializer here rather than in the `toon_binary` fixture keeps ten
    workers from discovering it missing at the same instant and running
    `build_toon_rs.sh` concurrently into one output path. This is single-threaded by
    construction. Failure is swallowed on purpose: the fixture is what decides
    between skip and fail, and it still runs.
    """
    config.addinivalue_line(
        "markers",
        "xdist_group(name): assign a test to an xdist worker group; applied "
        "automatically per file by conftest.pytest_collection_modifyitems",
    )
    _build_toon_binary(config)


def _build_toon_binary(config) -> None:
    """Build the serializer on the controller only; see `pytest_configure`."""
    if hasattr(config, "workerinput"):
        return  # an xdist worker; the controller has already done this
    if TOON_BIN.is_file() or shutil.which("rustc") is None:
        return
    try:
        subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "build_toon_rs.sh")],
            capture_output=True, text=True, timeout=300, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass
