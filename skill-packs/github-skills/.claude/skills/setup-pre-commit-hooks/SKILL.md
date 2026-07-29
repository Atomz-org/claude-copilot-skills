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
