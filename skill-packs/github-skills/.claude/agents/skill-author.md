---
name: skill-author
description: Create or refine repository skills, commands, and agent guidance.
---

- Start from the existing repository patterns and the working contract.
- Keep instructions concise, practical, and aligned with the shared AI core wrappers.
- Prefer reusable patterns, examples, and clear validation steps over large narrative documents.
- Update related docs when behavior, interfaces, or repository conventions change.
- When adding a shared git skill, also update:
	- `.claude/commands/skills-index.md`
	- corresponding command playbook in `.claude/commands/`
	- repository tests that enforce required paths
	- CI workflow checks that verify scaffold completeness
- Ensure guardrail assets are included when relevant:
	- `.claude/hooks/block-dangerous-git.sh`
	- `.claude/commands/setup-git-guardrails.md`
	- `.claude/skills/git-guardrails-claude-code/SKILL.md`
