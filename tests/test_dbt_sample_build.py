"""Tests for the sample build runner — the executable proof of the union contract.

The alignment checker proves the adapters' column *sets* match; dbt parse proves the refs
resolve. Neither ever runs the UNION. This runner does, on DuckDB, from the sample seeds,
with sqlglot owning the BigQuery→DuckDB boundary — and the integration test here is the
"tested with a sample use-case" guarantee in CI form.

Two properties beyond "it passes":

1. **Per-source accounting.** 36 rows would also be produced by one connector unioned three
   times. The runner groups by DataSource and requires every enabled connector present; the
   test pins that the check exists and fires.
2. **Toolchain absence is a skip, not a failure.** dbt, duckdb, and sqlglot are all
   optional here; a runner (CI-lite, a laptop without the venv) must see exit 3, never red.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import dbt_sample_build as runner  # noqa: E402

SCRIPT = REPO / "scripts/dbt_sample_build.py"
PROJECT = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project"

toolchain = all([runner.find_dbt(), runner.sqlglot, runner.duckdb])
needs_toolchain = pytest.mark.skipif(
    not toolchain, reason="sample build needs dbt + duckdb + sqlglot"
)
needs_seeds = pytest.mark.skipif(
    not (PROJECT / "seeds/sample").exists() or not any((PROJECT / "seeds/sample").glob("*.csv")),
    reason="sample seeds not generated in this checkout",
)


def test_missing_toolchain_is_exit_3(monkeypatch) -> None:
    """The skill-map rule: unavailable is not failed."""
    monkeypatch.setattr(runner, "find_dbt", lambda: None)
    assert runner.main(["--use-case", "enhanza-analytics"]) == 3


@needs_toolchain
@needs_seeds
def test_the_sample_union_builds_and_every_connector_contributes() -> None:
    """End to end: seeds -> staging -> adapters -> positional UNION -> tests, on DuckDB.

    This is the sample use-case test the seeds README documents, run exactly as a user
    would run it. dim_articles is chosen because it is the union the alignment checker
    once caught broken (isActive vs Active) — the regression this guards is real.
    """
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--format", "json"],
        capture_output=True, text=True, timeout=900, cwd=REPO,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["test_failures"] == []

    by_source = payload["union_rows_by_source"]
    assert len(by_source) == 3, f"a connector contributed nothing: {by_source}"
    assert all(n == 12 for n in by_source.values()), by_source

    # The artifact isolation that keeps this run from poisoning the canonical manifest.
    assert runner.TARGET_PATH != "target"


@needs_toolchain
@needs_seeds
def test_a_missing_connector_in_the_union_fails_the_run() -> None:
    """12 x 3 rows from one connector must not pass as three connectors.

    Enabling a connector that supplies dim_articles through a JSON-heavy path (fortnox)
    cannot work from placeholder seeds — the run must say so, not report a smaller union
    as success.
    """
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--connectors", "seventime,visma_eaccounting,fortnox",
         "--format", "json"],
        capture_output=True, text=True, timeout=900, cwd=REPO,
    )
    assert proc.returncode == 1, "a degraded union must fail loudly"
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
