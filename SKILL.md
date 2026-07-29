---
name: dbt-skill
description: Turn a data request into a working, tested, documented dbt Core implementation — request framing, conceptual and dimensional data modeling (entities, ERDs, keys, grain, bus matrix, star schemas, SCD types), source contracts, staging/intermediate/mart design, incremental and snapshot strategy, data tests and unit tests, MetricFlow semantic models and metrics, contracts/versions/access governance, CLI and node selection, state-based slim CI, performance and cost tuning, failure triage, and migrations. Routes to the focused skills in .claude/skills/. Use for anything involving dbt, dbt Core, dbt build/run/test, ref(), source(), staging models, marts, incremental models, snapshots, schema.yml, dbt tests, dbt docs, manifest.json, MetricFlow, metrics, semantic models, dbt packages, dbt macros, model contracts, or a warehouse transformation layer. Also for data modeling questions — entity design, ERD, star schema, conformed dimensions, slowly changing dimensions, normalization, Kimball/Inmon/Data Vault.
---

# dbt Skill

Canonical entrypoint skill name: `dbt-skill`.

Compatibility alias: `senior-analytics-engineer`.

Entry point for this scaffold. The method is split across fourteen focused skills; load
the one that matches the stage you are in rather than all of them.

**dbt Core only.** Everything here runs from the `dbt` CLI on a machine you control plus
the JSON artifacts in `target/`. Where dbt Cloud provides a hosted service — scheduler,
Semantic Layer API, Discovery API, managed CI — this scaffold gives the dbt Core
equivalent and says so.

| Stage | Skill | Use when |
|---|---|---|
| 0. Set up | [dbt-project-setup](.claude/skills/dbt-project-setup/SKILL.md) | no project yet, a broken `profiles.yml`, adapters, packages, or `dbt debug` fails |
| 1. Frame | [analytics-request-framing](.claude/skills/analytics-request-framing/SKILL.md) | a request has not yet been written down as a use case — **always first** |
| 2. Model | [data-modeling](.claude/skills/data-modeling/SKILL.md) | entities, ERD, keys, grain, bus matrix, star schema — **before** the first blueprint, when a subject area needs more than one model |
| 3. Design | [dbt-model-design](.claude/skills/dbt-model-design/SKILL.md) | sources, grain, layers, and the SQL for staging → intermediate → marts |
| 4. Load | [incremental-and-snapshots](.claude/skills/incremental-and-snapshots/SKILL.md) | the table is too big or too slow to rebuild, or history must be captured |
| 5. Test | [testing-and-documentation](.claude/skills/testing-and-documentation/SKILL.md) | data tests, `schema.yml`, descriptions, docs blocks, exposures |
| 6. Prove | [dbt-unit-testing](.claude/skills/dbt-unit-testing/SKILL.md) | the model has logic — CASE, windows, regex, date math, fan-out joins |
| 7. Define | [semantic-layer-metricflow](.claude/skills/semantic-layer-metricflow/SKILL.md) | metrics need one definition, or you are answering questions with `mf query` |
| 8. Govern | [dbt-mesh-governance](.claude/skills/dbt-mesh-governance/SKILL.md) | contracts, `access:`, groups, model versions, multi-project |
| 9. Run | [running-dbt-commands](.claude/skills/running-dbt-commands/SKILL.md) | which command, which selector, which flags — and what not to run |
| 10. Ship | [ops-and-deployment](.claude/skills/ops-and-deployment/SKILL.md) | environments, slim CI with `state:modified+`, scheduling, rollback |
| 11. Tune | [performance-and-cost](.claude/skills/performance-and-cost/SKILL.md) | the build is slow or expensive and you need to know which model to fix |
| 12. Fix | [troubleshooting-dbt](.claude/skills/troubleshooting-dbt/SKILL.md) | a run, test, or compile failed and you need the cause |
| 13. Move | [migration-and-refactoring](.claude/skills/migration-and-refactoring/SKILL.md) | legacy SQL/stored procs into dbt, a warehouse swap, or a version upgrade |

Specialist agents live in [.claude/agents/](.claude/agents/) — `senior-analytics-engineer`
orchestrates, with `data-modeler`, `dbt-model-designer`, `data-contract-owner`,
`analytics-quality-guardian`, `semantic-layer-architect`, and `dbt-troubleshooter` for
depth.

## Non-negotiables

Full list in [.claude/rules/analytics-engineering-rules.md](.claude/rules/analytics-engineering-rules.md).

- **No model before a use-case spec**, and no mart without a named consumer. If nothing
  changes based on the output, it is a reporting request — say so.
- **Declare the grain in one sentence** before writing SQL. Every downstream ambiguity
  traces back to a grain nobody wrote down.
