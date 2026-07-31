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

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| `/setup-git-guardrails` | Hook script and settings entry installed, existing hooks merged, then a live payload test |
| "are the guardrails actually on?" | The verification run, not a reading of the config file |
| "unblock git push" | The change refused by default in a shared stack; explicit repository approval is required |

**Worked example**

> `/setup-git-guardrails`

```
.claude/hooks/block-dangerous-git.sh   present, mode 644 → chmod +x
.claude/settings.json                  1 existing PreToolUse entry (formatter) → merged, not replaced

Verify — blocked path
  $ echo '{"tool_input":{"command":"git push --force origin main"}}' | .claude/hooks/block-dangerous-git.sh
  BLOCKED: git push
  exit 2

Verify — allowed path
  $ echo '{"tool_input":{"command":"git status --porcelain"}}' | .claude/hooks/block-dangerous-git.sh
  exit 0
```

Both probes matter. A hook that blocks everything, and a hook that blocks nothing, both
exit cleanly on the first probe alone.
