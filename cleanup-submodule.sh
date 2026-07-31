#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <submodule-path>" >&2
  echo "Example: $0 external/claude-skills" >&2
  exit 1
fi

submodule_path="$1"
root="$(git rev-parse --show-toplevel)"
cd "$root"

if [[ ! -f .gitmodules ]]; then
  echo "Error: no .gitmodules file found in $root" >&2
  exit 1
fi

if ! git config -f .gitmodules --get-regexp "submodule\.$submodule_path\." >/dev/null 2>&1; then
  echo "Error: submodule path '$submodule_path' not found in .gitmodules" >&2
  exit 1
fi

echo "Deinitializing submodule '$submodule_path'..."
git submodule deinit -f -- "$submodule_path"

if [[ -d ".git/modules/$submodule_path" ]]; then
  echo "Removing submodule git metadata..."
  rm -rf ".git/modules/$submodule_path"
fi

echo "Removing entry from .gitmodules..."
git config -f .gitmodules --remove-section "submodule.$submodule_path"

git config --remove-section "submodule.$submodule_path" || true

git add .gitmodules

echo "Removing working tree directory..."
git rm -f -- "$submodule_path"

echo "Submodule '$submodule_path' removed. Commit the result with:\n  git commit -m 'chore: remove $submodule_path submodule'"
