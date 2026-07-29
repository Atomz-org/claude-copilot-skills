# GitHub Copilot Instructions

## Tone & Style
- Be concise, explicit, and expert-level.
- Avoid conversational filler and unnecessary commentary.

## Code Standards
- Any new AI feature must import from src/ai-core and use the standardized wrappers for rtk, graphify, and agentmemory.
- Favor small, composable modules with clear interfaces and documentation.
- Keep naming consistent and avoid duplicated logic.

## Git Standards
- Use Conventional Commits for all commit messages.
- Prefer the format: feat:, fix:, chore:, or docs: followed by a short description.

## Testing
- Every new logic change must include a paired test file.
- Prefer fast, focused tests that exercise the real behavior of the module.
