---
description: Configure and verify git guardrail hooks for agent-driven Bash operations.
---

Set up git guardrails.

1. Verify hook script exists:
   - `.claude/hooks/block-dangerous-git.sh`
2. Ensure executable bit is set:
   - `chmod +x .claude/hooks/block-dangerous-git.sh`
3. Ensure `.claude/settings.json` includes a `PreToolUse` Bash hook invoking the script.
4. Verify behavior:
   - `echo '{"tool_input":{"command":"git push origin main"}}' | .claude/hooks/block-dangerous-git.sh`
5. Confirm expected output includes `BLOCKED` and exit code 2.
