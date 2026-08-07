#!/usr/bin/env bash
#
# One command that answers one question: would this change be accepted?
#
#   ./scripts/check.sh
#
# It runs the same eight gates as .github/workflows/pr-decision-diagram.yml, in the same
# order, so the answer here is the answer there. When a gate fails it says what the gate
# was protecting and prints the exact command that fixes it — no prior knowledge of this
# repository assumed.
#
# Exit code: 0 if nothing failed, 1 otherwise. A gate that cannot run (no Node, no rustc)
# is reported as "skipped", never as a failure — a check that goes red because a laptop
# lacks an optional toolchain gets ignored, and takes the real failures with it.
#
# Options:
#   --quiet   only print gates that did not pass
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

QUIET=""
[ "${1:-}" = "--quiet" ] && QUIET=1

# Colour only when a human is watching. Piping this into a file or a CI log gets plain text.
if [ -t 1 ]; then
    GREEN=$'\033[32m'; RED=$'\033[31m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; OFF=$'\033[0m'
else
    GREEN=""; RED=""; YELLOW=""; DIM=""; OFF=""
fi

PASSED=0; FAILED=0; SKIPPED=0

# Prefer the project's virtualenv, so the gate does not depend on which shell you are in.
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python

pass() { PASSED=$((PASSED + 1)); [ -n "$QUIET" ] || printf '  %s✓%s  %-24s %s\n' "$GREEN" "$OFF" "$1" "${2:-}"; }
skip() { SKIPPED=$((SKIPPED + 1)); printf '  %s—%s  %-24s %s%s%s\n' "$YELLOW" "$OFF" "$1" "$DIM" "${2:-}" "$OFF"; }

# fail <gate> <what happened> <what it means> <how to fix>
fail() {
    FAILED=$((FAILED + 1))
    printf '  %s✗%s  %-24s %s\n' "$RED" "$OFF" "$1" "$2"
    printf '     %swhat it means%s  %s\n' "$DIM" "$OFF" "$3"
    printf '     %show to fix%s     %s\n' "$DIM" "$OFF" "$4"
    printf '\n'
}

printf '\nRunning the eight gates a pull request has to pass.\n\n'

# ---------------------------------------------------------------------------------------
# 1. Branch naming
# ---------------------------------------------------------------------------------------
BRANCH="$(git branch --show-current 2>/dev/null || echo "")"
if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
    fail "branch naming" "you are on $BRANCH" \
        "This repository does not accept commits straight onto the main branch." \
        "git switch -c fix/no-ticket-short-description"
elif printf '%s' "$BRANCH" | grep -Eq '^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)/[A-Za-z0-9._-]+'; then
    pass "branch naming" "$BRANCH"
else
    fail "branch naming" "$BRANCH" \
        "Branch names have to start with a type, so tooling can tell a fix from a feature." \
        "git branch -m fix/no-ticket-short-description"
fi

# ---------------------------------------------------------------------------------------
# 2. Conventional Commits
# ---------------------------------------------------------------------------------------
BASE="$(git merge-base main HEAD 2>/dev/null || echo "")"
if [ -z "$BASE" ]; then
    skip "conventional commits" "no main branch to compare against"
else
    BAD="$(git log --no-merges --format='%s' "$BASE"..HEAD \
        | grep -Ev '^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([A-Za-z0-9._/-]+\))?!?: .+' || true)"
    if [ -z "$BAD" ]; then
        N="$(git log --no-merges --oneline "$BASE"..HEAD | wc -l | tr -d ' ')"
        pass "conventional commits" "$N commit(s) conform"
    else
        fail "conventional commits" "$(printf '%s' "$BAD" | head -1)" \
            "Every commit subject must read 'type: summary' — for example 'fix: stop the seed collision'." \
            "git commit --amend    (or: git rebase -i $BASE  to reword older ones)"
    fi
fi

# ---------------------------------------------------------------------------------------
# 3. Activation drift — the one that catches an edit made in the wrong place
# ---------------------------------------------------------------------------------------
# CI can run activation and throw away the result because its checkout is disposable. Yours
# is not, so this compares before and after instead of resetting anything. Nothing you have
# not committed is ever discarded here.
BEFORE="$(git status --porcelain)"
if ./scripts/activate_skill_stack.sh dbt-skills wren-skills lightdash-skills >/dev/null 2>&1; then
    AFTER="$(git status --porcelain)"
    if [ "$BEFORE" = "$AFTER" ]; then
        pass "activation drift" "pack and mirror in sync"
    else
        CHANGED="$(comm -13 <(printf '%s\n' "$BEFORE" | sort) <(printf '%s\n' "$AFTER" | sort) | head -1)"
        fail "activation drift" "${CHANGED:-a generated file changed}" \
            ".claude/, references/ and templates/ are copies, rebuilt from skill-packs/. Editing a copy works until the next rebuild silently reverts it." \
            "make the same edit under skill-packs/<pack>/, then: ./scripts/activate_skill_stack.sh dbt-skills wren-skills lightdash-skills"
    fi
else
    fail "activation drift" "activation script failed" \
        "The step that rebuilds .claude/ from skill-packs/ did not finish." \
        "./scripts/activate_skill_stack.sh dbt-skills wren-skills lightdash-skills    # run it directly to see the error"
fi

# ---------------------------------------------------------------------------------------
# 4. Marketplace portability
# ---------------------------------------------------------------------------------------
if OUT="$(./scripts/marketplace_portability_check.sh 2>&1)"; then
    pass "marketplace portability" "manifests and SKILL.md sizes OK"
else
    fail "marketplace portability" "$(printf '%s' "$OUT" | head -1)" \
        "Each skill pack must carry the metadata that lets another repository install it." \
        "./scripts/marketplace_portability_check.sh    # run it directly for the full list"
fi

# ---------------------------------------------------------------------------------------
# 5. TOON serializer build
# ---------------------------------------------------------------------------------------
if ! command -v rustc >/dev/null 2>&1; then
    skip "toon serializer build" "rustc is not installed (optional)"
elif OUT="$(./scripts/build_toon_rs.sh 2>&1)"; then
    pass "toon serializer build" "rustc -O clean"
else
    fail "toon serializer build" "$(printf '%s' "$OUT" | tail -1)" \
        "rust/toon/graph_to_toon.rs no longer compiles, so the graph-to-context pipeline would fall back silently." \
        "./scripts/build_toon_rs.sh    # run it directly to see the compiler error"
fi

# ---------------------------------------------------------------------------------------
# 6. Test suite
# ---------------------------------------------------------------------------------------
if ! "$PY" -c "import pytest" 2>/dev/null; then
    fail "test suite" "pytest is not installed" \
        "Nothing can be verified without the test runner." \
        "$PY -m pip install -r .github/requirements/ci.txt"
elif OUT="$("$PY" -m pytest -q 2>&1)"; then
    pass "test suite" "$(printf '%s' "$OUT" | grep -Eo '[0-9]+ passed[^,]*' | head -1)"
    if ! "$PY" -c "import sqlglot" 2>/dev/null; then
        printf '     %severy SQL-parsing test was skipped — install sqlglot to actually run them:%s\n' "$DIM" "$OFF"
        printf '     %s%s -m pip install -r .github/requirements/ci.txt%s\n\n' "$DIM" "$PY" "$OFF"
    fi
else
    fail "test suite" "$(printf '%s' "$OUT" | grep -E '^FAILED|^ERROR' | head -1)" \
        "A test that used to pass no longer does. The name above is the first one." \
        "$PY -m pytest -q --last-failed    # re-run only the failures, with full output"
fi

# ---------------------------------------------------------------------------------------
# 7. Harness integrity
# ---------------------------------------------------------------------------------------
# Only name collisions and unparseable frontmatter are budgeted here — the two failures that
# are silent at runtime, where the harness quietly loads something other than what you meant.
# Broken references are excluded on purpose: tests/test_docs_links.py owns those and is
# stricter, so the issue count this prints is not a defect count.
if [ ! -f scripts/skill_map_scan.py ]; then
    skip "harness integrity" "scanner not present on this branch"
else
    OUT="$("$PY" scripts/skill_map_scan.py --check --max-errors 1 --summary 2>&1)"
    case $? in
        0) pass "harness integrity" "$(printf '%s' "$OUT" | head -1)" ;;
        1) fail "harness integrity" "$(printf '%s' "$OUT" | tail -1)" \
               "Two skills, commands or agents now answer to the same name. Whichever one loads is a coin flip." \
               "$PY scripts/skill_map_scan.py --summary    # the colliding names are in the output" ;;
        *) skip "harness integrity" "needs Node, which is not installed (optional)" ;;
    esac
