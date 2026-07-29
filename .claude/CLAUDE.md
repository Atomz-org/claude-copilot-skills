# Repository Guidance

This repository is a standards-driven module designed to be reused as an independent submodule by other repositories.

## Core conventions
- Follow the working contract in [docs/WAY_OF_WORKING.md](../docs/WAY_OF_WORKING.md).
- Route AI-facing logic through the shared wrappers in [src/ai-core/rtk-setup.ts](../src/ai-core/rtk-setup.ts), [src/ai-core/graph-manager.ts](../src/ai-core/graph-manager.ts), and [src/ai-core/memory-store.ts](../src/ai-core/memory-store.ts).
- Use `dbt-skill` as the canonical dbt skill entrypoint (compatibility alias: `senior-analytics-engineer`).
- Keep the module self-contained, documented, and easy to adopt from a parent repository.
- Record important architectural decisions in [.claude/memory.md](memory.md) and update the memory store when the change is material.
- Preserve a reusable command/agent structure so this module can plug into different repositories without adaptation.
- Keep new domain use-cases under their owning pack path (`skill-packs/<pack>/use-cases/<slug>/`).

## Git and delivery
- Do not commit directly to main or master.
- Use Conventional Commits and pass the repository Git checks before merging.
- Prefer focused changes with a paired test file for new logic.
- Keep the module compatible with submodule-based integration and review workflows.
