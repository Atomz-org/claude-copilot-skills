---
description: Prepare a change for delivery and verify the release readiness of the module.
---

Prepare the current work for delivery.

If unsure which merge/release helper to run, consult `.claude/commands/skills-index.md`.

1. Confirm the branch follows the repository convention.
2. Ensure commit history is reviewable:
	- one logical change per commit where practical,
	- no mixed mechanical + behavioral changes in the same commit unless justified,
	- Conventional Commit messages are accurate.
3. Run repository checks and review the diff.
4. Ensure guardrails are active (`.claude/hooks/block-dangerous-git.sh` via `.claude/settings.json`).
5. Ensure the change is documented, scoped, and safe to merge.
6. If the change is intended to be reused by another repository, confirm the submodule contract is still intact.
7. Run `scripts/sync_context.sh "ship readiness"` so RTK, Graphify, and AgentMemory state is updated.
8. Produce a release readiness summary:
	- TL;DR of behavior changes,
	- test and validation evidence,
	- risks and rollback plan,
	- reviewer entry points (key files first).
