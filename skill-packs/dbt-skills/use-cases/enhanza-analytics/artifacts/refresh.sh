#!/usr/bin/env bash
#
# Rebuild the committed graphify fragment for enhanza-analytics.
#
# Run this after adding a connector, adding models, or changing any ref()/source(). It does
# three things in the order that matters:
#
#   1. `dbt parse` with EVERY connector enabled. This project is multi-tenant and gated on
#      `is_<source>_enabled` vars that all default to false, so a parse with defaults yields
#      a manifest holding a fraction of the project. The manifest committed here before this
#      script existed had 72 of 359 models and 66 of 981 dependency edges — internally
#      consistent, silently partial, and nothing in it said so.
#   2. Emit the graphify fragment. The full manifest is 3.0 MB and churns on every model
#      edit; the fragment is 736 KB, is what graphify actually consumes, and lets a fresh
#      clone rebuild dbt lineage without dbt or a warehouse.
#   3. Check connector alignment, so drift is caught here rather than at the next parse.
#
# Usage:  ./artifacts/refresh.sh          (from the use-case directory, or anywhere)
#
set -euo pipefail

USE_CASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${USE_CASE}/dbt_project"
REPO="$(cd "${USE_CASE}/../../../.." && pwd)"
ARTIFACTS="${USE_CASE}/artifacts"

DBT="${DBT_BIN:-${REPO}/.venv-dbt/bin/dbt}"
if [ ! -x "${DBT}" ]; then
    DBT="$(command -v dbt || true)"
fi
if [ -z "${DBT}" ] || [ ! -x "${DBT}" ]; then
    echo "dbt not found. Set DBT_BIN, or install dbt-core with the duckdb adapter." >&2
    exit 3
fi

# Every connector on. Derived from dbt_project.yml rather than hardcoded, so a connector
# added to the vars block is picked up here without editing this script.
VARS=$(python3 - "$PROJECT/dbt_project.yml" <<'PY'
import json, re, sys
text = open(sys.argv[1], encoding="utf-8").read()
block = text.split("vars:", 1)[1].split("\nmodels:", 1)[0]
flags = re.findall(r"^\s{2}(is_[a-z_0-9]+_enabled):", block, re.MULTILINE)
print(json.dumps({"uid": "canonical", **{f: True for f in flags}}))
PY
)

# dbt has no dedicated rtk filter. `rtk err <cmd>` is the documented route for an uncovered
# command, but it re-splits its arguments and mangles the JSON in `--vars` ("String '{uid:'
# is not valid YAML"), so the output is piped through `rtk pipe` instead — the protocol's
# other route, and the one that never touches the argv. Measured on a successful parse:
# 408 chars -> 261. Modest, because dbt is already terse on success; the filter earns its
# place on a *failed* parse, where the stack trace is what survives and the progress log is
# what does not.
#
# `set -o pipefail` is already in effect above, so a failed parse still fails this script
# rather than being masked by the filter's exit code.
echo "==> dbt parse with all connectors enabled"
if command -v rtk >/dev/null 2>&1; then
    ( cd "${PROJECT}" && "${DBT}" parse --profiles-dir . --vars "${VARS}" 2>&1 | rtk pipe )
else
    ( cd "${PROJECT}" && "${DBT}" parse --profiles-dir . --vars "${VARS}" )
fi

echo
echo "==> emit graphify fragment"
# `--with-columns` needs sqlglot; the emitter says so and carries on without it, so this is
# one command either way rather than two paths that drift.
python3 "${REPO}/scripts/dbt_manifest_to_graphify.py" \
    --manifest "${PROJECT}/target/manifest.json" \
    --out "${ARTIFACTS}/graphify-fragment.json" \
    --with-columns

echo
echo "==> connector alignment"
python3 "${REPO}/scripts/connector_alignment_check.py" \
    --use-case enhanza-analytics \
    --manifest "${PROJECT}/target/manifest.json" \
    --check

echo
echo "Done. Merge into the graph with:"
echo "  python3 scripts/dbt_manifest_to_graphify.py --manifest ${PROJECT}/target/manifest.json --merge"
