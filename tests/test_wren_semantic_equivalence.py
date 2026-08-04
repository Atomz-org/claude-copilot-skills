"""The equivalence gate: every compiled metric view returns its definition's numbers.

For each MetricFlow metric in example-order-revenue-mart, this compares the governed
result (`wren query` over the compiled MDL view) against **hand-written oracle SQL**
run directly on the same DuckDB file. The oracles restate each metric's definition
independently of the compiler — sharing the compiler's SQL would prove nothing — and
they are definition-faithful, not intuition-faithful: `revenue_trailing_28d` declares
no filter in dbt, so its oracle includes cancelled orders, deliberately.

Scope is honest (wren rule 7): the gate runs where the wren CLI, the wren venv's
duckdb, and the committed views exist — a laptop after `--stage wren`, not a bare CI
runner. Presence of the views is `test_committed_wren_project_is_current`'s job; this
gate owns the numbers. A metric that drifts from its view fails here instead of
surfacing as two dashboards disagreeing.
"""

from __future__ import annotations

import json
import subprocess
import sys
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
# The oracle runs through the interpreter co-located with the wren CLI: its venv
# carries duckdb via the wrenai dependency, and the test venv need not.
ORACLE_PY = Path(WREN_CLI).parent / "python" if WREN_CLI else None

pytestmark = [
    pytest.mark.skipif(WREN_CLI is None, reason="wren CLI not installed"),
    pytest.mark.skipif(
        not (WREN_DIR / "views").is_dir(),
        reason="no compiled views committed — run use_case_sync.py --stage wren",
    ),
    pytest.mark.skipif(not DUCKDB_FILE.exists(), reason="no dev.duckdb; run the demo"),
]


