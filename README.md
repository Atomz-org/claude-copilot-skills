# code-skills

> **New here — or not a data engineer at all?** Read
> [docs/START_HERE.md](docs/START_HERE.md): a plain-language tour of what this repository
> is, the one command that answers "would my change be accepted?", and a working miniature
> you can run on a laptop in about forty seconds.

This repository is a merged standalone scaffold that combines:

- Git automation and reusable workflow infrastructure from `git-skills`
- End-to-end dbt Core analytics engineering framework from `dbt-skill` (compat alias: `senior-analytics-engineer`)
- The WrenAI semantic layer / GenBI engine as the serving tier over dbt use-cases —
  source pinned at `external/WrenAI`, runtime pinned in `requirements.txt`, agent surface
  in `skill-packs/wren-skills/`. See [docs/WRENAI_INTEGRATION.md](docs/WRENAI_INTEGRATION.md)
  and run `./skill-packs/wren-skills/demo/run_wren_demo.sh` for the local end-to-end proof.

It keeps all major assets from both repositories: agents, skills, commands, rules,
scripts, templates, references, CI workflows, and tests.

## What is included

- `src/ai-core/`: RTK-style registry, graph manager, and memory store wrappers.
- `.claude/agents/`: meta-repo agents and dbt specialist agents.
- `.claude/commands/`: backward-compatible commands plus namespaced command packs.
- `.claude/skills/`: original analytics skills plus dbt-labs-to-Core translated skills.
- `.claude/rules/`: both standards and analytics non-negotiables.
- `scripts/`: artifact-driven dbt analyzers plus the stack activation and portability checks.
- `templates/`, `references/`: analytics design kit, **generated** at the repository root by
  `scripts/activate_skill_stack.sh` from the active pack. Edit the pack copy under
  `skill-packs/<pack>/`, never the root mirror — activation overwrites it.
- `use-cases/`: the directory a consuming repository fills in. Worked examples ship inside
  the pack at `skill-packs/dbt-skills/use-cases/`.
- `.github/`: CI and automation workflows.
- `tests/`: tests from both source repositories, plus documentation-integrity checks.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r .github/requirements/ci.txt
./scripts/check.sh
```

`dbt` is not needed for any of it. The derived artifacts are committed, which is what lets a
fresh clone work with no dbt and no warehouse.

For dbt worked example:

```bash
.venv/bin/pip install 'dbt-core~=1.9.0' 'dbt-duckdb~=1.9.0'
cd skill-packs/dbt-skills/use-cases/example-order-revenue-mart/dbt_project
./run_local.sh
```

## Verifying a change

```bash
./scripts/check.sh
```

One command, seven gates, the same ones a pull request runs and in the same order — so green
here means green there. Each failure prints what the gate was protecting and the exact
command that fixes it; [docs/DEBUGGING.md](docs/DEBUGGING.md) has the longer version. It
changes nothing you have not committed, and a gate that cannot run on your machine (no Rust,
no Node) reports `skipped` rather than failing.

The gate worth understanding before you make your first edit is **activation drift**.
`.claude/`, `references/`, and `templates/` are generated from `skill-packs/<pack>/`; an edit
made directly in one of them works until the next activation silently reverts it. Edit the
pack, then re-run `./scripts/activate_skill_stack.sh dbt-skills wren-skills`.

## Slash commands

- dbt flow: `/new-use-case`, `/data-model`, `/dbt-model`, `/dbt-build`, `/dbt-test`,
  `/dbt-audit`, `/dbt-debug`, `/dbt-semantic`, `/new-connector`, `/sync-context`
- repo flow: `/review`, `/ship`, `/pr-ready`, `/pr-merge`, `/branch-plan`,
  `/resolve-conflicts`, `/focused-fix`, `/write-docs`, `/sync-submodule`, `/skills-index`
- setup: `/setup-git-guardrails`, `/setup-pre-commit`, `/marketplace-portability`
- shell entrypoints: `.claude/commands/infra/git-standard.sh`, `update-memory.sh`,
  `lint-and-graph.sh`

`/new-connector` onboards a source system into an existing use-case's dbt project by
detecting that project's own conventions; `scripts/new_connector.py` does the scaffolding.

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
- Root `use-cases/` holds the working method only; the worked examples now live in the pack.

### Where an asset lives

The pack is the source of truth. Activation copies it into the paths agents actually load:

| Asset | Source of truth | Materialised to |
| --- | --- | --- |
| agents, skills, commands, rules, hooks | `skill-packs/<pack>/.claude/` | `.claude/` |
| `references/`, `templates/` | `skill-packs/<pack>/` | repository root |
| use-cases | `skill-packs/<pack>/use-cases/` | not copied |

Skills and agents link to these with one relative path — `../../references/x.md` — which is
why both copies must exist: it resolves inside the pack *and* after activation. Editing a
materialised copy directly is silently reverted on the next activation.

To activate a stack into live `.claude/` paths:

```bash
./scripts/activate_skill_stack.sh dbt-skills wren-skills
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
- `docs/source-manuals/README.dbt-skills.md`
- `docs/source-manuals/CLAUDE.dbt-skills.md`

## Contributing

- Keep changes scoped and documented.
- Keep dbt rules and git rules consistent with `.claude/rules/`.
- For architecture questions, use graph-first flow described in `CLAUDE.md`.

## Governance and release

- Branch protection recommendations: `.github/BRANCH_PROTECTION_RECOMMENDATIONS.md`
- Manual release workflow: `.github/workflows/release.yml`
