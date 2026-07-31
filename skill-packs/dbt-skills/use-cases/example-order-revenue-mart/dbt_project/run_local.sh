#!/usr/bin/env bash
#
# End-to-end run of the worked example on DuckDB, then every analyzer in scripts/
# against the artifacts it just produced.
#
#   ./run_local.sh                 # DuckDB, no credentials, ~20 seconds
#   ./run_local.sh bigquery        # needs DBT_BQ_PROJECT etc. — see profiles.yml
#   ./run_local.sh snowflake       # needs DBT_SF_ACCOUNT etc. — see profiles.yml
#
# Setup, once:
#   python3 -m venv .venv
#   .venv/bin/pip install 'dbt-core~=1.9.0' 'dbt-duckdb~=1.9.0'
#   # for the other targets, add 'dbt-bigquery' or 'dbt-snowflake'

set -euo pipefail

TARGET="${1:-duckdb_dev}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The scaffold root owns .venv/ and scripts/. This file lives five levels below it, at
# skill-packs/<pack>/use-cases/<slug>/dbt_project/ — it was three before the worked
# example moved into the pack, which left the script looking for dbt inside the pack.
SCAFFOLD="$(cd "$HERE/../../../../.." && pwd)"
DBT="${DBT_BIN:-$SCAFFOLD/.venv/bin/dbt}"
cd "$HERE"

if [ ! -x "$DBT" ]; then
    echo "dbt not found at $DBT — set DBT_BIN, or create the venv shown above." >&2
    exit 2
fi

step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

step "0. Connection check"
"$DBT" debug --profiles-dir . --target "$TARGET"

step "1. Install packages"
"$DBT" deps

step "2. Refresh the raw seed data (anchors load timestamps to now)"
python3 seeds/generate_seeds.py

step "3. Load the raw tables"
"$DBT" seed --profiles-dir . --target "$TARGET"

step "4. Source freshness"
# Runs before the build on purpose: building a mart on stale sources produces a table
# that is wrong and looks fine.
"$DBT" source freshness --profiles-dir . --target "$TARGET"

step "5. Build everything — models, data tests, unit tests, snapshot"
# `build`, never `run` then `test`: build stops a model's dependents the moment one of
# its tests fails, instead of propagating bad data through the whole DAG first.
#
# --exclude resource_type:seed is required *because* the raw tables here are seeds.
# dbt knows a source only by schema + identifier, so there is no DAG edge from a source
# test to the seed that populates it. With threads > 1, `build` will happily drop and
# recreate raw_order_lines at the same moment source_not_null_shopify_order_lines_id
# queries it, and the test fails with "table does not exist". Seeding in its own step
# (step 3 above) and excluding seeds here removes the race.
#
# In a real project the raw tables are landed by an EL tool, sources are genuinely
# external, and this flag is unnecessary.
"$DBT" build --profiles-dir . --target "$TARGET" --full-refresh --exclude resource_type:seed

step "6. Build again — exercises the incremental path"
# The first build is a plain create and never exercises incremental_strategy. Bugs there
# only appear on the second run.
"$DBT" build --profiles-dir . --target "$TARGET" --exclude resource_type:seed

step "7. Prove the incremental result equals the full-refresh result (rule 23)"
"$DBT" show --profiles-dir . --target "$TARGET" --inline \
  "select count(*) as rows, sum(order_amount_usd) as gross, sum(net_line_amount_usd) as net
   from {{ ref('fct_orders') }}"

step "8. Generate the catalog"
"$DBT" docs generate --profiles-dir . --target "$TARGET"

# ---------------------------------------------------------------------------
T="$HERE/target"
S="$SCAFFOLD/scripts"
M="$HERE/models"

step "9. Project audit — 20 health rules"
python3 "$S/dbt_project_auditor.py" --manifest "$T/manifest.json"

step "10. DAG structure and layer discipline"
python3 "$S/model_dependency_analyzer.py" --manifest "$T/manifest.json" --check-layers

step "11. Test coverage, ranked by blast radius"
python3 "$S/test_coverage_reporter.py" --manifest "$T/manifest.json"

step "12. Where the build time went"
python3 "$S/run_results_analyzer.py" --run-results "$T/run_results.json" --manifest "$T/manifest.json"

step "13. Source freshness, annotated with what each breach blocks"
python3 "$S/source_freshness_monitor.py" --sources "$T/sources.json" --manifest "$T/manifest.json"

step "14. ERD of the marts"
python3 "$S/erd_generator.py" --manifest "$T/manifest.json" --catalog "$T/catalog.json"

step "15. Dimensional model — 15 star-schema rules"
python3 "$S/dimensional_model_validator.py" --manifest "$T/manifest.json" --catalog "$T/catalog.json"

step "16. Semantic layer spec check"
python3 "$S/semantic_layer_validator.py" --path "$M"

printf '\n\033[1mDone.\033[0m Artifacts in %s\n' "$T"
printf 'The remaining scripts need two manifests to compare:\n'
printf '  python3 %s/contract_breaking_change_detector.py --base <prod>/manifest.json --head %s/manifest.json\n' "$S" "$T"
printf '  python3 %s/schema_yml_generator.py --manifest %s/manifest.json --model <model> --infer-tests\n' "$S" "$T"
printf '  python3 %s/unit_test_generator.py  --manifest %s/manifest.json --model <model> --adapter duckdb\n' "$S" "$T"
