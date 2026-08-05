> **Frozen provenance copy — not live guidance.** The original root manual from the
> `dbt-skills` source repository, preserved for history per
> [README.md § Feature provenance](../../README.md). It may contradict current behavior and
> must not be followed or edited to match. The live operating manual is
> [CLAUDE.md](../../CLAUDE.md); the live dbt rules are
> [.claude/rules/analytics-engineering-rules.md](../../.claude/rules/analytics-engineering-rules.md).

# dbt Skill Scaffold

A scaffold for turning any data request into a working, tested, documented **dbt Core**
transformation. The method lives in [.claude/](../../.claude/); the work lives in
[skill-packs/dbt-skills/use-cases/](../../skill-packs/dbt-skills/use-cases/).

Everything here is dbt Core — the open-source CLI, run on infrastructure you control,
reading and writing the JSON artifacts in `target/`. Where dbt Cloud sells a hosted
service, this scaffold documents the Core equivalent and names the gap explicitly.

## How this repo is wired

| Component | Location | Role |
|---|---|---|
| Agents | [.claude/agents/](../../.claude/agents/) | who does the work |
| Skills | [.claude/skills/](../../.claude/skills/) | how each stage is done |
| Rules | [.claude/rules/analytics-engineering-rules.md](../../.claude/rules/analytics-engineering-rules.md) | what is never negotiable |
| Commands | [.claude/commands/](../../.claude/commands/) | `/new-use-case`, `/data-model`, `/dbt-model`, `/dbt-build`, `/dbt-test`, `/dbt-audit`, `/dbt-debug`, `/dbt-semantic` |
| Templates | [templates/](../../templates/) | the deliverable shapes — specs, blueprints, YAML and SQL patterns, runbooks |
| References | [../../skill-packs/dbt-skills/references/](../../skill-packs/dbt-skills/references/) | method and syntax depth, loaded on demand |
| Scripts | [scripts/](../../scripts/) | eleven artifact-driven analyzers |
| Use cases | [skill-packs/dbt-skills/use-cases/](../../skill-packs/dbt-skills/use-cases/) | one directory per data request |

## Agents

- **`dbt-skill`** — the canonical entry point (compatibility alias: `senior-analytics-engineer`). Takes a data request end to end and
  delegates specialized depth.
- **`data-modeler`** — entities, ERD, keys, grain, bus matrix, conformed dimensions, star schemas, SCD strategy.
- **`dbt-model-designer`** — grain, layers, joins, materialization, incremental strategy, SQL.
- **`data-contract-owner`** — sources, freshness, contracts, versions, access, downstream impact.
- **`analytics-quality-guardian`** — data tests, unit tests, documentation, coverage, merge verdict.
- **`semantic-layer-architect`** — semantic models, metrics, time spine, MetricFlow validation.
- **`dbt-troubleshooter`** — failed runs, tests, compiles, and performance regressions, from artifacts.

## Skills

Each loads only when its stage is in play:

- **`dbt-project-setup`** — `dbt_project.yml`, `profiles.yml`, adapters, packages, `dbt debug`, MCP for Core.
- **`analytics-request-framing`** — vague request → written use-case spec. Always first.
- **`data-modeling`** — entities, ERDs, keys, grain, normalization, bus matrix, star schemas, SCD 0–6, paradigm choice.
- **`dbt-model-design`** — sources, grain, staging/intermediate/marts, joins, materialization, SQL.
- **`incremental-and-snapshots`** — incremental strategies, late-arriving data, microbatch, snapshots and SCD2.
- **`testing-and-documentation`** — `schema.yml`, data tests, docs blocks, exposures, coverage.
- **`dbt-unit-testing`** — fixed-input/fixed-output tests for models with real logic.
- **`semantic-layer-metricflow`** — semantic models, the six metric types, `mf query`, answering questions.
- **`dbt-mesh-governance`** — contracts, groups, `access:`, versions, multi-project on Core.
- **`running-dbt-commands`** — which command, which selector, which flags, and what not to run.
- **`ops-and-deployment`** — environments, slim CI with state, orchestration, rollback.
- **`performance-and-cost`** — finding the slow model and fixing the right thing.
- **`troubleshooting-dbt`** — triage from `run_results.json`, error taxonomy, investigation loop.
- **`migration-and-refactoring`** — legacy SQL into dbt, warehouse swaps, version upgrades, safe refactors.

## Commands

- `/new-use-case <request>` — frame a data request into a use-case spec.
- `/data-model <subject area>` — entities, ERD, keys, grain, bus matrix, star schema spec.
- `/dbt-model <concept>` — design and scaffold a model end to end.
- `/dbt-build <model or selector>` — define the build scope and the acceptance bar.
- `/dbt-test <model or selector>` — write the test plan before merge.
- `/dbt-audit [path]` — health sweep, ranked and actionable.
- `/dbt-debug <error or node>` — triage a failure from the artifacts.
- `/dbt-semantic <metric>` — define and validate a metric.

## Scripts

All eleven are standard-library Python — no install step, no warehouse connection. They
read dbt's own artifacts, so run any `dbt` command (`dbt parse` is enough) first.

