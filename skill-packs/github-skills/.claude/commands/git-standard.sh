#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: git-standard.sh <commit-message>"
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

git commit -m "$message"
echo "Commit message approved: $message"
