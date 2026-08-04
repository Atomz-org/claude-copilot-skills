---
name: setup-pre-commit-hooks
description: Set up Husky + lint-staged + Prettier with package-manager-aware commands and verification.
---

# Setup Pre-Commit Hooks

Use this skill in JavaScript/TypeScript repositories.

## Workflow

1. Detect package manager from lockfile.
2. Install `husky`, `lint-staged`, and `prettier` as dev dependencies.
3. Initialize Husky.
4. Configure `.husky/pre-commit` to run lint-staged and optional project scripts.
5. Add `.lintstagedrc` rules for staged formatting.
6. Add a Prettier config only when missing.
7. Verify hooks execute correctly.

## Guardrails

- Do not overwrite existing style config without confirmation.
- Skip typecheck/test hook lines if scripts are absent.
- Keep setup idempotent.

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| `/setup-pre-commit` | Package manager detected from the lockfile, then install + config + a real verification run |
| "format on commit" | The same setup, scoped to staged files only via lint-staged |
| "we already have .prettierrc" | The existing config left alone, and confirmation asked before any change to it |

**Worked example**

> `/setup-pre-commit`

```
Detected: pnpm-lock.yaml → pnpm
Scripts  : typecheck ✓, test ✓, lint ✗ (absent — that hook line is skipped)
Existing : .prettierrc found → left as is, not overwritten

pnpm add -D husky lint-staged prettier
pnpm exec husky init

.husky/pre-commit
  pnpm exec lint-staged
  pnpm run typecheck

.lintstagedrc
  { "*.{ts,tsx,js,json,md}": ["prettier --write"] }

Verify
  echo 'const x   =1' > /tmp/probe.ts && git add /tmp/probe.ts && git commit -m "chore: probe"
  → lint-staged rewrites the file; commit proceeds with formatted content
```

Re-running is safe: existing dependencies, hook lines, and config are detected and left in
place rather than duplicated.
