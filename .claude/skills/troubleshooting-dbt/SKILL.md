---
name: troubleshooting-dbt
description: Diagnose failed or degraded dbt Core runs from the artifacts — parse and compile errors, Jinja errors, warehouse errors, failing data tests, incremental corruption, freshness breaches, dependency cycles, permission problems, and performance regressions. Reads run_results.json, manifest.json, and compiled SQL rather than guessing. Use when a dbt run/test/build failed, when a scheduled job errored, when numbers changed unexpectedly, or when asked "why did this fail" or "why is this broken".
---

# Troubleshooting dbt Core

Diagnose from evidence. dbt writes everything you need into `target/` — read it before
changing code, and never "just re-run it and see".

## The investigation loop

1. **Reproduce.** Get the exact command, target, and dbt version. `dbt --version`.
2. **Read the artifact**, not the scrollback:
   ```bash
   python scripts/run_results_analyzer.py --run-results target/run_results.json \
       --manifest target/manifest.json --top 15
   ```
3. **Localize** with the triage ladder below — each rung rules out the ones under it.
4. **Read the compiled SQL.** `target/compiled/...` is what you wrote after Jinja;
   `target/run/...` is what dbt actually sent, including the DDL wrapper. Incremental merge
   bugs are visible only in `run/`.
5. **Form one hypothesis, test it, then change one thing.**
6. **Record it** in [templates/incident-investigation.md](../../../templates/incident-investigation.md),
   including the test that would have caught it.

## Triage ladder

| # | Check | Command | If it fails |
|---|---|---|---|
| 1 | Does it parse? | `dbt parse` | YAML or Jinja syntax. Nothing downstream is real |
| 2 | Does the connection work? | `dbt debug` | Profile, credentials, network, role |
| 3 | Does it compile? | `dbt compile --select <model>` | Jinja, a missing `ref`, a missing macro |
| 4 | Does the SQL run? | paste `target/compiled/...` into the warehouse | It is a SQL/warehouse problem, not a dbt problem |
| 5 | Do the tests pass? | `dbt test --select <model> --store-failures` | Data quality — read the failure rows |
| 6 | Is the logic right? | unit tests | Go to `dbt-unit-testing` |

Skipping rungs is how an afternoon disappears.

## Parse and compile errors

| Message | Cause | Fix |
|---|---|---|
| `depends on a node named 'X' which was not found` | `ref()` to a nonexistent, disabled, or uninstalled-package model | Check spelling; `dbt ls --select X`; `dbt deps`; look for `enabled: false` |
| `'dbt_utils' is undefined` | Package not installed, or `packages.yml` changed without `dbt deps` | `dbt deps`. In CI it must run first |
| `'dict object' has no attribute 'X'` | A `var()` or Jinja variable undefined for this target | `{{ var('x', 'default') }}`; check per-target `vars:` |
| `Found a cycle in the DAG` | Two models `ref` each other, directly or via a chain | `model_dependency_analyzer.py --check-layers` names the cycle |
| `Model X depends on a source named Y which was not found` | `source()` name/table mismatch | Case-sensitive; the order is `source('source_name', 'table_name')` |
| `dbt found two resources with the name "X"` | Two model files with the same name in different folders | dbt model names are globally unique regardless of directory |
| `Parsing Error ... could not parse YAML` | Indentation, a tab character, or an unquoted `:` in a description | Quote descriptions containing `:`; use `>` blocks |
| `unexpected '}' ` / `expected token 'end of statement block'` | Unbalanced Jinja | Every `{% if %}` needs `{% endif %}`; `{{ }}` vs `{% %}` |
| Config in YAML has no effect | Wrong nesting, or the file is outside `model-paths` | `dbt ls --select X --output json` shows the resolved config |
| `Compilation Error ... contract ... columns do not match` | Actual output drifted from the contract YAML | The error names the mismatch; usually a `data_type` precision difference |

### Debugging Jinja

Do not read the model file — read what it produced.

```bash
dbt compile --select fct_orders
cat target/compiled/analytics/models/marts/fct_orders.sql
```

To inspect a value mid-compile:

```sql
{{ log("var value is: " ~ var('start_date'), info=true) }}
{{ log(dbt_utils.get_column_values(ref('dim_status'), 'status') | join(','), info=true) }}
```

`{{ log(..., info=true) }}` prints during compilation, which is the only way to see what a
macro actually returned.

Common Jinja traps:

- **Whitespace control.** `{%- ... -%}` strips surrounding whitespace. Missing it in a loop
  produces syntactically broken SQL that reads fine in the template.