- **`source()` and `ref()` only.** A hardcoded table name is invisible to lineage,
  selection, and state comparison.
- **`dbt build`, never `dbt run` then `dbt test`.** `build` stops dependents when a test
  fails instead of propagating bad data through the DAG.
- **No model merges without `unique` + `not_null` on its primary key**, and a unit test
  for any model that contains real logic.
- **Never invent a number or a table name.** Mark it `[NEEDS INPUT]` and design around it.

## Tools

Standard-library Python only, no install step. All eleven read dbt's JSON artifacts
(`target/manifest.json`, `run_results.json`, `sources.json`, `catalog.json`) and your
project files; none call the warehouse or any dbt Cloud API.

| Script | Purpose | Key flags |
|---|---|---|
| `dbt_project_auditor.py` | 20 project-health rules: missing PK tests, undocumented models, hardcoded refs, `select *` in marts, orphans, layer violations, stale configs | `--manifest --project-dir --strict --only --skip --json` |
| `model_dependency_analyzer.py` | lineage up/down, blast radius, fan-in/out, cycles, layer-boundary violations, **Mermaid DAG** | `--manifest --model --direction --depth --mermaid --check-layers` |
| `test_coverage_reporter.py` | per-model and per-layer test coverage, ranked by downstream blast radius | `--manifest --min-coverage --layer --strict --json` |
| `run_results_analyzer.py` | slowest models, failures with error text, run-over-run regressions, critical path | `--run-results --manifest --top --compare --slower-than` |
| `source_freshness_monitor.py` | SLA breaches from `sources.json`, with the marts each breach blocks | `--sources --manifest --strict --json` |
| `schema_yml_generator.py` | generate a `schema.yml` skeleton with inferred tests from the manifest/catalog | `--manifest --model --catalog --out --infer-tests` |
| `unit_test_generator.py` | scaffold a dbt unit test with every `ref`/`source` stubbed and typed per warehouse | `--manifest --model --catalog --format --adapter --out` |
| `semantic_layer_validator.py` | validate semantic models and metrics before `mf validate-configs` reaches the warehouse | `--path --manifest --strict --json` |
| `contract_breaking_change_detector.py` | diff two manifests for removed models/columns, type changes, contract and access breaks | `--base --head --strict --json` |
| `erd_generator.py` | **Mermaid ER diagram** from the manifest — entities, attributes, and foreign keys, with tested relationships drawn solid and inferred ones dashed | `--manifest --catalog --layer --models --format --out` |
| `dimensional_model_validator.py` | 15 star-schema rules: facts joined to facts, untested FKs, orphan and unconformed dimensions, non-additive and foreign-entity measures, snapshot/SCD2 config | `--manifest --catalog --strict --only --skip --json` |

```bash
python scripts/dbt_project_auditor.py --manifest target/manifest.json --strict
python scripts/model_dependency_analyzer.py --manifest target/manifest.json --model fct_orders --mermaid
python scripts/test_coverage_reporter.py --manifest target/manifest.json --layer marts --min-coverage 0.9
python scripts/run_results_analyzer.py --run-results target/run_results.json --top 15
python scripts/source_freshness_monitor.py --sources target/sources.json --manifest target/manifest.json --strict
python scripts/schema_yml_generator.py --manifest target/manifest.json --model stg_orders --infer-tests
python scripts/unit_test_generator.py --manifest target/manifest.json --model int_order_items --adapter snowflake
python scripts/semantic_layer_validator.py --path models/ --strict
python scripts/contract_breaking_change_detector.py --base prod/manifest.json --head target/manifest.json --strict
python scripts/erd_generator.py --manifest target/manifest.json --layer marts --format markdown --out docs/erd.md
python scripts/dimensional_model_validator.py --manifest target/manifest.json --strict
```

## Commands

- `/new-use-case <request>` — frame a data request into a use-case spec.
- `/data-model <subject area>` — entities, ERD, keys, grain, bus matrix, star schema spec.
- `/dbt-model <concept>` — design and scaffold a model end to end: spec → SQL → `schema.yml` → tests.
- `/dbt-build <model or selector>` — decide the build scope and the acceptance bar.
- `/dbt-test <model or selector>` — write the test plan, data tests plus unit tests.
- `/dbt-audit [path]` — run the health sweep and return a ranked, actionable list.
- `/dbt-debug <error or node>` — triage a failed run, test, or compile from the artifacts.
- `/dbt-semantic <metric>` — define a metric in MetricFlow and validate it.

## References