```bash
# 20 project-health rules. --strict exits 1 on any error-severity finding — use it in CI.
python scripts/dbt_project_auditor.py --manifest target/manifest.json --project-dir . --strict

# Blast radius before you change something, and a Mermaid DAG for the PR description.
python scripts/model_dependency_analyzer.py --manifest target/manifest.json \
    --model fct_orders --direction down --mermaid

# Coverage ranked by how much depends on the untested model, not alphabetically.
python scripts/test_coverage_reporter.py --manifest target/manifest.json \
    --layer marts --min-coverage 0.9 --strict

# Where the build time actually went, and what regressed since the last run.
python scripts/run_results_analyzer.py --run-results target/run_results.json \
    --manifest target/manifest.json --top 15 --compare prod/run_results.json

# Freshness breaches, each annotated with the marts it blocks.
python scripts/source_freshness_monitor.py --sources target/sources.json \
    --manifest target/manifest.json --strict

# Skeleton schema.yml with tests inferred from column names and types.
python scripts/schema_yml_generator.py --manifest target/manifest.json \
    --model stg_orders --catalog target/catalog.json --infer-tests

# Unit test scaffold: every ref and source stubbed, typed for your adapter.
python scripts/unit_test_generator.py --manifest target/manifest.json \
    --model int_order_items --adapter snowflake --format dict

# Catch MetricFlow spec errors locally, before mf validate-configs hits the warehouse.
python scripts/semantic_layer_validator.py --path models/ --strict

# Breaking-change gate: diff the PR manifest against production's.
python scripts/contract_breaking_change_detector.py \
    --base prod/manifest.json --head target/manifest.json --strict

# Mermaid ERD of the marts: tested FKs solid, naming-inferred FKs dashed.
python scripts/erd_generator.py --manifest target/manifest.json \
    --layer marts --format markdown --out docs/erd.md

# 15 star-schema rules the project auditor deliberately does not cover.
python scripts/dimensional_model_validator.py --manifest target/manifest.json --strict
```

## Working sequence

1. **Frame** — `/new-use-case <request>` writes `skill-packs/dbt-skills/use-cases/<slug>/use-case-spec.md`.
   Nothing is modeled until the decision sentence and the grain are written down.
2. **Model** — for any subject area producing more than one model: entities, ERD with
   cardinality *and* optionality, keys, grain per table, bus matrix, star schema spec.
   Skip only when it is one model on one source with an obvious grain.
3. **Contract the sources** — `sources.yml` with freshness, and a staging model per source
   table. Sources first: a mart built on an unstable source is rework waiting to happen.
4. **Design** — grain, layers, joins, materialization. Write the model blueprint before
   the SQL.
5. **Build** — staging → intermediate → marts, one layer at a time, running
   `dbt build --select <model>` as you go.
6. **Test** — `unique` + `not_null` on every PK, `relationships` on every FK, a unit test
   for every piece of real logic, and a data test for every assumption in the spec.
7. **Document** — grain and meaning in the description, shared definitions in `docs`
   blocks, consumers in `exposures:`.
8. **Define metrics** — semantic models on the marts, metrics validated with
   `mf validate-configs` and sanity-checked with `mf query`.
9. **Ship** — slim CI with `state:modified+`, breaking-change check against production,
   stated rollback path, named owner.

Stuck? [../../skill-packs/dbt-skills/references/troubleshooting.md](../../skill-packs/dbt-skills/references/troubleshooting.md) maps symptoms to
causes for dbt, the warehouse, and these tools.

## The rules that override everything

Full list in [.claude/rules/analytics-engineering-rules.md](../../.claude/rules/analytics-engineering-rules.md).
The five that matter most:

- **No model before a use-case spec, no mart without a named consumer.** If nothing
  changes based on the output, it is a reporting request — write the query and say so.
- **Declare the grain in one sentence** before writing SQL: "one row per `<entity>` per
  `<period>`". Every downstream ambiguity traces back to a grain nobody wrote down.
- **`source()` and `ref()` only.** A hardcoded table name is invisible to lineage,
  `--select`, and state comparison — it breaks every tool in this repo and dbt itself.
- **`dbt build`, never `dbt run` then `dbt test`.** `build` interleaves tests with models
  and stops dependents on failure; run-then-test propagates bad data through the whole DAG
  before anything fails.
- **Never invent a number or a table name.** Unknown row counts, freshness SLAs, and
  source names are marked `[NEEDS INPUT]` and the design continues around them.
- **One entity, one definition, one table.** A dimension shared by two business processes
  must be conformed — same key, same table. Two `dim_customer`s means the two stars can
  never be compared, and nothing in dbt will tell you.

## Example

[skill-packs/dbt-skills/use-cases/example-order-revenue-mart/](../../skill-packs/dbt-skills/use-cases/example-order-revenue-mart/) is a
complete worked case that **runs**:

```bash
python3 -m venv .venv && .venv/bin/pip install 'dbt-core~=1.9.0' 'dbt-duckdb~=1.9.0'
cd skill-packs/dbt-skills/use-cases/example-order-revenue-mart/dbt_project && ./run_local.sh
```

DuckDB, no credentials, ~40 seconds: seeds, source freshness, every model, 52 data tests,
6 unit tests, an SCD2 snapshot, a full-refresh-vs-incremental equivalence check, the
catalog, and then all eleven analyzers against the artifacts it just produced. The same
project runs on BigQuery and Snowflake via `./run_local.sh bigquery|snowflake` — the
portability layer is in `macros/cross_db.sql`.

It also ships a second, synthetic artifact set under `artifacts/` carrying ten planted
defects, because a healthy project makes a poor tool demo. Read the README for what broke
during development and where each fix lives.
