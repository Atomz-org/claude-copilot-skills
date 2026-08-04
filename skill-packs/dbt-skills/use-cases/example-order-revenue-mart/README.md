# Worked Example — Order Revenue Mart

A complete dbt Core use case that **actually runs**, on DuckDB, with no warehouse account
and no credentials. Read it to calibrate the expected level of specificity, and run it to
see what each tool in [scripts/](../../../../scripts/) outputs against a real manifest.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install 'dbt-core~=1.9.0' 'dbt-duckdb~=1.9.0'

cd skill-packs/dbt-skills/use-cases/example-order-revenue-mart/dbt_project
./run_local.sh
```

About 40 seconds. It seeds the raw tables from **two source systems** — the Shopify web
shop and the Demo POS in-store till — checks source freshness, builds every model, runs
52 data tests and 6 unit tests, takes an SCD2 snapshot, proves the incremental result
equals the full-refresh result, generates the catalog, and then runs every analyzer
against the artifacts it just produced.

Expected result: **67 pass, 1 warn, 0 errors.** The warning is intentional — see
"the deliberate warning" below.

### Other warehouses

The same project runs on BigQuery and Snowflake without editing a model:

```bash
./run_local.sh bigquery     # needs DBT_BQ_PROJECT, DBT_BQ_DATASET, and auth
./run_local.sh snowflake    # needs DBT_SF_ACCOUNT, DBT_SF_USER, key-pair or password
```

Credentials come from `env_var()` only — see [dbt_project/profiles.yml](dbt_project/profiles.yml)
for the full list. **Only the DuckDB path has been executed here**; the BigQuery and
Snowflake targets are configured and reviewed but need real accounts to verify.

What makes one project run on all three is documented in
[references/warehouse_platform_notes.md](../../references/warehouse_platform_notes.md#writing-one-project-that-runs-on-all-of-them),
and is visible in the project as:

| File | Handles |
|---|---|
| [macros/cross_db.sql](dbt_project/macros/cross_db.sql) | incremental strategy, clustering vs partitioning, money type, UTC now |
| [macros/generate_schema_name.sql](dbt_project/macros/generate_schema_name.sql) | verbatim schema names, opt-in per target and refused at parse time if the target resolves to a production database |
| [models/marts/metricflow_time_spine.sql](dbt_project/models/marts/metricflow_time_spine.sql) | `dbt.dateadd` instead of dialect `dateadd`, and the Jinja capture trap |
| [models/marts/finance/fct_orders.sql](dbt_project/models/marts/finance/fct_orders.sql) | computed `incremental_strategy`, casts that satisfy an enforced contract |

## What's here

| Path | What it shows |
|---|---|
| [use-case-spec.md](use-case-spec.md) | A filled-in spec — `[NEEDS INPUT]` markers that survived approval, a measured arrival lag, and a section 11 recording what the spec got wrong |
| [data-model-canvas.md](data-model-canvas.md) | Entities, rejected candidates, ERD with optionality, keys, grain matrix, SCD decisions, additivity, decisions log |
| [star-schema-spec.md](star-schema-spec.md) | Kimball's four steps for "an order is placed", including the measure that was rejected for being at the wrong grain |
| [dbt_project/](dbt_project/) | The runnable project: `dbt_project.yml`, `profiles.yml`, macros, seeds, models, snapshot, semantic layer |
| [dbt_project/seeds/generate_seeds.py](dbt_project/seeds/generate_seeds.py) | Generates the raw CSVs, with the awkward cases planted deliberately |
| [dbt_project/models/staging/demopos/](dbt_project/models/staging/demopos/) | The second connector — a worked example of onboarding a new source system, below |
| [dbt_project/run_local.sh](dbt_project/run_local.sh) | The end-to-end run above |
| [artifacts/](artifacts/) | A **separate, synthetic** artifact set carrying planted defects, so each tool has something to find |
| [artifacts/build_artifacts.py](artifacts/build_artifacts.py) | Regenerates those synthetic artifacts |

### Two artifact sets, and why

| | `dbt_project/target/` | `artifacts/` |
|---|---|---|
| Produced by | a real `dbt build` | a Python generator |
| Committed | no — gitignored build output | yes |
| Represents | a healthy project | a project with ten planted defects |
| Use it to | see the tools on real output | see what each tool *finds* |

A healthy project makes a poor tool demo — most analyzers return "clean". The synthetic
set exists so every rule has something to report. Run the tools against both.

## The second connector — Demo POS

The project has two source systems on purpose. Shopify is the original; **Demo POS** — a
synthetic in-store till — was onboarded afterwards, with the repository's own tooling, as
the worked example of adding a connector to a use-case that already has one. To retrace
it, from the repository root (four levels above this file):

```bash
# 1. Dry-run the scaffold. It detects THIS project's conventions (stg_<src>__<table>
#    staging names, the enable var, the source name) from the busiest existing
#    connector, and prints them for review instead of assuming.
python3 scripts/new_connector.py demopos \
    --use-case example-order-revenue-mart \
    --tables customers,receipts --display-name "Demo POS" --dry-run

