# Troubleshooting

Symptom → likely cause → what to do. Covers dbt, the warehouse, and this repo's tools.

Read the artifact before changing code:

```bash
python scripts/run_results_analyzer.py --run-results target/run_results.json \
    --manifest target/manifest.json --top 15
cat target/compiled/<project>/models/marts/fct_orders.sql    # what you wrote, Jinja resolved
cat target/run/<project>/models/marts/fct_orders.sql         # what dbt actually sent
```

## Triage ladder

| # | Check | Command |
|---|---|---|
| 1 | Does it parse? | `dbt parse` |
| 2 | Does the connection work? | `dbt debug` |
| 3 | Does it compile? | `dbt compile --select <model>` |
| 4 | Does the SQL run? | paste `target/compiled/...` into the warehouse |
| 5 | Do the tests pass? | `dbt test --select <model> --store-failures` |
| 6 | Is the logic right? | unit tests |

Each rung rules out the ones below it. Skipping is how an afternoon disappears.

## Parse and compile

| Symptom | Likely cause | Resolution |
|---|---|---|
| `depends on a node named 'X' which was not found` | `ref()` to a nonexistent, disabled, or uninstalled-package model | Check spelling; `dbt ls --select X`; `dbt deps`; look for `enabled: false` |
| `'dbt_utils' is undefined` | Package not installed | `dbt deps`. In CI it must run first |
| `'dict object' has no attribute 'X'` | `var()` or Jinja variable undefined for this target | `{{ var('x','default') }}`; check per-target `vars:` |
| `Found a cycle in the DAG` | Two models `ref` each other, directly or via a chain | `model_dependency_analyzer.py --check-layers` names it |
| `depends on a source named 'Y' which was not found` | `source()` name/table mismatch | Case-sensitive; order is `source('source_name','table_name')` |
| `dbt found two resources with the name "X"` | Duplicate model filenames | Model names are globally unique regardless of directory |
| `could not parse YAML` | Indentation, a tab, or an unquoted `:` in a description | Quote descriptions containing `:`; use `>` blocks |
| `expected token 'end of statement block'` | Unbalanced Jinja | Every `{% if %}` needs `{% endif %}`; `{{ }}` vs `{% %}` |
| Config in YAML does nothing | Wrong nesting, or the file is outside `model-paths` | `dbt ls --select X --output json` shows the resolved config |
| `contract ... columns do not match` | Actual output drifted from the contract YAML | Usually a `data_type` precision difference; read real types from `catalog.json` |
| A `+` config key was ignored | Missing the `+` prefix in `dbt_project.yml` | Without `+`, dbt reads it as a subdirectory name |
| Model compiles to broken SQL with a loop | Missing whitespace control, or an introspective query unguarded by `{% if execute %}` | Read `target/compiled/`; add the guard |

## Runtime

| Symptom | Likely cause | Resolution |
|---|---|---|
| `relation "X" does not exist` | Upstream not built in this target, or a stale `--defer` manifest | Build upstream, or refresh the `--state` manifest |
| `permission denied` / `insufficient privileges` | The role lacks grants on the schema or a source | `dbt debug` confirms the connection but not object grants. Check `grants:` and the warehouse role |
| `column "X" does not exist` after an upstream change | An upstream model's output changed | Run the breaking-change detector against production |
| `invalid input syntax for type ...` | A cast that works on most rows fails on some | Find the rows with a singular test; `try_cast`/`safe_cast` where a null is acceptable |
| `division by zero` | Missing `nullif` | `x / nullif(y, 0)` |
| Query timeout / resource exhausted | Cross join, fan-out, or full scan | Read the compiled SQL and the query plan |
| `Nondeterministic merge` (BigQuery) | Duplicate `unique_key` values in the incoming batch | Dedupe with `qualify row_number() over (...) = 1` |
| `Database Error` with no detail | Adapter swallowed it | `--debug` prints the full statement and stack trace |
| Model runs 40x slower overnight | Row explosion from a join whose key became non-unique | Count each CTE in isolation |

## Data correctness