fi

# ---------------------------------------------------------------------------------------
# 8. Stack hygiene — the branch grammar, and where generated artifacts may land
# ---------------------------------------------------------------------------------------
# Gate 1 checks only the `<type>/` prefix. Everything after it — the lane that routes the
# review and the layer ordinal that orders the stack — went unenforced, and so did the rule
# that keeps a stack from conflicting with itself: generated artifacts belong to the top
# layer alone. A legacy `<type>/<description>` branch warns and passes; most of this
# repository's history is that form.
if [ ! -f scripts/stack_lint.py ]; then
    skip "stack hygiene" "linter not present on this branch"
else
    OUT="$("$PY" scripts/stack_lint.py --check 2>&1)"
    if [ $? -eq 0 ]; then
        pass "stack hygiene" "$(printf '%s' "$OUT" | sed -n 2p | sed 's/^ *//')"
    else
        fail "stack hygiene" "$(printf '%s' "$OUT" | grep ERROR | head -1 | sed 's/^ *//')" \
            "A stack layer that commits regenerated artifacts collides with its own siblings, and an off-grammar branch cannot be routed or ordered." \
            "$PY scripts/stack_lint.py    # prints the fix for each finding"
    fi
fi

# ---------------------------------------------------------------------------------------
printf '\n'
if [ "$FAILED" -eq 0 ]; then
    printf '  %s%s of 8 gates passed%s' "$GREEN" "$PASSED" "$OFF"
    [ "$SKIPPED" -gt 0 ] && printf ', %s skipped' "$SKIPPED"
    printf '. Nothing is blocking this change.\n\n'
    exit 0
fi

printf '  %s%s gate(s) failed%s' "$RED" "$FAILED" "$OFF"
[ "$SKIPPED" -gt 0 ] && printf ', %s skipped' "$SKIPPED"
printf '. Each one above says how to fix it.\n'
printf '  %sLonger explanations: docs/DEBUGGING.md%s\n\n' "$DIM" "$OFF"
exit 1