# 2. The convention gate. Run it any time; CI runs it via use_case_sync.
python3 scripts/connector_alignment_check.py --use-case example-order-revenue-mart --check
```

One hand adjustment to notice when retracing: the scaffolder prints the source block and
suggests pasting it into the existing `_shopify__sources.yml`, and would write a generic
`schema.yml`. This project keeps one sources file and one models file per connector, so
the block went into a new `_demopos__sources.yml` (and the stubs became
`_demopos__models.yml`) instead — the project's own conventions outrank the tool's
suggestion, which is rule 47 in practice.

What to look at, and why it looks that way:

| File | The lesson |
|---|---|
| [_demopos__sources.yml](dbt_project/models/staging/demopos/_demopos__sources.yml) | The source contract: the raw columns staging depends on, declared where removal becomes a detectable breaking change. The raw names (`customer_ref`, `receipt_ref`, `status`) are deliberately not our names |
| [stg_demopos__receipts.sql](dbt_project/models/staging/demopos/stg_demopos__receipts.sql) | Staging quarantines the source: every rename and cast happens here, nothing downstream ever sees a raw column |
| [_demopos__models.yml](dbt_project/models/staging/demopos/_demopos__models.yml) | Tests on the things that can actually break: keys, the nullable FK (walk-in sales), a closed status domain |
| `is_demopos_enabled` in [dbt_project.yml](dbt_project/dbt_project.yml) | Connectors are switched on per deployment by a string-matched var — the var name, directory, and file prefix must all carry the same key |

Two details worth noticing:

- **The checker caught real drift during this very onboarding.** Demo POS arrived with an
  enable var; Shopify predated the pattern and had none. `connector_alignment_check.py`
  errored with `no-enable-var` — two connectors doing it two ways — and the fix was to
  converge Shopify onto the pattern, not to silence the checker.
- **Demo POS is source-aligned only.** Its receipts are not unioned into `fct_orders`,
  because no consumer has asked for in-store revenue in the mart yet
  (rule 3: name the consumer before the model). The day one does, the staging layer is
  ready and the decision is recorded here.

## The planted defects

The synthetic project in `artifacts/` deliberately contains real problems, so every tool has
something to find. The **model files** in `dbt_project/models/` are the corrected version —
compare the two.

| Defect | Found by |
|---|---|
| `stg_netsuite__revenue_postings` selects from a hardcoded `raw.netsuite.revenue_postings` | `dbt_project_auditor.py` — `hardcoded_ref` |
| `netsuite.revenue_postings` has no freshness block | `dbt_project_auditor.py` — `source_without_freshness` |
| `fct_order_line_detail` has no tests, no description, no consumer | auditor + `test_coverage_reporter.py` |
| `fct_order_line_detail` is incremental with `merge` and no `unique_key` | auditor — `incremental_no_unique_key` |
| ...and leaves `on_schema_change` at `ignore` | auditor — `incremental_schema_change_default` |
| `stg_shopify__customers` has no description but 12 downstream nodes | auditor + coverage, ranked first by blast radius |
| `dim_customers` and `fct_orders` contain CASE logic with no unit test | coverage — "has logic, no unit test" |
| `shopify.customers` is 1.6 days stale, blocking a live exposure | `source_freshness_monitor.py` |
| A failing `accepted_values` test on `fct_orders.order_status` | `run_results_analyzer.py` |
| `fct_orders` got 2.5x slower run over run | `run_results_analyzer.py --compare` |
| `fct_orders` dropped `currency_code` and retyped `order_amount_usd` on a contracted model | `contract_breaking_change_detector.py` |

## Run every tool

```bash
cd /path/to/code-skills
A=skill-packs/dbt-skills/use-cases/example-order-revenue-mart/artifacts
M=skill-packs/dbt-skills/use-cases/example-order-revenue-mart/dbt_project/models

# Regenerate the artifacts (optional — they are committed)
python3 $A/build_artifacts.py

# 1. Project health — 20 rules, ranked by blast radius
python3 scripts/dbt_project_auditor.py --manifest $A/target/manifest.json
python3 scripts/dbt_project_auditor.py --manifest $A/target/manifest.json --strict   # exits 1

