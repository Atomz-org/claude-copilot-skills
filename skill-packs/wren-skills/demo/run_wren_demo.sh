#!/usr/bin/env bash
# End-to-end WrenAI demo over this repository's own use-case, entirely local:
#
#   dbt build (DuckDB)  ->  wren stage (native import + ontology/metric enrichment)
#   ->  wren context build (MDL)  ->  governed `wren query`  ->  cross-check vs DuckDB
#
# No Docker, no warehouse, no LLM key. The pass criterion is exact row equality between
# the governed query (through the generated semantic layer) and the same aggregation run
# directly against the DuckDB file — if the semantic layer misroutes a single join or
# column, the two disagree and this exits 1.
set -euo pipefail

root="$(cd "$(dirname "$0")/../../.." && pwd)"
uc="skill-packs/dbt-skills/use-cases/example-order-revenue-mart"
dbt_project="${root}/${uc}/dbt_project"

step() { printf '\n== %s\n' "$1"; }

step "0/5 toolchain"
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

step "1/5 dbt build + catalog (DuckDB, local)"
(cd "${dbt_project}" && "${dbt}" build --quiet && "${dbt}" docs generate --quiet)
echo "built $(ls "${dbt_project}"/dev.duckdb)"

step "2/5 regenerate the wren/ project (import + enrichment, validate, build)"
WREN_CLI="${wren}" python3 "${root}/scripts/use_case_sync.py" \
  --use-case example-order-revenue-mart --stage wren

step "3/5 compile MDL"
"${wren}" context build --path "${root}/${uc}/wren"

step "4/5 governed query through the semantic layer"
conn="{\"datasource\":\"duckdb\",\"url\":\"${dbt_project}\",\"format\":\"duckdb\"}"
sql="select c.region, count(*) as orders, round(sum(o.order_amount_usd),2) as revenue
     from fct_orders o join dim_customers c on o.customer_id = c.customer_id
     group by 1 order by revenue desc"
governed="$("${wren}" query --sql "${sql}" \
  --mdl "${root}/${uc}/wren/target/mdl.json" --connection-info "${conn}" -o json -q)"
echo "${governed}"

step "5/5 cross-check against DuckDB directly"
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

printf '\nWrenAI end-to-end demo: PASS\n'
