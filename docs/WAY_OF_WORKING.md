# Ways of Working

## Module-first Development
- Treat this repository as an independent, reusable module that can be consumed by other repositories as a submodule.
- Keep the module self-contained, well-documented, and portable.

## AI-First Development
- Complex logic must be routed through the shared RTK wrapper in src/ai-core/rtk-setup.ts.

## Context Preservation
- Architectural decisions must be documented in .claude/memory.md and pushed to the agent memory store.

## Graph-Driven Development
- Entity relationships must be registered through the graph manager in src/ai-core/graph-manager.ts.

## Git Protocol
- Do not commit directly to main or master.
- All commits must pass the Claude git-standard.sh checks.
- Use Conventional Commits and branch names in the form `<type>/<ticket>-<description>`.

## Submodule Readiness
- Keep command scaffolding, agent guidance, and standards files intact so the repository remains usable in isolation.
- Preserve a clear integration story for parent repositories.