@pytest.fixture(scope="module")
def mdl(tmp_path_factory) -> Path:
    """Build the committed project once; target/ is derived state (wren rule 3)."""
    proc = subprocess.run(
        [str(WREN_CLI), "context", "build", "--path", str(WREN_DIR)],
        capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, f"wren context build failed: {proc.stderr or proc.stdout}"
    return WREN_DIR / "target/mdl.json"


def _wren_rows(mdl: Path, sql: str) -> list[dict]:
    conn = json.dumps({"datasource": "duckdb", "url": str(DBT_DIR), "format": "duckdb"})
    proc = subprocess.run(
        [str(WREN_CLI), "query", "--sql", sql, "--mdl", str(mdl),
         "--connection-info", conn, "-o", "json", "-q"],
        capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, f"wren query failed: {proc.stderr or proc.stdout}"
    # `wren query -o json` emits JSON Lines — one object per row.
    return [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip()]


def _oracle_rows(sql: str) -> list[dict]:
    if ORACLE_PY is None or not ORACLE_PY.exists():
        pytest.skip("no interpreter beside the wren CLI for the duckdb oracle")
    script = (
        "import duckdb, json, sys\n"
        f"c = duckdb.connect({str(DUCKDB_FILE)!r}, read_only=True)\n"
        f"r = c.sql({sql!r})\n"
        "for row in r.fetchall():\n"
        "    print(json.dumps(dict(zip([d[0] for d in r.description], row)), default=str))\n"
    )
    proc = subprocess.run(
        [str(ORACLE_PY), "-c", script], capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0 and "duckdb" in (proc.stderr or ""):
        pytest.skip(f"duckdb unavailable beside the wren CLI: {proc.stderr.strip()[:120]}")
    assert proc.returncode == 0, f"oracle failed: {proc.stderr}"
    return [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip()]


def _series(rows: list[dict], key: str, value: str) -> list[tuple]:
    """Normalize to sorted (key, value-as-float-or-None) pairs.

    wren emits timestamps as epoch ms and decimals as strings; the oracle emits
    stringified datetimes. Both sides round-trip through this before comparing.
    """
    out = []
    for r in rows:
        v = r[value]
        out.append((str(r[key]), None if v is None else round(float(v), 4)))
    return sorted(out)


# Oracle SQL restates each definition; epoch_ms() normalizes the time key to what
# the engine emits, so the comparison needs no datetime parsing.
_T = "epoch_ms(mt) AS metric_time"

ORACLES = {
    "revenue": f"""
        WITH base AS (
          SELECT date_trunc('day', ordered_at) mt, SUM(order_amount_usd) v
          FROM marts.fct_orders WHERE order_status <> 'cancelled' GROUP BY 1),
        spine AS (
          SELECT DISTINCT date_trunc('day', CAST(date_day AS TIMESTAMP)) mt
          FROM marts.metricflow_time_spine)
        SELECT {_T}, ROUND(COALESCE(base.v, 0), 4) AS revenue
        FROM spine LEFT JOIN base USING (mt)
        WHERE mt BETWEEN (SELECT MIN(mt) FROM base) AND (SELECT MAX(mt) FROM base)""",
    "order_count": f"""
        SELECT {_T}, ROUND(COUNT(order_id), 4) AS order_count FROM (
          SELECT date_trunc('day', ordered_at) mt, order_id
          FROM marts.fct_orders WHERE order_status <> 'cancelled') GROUP BY mt""",
    "average_order_value": f"""
        WITH r AS (SELECT date_trunc('day', ordered_at) mt, SUM(order_amount_usd) v
                   FROM marts.fct_orders WHERE order_status <> 'cancelled' GROUP BY 1),
             n AS (SELECT date_trunc('day', ordered_at) mt, COUNT(order_id) v
                   FROM marts.fct_orders WHERE order_status <> 'cancelled' GROUP BY 1)
        SELECT {_T}, ROUND(COALESCE(r.v, 0) / NULLIF(n.v, 0), 4) AS average_order_value
        FROM n LEFT JOIN r USING (mt)""",
    "emea_revenue_share": f"""
        -- Guests: numerator joins customers, denominator does not (per the metric).
        WITH num AS (SELECT date_trunc('day', o.ordered_at) mt, SUM(o.order_amount_usd) v
                     FROM marts.fct_orders o
                     JOIN marts.dim_customers c USING (customer_id)
                     WHERE o.order_status <> 'cancelled' AND c.region = 'EMEA' GROUP BY 1),
             den AS (SELECT date_trunc('day', ordered_at) mt, SUM(order_amount_usd) v
                     FROM marts.fct_orders WHERE order_status <> 'cancelled' GROUP BY 1)
        SELECT {_T}, ROUND(COALESCE(num.v, 0) / NULLIF(den.v, 0), 4) AS emea_revenue_share
        FROM den LEFT JOIN num USING (mt)""",
    "revenue_growth_mom": f"""
        WITH m AS (SELECT date_trunc('month', ordered_at) mt, SUM(order_amount_usd) v
                   FROM marts.fct_orders WHERE order_status <> 'cancelled' GROUP BY 1)
        SELECT {_T}, ROUND((v - LAG(v) OVER (ORDER BY mt)) * 100.0
                           / NULLIF(LAG(v) OVER (ORDER BY mt), 0), 4) AS revenue_growth_mom
        FROM m""",
    "revenue_trailing_28d": f"""
        -- The dbt metric declares NO filter: trailing gross, cancelled included.
        -- The series runs over every spine day in the observed range, not only days
        -- with orders — a rolling window is defined on the calendar.
        WITH d AS (SELECT date_trunc('day', ordered_at) mt, SUM(order_amount_usd) v
                   FROM marts.fct_orders GROUP BY 1),
             s AS (SELECT DISTINCT CAST(date_day AS TIMESTAMP) mt
                   FROM marts.metricflow_time_spine
                   WHERE CAST(date_day AS TIMESTAMP)
                         BETWEEN (SELECT MIN(mt) FROM d) AND (SELECT MAX(mt) FROM d))
        SELECT {_T}, ROUND((SELECT SUM(v) FROM d
                            WHERE d.mt > s.mt - INTERVAL 28 DAY AND d.mt <= s.mt), 4)
               AS revenue_trailing_28d
        FROM s""",
    "revenue_mtd": f"""
        WITH d AS (SELECT date_trunc('day', ordered_at) mt, SUM(order_amount_usd) v
                   FROM marts.fct_orders GROUP BY 1),
             s AS (SELECT DISTINCT CAST(date_day AS TIMESTAMP) mt
                   FROM marts.metricflow_time_spine
                   WHERE CAST(date_day AS TIMESTAMP)
                         BETWEEN (SELECT MIN(mt) FROM d) AND (SELECT MAX(mt) FROM d))
        SELECT {_T}, ROUND((SELECT SUM(v) FROM d
                            WHERE d.mt >= date_trunc('month', s.mt) AND d.mt <= s.mt), 4)
               AS revenue_mtd
        FROM s""",
}


@pytest.mark.parametrize("metric", sorted(ORACLES))
def test_view_equals_definition(mdl: Path, metric: str) -> None:
    governed = _wren_rows(
        mdl, f"SELECT metric_time, ROUND(CAST({metric} AS DOUBLE), 4) AS {metric} "
             f"FROM {metric}"
    )
    oracle = _oracle_rows(ORACLES[metric])
    assert _series(governed, "metric_time", metric) == _series(oracle, "metric_time", metric), (
        f"'{metric}' through the semantic layer disagrees with its own definition"
    )


def test_saved_query_view_equals_definition(mdl: Path) -> None:
    governed = _wren_rows(
        mdl, "SELECT metric_time, region, ROUND(CAST(revenue AS DOUBLE), 4) AS revenue, "
             "ROUND(CAST(order_count AS DOUBLE), 4) AS order_count "
             "FROM weekly_revenue_by_region"
    )
    oracle = _oracle_rows(f"""
        SELECT epoch_ms(mt) AS metric_time, region,
               ROUND(rev, 4) AS revenue, ROUND(n, 4) AS order_count
        FROM (SELECT date_trunc('week', o.ordered_at) mt, c.region,
                     SUM(o.order_amount_usd) rev, COUNT(o.order_id) n
              FROM marts.fct_orders o JOIN marts.dim_customers c USING (customer_id)
              WHERE o.order_status <> 'cancelled' AND c.region IS NOT NULL
              GROUP BY 1, 2)""")
    key = lambda r: (str(r["metric_time"]), str(r["region"]))  # noqa: E731
    gov = sorted((key(r), round(float(r["revenue"]), 4), round(float(r["order_count"]), 4))
                 for r in governed)
    ora = sorted((key(r), round(float(r["revenue"]), 4), round(float(r["order_count"]), 4))
                 for r in oracle)
    assert gov == ora
