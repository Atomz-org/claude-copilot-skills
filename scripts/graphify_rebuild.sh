#!/usr/bin/env bash
#
# Rebuild graphify-out/ from scratch, transactionally.
#
# The previous `make init` recipe was `init: clean build`, and `clean` is
# `rm -rf graphify-out`. So the graph was destroyed *before* anything checked
# that a rebuild could succeed. It could not: `graphify .` needs an LLM API key
# to extract the repository's ~350 doc files, and with no key set it exits 1 at
# step 1 of 3 — leaving no graph, no report, and no way back. Recovering meant
# having taken a manual copy first.
#
# This script makes the rebuild atomic from the caller's point of view:
#
#   * every precondition is checked BEFORE the old graph is touched;
#   * the old graph is moved aside, never deleted;
#   * the new graph must pass verification, not merely exit 0;
#   * any failure — or an interrupt — restores exactly what was there before.
#
# It also preserves graphify-out/cache/, the semantic-extraction cache. A full
# labeled build cost ~1.3M input tokens on this repository; re-paying for files
# that have not changed is money for nothing. Pass --cold to discard it.
#
# The step order is the one this repository's manual requires and is not
# negotiable: rebuild the code graph FIRST, merge dbt lineage AFTER. graphify
# has no SQL parser, so a rebuild run after a merge drops every dbt model node
# and its edges while leaving a graph that still looks populated.
#
# Usage:
#   scripts/graphify_rebuild.sh [--use-case SLUG] [--code-only] [--cold]
#
# Env:
#   GRAPHIFY   override the graphify binary (default: first on PATH)
#   PYTHON     override the interpreter for the sync step
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${ROOT_DIR}/graphify-out"
PREV_DIR="${ROOT_DIR}/.graphify-out.prev"

USE_CASE="enhanza-analytics"
CODE_ONLY=0
COLD=0

while [ $# -gt 0 ]; do
    case "$1" in
        --use-case) USE_CASE="${2:?--use-case needs a value}"; shift 2 ;;
        --code-only) CODE_ONLY=1; shift ;;
        --cold) COLD=1; shift ;;
        -h|--help) sed -n '2,34p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

GRAPHIFY="${GRAPHIFY:-$(command -v graphify || true)}"
PYTHON="${PYTHON:-${ROOT_DIR}/.venv/bin/python3}"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"

SYNC_SCRIPT="${ROOT_DIR}/scripts/use_case_sync.py"
REFRESH_SCRIPT="${ROOT_DIR}/skill-packs/dbt-skills/use-cases/${USE_CASE}/artifacts/refresh.sh"

say() { printf '==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# --------------------------------------------------------------------------
# 1. preflight — everything that can be known before destroying anything
# --------------------------------------------------------------------------

say "Preflight"

[ -n "$GRAPHIFY" ] || die "graphify not found on PATH. Install it, or set GRAPHIFY."
[ -f "$SYNC_SCRIPT" ] || die "missing $SYNC_SCRIPT"

if [ "$CODE_ONLY" -eq 0 ]; then
    # The exact failure this script exists to prevent. graphify names these six.
    have_key=0
    for k in GEMINI_API_KEY GOOGLE_API_KEY MOONSHOT_API_KEY ANTHROPIC_API_KEY \
             OPENAI_API_KEY DEEPSEEK_API_KEY; do
        if [ -n "${!k:-}" ]; then
            say "  LLM backend: \$$k is set"
            have_key=1
            break
        fi
    done
    if [ "$have_key" -eq 0 ]; then
        die "no LLM API key set, and this repository has doc/paper files that need
       semantic extraction. Set one of GEMINI_API_KEY, GOOGLE_API_KEY,
       MOONSHOT_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY, DEEPSEEK_API_KEY —
       or pass --code-only to index just the code with the local AST pass.

       Nothing has been changed. The existing graph is untouched."
    fi
fi

[ -f "$REFRESH_SCRIPT" ] || say "  note: no dbt refresh script for '${USE_CASE}'; assuming the manifest is current"
say "  ok"

# --------------------------------------------------------------------------
# 2. move the old graph aside — never delete it
# --------------------------------------------------------------------------

restore() {
    if [ -d "$PREV_DIR" ]; then
        printf 'ERROR: rebuild failed — restoring the previous graph\n' >&2
        rm -rf "$OUT_DIR"
        mv "$PREV_DIR" "$OUT_DIR"
        printf 'Restored %s\n' "$OUT_DIR" >&2
    fi
}
trap restore ERR INT TERM

rm -rf "$PREV_DIR"
if [ -d "$OUT_DIR" ]; then
    say "Setting the current graph aside"
    mv "$OUT_DIR" "$PREV_DIR"
fi
mkdir -p "$OUT_DIR"

if [ "$COLD" -eq 0 ] && [ -d "$PREV_DIR/cache" ]; then
    say "Reusing the semantic cache (pass --cold to discard)"
    cp -R "$PREV_DIR/cache" "$OUT_DIR/cache"
fi

# --------------------------------------------------------------------------
# 3. rebuild, then merge — in that order, never the reverse
# --------------------------------------------------------------------------

say "Step 1/3: code graph"
if [ "$CODE_ONLY" -eq 1 ]; then
    "$GRAPHIFY" . --code-only
else
    "$GRAPHIFY" .
fi

say "Step 2/3: dbt manifest"
if [ -f "$REFRESH_SCRIPT" ]; then
    "$REFRESH_SCRIPT"
else
    say "  skipped: no refresh script for '${USE_CASE}'"
fi

say "Step 3/3: merge dbt lineage"
"$PYTHON" "$SYNC_SCRIPT" --use-case "$USE_CASE"

# --------------------------------------------------------------------------
# 4. verify before committing to the result
# --------------------------------------------------------------------------

say "Verifying"
GRAPH_JSON="$OUT_DIR/graph.json" "$PYTHON" - <<'PY'
import json, os, sys

path = os.environ["GRAPH_JSON"]
if not os.path.isfile(path):
    sys.exit(f"no graph.json at {path}")
with open(path, encoding="utf-8") as fh:
    graph = json.load(fh)

nodes = graph.get("nodes") or []
edges = graph.get("edges") or graph.get("links") or []
if len(nodes) < 100 or not edges:
    sys.exit(f"graph looks empty: {len(nodes)} nodes, {len(edges)} edges")

print(f"  {len(nodes)} nodes, {len(edges)} edges")
PY

say "Rebuild succeeded — discarding the previous graph"
trap - ERR INT TERM
rm -rf "$PREV_DIR"
