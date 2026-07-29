---
description: Repair a specific feature or module with a focused workflow.
---

Systematically repair the feature or module at `$ARGUMENTS` using a tight, evidence-driven workflow.

If `$ARGUMENTS` is empty, ask which feature or module should be fixed.

Follow this sequence in order:

1. Scope the change: identify the relevant files, entry points, and tests.
2. Trace dependencies: check how the feature connects to the rest of the repository.
3. Diagnose the issue: gather errors, test output, logs, or code evidence before changing anything.
4. Fix the root cause: make the smallest change that addresses the problem and keep edits focused.
5. Verify the result: run the relevant checks and summarize the outcome.

Keep the change small, documented, and easy to review.
