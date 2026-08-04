---
name: pr-reviewability-prep
description: Prepare a branch or PR for fast reviewer comprehension without changing intended behavior.
---

# PR Reviewability Prep

Use this skill when the code works but the PR is hard to review.

## Workflow

1. Inspect commit list, changed files, and diff size.
2. Detect reviewability problems:
   - mixed mechanical and behavior changes,
   - stale PR description,
   - unclear reviewer entry points,
   - missing test evidence.
3. Propose a plan before any history rewrite.
4. If rewriting is approved, preserve behavior intent and verify resulting diff/tree.
5. Produce reviewer guidance:
   - TL;DR,
   - high-risk files,
   - test evidence,
   - rollout/rollback notes.

## Guardrails

- Do not hide behavior changes in cleanup commits.
- If diff remains too large, recommend splitting the PR.

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| `/pr-ready` | A reviewability report plus a proposed plan — no history is rewritten until you approve |
| "nobody is reviewing this PR" | The diagnosis (usually size or mixed concerns) and the split that fixes it |
| "write the PR description" | TL;DR, high-risk files, test evidence, rollback — from the actual diff |

**Worked example**

> `/pr-ready`

```
Branch: feature/CHK-412-vat-rounding — 14 commits, 31 files, +1,840 −620

Problems
  1. Commits 3-9 are a prettier reformat of 22 files mixed with the tax change.
     → Split: one commit "style: reformat checkout module", one "fix(checkout): round VAT once".
  2. PR body still describes the first approach, which was replaced in commit 11.
  3. No test evidence in the body; tests/tax.test.ts did change.

Plan (needs your approval — this rewrites history)
  git rebase -i main   # reorder mechanical commits ahead of behavioral ones
  verify: git diff main..HEAD before and after must be identical

Reviewer guidance, once split
  TL;DR      : VAT was rounded twice on multi-line orders; now rounded once at the total.
  Read first : src/checkout/tax.ts (the only behavior change)
  Evidence   : tests/tax.test.ts adds the 4-line-item case that used to drift 2c
  Rollback   : revert the single behavioral commit; the reformat is safe to keep
```

If the diff stays over the team's review budget after splitting, say "split the PR" rather
than shipping a tidier version of something too big to review.
