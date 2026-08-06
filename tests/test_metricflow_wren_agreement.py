"""MetricFlow's query engine and Wren's compiled view must produce the same numbers.

The stack gives MetricFlow two of its three hats — definition language and
validator — and hands the third, the query engine in the serving path, to Wren:
`build_metric_views()` freezes each metric into a static MDL view at sync time.
That is a re-implementation of MetricFlow's SQL generation for the supported
subset, and a re-implementation drifts silently unless something holds the two
engines to the same rows.

`test_wren_semantic_equivalence.py` already holds the wren view to a hand-written
oracle. This file closes the triangle: the *actual MetricFlow engine* (`mf query`)
against the *actual wren view*, on the same DuckDB warehouse, for the same metric.
First measured 2026-08-06: both produce 277,183.41 — the filtered metric, not the
289,470.66 raw measure — with every overlapping day identical.

One shape difference is expected and asserted rather than papered over: with
`join_to_timespine` + `fill_nulls_with: 0`, mf emits the FULL spine (thousands of
zero rows into the future), while the wren view bounds the fill to the observed
data range. Totals must agree exactly; mf's rows outside wren's range must all be
zero. A non-zero row out there would mean the two engines disagree about what the
fill policy covers.

Skips, never fails, where the toolchain is absent (mf, wren, or the demo-built
dev.duckdb) — the same honest scope as the oracle test: a laptop after the demo,
not bare CI.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import wren_context_sync as wcs  # noqa: E402

UC = REPO / "skill-packs/dbt-skills/use-cases/example-order-revenue-mart"
WREN_DIR = UC / "wren"
DBT_DIR = UC / "dbt_project"
DUCKDB_FILE = DBT_DIR / "dev.duckdb"

WREN_CLI = wcs.find_wren_cli()


def find_mf_cli() -> Path | None:
    """MF_BIN env → the repo's dbt venv → PATH. Mirrors find_wren_cli's ladder."""
    env = os.environ.get("MF_BIN")
    if env and Path(env).exists():
        return Path(env)
    venv_mf = REPO / ".venv-dbt" / "bin" / "mf"
    if venv_mf.exists():
        return venv_mf
    which = shutil.which("mf")
    return Path(which) if which else None


MF_CLI = find_mf_cli()

pytestmark = [
    pytest.mark.skipif(MF_CLI is None, reason="mf CLI not installed — "
                       'pip install "dbt-metricflow[dbt-duckdb]" into the dbt venv'),
    pytest.mark.skipif(WREN_CLI is None, reason="wren CLI not installed"),
    pytest.mark.skipif(
        not (WREN_DIR / "views").is_dir(),
        reason="no compiled views committed — run use_case_sync.py --stage wren",
    ),
    pytest.mark.skipif(not DUCKDB_FILE.exists(), reason="no dev.duckdb; run the demo"),
]

MF_ENV = {**os.environ, "DBT_PROFILES_DIR": "."}


def mf_series(metric: str, tmp_path: Path) -> dict[str, float]:
    """One metric through the real MetricFlow engine, keyed by ISO day."""
    out = tmp_path / f"mf_{metric}.csv"
    proc = subprocess.run(
        [str(MF_CLI), "query", "--metrics", metric,
         "--group-by", "metric_time", "--order", "metric_time", "--csv", str(out)],
        cwd=DBT_DIR, env=MF_ENV, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, f"mf query failed: {proc.stderr or proc.stdout}"
    rows = list(csv.reader(out.open()))[1:]
    return {r[0][:10]: round(float(r[1]), 4) for r in rows if r[1]}


@pytest.fixture(scope="module")
def mdl() -> Path:
    proc = subprocess.run(
        [str(WREN_CLI), "context", "build", "--path", str(WREN_DIR)],
        capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, f"wren context build failed: {proc.stderr or proc.stdout}"
    return WREN_DIR / "target" / "mdl.json"


def wren_series(metric: str, mdl_path: Path) -> dict[str, float]:
    """The same metric through the wren engine's compiled view."""
    conn = json.dumps({"datasource": "duckdb", "url": str(DBT_DIR), "format": "duckdb"})
    proc = subprocess.run(
        [str(WREN_CLI), "query",
         "--sql", f"SELECT metric_time, {metric} FROM {metric} ORDER BY metric_time",
         "--mdl", str(mdl_path), "--connection-info", conn, "-o", "json"],
        capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, f"wren query failed: {proc.stderr or proc.stdout}"
    series: dict[str, float] = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        row = json.loads(line)  # epoch-ms keys, stringified decimals
        day = datetime.fromtimestamp(
            row["metric_time"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        series[day] = round(float(row[metric]), 4)
    assert series, "wren returned no rows"
    return series


def test_mf_validate_configs_is_clean() -> None:
    """Rule 45's gate, now runnable on dbt Core: manifest semantics AND live
    warehouse validation of every semantic model, dimension, entity, and metric."""
    proc = subprocess.run(
        [str(MF_CLI), "validate-configs"],
        cwd=DBT_DIR, env=MF_ENV, capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "ERRORS: 0" in proc.stdout.replace("\x08", "")


def test_the_two_engines_agree_on_revenue(mdl: Path, tmp_path: Path) -> None:
    """The triangle's third side: mf query ≡ the compiled view, row for row on
    the observed range, zero-fill only outside it, totals equal to the cent."""
    mf = mf_series("revenue", tmp_path)
    wren = wren_series("revenue", mdl)

    mismatched = {d: (wren[d], mf.get(d)) for d in wren if mf.get(d) != wren[d]}
    assert not mismatched, f"per-day disagreement: {dict(list(mismatched.items())[:5])}"

    nonzero_outside = {d: v for d, v in mf.items() if d not in wren and v != 0.0}
    assert not nonzero_outside, (
        f"mf has revenue outside the view's fill range: {nonzero_outside}"
    )

    assert round(sum(wren.values()), 2) == round(sum(mf.values()), 2)


def test_the_two_engines_agree_on_a_ratio(mdl: Path, tmp_path: Path) -> None:
    """Ratios exercise a different compilation path (two legs, IS NOT DISTINCT
    FROM join) — agreement on a simple metric does not imply it here."""
    mf = mf_series("average_order_value", tmp_path)
    wren = wren_series("average_order_value", mdl)
    shared = set(mf) & set(wren)
    assert shared, "no overlapping days between the two engines"
    mismatched = {d: (wren[d], mf[d]) for d in shared if abs(wren[d] - mf[d]) > 0.0001}
    assert not mismatched, f"per-day disagreement: {dict(list(mismatched.items())[:5])}"
