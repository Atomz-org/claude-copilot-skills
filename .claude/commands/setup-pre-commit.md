---
description: Set up Husky + lint-staged + Prettier in JavaScript/TypeScript repositories.
---

Set up pre-commit hooks.

1. Detect package manager from lockfile.
2. Install dev dependencies for hook tooling.
3. Initialize Husky.
4. Create/update `.husky/pre-commit` with lint-staged and optional scripts.
5. Add `.lintstagedrc` and Prettier config if missing.
6. Verify hook execution.
7. Summarize files created/updated.
