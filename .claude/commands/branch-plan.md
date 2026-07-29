---
description: Analyze changes and propose or create a Git Flow style branch.
---

Plan a branch for current changes.

1. Collect context:
   - `git branch --show-current`
   - `git status --short`
   - `git diff --stat`
2. Classify work as feature, release, or hotfix.
3. Propose 2-3 branch names.
4. Check for branch-name conflicts:
   - `git branch --list "<name>"`
   - `git ls-remote --heads origin "<name>"`
5. On confirmation, create the branch from the correct base.
