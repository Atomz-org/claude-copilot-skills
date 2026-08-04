"""A failed graph rebuild must never leave the repository without a graph.

What happened, and what this pins: `make init` was `init: clean build`, where
`clean` is `rm -rf graphify-out`. The graph was deleted before anything checked
that a rebuild could succeed. It could not -- `graphify .` needs an LLM API key
for this repository's doc files and exits 1 without one -- so the run ended with
no graph, no report, and nothing to roll back to.

Every test here drives the real scripts/graphify_rebuild.sh against a fake
repository with a stub `graphify` on PATH, so no LLM call and no real build is
involved.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REBUILD = REPO_ROOT / "scripts" / "graphify_rebuild.sh"
MAKEFILE = REPO_ROOT / "scripts" / "Makefile"

LLM_KEYS = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "MOONSHOT_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
)

SENTINEL = {
    "nodes": [{"id": f"n{i}"} for i in range(200)],
    "edges": [{"source": "n0", "target": "n1"}],
}


def make_stub(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def sandbox(tmp_path: Path) -> dict:
    """A miniature repo: an existing graph, a stub graphify, a stub sync script."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "graphify-out" / "cache").mkdir(parents=True)

    (root / "graphify-out" / "graph.json").write_text(json.dumps(SENTINEL), encoding="utf-8")
    (root / "graphify-out" / "GRAPH_REPORT.md").write_text("# old report\n", encoding="utf-8")
    (root / "graphify-out" / "cache" / "warm.bin").write_text("cached", encoding="utf-8")

    shutil.copy(REBUILD, root / "scripts" / "graphify_rebuild.sh")
    (root / "scripts" / "graphify_rebuild.sh").chmod(0o755)

    # the sync step: writes nothing, it only has to succeed
    make_stub(root / "scripts" / "use_case_sync.py", "#!/usr/bin/env python3\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    return {"root": root, "bin": bin_dir}


def run_rebuild(sandbox: dict, *args: str, key: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    for k in LLM_KEYS:
        env.pop(k, None)
    if key:
        env["GEMINI_API_KEY"] = "test-key-not-used"
    env["PATH"] = f"{sandbox['bin']}{os.pathsep}{env['PATH']}"
    env["PYTHON"] = "python3"
    return subprocess.run(
        ["bash", str(sandbox["root"] / "scripts" / "graphify_rebuild.sh"), *args],
        cwd=str(sandbox["root"]),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def graph_of(sandbox: dict) -> dict | None:
    p = sandbox["root"] / "graphify-out" / "graph.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def write_graph_stub(sandbox: dict, payload: dict) -> None:
    make_stub(
        sandbox["bin"] / "graphify",
        "#!/bin/sh\ncat > graphify-out/graph.json <<'EOF'\n"
        + json.dumps(payload)
        + "\nEOF\n",
    )


# --------------------------------------------------------------------------
# the regression: a failing build must not cost you the graph
# --------------------------------------------------------------------------


def test_failed_build_restores_the_previous_graph(sandbox: dict) -> None:
    make_stub(sandbox["bin"] / "graphify", "#!/bin/sh\necho 'boom' >&2\nexit 1\n")

    result = run_rebuild(sandbox)

    assert result.returncode != 0
    assert graph_of(sandbox) == SENTINEL, "the previous graph was not restored"
    assert (sandbox["root"] / "graphify-out" / "GRAPH_REPORT.md").is_file()
    assert not (sandbox["root"] / ".graphify-out.prev").exists(), "left a stray backup dir"


def test_missing_llm_key_changes_nothing_at_all(sandbox: dict) -> None:
    """The exact failure that started this: refuse in preflight, touch nothing."""
    make_stub(sandbox["bin"] / "graphify", "#!/bin/sh\nexit 0\n")

    result = run_rebuild(sandbox, key=False)

    assert result.returncode != 0
    assert b"no LLM API key" in result.stderr
    assert graph_of(sandbox) == SENTINEL
    assert not (sandbox["root"] / ".graphify-out.prev").exists()


def test_code_only_needs_no_key(sandbox: dict) -> None:
    write_graph_stub(sandbox, SENTINEL)

    result = run_rebuild(sandbox, "--code-only", key=False)

    assert result.returncode == 0, result.stderr.decode()


def test_empty_result_is_rejected_and_rolled_back(sandbox: dict) -> None:
    """Exiting 0 is not success. A graph that came out empty must not be kept."""
    make_stub(
        sandbox["bin"] / "graphify",
        '#!/bin/sh\necho \'{"nodes":[],"edges":[]}\' > graphify-out/graph.json\n',
    )

    result = run_rebuild(sandbox)

    assert result.returncode != 0
    assert b"looks empty" in result.stdout + result.stderr
    assert graph_of(sandbox) == SENTINEL


def test_successful_rebuild_replaces_the_graph_and_cleans_up(sandbox: dict) -> None:
    fresh = {
        "nodes": [{"id": f"m{i}"} for i in range(300)],
        "edges": [{"source": "m0", "target": "m1"}],
    }
    write_graph_stub(sandbox, fresh)

    result = run_rebuild(sandbox)

    assert result.returncode == 0, result.stderr.decode()
    assert graph_of(sandbox) == fresh
    assert not (sandbox["root"] / ".graphify-out.prev").exists()


def test_semantic_cache_survives_a_rebuild(sandbox: dict) -> None:
    """A labeled build cost ~1.3M input tokens; re-paying for unchanged files is waste."""
    write_graph_stub(sandbox, SENTINEL)

    assert run_rebuild(sandbox).returncode == 0
    assert (sandbox["root"] / "graphify-out" / "cache" / "warm.bin").is_file()


def test_cold_discards_the_cache(sandbox: dict) -> None:
    write_graph_stub(sandbox, SENTINEL)

    assert run_rebuild(sandbox, "--cold").returncode == 0
    assert not (sandbox["root"] / "graphify-out" / "cache" / "warm.bin").exists()


# --------------------------------------------------------------------------
# the ordering rule the whole repository depends on
# --------------------------------------------------------------------------


def test_rebuild_runs_before_the_dbt_merge() -> None:
    """graphify has no SQL parser: a rebuild after a merge deletes the dbt DAG."""
    text = REBUILD.read_text(encoding="utf-8")

    build_at = text.index('"$GRAPHIFY" .')
    merge_at = text.index('"$SYNC_SCRIPT" --use-case')

    assert build_at < merge_at, "the code-graph rebuild must precede the dbt merge"


def test_makefile_init_no_longer_depends_on_clean() -> None:
    """`init: clean build` is what destroyed the graph up front."""
    text = MAKEFILE.read_text(encoding="utf-8")

    assert "init: clean build" not in text
    assert "init: build" in text
    assert "graphify_rebuild.sh" in text


def test_clean_target_still_exists() -> None:
    """Deleting the graph on purpose stays available -- it just is not `init`."""
    assert "\nclean:" in MAKEFILE.read_text(encoding="utf-8")
