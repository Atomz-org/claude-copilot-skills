---
name: git-guardrails-claude-code
description: Set up and verify PreToolUse hook guardrails that block destructive git commands before execution.
---

# Git Guardrails for Claude/Copilot Workflows

Use this skill to protect repositories from destructive git commands run by agents.

## What is blocked

- `git push` (including force variants)
- `git reset --hard`
- `git clean -f` / `git clean -fd`
- `git branch -D`
- `git checkout .`
- `git restore .`

## Workflow

1. Ensure `.claude/hooks/block-dangerous-git.sh` exists and is executable.
2. Ensure `.claude/settings.json` has a `PreToolUse` hook entry for Bash commands.
3. Keep existing hooks and merge entries rather than overwriting.
4. Verify with a dry payload test:

```bash
echo '{"tool_input":{"command":"git push origin main"}}' | .claude/hooks/block-dangerous-git.sh
```

Expected result: non-zero exit and BLOCKED message.

## Guardrails

- Do not disable this hook in shared stacks.
- Adjust blocked patterns only with explicit repository approval.
