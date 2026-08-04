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

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| `/resolve-conflicts` | Every conflict enumerated with both intents named, then resolutions — not `--ours` applied wholesale |
| "the rebase stopped" | The operation state read first (`rebase` vs `merge`), then the right continue command |
| "just take my version" | The files where that is safe, and the ones where it silently drops the other side |

**Worked example**

> `/resolve-conflicts`

```
State: rebase in progress, feature/CHK-412 onto main — stopped at 3/7
Conflicted: src/checkout/tax.ts, package-lock.json

src/checkout/tax.ts:88
  ours   (main)    : rate lookup moved to getRegionRate(region)
  theirs (branch)  : rounding moved from per-line to order total
  Compatible — both survive: call getRegionRate(region), keep the single total rounding.

package-lock.json
  Generated file. Do not hand-merge.
  → git checkout --theirs package-lock.json && npm install

Checks after resolution: npm run typecheck && npm test -- tax
Then: git add -A && git rebase --continue
```

Aborting is the last option, not the first — and if one side genuinely has to lose, the
report says which behavior was dropped and why.
