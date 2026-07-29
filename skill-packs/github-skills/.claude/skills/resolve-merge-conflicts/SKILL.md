---
name: resolve-merge-conflicts
description: Resolve merge or rebase conflicts by preserving intent, validating behavior, and completing the operation safely.
---

# Resolve Merge Conflicts

Use this skill when conflict markers are present.

## Workflow

1. Enumerate conflicted files and operation state.
2. Read both sides of each conflict and infer original intent.
3. Resolve hunks by preserving both intents when compatible.
4. Avoid introducing new behavior during conflict resolution.
5. Run project checks (typecheck, tests, lint, formatting).
6. Stage resolved files and continue merge/rebase.

## Guardrails

- Do not panic-abort as first response.
- Do not choose sides blindly by file.
- Document trade-offs when one side must win.
