---
description: Run a local review pass before committing or opening a PR.
---

Perform a lightweight review pass for this repository before committing or pushing.

If unsure which workflow to use first, open `.claude/commands/skills-index.md`.

1. Pick review scope:
   - `branch`: committed work vs base branch.
   - `working`: uncommitted changes vs `HEAD`.
   - `staged`: staged-only diff vs `HEAD`.
   - `all`: committed + uncommitted changes.
2. Capture review context:
   - `git status --short`
   - `git diff --stat` (or `git diff --cached --stat` for staged scope)
   - `git diff` (or `git diff --cached`)
3. Run repository checks:
   - `./.claude/commands/lint-and-graph.sh`
4. Check consistency with `.claude/CLAUDE.md` and `.claude/rules/standards.md`.
5. Report findings in concise format:
   - `🔴 bug`: broken behavior or likely incident.
   - `🟡 risk`: fragile behavior or missing guardrails.
   - `🔵 nit`: low-impact cleanup.
   - `❓ q`: question requiring author confirmation.
6. For each finding, include:
   - location (`file` and line or symbol),
   - concrete problem,
   - concrete fix.
7. Summarize readiness:
   - `Ready`, `Ready with follow-ups`, or `Not ready`.
   - include top 1-3 blockers if not ready.

If anything fails, fix it before continuing.
