# claude-copilot-skills

Agent-native analytics engineering: skills, knowledge-graph context, and a governed
semantic layer for dbt Core — built for Claude Code and GitHub Copilot.

[![Repository Baseline](https://github.com/Atomz-org/claude-copilot-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/Atomz-org/claude-copilot-skills/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

The module is also consumable as a git submodule under the name `code-skills` — that is
the name its own docs and `CLAUDE.md` use internally.

> **New here — or not a data engineer at all?** Read
> [docs/START_HERE.md](docs/START_HERE.md): a plain-language tour of what this repository
> is, the one command that answers "would my change be accepted?", and a working miniature
> you can run on a laptop in about forty seconds.

## What this is

- **Skill packs for Claude Code and GitHub Copilot.** Agents, slash commands, skills, and
  binding rules live under `skill-packs/` and are activated into the paths agents load.
  Copilot gets its own guidance in `.github/copilot-instructions.md`, and CI asserts that
  file exists — the Copilot surface is a gated artifact, not a courtesy.
- **A dbt Core analytics method.** 47 binding rules
  (`.claude/rules/analytics-engineering-rules.md`), artifact-driven analyzers in
  `scripts/` that read `manifest.json` rather than the warehouse, and derived artifacts
  (lineage fragments, column contracts, the ontology index) committed to the tree — so a
  fresh clone works with no dbt installed and no warehouse credentials.
- **Knowledge-graph context.** The graphify code graph is merged with dbt's own lineage,
  so model DAGs, join topology, and column contracts are queryable during orientation
  instead of re-read from files. Uniform record output is serialized as TOON where that
  was measured to reduce bytes, and only there.
- **A WrenAI semantic serving tier.** MetricFlow metric definitions compile to MDL views,
  and `tests/test_wren_semantic_equivalence.py` holds every generated view row-for-row
  equal to a hand-written oracle. See [docs/WRENAI_INTEGRATION.md](docs/WRENAI_INTEGRATION.md)
  and [docs/SEMANTIC_LAYER_ALIGNMENT.md](docs/SEMANTIC_LAYER_ALIGNMENT.md).
  Lightdash serves the exploration tier over the same projects
  ([docs/LIGHTDASH_INTEGRATION.md](docs/LIGHTDASH_INTEGRATION.md)).
- **A Lightdash BI tier for exploration and agentic analytics.** The `lightdash` sync
  stage derives explore joins from `relationships` tests, PII hiding and AI hints from
  the column annotations, and validates offline with `lightdash compile` — while
  MetricFlow metrics reach Lightdash through its own native translation, never as a
  second definition. See [docs/LIGHTDASH_INTEGRATION.md](docs/LIGHTDASH_INTEGRATION.md).
- **An MCP surface for agents and BI.** The `wren` sync stage emits a per-use-case MCP
  server config at `wren/mcp.json` (gitignored, regenerated per clone), each use-case's
  `ontology/index.json` is a flat projection whose `mcp_tools` block names the key that
  backs each tool, and a running Lightdash instance serves MCP at `/api/v1/mcp`.

## Try it in 60 seconds

```bash
python3 -m venv .venv
.venv/bin/pip install -r .github/requirements/ci.txt
./scripts/check.sh
```

`dbt` is not needed for any of it. The derived artifacts are committed, which is what lets
a fresh clone work with no dbt and no warehouse.

For the dbt worked example:

```bash
.venv/bin/pip install 'dbt-core~=1.9.0' 'dbt-duckdb~=1.9.0'
cd skill-packs/dbt-skills/use-cases/example-order-revenue-mart/dbt_project
./run_local.sh
```

## The end-to-end demo

```bash
./skill-packs/wren-skills/demo/run_wren_demo.sh
```

No Docker, no API keys, no warehouse account — DuckDB, locally. It builds the example
use-case with dbt, imports it into WrenAI, compiles the semantic layer, and proves two
exact equalities: the governed join query matches the same aggregation run directly on
DuckDB, and `SELECT sum(revenue) FROM revenue` — the compiled metric view — equals the
filtered MetricFlow definition, not the raw measure.

## Works with

| Surface | How |
| --- | --- |
| GitHub Copilot | `.github/copilot-instructions.md` — present-checked by CI |
| Claude Code | skills, slash commands, and agents in `.claude/`, generated from `skill-packs/` |
| VS Code & GitHub Codespaces | `.devcontainer/devcontainer.json` |
| Any MCP client | per-use-case server config at `wren/mcp.json`, emitted by the `wren` sync stage |
| Lightdash | explore joins, PII hiding, and AI hints generated into dbt `meta` tags by the `lightdash` sync stage; local instance via `skill-packs/lightdash-skills/deploy/` |
| OpenMetadata | glossary, governance tags, and column-level lineage emitted by the `openmetadata` sync stage into a committed bundle, pushed one way on explicit confirmation |

## How it fits together

[public/code-skills-architecture.html](public/code-skills-architecture.html) is the
self-contained architecture page — data flow, the derivation stages and what each one
refuses to do, and the deployment surface. [docs/index.mdx](docs/index.mdx) is the same
positioning as a docs-site overview. The shape in one sentence: raw sources are declared
under contracts, ontology artifacts (taxonomy, column contracts, annotations, RDF index)
are derived from the dbt project's own `manifest.json`, and three serving tiers project
that meaning outward — WrenAI as governed SQL, Lightdash as explores and an AI analyst,
and OpenMetadata as a searchable catalog with column-level lineage.

## Verifying a change

```bash
./scripts/check.sh
```

One command, eight gates, the same ones a pull request runs and in the same order — so
green here means green there. Each failure prints what the gate was protecting and the
exact command that fixes it; [docs/DEBUGGING.md](docs/DEBUGGING.md) has the longer
version. A gate that cannot run on your machine (no Rust, no Node) reports `skipped`
rather than failing. Tests alone: `python -m pytest -q`.

The gate worth understanding before your first edit is **activation drift**. `.claude/`,
`references/`, and `templates/` are generated from `skill-packs/<pack>/`; an edit made
directly in one of them works until the next activation silently reverts it. Edit the
pack, then re-run:

```bash
./scripts/activate_skill_stack.sh dbt-skills wren-skills lightdash-skills openmetadata-skills
```

## Slash commands

| Family | Commands |
| --- | --- |
| dbt flow | `/new-use-case`, `/data-model`, `/dbt-model`, `/dbt-build`, `/dbt-test`, `/dbt-audit`, `/dbt-debug`, `/dbt-semantic`, `/new-connector`, `/sync-context` |
| repo flow | `/review`, `/ship`, `/pr-ready`, `/pr-merge`, `/branch-plan`, `/resolve-conflicts`, `/focused-fix`, `/write-docs`, `/sync-submodule`, `/skills-index` |
| setup | `/setup-git-guardrails`, `/setup-pre-commit`, `/marketplace-portability` |

The full inventory, indexed by intent, is [docs/skills-inventory.md](docs/skills-inventory.md).

## Skill-pack architecture

Packs are the source of truth; activation materialises them into the paths agents load:

| Asset | Source of truth | Materialised to |
| --- | --- | --- |
| agents, skills, commands, rules, hooks | `skill-packs/<pack>/.claude/` | `.claude/` |
| `references/`, `templates/` | `skill-packs/<pack>/` | repository root |
| use-cases | `skill-packs/<pack>/use-cases/` | not copied |

Skills link to shared assets with one relative path — `../../references/x.md` — which is
why both copies must exist: it resolves inside the pack *and* after activation.

Current packs: `skill-packs/github-skills/` (shared base), `skill-packs/dbt-skills/`
(analytics domain), `skill-packs/wren-skills/` (semantic serving),
`skill-packs/lightdash-skills/` (BI serving), `skill-packs/openmetadata-skills/`
(catalog and discovery). Each carries a
`.claude-plugin/plugin.json` manifest, validated by
`scripts/marketplace_portability_check.sh`. The canonical dbt entrypoint is `dbt-skill`
(`skill-packs/dbt-skills/.claude/skills/dbt-skill/SKILL.md`); `senior-analytics-engineer`
is its compatibility alias.

## Use-case ownership

- New use-cases are created inside the owning pack: `skill-packs/<pack>/use-cases/<slug>/`.
- For dbt work, that means `skill-packs/dbt-skills/use-cases/<slug>/`.
- The worked examples live in the pack; there is no root `use-cases/` directory.

## More documentation

- [docs/WAY_OF_WORKING.md](docs/WAY_OF_WORKING.md) — the delivery contract
- [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) — RTK, Graphify, TOON, and AgentMemory
- [docs/OPENMETADATA_INTEGRATION.md](docs/OPENMETADATA_INTEGRATION.md) — the discovery
  tier: what the catalog bundle carries, what it refuses to publish, and how to push it
- [docs/OPENMETADATA_INTEGRATION.md](docs/OPENMETADATA_INTEGRATION.md) — the discovery tier
  (the wrappers live in `src/ai-core/`)
- [docs/BRANCHING_STRATEGY.md](docs/BRANCHING_STRATEGY.md) — trunk, stacks, and conflict
  prevention
- [docs/AUTOMATION_WORKFLOW.md](docs/AUTOMATION_WORKFLOW.md) — what runs on every PR
- [docs/use-cases.md](docs/use-cases.md) — the worked examples
- `docs/source-manuals/` — the original manuals of the merged source repositories,
  preserved for provenance

## Contributing, security, and governance

- [Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md) ·
  [Support](SUPPORT.md) · [Code of conduct](CODE_OF_CONDUCT.md)
- License: [MIT](LICENSE)
- Branch protection recommendations:
  `.github/BRANCH_PROTECTION_RECOMMENDATIONS.md`
- Releases: `.github/workflows/release.yml`, a manual `workflow_dispatch` run that takes a
  version tag input