| Symptom | Likely cause | Resolution |
|---|---|---|
| Row count multiplied | Joined a 1:N table without aggregating | Aggregate to the join grain in its own CTE first |
| Totals inflated | Same fan-out, `sum()` after the join | Same fix. Never `sum()` across a fanned-out join |
| Rows disappeared | `inner join` to an incomplete right side | `left join`, and decide what a null means |
| Duplicate PKs after a "1:1" join | The right side is not unique on that key | Test the right side's uniqueness independently — usually versioned or soft-deleted rows |
| Row count varies between identical runs | Non-deterministic dedup — `row_number()` without a full tiebreaker | Add enough `order by` columns to make it total |
| Numbers changed with no code change | An upstream or source-system change | `git log` upstream; check the EL job history |
| A `distinct` appeared at the top of a mart | Someone is hiding a fan-out | Find the fan-out; `distinct` is a symptom |
| Two dashboards disagree | Definition, grain, timezone, freshness, or fan-out — in that order of likelihood | Fix with one MetricFlow definition, not a third table |
| The number is plausible but wrong | A formula error that data tests cannot catch | This is what unit tests are for |

## Test failures

| Failure | Usual meaning |
|---|---|
| `unique` on the PK | A join fanned out, or soft-deleted/versioned source duplicates |
| `not_null` on a new column | An upstream left join now misses |
| `relationships` | The parent is filtered more tightly than the child, or was rebuilt late |
| `accepted_values` | The source added an enum value. Real change — update the list **and** check downstream CASE statements for a silent fallthrough |
| Row count test | A truncated or duplicated load |
| Suddenly failing after months | An upstream change, not decay |

**Never delete a test to unblock a deploy.** Scope it and record why:

```yaml
- not_null:
    config: {where: "ordered_at >= '2023-01-01'"}   # pre-migration known-bad, DATA-412
```

Get the failing rows: `dbt test --select <model> --store-failures`, then query the table dbt
names.

## Incremental

| Symptom | Cause | Fix |
|---|---|---|
| Incremental and `--full-refresh` disagree | The filter drops late-arriving rows | Widen the lookback from measured arrival lag |
| Duplicates growing over time | No `unique_key`, or one that is not unique | Set/fix it, then `--full-refresh` once |
| Permanent gap after a skipped run | Filter anchored to `current_date` | Anchor to `max()` in `{{ this }}`; backfill |
| Old rows never update | `append` on mutable data | Switch to `merge` |
| A new column is always null | `on_schema_change: ignore` (the default) | `append_new_columns` + one full refresh |
| Partitions deleted after a backfill | `insert_overwrite` with an incomplete partition query | The query must emit complete partitions |
| First run fails on `{{ this }}` | `{{ this }}` outside `is_incremental()` | Keep it inside the guard |

**The invariant:** `--full-refresh` must reproduce the incremental result. Verify it
deliberately with `audit_helper.compare_relations`, on a schedule.

## Snapshots

| Symptom | Cause |
|---|---|
| Changes missing from history | `strategy: timestamp` with an `updated_at` that does not move on every change |
| Every run creates new rows | `check_cols='all'` on a table with a metadata column that always changes |
| Snapshot broke after a config change | `unique_key` or `strategy` changed after the first run — **not reconcilable**; rebuild from backup |
| Dev and prod histories differ | Snapshots built into environment-suffixed schemas |
| Overlapping validity windows downstream | A consumption-query bug, not a snapshot bug | Test with `dbt_utils.mutually_exclusive_ranges` |

Snapshot failures are the only unrecoverable class in dbt. Back up before any structural
change.

## Freshness

| Symptom | Cause |
|---|---|
| Every source stale at once | The EL platform is down, or the warehouse timezone changed |
| One source stale | That connector broke, or the table was renamed upstream |
| Reports "fresh" but the data is old | `loaded_at_field` is a source-system `updated_at`, not a load timestamp — a dead pipeline looks fresh forever |
| Fails only on Mondays | The SLA does not account for the weekend |
| `loaded_at_field` not found | The connector renamed its metadata column |

## Environment and CI

