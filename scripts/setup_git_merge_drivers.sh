#!/usr/bin/env bash
# Registers the merge drivers that .gitattributes names. Git does not propagate
# merge drivers through the repository — each clone carries them in its own
# .git/config — so registration has to happen per clone, and
# scripts/activate_skill_stack.sh calls this on every activation to make that
# automatic. Idempotent: `git config` overwrites the same keys in place.
#
# generated: resolves a merge of a derived artifact by keeping the current
# branch's version. `true` exits 0 and leaves %A (ours) as the result, which is
# the whole driver. Correctness does not come from the merge — regenerate with
#
#   python3 scripts/use_case_sync.py --all
#
# and the freshness gate (tests/test_use_case_sync.py, `--check` in CI) fails
# the build if that step was skipped. Hand-merging these files is never right:
# the generator is the authority on their content.
set -euo pipefail

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  # Not a git checkout (e.g. an exported tarball): nothing to register, and
  # nothing that could need it.
  exit 0
fi

git config merge.generated.name "generated artifact: keep ours, then regenerate via use_case_sync.py"
git config merge.generated.driver true

echo "Registered merge driver 'generated' in $(git rev-parse --git-dir)/config"
