# Hook wiring

Registered in `.claude/settings.json`. Read this before editing a
`command` string there.

## Why the commands look the way they do

Hook commands resolve the repository root themselves and never assume one
runtime's environment.

$CLAUDE_PROJECT_DIR is set by Claude Code and by nothing else. Any other
harness that reads this file — GitHub Copilot CLI does — expands it to the
empty string, so "$CLAUDE_PROJECT_DIR/scripts/hooks/x.sh" becomes the
absolute path "/scripts/hooks/x.sh", bash exits 127, and a runtime that
treats a failing PreToolUse hook as a refusal blocks every tool call the
agent makes. The agent reports it cannot run anything; the actual cause is
one line of 'No such file or directory' that nobody sees.

So each command falls back to the git toplevel, then to the working
directory. Optional hooks additionally degrade to a no-op when their script
or binary is absent — a token optimisation must never be able to stop an
agent, and an absolute path into one developer's home directory is not a
dependency a submodule consumer can satisfy. block-dangerous-git.sh
deliberately does NOT degrade: a guardrail that disappears when its script
goes missing is worse than one that blocks.

Pinned by tests/test_hook_command_portability.py.

## The rule

A hook command must run correctly under **any** harness that reads this file,
from **any** working directory, on **any** machine. Three things follow:

- resolve the repository root yourself — `${CLAUDE_PROJECT_DIR:-$(git rev-parse
  --show-toplevel 2>/dev/null || pwd)}`;
- never write an absolute path into a home directory;
- optional hooks end in `|| true`, the guardrail does not.

`tests/test_hook_command_portability.py` enforces all three, and asserts the
original broken form still fails so the check cannot quietly stop testing
anything.