| Symptom | Cause |
|---|---|
| `Could not find profile named 'X'` | `profile:` in `dbt_project.yml` ≠ the key in `profiles.yml` |
| `Env var required but not provided` | Unset in this shell/CI — intended for a secret |
| Models land in the wrong schema | dbt concatenates `<target_schema>_<custom_schema>`; override `generate_schema_name` |
| Works locally, fails in CI | Different dbt/adapter version, missing `dbt deps`, different target |
| Stale results after an edit | Partial parse cache. `dbt clean && dbt parse` |
| `state:modified` matches everything | State manifest from a different dbt version or project |
| `state:modified` matches nothing after a real change | `--state` points at the current `target/` |
| CI passes, production breaks | CI selected `state:modified` without the trailing `+` |
| `--defer` still rebuilds upstream | The upstream node is *selected* |
| CI slower every week | CI schemas never dropped |
| Different package versions than a teammate | `package-lock.yml` not committed |

## MetricFlow

| Symptom | Cause |
|---|---|
| `time granularity not specified` | A `type: time` dimension missing `time_granularity` — the most common failure |
| `unable to find dimension X` | Missing the `entity__dimension` prefix in a filter |
| `no time spine configured` | A cumulative/offset metric with no `time_spine:` model |
| Cumulative metric truncates at the tail | The spine ends before the fact data does |
| `entity X not found` | A foreign entity with no matching primary elsewhere |
| Metric returns null for recent periods | Missing `fill_nulls_with` |
| Query fans out / totals inflated | The underlying mart's grain is not what the semantic model assumes |
| `mf` errors on startup | `dbt-metricflow` does not match the dbt Core minor version |
| Two metrics that should match do not | Different `filter` clauses — compare with `--explain` |

## This repo's tools

| Symptom | Cause | Resolution |
|---|---|---|
| Every script: `manifest not found` | No `dbt` command has run | `dbt parse` — no warehouse needed |
| `dbt_project_auditor.py`: everything flagged as undocumented | The manifest was generated before the YAML was written | Re-run `dbt parse` |
| `--strict` exits 1 | An error-severity finding | Intended. Fix the finding; do not drop `--strict` |
| `test_coverage_reporter.py` reports 0% on a well-tested project | Wrong `--layer` value, or the project uses different folder names | Check the paths in `manifest.json`; pass the actual folder name |
| `contract_breaking_change_detector.py` flags everything | `--base` and `--head` are from different projects or dbt versions | Regenerate the base manifest with the current dbt version |
| `contract_breaking_change_detector.py` misses a real break | It cannot see grain changes — the column list is identical | Grain changes need human review; the script says so in its output |
| `run_results_analyzer.py`: "no results" | `run_results.json` is from a `parse`/`compile`, which executes no nodes | Use one from `build`/`run`/`test` |
| `source_freshness_monitor.py`: "no sources checked" | `dbt source freshness` was not run, or every source has `freshness: null` | Run it; check the source YAML |
| `semantic_layer_validator.py` passes but `mf validate-configs` fails | The script checks the spec offline; MetricFlow also checks the warehouse | Both are needed; the script is the fast pre-check |
| `unit_test_generator.py` emits nulls for every column | No `--catalog` supplied, so it cannot see types | `dbt docs generate`, then pass `--catalog target/catalog.json` |
| `model_dependency_analyzer.py --mermaid` output is unreadable | Too many nodes | Use `--depth 2` or scope to one model |
| `schema_yml_generator.py` types do not match the contract | Catalog is stale | Re-run `dbt docs generate` after building the model |

## When the answer is "this is not a dbt problem"

These are successful outcomes. Say so plainly:

- **The source data is wrong** → fix the source system. A mart that cleans bad data hides the
  bug and makes it permanent.
- **The number is needed once** → write the query. Do not add a mart.
- **The question is "why did X happen"** → that is an analysis, not a model.
- **Two dashboards disagree** → one metric definition in MetricFlow, not a third table.
- **It needs prediction or causal inference** → hand to data science; deliver a feature-ready
  mart with point-in-time correctness stated.
- **The EL job is broken** → escalate to the platform team. Modeling around a broken pipeline
  makes the breakage permanent.
- **A business definition is contested** → that is a decision, not a bug. Name the owner and
  stop until they decide.

## When to escalate rather than guess

- The fix requires a **business decision** — which of two disagreeing sources is right, or
  whether history should be restated.
- The failure is in the **source system or EL job**.
- A fix would **restate published numbers**. Someone owns that communication.
- The data is **wrong but plausible** and you cannot determine what it should be. Say so
  explicitly rather than shipping a guess.