- [dbt_core_cli.md](references/dbt_core_cli.md) — every command, node selection syntax, selectors, flags, artifacts
- [project_structure_and_naming.md](references/project_structure_and_naming.md) — layers, file layout, naming, SQL style
- [dimensional_modeling.md](references/dimensional_modeling.md) — Kimball four steps, fact and dimension types, SCD 0–6, bridges, the date dimension
- [data_modeling_paradigms.md](references/data_modeling_paradigms.md) — Kimball, Inmon, Data Vault, OBT, Activity Schema, medallion — and how to choose
- [materializations.md](references/materializations.md) — view/table/incremental/ephemeral/MV, configs, when each is wrong
- [incremental_strategies.md](references/incremental_strategies.md) — append/merge/delete+insert/insert_overwrite/microbatch per adapter
- [jinja_and_macros.md](references/jinja_and_macros.md) — Jinja, macros, `dispatch`, custom generic tests, hooks, packages
- [testing_catalog.md](references/testing_catalog.md) — built-in, `dbt_utils`, `dbt_expectations`, singular, unit tests, severity
- [semantic_layer_metricflow.md](references/semantic_layer_metricflow.md) — semantic models, all six metric types, time spine, `mf` CLI
- [dbt_mesh_governance.md](references/dbt_mesh_governance.md) — contracts, groups, access, versions, cross-project on dbt Core
- [state_and_ci.md](references/state_and_ci.md) — deferral, `state:modified`, slim CI, artifact storage, orchestration
- [performance_and_cost.md](references/performance_and_cost.md) — where dbt time actually goes, per-warehouse tuning
- [warehouse_platform_notes.md](references/warehouse_platform_notes.md) — Snowflake, BigQuery, Databricks, Postgres, Redshift, DuckDB, Trino
- [migration_playbooks.md](references/migration_playbooks.md) — stored procs → dbt, warehouse swaps, version upgrades
- [troubleshooting.md](references/troubleshooting.md) — symptom → cause → fix, for dbt, the warehouse, and these tools

## Definition of done

A use case is complete when:

- The Frame → Model → Design → Test → Ship sequence was followed, and the use-case spec
  exists before any model file.
- For a subject area producing more than one model: entities, keys, and relationships are
  written down, and every shared dimension is conformed — one key, one definition, one
  table.
- Every model states its grain, has a tested primary key, and has a description that says
  more than the model name.
- Every model with real logic has a unit test; every material assumption in the spec has
  a data test.
- `dbt build --select <the new models>+` passes clean, and the run is reproducible with
  `--full-refresh`.
- Source freshness is declared for every source the models depend on.
- Downstream impact was checked against the production manifest, and any breaking change
  is versioned or coordinated.
- The change has a stated rollback path and a named owner.

## Scope

**In scope:** request framing, conceptual/logical/dimensional data modeling, source
contracts, layer design, SQL
implementation, materialization and incremental strategy, snapshots, data and unit
testing, documentation and exposures, MetricFlow semantic models and metrics, governance
(contracts, versions, access), CLI usage and node selection, slim CI with state, build
performance and cost, failure triage, and migrations into or across dbt Core.

**Out of scope:** ingestion and EL tooling (Fivetran, Airbyte, custom extractors),
warehouse administration and provisioning, BI dashboard building, reverse ETL, and dbt
Cloud–specific features (the hosted scheduler, the Semantic Layer API, the Discovery API,
Cloud CI). The scaffold defines the contracts and artifacts those systems need and hands
them over; it does not build them.

**Limitations:** the bundled tools are static analyzers. They read dbt's JSON artifacts
and your YAML/SQL files — they never connect to the warehouse, so they cannot verify that
a test would actually pass, that a type cast is valid, or that a metric returns the right
number. `dbt_project_auditor.py`, `dimensional_model_validator.py`, and
`semantic_layer_validator.py` catch structural and spec problems; only `dbt build` and
`mf query` catch semantic ones. In particular, no static check can see a mixed-grain
fact — it has the same manifest signature as a correct one. Every script needs a
`manifest.json`, which means `dbt parse` (or any `dbt` command) must have run first.

## Start here

`/new-use-case <the data request>`.

To see the whole method working before you write anything, run the worked example. It
needs no warehouse account and takes about 20 seconds:

```bash
python3 -m venv .venv && .venv/bin/pip install 'dbt-core~=1.9.0' 'dbt-duckdb~=1.9.0'
cd use-cases/example-order-revenue-mart/dbt_project && ./run_local.sh
```

It seeds raw tables, checks freshness, builds every model, runs the data and unit tests,
takes an SCD2 snapshot, proves the incremental result matches a full refresh, and then
runs all eleven analyzers against the artifacts it just produced. The same project runs
on BigQuery and Snowflake with `./run_local.sh bigquery|snowflake`.