- **Two compile passes.** dbt parses the project first, then compiles. Anything that queries
  the warehouse at parse time (`run_query`, `get_column_values`) must be guarded with
  `{% if execute %}`, or it runs during parsing with no results and yields `None`.
- **`ref()` inside a conditional still creates the dependency.** dbt statically extracts
  every `ref` regardless of the branch taken.

## Runtime errors

| Message | Cause | Fix |
|---|---|---|
| `relation "X" does not exist` | Upstream not built in this target/schema, or a stale `--defer` manifest | Build upstream, or refresh the `--state` manifest |
| `permission denied` / `insufficient privileges` | Role lacks grants on the target schema or a source | `dbt debug` confirms the connection but not object-level grants. Check `grants:` config and the warehouse role |
| `column "X" does not exist` | An upstream model's output changed | Check what merged upstream; run the breaking-change detector |
| `invalid input syntax for type ...` | A cast that works on most rows fails on some | Find the rows with a singular test; use `try_cast`/`safe_cast` where a null is acceptable |
| `division by zero` | Missing `nullif` | `x / nullif(y, 0)` |
| Query timeout / resource exhausted | Cross join, fan-out, or full scan | Read the compiled SQL and the query profile; go to `performance-and-cost` |
| `Nondeterministic merge` (BigQuery) | Duplicate `unique_key` values in the incoming batch | Dedup before the merge |
| `Database Error` with no detail | Adapter swallowed it | `--debug` prints the full statement and stack trace |

## Test failures

A failing test is data telling you something. Investigate before weakening it.

```bash
dbt test --select fct_orders --store-failures
# dbt prints the table it wrote the failing rows to — query that
```

| Failure | Usual meaning |
|---|---|
| `unique` on the PK | A join fanned out, or the source has soft-deleted/versioned duplicates |
| `not_null` on a new column | An upstream left join now misses. Check what changed upstream |
| `relationships` | The parent is filtered more tightly than the child, or was rebuilt late |
| `accepted_values` | The source added an enum value. A real change — update the list **and** check downstream CASE statements for a silent fallthrough |
| Row count test | A truncated or duplicated load |
| Suddenly failing after months | An upstream or source-system change, not decay. Check `git log` upstream and the EL job history |

**Never** delete a test to unblock a deploy. Scope it with `where:` and record why:

```yaml
- not_null:
    config:
      where: "ordered_at >= '2023-01-01'"   # pre-migration rows are known-bad, ticket DATA-412
```

## Incremental corruption

The nastiest class, because nothing errors.

| Symptom | Cause | Fix |
|---|---|---|
| Incremental and `--full-refresh` disagree | The `is_incremental()` filter drops late-arriving rows | Widen the lookback from measured arrival lag |
| Duplicates growing over time | No `unique_key`, or one that is not actually unique | Set/fix it, then `--full-refresh` once |
| Permanent gap after a skipped run | Filter anchored to `current_date` not `max()` in `{{ this }}` | Anchor to `this`; backfill the gap |
| Old rows never update | `append` on mutable data | Switch to `merge` |
| A new column is always null | `on_schema_change: ignore` (the default) | `append_new_columns` + one full refresh |
| Partitions deleted after a backfill | `insert_overwrite` with an incomplete partition query | The query must emit complete partitions |
| First run fails on `{{ this }}` | `{{ this }}` referenced outside `is_incremental()` | It does not exist on run one — keep it inside the guard |

**The invariant:** `dbt build --select <model> --full-refresh` must reproduce the
incremental result. Verify it deliberately with `audit_helper.compare_relations`, on a
schedule — not by accident.

## Freshness

```bash
dbt source freshness
python scripts/source_freshness_monitor.py --sources target/sources.json \
    --manifest target/manifest.json --strict
```

| Symptom | Cause |
|---|---|
| Every source stale at once | The EL platform is down, or the warehouse timezone changed |
| One source stale | That connector broke, or the table was renamed upstream |
| Reports "fresh" but the data is old | `loaded_at_field` is a source-system `updated_at`, not a load timestamp — a dead pipeline looks fresh forever if one old row was edited |
| Fails only on Mondays | The SLA does not account for the weekend |
| `loaded_at_field` not found | The connector renamed its metadata column |

## Performance regression

```bash
python scripts/run_results_analyzer.py --run-results target/run_results.json \
    --compare prod/run_results.json --slower-than 1.5 --top 20
```

Localize before optimizing:

