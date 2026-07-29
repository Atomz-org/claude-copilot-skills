#!/usr/bin/env bash
set -euo pipefail

dry_run="false"

if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run="true"
  shift
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: git-standard.sh [--dry-run] <commit-message>"
  exit 1
fi

message="$1"
branch="$(git branch --show-current 2>/dev/null || echo "unknown")"

if [[ "$branch" == "main" || "$branch" == "master" ]]; then
  echo "Direct commits to main/master are not allowed."
  exit 1
fi

if [[ ! "$branch" =~ ^(feat|fix|chore|docs|sync)/[A-Za-z0-9._-]+-[A-Za-z0-9._-]+$ ]]; then
  echo "Branch name must follow <type>/<ticket>-<description>."
  exit 1
fi

if [[ ! "$message" =~ ^(feat|fix|chore|docs)(\([a-zA-Z0-9._-]+\))?:\ .+ ]]; then
  echo "Commit message must follow Conventional Commits."
  exit 1
fi

if [[ "$message" =~ ^(feat|fix|chore|docs)(\([a-zA-Z0-9._-]+\))?:\ .{73,}$ ]]; then
  echo "Commit summary should be under 72 characters after the colon."
  exit 1
fi

if [[ -z "$(git diff --cached --name-only)" ]]; then
  echo "No staged changes found. Stage files before committing."
  exit 1
fi

staged_patch="$(git diff --cached)"
if printf '%s' "$staged_patch" | grep -Eiq '(api[_-]?key|secret|private[_-]?key|BEGIN[[:space:]]+RSA[[:space:]]+PRIVATE[[:space:]]+KEY|password[[:space:]]*=|token[[:space:]]*=)'; then
  echo "Potential secret detected in staged diff. Review and remove sensitive data before committing."
  exit 1
fi

if [[ "$dry_run" == "true" ]]; then
  echo "Dry run passed for branch '$branch' with message: $message"
  exit 0
fi

git commit -m "$message"
echo "Commit message approved: $message"
