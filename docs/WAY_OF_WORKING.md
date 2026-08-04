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

## Conflict Prevention
Every conflict this repository has produced falls into one of three classes, each with its
own rule:

- **Branch from fresh `origin/main`, always.** `git fetch origin` immediately before
  `git checkout -b`. The `PR Auto Update` workflow keeps open PR branches current with main
  after that, so a divergence never grows past one merge; a PR it cannot update (GitHub
  reports it conflicting) gets a comment with the resolution recipe.
- **One change lands from one checkout.** This remote is cloned more than once
  (`code-skills` and `claude-copilot-skills` are the same repository). Starting the same
  work in both produces add/add conflicts between files with near-identical content —
  the worst kind, because every line differs slightly. Pick the checkout, finish there.
- **Generated artifacts are regenerated, never hand-merged.** `graphify-fragment.json`,
  `column-memory.json`, ontology outputs, and sample seeds are produced by
  `scripts/use_case_sync.py` and gated for freshness in CI. On a merge, keep either side
  and re-run `python3 scripts/use_case_sync.py --all`; the `.gitattributes` `generated`
  merge driver (registered per clone by `scripts/setup_git_merge_drivers.sh`, which
  activation runs for you) does the "keep ours" half automatically. `.gitignore` merges by
  `union` — appends from both sides survive without a conflict, but review the result when
  both sides rewrote the same lines.

## Submodule Readiness
- Keep command scaffolding, agent guidance, and standards files intact so the repository remains usable in isolation.
- Preserve a clear integration story for parent repositories.