1. **One model or all of them?** All → warehouse contention, a resized cluster, or thread
   count. One → that model's SQL.
2. **The model or its tests?** `run_results.json` times them separately. An expensive
   `relationships` test between two large tables is often the real cost.
3. **Did the data grow, or did the SQL change?** `git log` on the model vs the row-count trend.
4. **Is it on the critical path?** A slow model with no dependents costs nothing on a
   parallel build. The analyzer flags critical-path nodes.

Details: [performance-and-cost](../performance-and-cost/SKILL.md).

## Environment and setup

| Symptom | Cause |
|---|---|
| `Could not find profile named 'X'` | `profile:` in `dbt_project.yml` ≠ the key in `profiles.yml` |
| `Env var required but not provided` | Unset in this shell/CI — intended behavior for a secret |
| Models land in the wrong schema | dbt concatenates `<target_schema>_<custom_schema>`; override `generate_schema_name` |
| Works locally, fails in CI | Different dbt/adapter version, missing `dbt deps`, or a different target |
| Stale results after an edit | Partial parsing cache. `dbt clean && dbt parse`, or `--no-partial-parse` |
| `dbt: command not found` | Wrong venv activated |
| Different package versions than a teammate | `package-lock.yml` not committed |

## When to stop and ask

Escalate rather than guessing when:

- The fix requires a **business decision** — which of two disagreeing sources is right, or
  whether historical data should be restated.
- The failure is in the **source system or EL job**. Modeling around bad source data hides
  the bug and makes it permanent.
- A fix would **restate published numbers**. Someone owns that communication.
- The data is **wrong but plausible**, and you cannot determine what it should be. Say so
  explicitly rather than shipping a guess.

## Investigation record

Anything that took over fifteen minutes or reached production gets an entry in
[templates/incident-investigation.md](../../../templates/incident-investigation.md):
symptom, evidence, root cause, fix, and **the test or check that would have caught it**.
That last field is the only one that changes the future. Every investigation ends with a new
test, a new freshness block, or a written reason why neither was possible.

## Anti-patterns

- Re-running to see if it passes. It sometimes does, which teaches nothing and hides an
  intermittent bug.
- `--full-refresh` as a first response.
- Weakening or deleting a failing test without recording why.
- Reading the log instead of `run_results.json`.
- Debugging Jinja by reading the model file instead of `target/compiled/`.
- Blaming dbt for a warehouse error — if the compiled SQL fails when pasted in, dbt is not
  involved.
- Fixing the symptom in the mart when the defect is in the source system.

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| `/dbt-debug` | `run_results.json` read first — the failing node, its error, its timing, its blast radius |
| "just re-run it" | A pushback: re-running blind costs a full build and discards the evidence |
| "this Jinja error makes no sense" | `target/compiled/` read, not the model file — the error is in the rendered SQL |
| "the numbers changed and nothing was deployed" | Source freshness and the incremental invariant checked before any code is touched |

**Worked example**

> "last night's build failed"

```bash
python scripts/run_results_analyzer.py \
    --run-results target/run_results.json --manifest target/manifest.json --top 20
```

```
FAIL  test  unique_fct_orders_order_id     0.4s    142 failing rows
SKIP  model dim_customer_orders                    (dependent on the failed test)
PASS  model fct_orders                    48.2s    ← the SQL ran fine; the data is wrong
```

```sql
-- store_failures wrote the offending rows to a table. Query it instead of guessing.
select order_id, count(*) from analytics_dbt_test__audit.unique_fct_orders_order_id
group by 1 order by 2 desc limit 10;
--   4471 | 2      ← every duplicate has exactly 2 rows
```

```bash
# Upstream or here? Check the staging model's own PK.
dbt build --select stg_shopify__orders
#   unique_stg_shopify__orders_order_id → FAIL, same 142 keys.
#   The defect is a double load upstream, not the mart.

python scripts/model_dependency_analyzer.py \
    --manifest target/manifest.json --model fct_orders --direction down
```

```
Diagnosis  Duplicate source load on 2026-07-30; 142 order_ids landed twice.
Fix        Deduplicate in staging on (order_id, _loaded_at) — and raise the double load
           with the EL owner. A mart-level distinct would hide it.
Prevention unique test on stg_shopify__orders, plus a freshness block on the source.
Verify     dbt build --select stg_shopify__orders+
```

The last two lines are the ones that change the future. An investigation that ends without
a new test, a new freshness block, or a written reason why neither was possible will repeat.

Reference: [references/troubleshooting.md](../../../references/troubleshooting.md).
