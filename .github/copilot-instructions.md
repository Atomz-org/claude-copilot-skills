# GitHub Copilot Instructions

## Tone & Style
- Be concise, explicit, and expert-level.
- Avoid conversational filler and unnecessary commentary.

## Code Standards
- Any new AI feature must import from src/ai-core and use the standardized wrappers for rtk, graphify, and agentmemory.
- Favor small, composable modules with clear interfaces and documentation.
- Keep naming consistent and avoid duplicated logic.

## AI Runtime Workflow
- For material code or git workflow changes, run `scripts/sync_context.sh` to persist AgentMemory updates and Graphify snapshots.
- Prefer repository wrappers and scripts over ad-hoc direct calls so RTK, Graphify, and AgentMemory stay in sync.
- Keep integration references aligned with `src/ai-core/rtk-setup.ts`, `src/ai-core/graph-manager.ts`, and `src/ai-core/memory-store.ts`.

## Git Standards
- Use Conventional Commits for all commit messages.
- Prefer the format: feat:, fix:, chore:, or docs: followed by a short description.
- Keep `.claude/hooks/block-dangerous-git.sh` enabled in `.claude/settings.json` PreToolUse hooks.
- Do not bypass guardrails for destructive git commands from agent-driven Bash operations.

## Testing
- Every new logic change must include a paired test file.
- Prefer fast, focused tests that exercise the real behavior of the module.
