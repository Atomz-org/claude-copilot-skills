---
description: Run a pre-merge checklist and merge a GitHub PR with explicit confirmation.
---

Merge a PR safely.

1. Gather PR state:
   - `gh pr view <PR> --json number,title,baseRefName,headRefName,state`
   - `gh pr checks <PR>`
2. Validate:
   - checks passing,
   - comments addressed,
   - changelog policy satisfied (when applicable).
3. Show checklist summary.
4. Ask explicit confirmation.
5. Execute merge with repository merge strategy.
6. Sync base branch locally and report outcome.
