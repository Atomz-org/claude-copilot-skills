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
3. Confirm guardrail hook is enabled in `.claude/settings.json`.
4. Show checklist summary.
5. Ask explicit confirmation.
6. Execute merge with repository merge strategy.
7. Sync base branch locally and report outcome.
8. Run `scripts/sync_context.sh "post merge sync"` to checkpoint RTK/Graphify/AgentMemory state.
