#!/usr/bin/env bash
# In-container half of the podman demo. Runs from the read-only stage mount.
#
# The host half (run_wren_podman_demo.sh) copies the use-case to a staging directory,
# mounts it at /stage read-only, and invokes this. Everything below writes to /work,
# never to /stage: `dbt build` and `wren context build` both drop derived state
# (dev.duckdb, target/) beside the sources they read, so a writable mount would leave
# the host tree dirty after every run.
#
# The two assertions are deliberately the same ones run_wren_demo.sh makes on the host.
# A containerised run that checked something weaker would prove only that the image
# builds.
set -euo pipefail

step() { printf '\n== %s\n' "$1"; }

step "0/5 toolchain (in container)"
echo "python: $(python3 --version)"
echo "dbt:    $(dbt --version 2>/dev/null | awk '/installed:/{print $3; exit}')"
echo "wren:   $(wren --version)"
echo "arch:   $(uname -m)"

step "1/5 copy the use-case out of the read-only mount"
mkdir -p /work
cp -r /stage/uc /work/uc
uc=/work/uc
dbt_project="${uc}/dbt_project"

step "2/5 dbt build + catalog (DuckDB, in container)"
(cd "${dbt_project}" && dbt build --quiet && dbt docs generate --quiet)
echo "built ${dbt_project}/dev.duckdb"

step "3/5 compile MDL from the committed wren/ project"
wren context build --path "${uc}/wren"

step "4/5 governed query through the semantic layer"
conn="{\"datasource\":\"duckdb\",\"url\":\"${dbt_project}\",\"format\":\"duckdb\"}"
sql="select c.region, count(*) as orders, round(sum(o.order_amount_usd),2) as revenue
     from fct_orders o join dim_customers c on o.customer_id = c.customer_id
     group by 1 order by revenue desc"
governed="$(wren query --sql "${sql}" \
  --mdl "${uc}/wren/target/mdl.json" --connection-info "${conn}" -o json -q)"
echo "${governed}"

step "5/5 assertions: governed == direct, and the metric view IS the metric"
metric="$(wren query --sql "select round(sum(revenue),2) as v from revenue" \
  --mdl "${uc}/wren/target/mdl.json" --connection-info "${conn}" -o json -q)"

GOVERNED="${governed}" METRIC="${metric}" DEMO_DB="${dbt_project}/dev.duckdb" python3 - <<'EOF'
import json, os, sys
import duckdb

# `wren query -o json` emits JSON Lines: one object per row, not a JSON array.
rows = [json.loads(ln) for ln in os.environ["GOVERNED"].splitlines() if ln.strip()]
governed = [(r["region"], int(r["orders"]), float(r["revenue"])) for r in rows]

con = duckdb.connect(os.environ["DEMO_DB"], read_only=True)
direct = [
    (r[0], int(r[1]), float(r[2]))
    for r in con.execute(
        "select c.region, count(*) as orders, round(sum(o.order_amount_usd),2) as revenue "
        "from marts.fct_orders o join marts.dim_customers c on o.customer_id = c.customer_id "
        "group by 1 order by revenue desc"
    ).fetchall()
]

failed = False
if governed == direct:
    print(f"PASS: governed == direct, {len(direct)} rows: {direct}")
else:
    print(f"FAIL:\n  governed: {governed}\n  direct:   {direct}")
    failed = True

# The cube projection this replaced dropped the metric's filter and read 4.4% high while
# staying internally consistent. The view must equal the filtered definition and must not
# regress to the raw measure.
view = float(json.loads(os.environ["METRIC"].splitlines()[0])["v"])
oracle = float(con.execute(
    "select round(sum(order_amount_usd),2) from marts.fct_orders "
    "where order_status <> 'cancelled'").fetchone()[0])
measure = float(con.execute(
    "select round(sum(order_amount_usd),2) from marts.fct_orders").fetchone()[0])

if view == oracle and view != measure:
    print(f"PASS: view revenue == metric definition == {view} "
          f"(raw measure is {measure}; the view did not regress to it)")
else:
    print(f"FAIL: view={view} metric_oracle={oracle} raw_measure={measure}")
    failed = True

sys.exit(1 if failed else 0)
EOF

printf '\nWrenAI podman demo (in container): PASS\n'
