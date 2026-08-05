#!/usr/bin/env bash
# End-to-end WrenAI demo over this repository's own use-case, entirely local:
#
#   dbt build (DuckDB)  ->  wren stage (native import + ontology/metric enrichment)
#   ->  wren context build (MDL)  ->  governed `wren query`  ->  cross-check vs DuckDB
#   ->  metric view == MetricFlow definition
#
# No Docker, no warehouse, no LLM key. Two pass criteria, both exact:
#   - the governed join query equals the same aggregation run directly on DuckDB
#   - `SELECT sum(revenue) FROM revenue` — the compiled metric VIEW — equals the
#     MetricFlow definition (filtered), not the raw measure. This is the number the
#     cubes used to get wrong by 4.4%.
set -euo pipefail

root="$(cd "$(dirname "$0")/../../.." && pwd)"
uc="skill-packs/dbt-skills/use-cases/example-order-revenue-mart"
dbt_project="${root}/${uc}/dbt_project"

step() { printf '\n== %s\n' "$1"; }

step "0/6 toolchain"
dbt="${root}/.venv-dbt/bin/dbt"
if [[ ! -x "${dbt}" ]]; then
  dbt="$(command -v dbt || true)"
  [[ -n "${dbt}" ]] || { echo "no dbt: create .venv-dbt with dbt-core + dbt-duckdb" >&2; exit 1; }
fi
wren="${WREN_CLI:-${root}/.venv-wren/bin/wren}"
if [[ ! -x "${wren}" ]]; then
  echo "no wren CLI at ${wren} — creating .venv-wren from requirements.txt"
  python3 -m venv "${root}/.venv-wren"
  "${root}/.venv-wren/bin/pip" install --quiet -r "${root}/requirements.txt"
  wren="${root}/.venv-wren/bin/wren"
fi
echo "dbt:  ${dbt}"
echo "wren: ${wren} ($("${wren}" --version))"

step "1/6 dbt build + catalog (DuckDB, local)"
(cd "${dbt_project}" && "${dbt}" build --quiet && "${dbt}" docs generate --quiet)
echo "built $(ls "${dbt_project}"/dev.duckdb)"

step "2/6 regenerate the wren/ project (import + enrichment, validate, build)"
WREN_CLI="${wren}" python3 "${root}/scripts/use_case_sync.py" \
  --use-case example-order-revenue-mart --stage wren

step "3/6 compile MDL"
"${wren}" context build --path "${root}/${uc}/wren"

step "4/6 governed query through the semantic layer"
conn="{\"datasource\":\"duckdb\",\"url\":\"${dbt_project}\",\"format\":\"duckdb\"}"
sql="select c.region, count(*) as orders, round(sum(o.order_amount_usd),2) as revenue
     from fct_orders o join dim_customers c on o.customer_id = c.customer_id
     group by 1 order by revenue desc"
governed="$("${wren}" query --sql "${sql}" \
  --mdl "${root}/${uc}/wren/target/mdl.json" --connection-info "${conn}" -o json -q)"
echo "${governed}"

step "5/6 cross-check against DuckDB directly"
# Use the interpreter co-located with the resolved CLI: its venv carries duckdb via the
# wrenai dependency, and this keeps a WREN_CLI override working end to end.
py="$(dirname "${wren}")/python"
[[ -x "${py}" ]] || py=python3
GOVERNED="${governed}" DEMO_DB="${dbt_project}/dev.duckdb" "${py}" - <<'EOF'
import json, os, sys
import duckdb

# `wren query -o json` emits JSON Lines: one object per row.
rows = [json.loads(ln) for ln in os.environ["GOVERNED"].splitlines() if ln.strip()]
norm_governed = [tuple(r.values()) for r in rows]

con = duckdb.connect(os.environ["DEMO_DB"], read_only=True)
direct = con.execute(
    "select c.region, count(*) as orders, round(sum(o.order_amount_usd),2) as revenue "
    "from marts.fct_orders o join marts.dim_customers c on o.customer_id = c.customer_id "
    "group by 1 order by revenue desc"
).fetchall()
norm_direct = [(r[0], int(r[1]), float(r[2])) for r in direct]
norm_governed = [(r[0], int(r[1]), float(r[2])) for r in norm_governed]

if norm_governed == norm_direct:
    print(f"PASS: governed == direct, {len(norm_direct)} rows: {norm_direct}")
else:
    print(f"FAIL:\n  governed: {norm_governed}\n  direct:   {norm_direct}")
    sys.exit(1)
EOF

step "6/6 the metric view IS the metric"
# The cubes this replaced projected the raw measure — sum(order_amount_usd) with the
# metric's filter dropped, 4.4% high and internally consistent. The compiled view
# carries the whole MetricFlow definition, so the governed number below must equal the
# *filtered* oracle, and must NOT equal the unfiltered measure.
metric="$("${wren}" query --sql "select round(sum(revenue),2) as v from revenue" \
  --mdl "${root}/${uc}/wren/target/mdl.json" --connection-info "${conn}" -o json -q)"
METRIC="${metric}" DEMO_DB="${dbt_project}/dev.duckdb" "${py}" - <<'EOF'
import json, os, sys
import duckdb

governed = float(json.loads(os.environ["METRIC"].splitlines()[0])["v"])
con = duckdb.connect(os.environ["DEMO_DB"], read_only=True)
oracle = float(con.execute(
    "select round(sum(order_amount_usd),2) from marts.fct_orders "
    "where order_status <> 'cancelled'").fetchone()[0])
measure = float(con.execute(
    "select round(sum(order_amount_usd),2) from marts.fct_orders").fetchone()[0])

if governed == oracle and governed != measure:
    print(f"PASS: view revenue == metric definition == {governed} "
          f"(raw measure is {measure}; the view did not regress to it)")
else:
    print(f"FAIL: view={governed} metric_oracle={oracle} raw_measure={measure}")
    sys.exit(1)
EOF

printf '\nWrenAI end-to-end demo: PASS\n'
printf 'MCP: register the per-use-case server printed by step 2 (wren/mcp.json).\n'