# 2. DAG: structure, lineage, layer check, Mermaid, changed-vs-prod
python3 scripts/model_dependency_analyzer.py --manifest $A/target/manifest.json
python3 scripts/model_dependency_analyzer.py --manifest $A/target/manifest.json --model fct_orders --direction down
python3 scripts/model_dependency_analyzer.py --manifest $A/target/manifest.json --check-layers
python3 scripts/model_dependency_analyzer.py --manifest $A/target/manifest.json \
    --changed-vs $A/prod/manifest.json --mermaid

# 3. Test coverage, ranked by what depends on the gap
python3 scripts/test_coverage_reporter.py --manifest $A/target/manifest.json
python3 scripts/test_coverage_reporter.py --manifest $A/target/manifest.json \
    --layer marts --min-coverage 0.9 --strict

# 4. Run analysis: failures, critical path, regressions
python3 scripts/run_results_analyzer.py --run-results $A/target/run_results.json \
    --manifest $A/target/manifest.json --compare $A/prod/run_results.json

# 5. Freshness breaches, annotated with the exposures they block
python3 scripts/source_freshness_monitor.py --sources $A/target/sources.json \
    --manifest $A/target/manifest.json --strict

# 6. schema.yml skeleton with real warehouse types
python3 scripts/schema_yml_generator.py --manifest $A/target/manifest.json \
    --model dim_customers --catalog $A/target/catalog.json --infer-tests --contract

# 7. Unit test scaffold, every ref stubbed, typed for the adapter
python3 scripts/unit_test_generator.py --manifest $A/target/manifest.json \
    --model fct_orders --catalog $A/target/catalog.json --adapter snowflake

# 8. Semantic layer spec check (offline — no warehouse, no mf install)
python3 scripts/semantic_layer_validator.py --path $M --strict

# 9. Breaking-change gate
python3 scripts/contract_breaking_change_detector.py \
    --base $A/prod/manifest.json --head $A/target/manifest.json --strict

# 10. Mermaid ERD of the marts
python3 scripts/erd_generator.py --manifest $A/target/manifest.json \
    --catalog $A/target/catalog.json --layer marts

# 11. Star-schema rules
python3 scripts/dimensional_model_validator.py --manifest $A/target/manifest.json \
    --catalog $A/target/catalog.json
