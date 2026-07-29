---
description: Run a local review pass before committing or opening a PR.
---

Perform a lightweight review pass for this repository before committing or pushing.

1. Review the working tree and confirm only intended files changed.
2. Run the repository checks:
   - `./.claude/commands/lint-and-graph.sh`
3. Check that the change is consistent with the repository guidance in `.claude/CLAUDE.md`.
4. Verify the diff is focused, documented, and easy to understand.
5. Summarize any remaining risks, follow-up items, or blockers.

If anything fails, fix it before continuing.
