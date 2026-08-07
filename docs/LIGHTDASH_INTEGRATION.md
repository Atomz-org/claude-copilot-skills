# Lightdash integration

Lightdash is this repository's BI and agentic-analytics tier: dbt models become
explores, MetricFlow metrics are translated natively by its CLI, and the bridge
projects into `meta` tags exactly the knowledge dbt alone cannot express — explore
joins, primary keys, PII hiding, and AI hints. WrenAI serves governed SQL and the
full metric definitions; Lightdash serves the exploration surface and the in-app AI
analyst. The two tiers are complementary, and `lightdash/knowledge/semantic-coverage.md`
in each use-case states precisely which metrics each one carries.

## How it is included, and why this shape

- **Source** is pinned as a fork submodule at `external/lightdash`
  (https://github.com/PackMaaan/lightdash, upstream lightdash/lightdash; MIT with an
  EE-licensed `packages/backend/src/ee` carve-out), shallow-cloned
  (`shallow = true` in `.gitmodules` — the full history is ~486 MB).
- **Runtime** is `@lightdash/cli`, installed repo-local and gitignored:
  `npm install --prefix .lightdash-cli @lightdash/cli@1.97.0`. The submodule SHA, the
  CLI version, and the deploy image tag are the same release and move together — the
  same lockstep rule as the WrenAI submodule and wheel.
- **Bridge** is `scripts/lightdash_context_sync.py`, run as the `lightdash` stage of
  `use_case_sync.py` — sequenced after `wren`, because it projects the
  `column-annotations.json` the earlier stages refresh.
- **Agent surface** is `skill-packs/lightdash-skills/` (skill `lightdash-bi`, command
  `/lightdash`, rules `.claude/rules/lightdash-rules.md`).

## What the bridge adds (and what it refuses to)

| It writes | Derived from | It refuses to |
| --- | --- | --- |
| `meta.joins` on child models | dbt `relationships` tests | invent a join no test declares |
| `relationship:` cardinality | `unique` tests | guess cardinality where untested (key omitted) |
| `meta.primary_key` | the one unique+not_null column | choose among ambiguous keys (reported instead) |
| `dimension.hidden: true` | `column-annotations.json` `pii: direct` | hide by name-pattern, or touch quasi-PII (remedies differ) |
| `dimension.ai_hint` | recorded definitions + additivity | paraphrase or embellish an annotation |
| `lightdash/knowledge/*.md` | manifest + upstream translator rules | — |

Two refusals define the integration:

- **It never writes a metric.** The Lightdash CLI translates MetricFlow metrics from
  `manifest.json` itself (simple metrics, and ratio/derived metrics whose inputs stay
  on one semantic model). Restating one as a `meta.metrics` block would be a second
  source of truth — analytics rule 42. The classes the translator skips (cumulative,
  conversion, time-offset, cross-model inputs or filters) are served by the Wren
  metric views instead, and named per-metric in `semantic-coverage.md`. Measured on
  example-order-revenue-mart: the bridge's classifier and the upstream translator
  agree 7/7 — 3 translated, 4 skipped, identical reasons.
- **It never edits what it does not own.** Meta blocks carry an inline
  `# generated: lightdash_context_sync` marker; a `meta:` without the marker is
  hand-authored and left alone, and a schema file headed by another generator
  (`schema_generated.yml`, owned by `ontology_to_dbt.py`) is refused whole, with the
  reason in the payload.

The offline compile gate (`lightdash compile --skip-dbt-compile
--skip-warehouse-catalog`) validates explores with no server and no warehouse. Its
verdict separates what the bridge caused from what it observed: `fail` only when a
failing explore carries bridge meta; a project whose columnless models cannot compile
offline is `unready` — counted, explained, never red. Measured: the example compiles
8/8 explores; enhanza-analytics reports 172/267 pre-existing failures with all 42
join-bearing models compiling clean.

## Running it

```bash
# the one regeneration path (meta tags + lightdash/knowledge/)
python3 scripts/use_case_sync.py --use-case example-order-revenue-mart --stage lightdash

# meta changed? re-parse so the manifest carries it — Lightdash reads the manifest
./skill-packs/dbt-skills/use-cases/example-order-revenue-mart/artifacts/refresh.sh

# the no-server gate, directly
.lightdash-cli/node_modules/.bin/lightdash compile \
  --project-dir skill-packs/dbt-skills/use-cases/example-order-revenue-mart/dbt_project \
  --profiles-dir skill-packs/dbt-skills/use-cases/example-order-revenue-mart/dbt_project \
  --skip-dbt-compile --skip-warehouse-catalog

# a local instance (podman-compose; no repository bind mounts — deploy pushes instead)
podman-compose -f skill-packs/lightdash-skills/deploy/podman-compose.yml up -d
```

Without Node or the CLI every gate skips with the install command named — the
toolchain is optional here, like rustc everywhere else in this repository.

## Day-to-day agent workflow

- Orient from the generated knowledge: `lightdash/knowledge/semantic-coverage.md`
  (which metrics live where, which joins exist) and `lightdash/knowledge/mcp.md`
  (registering the instance MCP at `/api/v1/mcp` — environment variables only, no
  tokens on disk).
- The in-app AI analyst reads the same `ai_hint`s the bridge derived from
  `column-annotations.json`, so the aggregation prohibitions and PII rules an agent
  sees in Wren's knowledge files reach Lightdash's agents too — one annotation store,
  two serving tiers.
- `lightdash deploy` / previews to any non-local instance is data egress:
  explicit per-deploy confirmation, every time (lightdash-rules.md rule 9).