```

## What the real run teaches

These are not hypotheticals — every one of them broke this project during development, and
the fix is in the file named.

| What happened | Why | Where the fix lives |
|---|---|---|
| Model built fine, then failed on the **second** run: "incremental strategy 'merge' is not valid for this adapter" | DuckDB has no `merge`. The first build is a plain create and never exercises the strategy | `incremental_upsert_strategy()` in [macros/cross_db.sql](dbt_project/macros/cross_db.sql) |
| Contract failed: `BIGINT` vs `INTEGER`, `DECIMAL(38,6)` vs `DECIMAL(28,6)` | `count(*)` and `sum()` widen differently per warehouse; enforced contracts compare exact types | explicit casts in [int_orders_with_line_totals.sql](dbt_project/models/intermediate/finance/int_orders_with_line_totals.sql) |
| Time spine compiled to `( + cast( as bigint) * interval 1 )` | dbt's cross-database macros emit text rather than returning a value, so `set x = dbt.dateadd(...)` captures nothing | block-form `set` in [metricflow_time_spine.sql](dbt_project/models/marts/metricflow_time_spine.sql) |
| `Expected an expression, got 'end of statement block'` from a **comment** | Jinja renders SQL comments. A Jinja tag inside `--` is evaluated, not ignored | same file, and the header of [fct_orders.sql](dbt_project/models/marts/finance/fct_orders.sql) |
| `'money_type' is undefined` in a seed's `column_types` | Property YAML is rendered in a restricted context with no project macros — only `var`, `env_var`, `target` | literal type + note in [seeds/_seeds.yml](dbt_project/seeds/_seeds.yml) |
| Source test failed with "table does not exist" only sometimes | Seeds-as-sources have no DAG edge, so `dbt build` recreates the seed while a source test reads it | `--exclude resource_type:seed` in [run_local.sh](dbt_project/run_local.sh) |
| FK test found 10 orphaned order lines | The generator soft-deleted an order but not its lines; staging filters soft deletes | [generate_seeds.py](dbt_project/seeds/generate_seeds.py) |
| `accepted_values` failed on `partially_refunded` | The CASE passed unmapped statuses through, contradicting the model's own description | closed CASE + a warn-severity test, [_int_finance__models.yml](dbt_project/models/intermediate/finance/_int_finance__models.yml) |

### The deliberate warning

The green run still reports one warning, and it is meant to:

```
WARN 1 accepted_values_int_orders_with_line_totals_order_status__pending__paid__fulfilled__refunded__cancelled
```

`order_status` carries **two** `accepted_values` tests. The error-severity one includes
`unknown` and guards the closed domain — breaking it means the CASE has a bug. The
warn-severity one excludes `unknown`, so it fires the moment Shopify ships a status nobody
has mapped. The build stays green, and someone still finds out. A single error-severity
test would have forced a choice between "red build for something nobody can fix today" and
"silent unknowns".

### Closing the loop with the tools

The auditor found a real gap on the first real manifest:

```
[WARN] logic_without_unit_test  dim_customers  24 downstream
```

`dim_customers` maps country to region with a CASE — business policy that a data test
cannot verify, because `accepted_values` passes whether `fr` maps to EMEA or AMER. The
fix is `test_region_mapping_covers_each_branch` in
[_finance__models.yml](dbt_project/models/marts/finance/_finance__models.yml). Auditor is
clean now.

The dimensional validator then found `fct_orders.region` also exists on `dim_customers` —
a denormalized attribute with no recorded as-was/as-is decision. It is now documented as
**as-is**, with the snapshot join written out for anyone who needs as-was.

## Following the thread

The point of the modeling artifacts is that they are traceable to running code. Pick any
decision and follow it:

| Decision, in the canvas | Where it lands |
|---|---|
| "Customer → Order is optional on the FK side" | `left join` in [fct_orders.sql](dbt_project/models/marts/finance/fct_orders.sql), `relationships` test scoped `where: customer_id is not null` |
| "`country_code` is the only Type 2 attribute" | [customers_snapshot.yml](dbt_project/snapshots/customers_snapshot.yml) with `check_cols: [email, country_code]` — not SCD2 on the whole dimension |
| "Average order value is non-additive" | a ratio metric in [_metrics.yml](dbt_project/models/semantic/_metrics.yml), not a column on the fact |
| "Refund overrides fulfilment" (decisions log, 2026-07-11) | the CASE order in [int_orders_with_line_totals.sql](dbt_project/models/intermediate/finance/int_orders_with_line_totals.sql), asserted by `test_refund_overrides_fulfilled_status` |
| "Region is denormalized as **as-is**" | the column description in [_finance__models.yml](dbt_project/models/marts/finance/_finance__models.yml), with the snapshot join written out for as-was |
| "No `dim_products` — nobody asks by product" | no model, and open question #2 in the canvas |
| "Customer lifetime value is at the wrong grain" | not built; `dimensional_model_validator.py` would flag it as `foreign_entity_measure` |

A canvas whose rows you cannot find in the project has stopped being a decision record and
become documentation. That is the failure mode to watch for.

## Things worth noticing

**The critical path.** `run_results_analyzer.py` reports a 3m01s critical path against 3m07s
wall-clock — 97%. This project is latency-bound, so adding threads would do nothing.
`fct_order_line_detail` takes 1m01s and is not on the critical path; optimizing it would
change wall-clock by zero. That is the point of measuring first.

**Blast-radius ranking.** `stg_shopify__customers` has a trivial gap (no description) but
ranks first in the coverage report, because 12 nodes and a live exposure depend on it.
`metricflow_time_spine` has no tests at all and ranks last, because nothing depends on it.
Coverage as a bare percentage would invert that.

**What the breaking-change detector cannot see.** It finds the dropped `currency_code` and
the `numeric` → `numeric(28,6)` retype, and then it explicitly tells you it cannot detect a
grain change — the column list would be identical, every contract would pass, every test
would pass, and every downstream number would be silently wrong. It lists the models whose
SQL changed so a human can check.

**The dimensional validator finds almost nothing here — on purpose.** This example is a
single-star revenue mart, and it is dimensionally sound: one fact, one conformed
dimension, a tested foreign key. The one finding it does return is real —
`fct_orders.customer_id` has a `relationships` test but no `not_null` test, so guest
checkouts arrive as null foreign keys and every consumer's `inner join` silently drops
them. That is exactly the class of defect the rule exists for, and it is invisible to the
project auditor.

**The spec's section 11.** The example records that the spec got an assumption wrong — orders
with zero line items — and the test that was added afterwards. A spec with no section 11 has
not been through delivery yet.

## Regenerating

```bash
python3 skill-packs/dbt-skills/use-cases/example-order-revenue-mart/artifacts/build_artifacts.py
```

Edit `build_artifacts.py` to change the synthetic project. It is deliberately readable: the
model definitions near the top are what every tool reads.
