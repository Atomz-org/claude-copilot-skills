# code-skills

This repository is a merged standalone scaffold that combines:

- Git automation and reusable workflow infrastructure from `git-skills`
- End-to-end dbt Core analytics engineering framework from `dbt-skill` (compat alias: `senior-analytics-engineer`)

It keeps all major assets from both repositories: agents, skills, commands, rules,
scripts, templates, references, CI workflows, and tests.

## What is included

- `src/ai-core/`: RTK-style registry, graph manager, and memory store wrappers.
- `.claude/agents/`: meta-repo agents and dbt specialist agents.
- `.claude/commands/`: backward-compatible commands plus namespaced command packs.
- `.claude/skills/`: original analytics skills plus dbt-labs-to-Core translated skills.
- `.claude/rules/`: both standards and analytics non-negotiables.
- `scripts/`: artifact-driven dbt analyzers.
- `templates/`, `references/`, `use-cases/`: analytics design kit and runnable examples.
- `.github/`: CI and automation workflows.
- `tests/`: tests from both source repositories.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pytest -q
```

For dbt worked example:

```bash
.venv/bin/pip install 'dbt-core~=1.9.0' 'dbt-duckdb~=1.9.0'
cd use-cases/example-order-revenue-mart/dbt_project
./run_local.sh
```

## Slash commands

- dbt flow: `/new-use-case`, `/data-model`, `/dbt-model`, `/dbt-build`, `/dbt-test`, `/dbt-audit`, `/dbt-debug`, `/dbt-semantic`
- repo flow: `/review`, `/ship`, `/sync-submodule`, `git-standard.sh`

## Command namespaces

- Canonical infra command set: `.claude/commands/infra/`
- Canonical analytics command set: `.claude/commands/analytics/`
- Backward compatibility: original command files remain in `.claude/commands/`.

## Skill-pack architecture

Skills are now separated into reusable packs so new domains can be added cleanly:

- Shared base pack: `skill-packs/github-skills/`
- Domain pack (current): `skill-packs/dbt-skills/`

The shared GitHub pack is intended to be common across all domain packs.

Pack portability features (inspired by multi-harness marketplace patterns):

- Plugin-style pack manifests: `skill-packs/*/.claude-plugin/plugin.json`
- Portability validation script: `scripts/marketplace_portability_check.sh`
- Shared portability skill and command in `skill-packs/github-skills/.claude/`

Canonical dbt skill entrypoint:

- `dbt-skill` in `skill-packs/dbt-skills/.claude/skills/dbt-skill/SKILL.md`
- Backward-compatible alias: `senior-analytics-engineer`

### Use-case ownership by skill pack

- New use-cases must be created inside the owning pack path: `skill-packs/<pack>/use-cases/<slug>/`.
- For dbt work and dbt agents, create use-cases in `skill-packs/dbt-skills/use-cases/<slug>/`.
- Keep legacy root `use-cases/` examples as historical references unless explicitly migrated.

To activate a stack into live `.claude/` paths:

```bash
./scripts/activate_skill_stack.sh dbt-skills
```

Future packs can follow the same pattern, for example:

- `skill-packs/senior-data-scientist/`
- `skill-packs/principal-data-engineer-skills/`

## RTK, Graphify, and AgentMemory

- RTK integration layer: `src/ai-core/` and `src/ai-core/dbt-integration.ts`
- Graph snapshots: `.claude/commands/infra/lint-and-graph.sh`
- Project memory sync: `.claude/commands/infra/update-memory.sh` and `scripts/sync_context.sh`
- AgentMemory setup and usage notes: `docs/INTEGRATIONS.md`

## dbt Labs skill translation

The repository incorporates dbt-labs/dbt-agent-skills patterns translated to dbt Core under:

- `.claude/skills/dbt-labs-core-translation/`
- `.claude/skills/using-dbt-for-analytics-engineering-core/`
- `.claude/skills/running-dbt-commands-core/`
- `.claude/skills/building-dbt-semantic-layer-core/`
- `.claude/skills/adding-dbt-unit-test-core/`
- `.claude/skills/working-with-dbt-mesh-core/`
- `.claude/skills/troubleshooting-dbt-job-errors-core/`

## Feature provenance

Original root manuals from both source repositories are preserved in:

- `docs/source-manuals/README.git-skills.md`
- `docs/source-manuals/CLAUDE.git-skills.md`
- `docs/source-manuals/README.senior-analytics-engineer.md`
- `docs/source-manuals/CLAUDE.senior-analytics-engineer.md`

## Contributing

- Keep changes scoped and documented.
- Keep dbt rules and git rules consistent with `.claude/rules/`.
- For architecture questions, use graph-first flow described in `CLAUDE.md`.

## Governance and release

- Branch protection recommendations: `.github/BRANCH_PROTECTION_RECOMMENDATIONS.md`
- Manual release workflow: `.github/workflows/release.yml`
