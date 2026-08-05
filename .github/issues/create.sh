#!/usr/bin/env bash
#
# Create the two "deliberately not fixed" findings as GitHub issues and put them on the
# project board.
#
# Both are findings from `scripts/connector_alignment_check.py` that are correct to leave
# open rather than silence: one needs a fact only a human has (the freshness SLA), the other
# is a deliberate convention the checker cannot know about. Neither is a bug to fix quietly.
#
# Usage:
#   gh auth login                    # interactive, once
#   gh auth refresh -s project       # Projects v2 needs a scope `auth login` does not grant
#   .github/issues/create.sh
#
# Env:
#   REPO      target repository   (default: the `origin` remote)
#   PROJECT   project number      (default: 1)
#   OWNER     project owner       (default: PackMaaan)
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="${PROJECT:-1}"
OWNER="${OWNER:-PackMaaan}"

if ! command -v gh >/dev/null 2>&1; then
    echo "gh is not installed:  brew install gh" >&2
    exit 1
fi

# Auth is checked before anything else. `gh repo view` also needs a token, so detecting the
# repository first reported "could not determine the repository" to someone whose only
# problem was that they had not logged in — an error message pointing at the wrong thing.
if ! gh auth status >/dev/null 2>&1; then
    echo "not authenticated. Run:" >&2
    echo "    gh auth login" >&2
    echo "    gh auth refresh -s project" >&2
    exit 1
fi

# Default the repo to whatever `origin` points at rather than hardcoding it: this module is
# checked out under two names that are the same remote, and guessing picks the wrong one.
# The git remote is the fallback so this still works from a detached or API-less state.
if [ -z "${REPO:-}" ]; then
    REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)"
fi
if [ -z "${REPO:-}" ]; then
    REPO="$(git config --get remote.origin.url 2>/dev/null \
        | sed -E 's#^.*github\.com[:/]##; s#\.git$##')"
fi
if [ -z "${REPO}" ]; then
    echo "could not determine the repository; set REPO=owner/name" >&2
    exit 1
fi

# Projects v2 is GraphQL-only and needs the `project` scope. Checking up front turns an
# opaque GraphQL permission error at the last step into one actionable line here — after the
# issues have already been created, which would make a re-run create duplicates.
if ! gh auth status 2>&1 | grep -q "project"; then
    echo "The token has no 'project' scope, so issues could be created but not added to the" >&2
    echo "board — and re-running would then duplicate them. Run:" >&2
    echo "    gh auth refresh -s project" >&2
    exit 1
fi

echo "repo:    ${REPO}"
echo "project: https://github.com/users/${OWNER}/projects/${PROJECT}"
echo

create() {
    local title="$1" body_file="$2" labels="$3"

    # Idempotent by title: this script is the kind that gets run twice when the first run
    # half-failed, and two copies of a design question is worse than none.
    local existing
    existing="$(gh issue list --repo "${REPO}" --state all --search "\"${title}\" in:title" \
        --json number,title -q ".[] | select(.title == \"${title}\") | .number" | head -1)"
    if [ -n "${existing}" ]; then
        echo "exists  #${existing}  ${title}"
        gh project item-add "${PROJECT}" --owner "${OWNER}" \
            --url "https://github.com/${REPO}/issues/${existing}" >/dev/null 2>&1 || true
        return
    fi

    local url
    url="$(gh issue create --repo "${REPO}" \
        --title "${title}" \
        --body-file "${body_file}" \
        ${labels:+--label "${labels}"})"
    echo "created ${url}"
    gh project item-add "${PROJECT}" --owner "${OWNER}" --url "${url}"
}

# Labels are passed only if they already exist on the repo; `gh issue create` fails outright
# on an unknown label rather than creating it, which would abort the run.
label_if_present() {
    gh label list --repo "${REPO}" --json name -q '.[].name' 2>/dev/null | grep -qx "$1" \
        && printf '%s' "$1" || printf ''
}

DBT_LABEL="$(label_if_present dbt)"
DOCS_LABEL="$(label_if_present documentation)"

create "dbt: declare source freshness SLAs for all 8 connectors" \
       "${HERE}/source-freshness-slas.md" \
       "${DBT_LABEL}"

create "alignment: decide how base_ models are recognised (fortnox_base_v2_invoices)" \
       "${HERE}/base-model-naming-exception.md" \
       "${DOCS_LABEL}"

echo
echo "Done. Board: https://github.com/users/${OWNER}/projects/${PROJECT}"
