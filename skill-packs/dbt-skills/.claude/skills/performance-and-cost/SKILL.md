---
name: performance-and-cost
description: Find and fix slow or expensive dbt Core builds — measuring where time actually goes with run_results.json, critical path vs total time, threading, materialization and incremental trade-offs, clustering/partitioning/sort keys, expensive test patterns, and per-warehouse tuning for Snowflake, BigQuery, Databricks, Redshift, and Postgres. Use when a build is slow or the warehouse bill went up, when a model regressed, or when asked "why is this slow", "how do I make dbt faster", or "how do I cut warehouse cost".
---

# Performance and Cost

Measure, then fix the thing that is actually costing you. Most dbt performance work targets
the wrong model.

## Measure first

```bash
python scripts/run_results_analyzer.py --run-results target/run_results.json \
    --manifest target/manifest.json --top 20

python scripts/run_results_analyzer.py --run-results target/run_results.json \
    --compare prod/run_results.json --slower-than 1.5
```

Four numbers to get before touching anything:

1. **Total wall-clock** — what the job actually takes.
2. **Sum of node execution times** — total work done. If this is much larger than wall-clock,
   parallelism is working; if it is close, you are serialized.
3. **The critical path** — the longest dependency chain. **Wall-clock cannot go below this**
   no matter how many threads you add. Optimizing a model off the critical path changes
   nothing.
4. **Model time vs test time.** Often a third or more of a build is tests, and an expensive
   `relationships` test between two large tables is a frequent hidden cost.

The analyzer reports all four and flags critical-path nodes.

## Where dbt time actually goes

| Phase | Typical share | Fix |
|---|---|---|
| Parse | seconds | partial parsing handles it; `--no-partial-parse` only when debugging |
| Compile | seconds | slow only with heavy `run_query` macros at parse time |
| **Model execution** | the bulk | the warehouse. SQL, materialization, table design |
| **Test execution** | often 20–40% | scope, tag, and schedule expensive tests |
| Catalog (`docs generate`) | minutes on wide projects | run once daily, not per build |

dbt itself is almost never the bottleneck. It is the warehouse, and the fix is SQL or table
design.

## The levers, in order of payoff

### 1. Do not build what nobody uses

The cheapest model is the one you delete.

```bash
python scripts/dbt_project_auditor.py --manifest target/manifest.json --only orphan_models
python scripts/model_dependency_analyzer.py --manifest target/manifest.json --model X --direction down
```

A mart with no downstream model and no exposure is pure cost — build time, test time, review
time, every single run. Delete it or claim a consumer for it.

### 2. Threads

```bash
dbt build --threads 12
```

Raise until the warehouse becomes the bottleneck. 4–8 in dev, 8–16 in prod is typical. Past
that, queries queue rather than parallelize and you pay warehouse contention for nothing.
Threads cannot beat the critical path — if wall-clock ≈ critical path, more threads do
literally nothing.

### 3. Materialization

| Change | When it wins | When it backfires |
|---|---|---|
| `view` → `table` | queried more than it is built | the model is built often and read rarely |
| `table` → `view` | rarely queried, expensive to build | downstream joins against it get slow |
| `table` → `incremental` | measured full refresh is genuinely too slow | small tables — complexity with no gain |
| model → `ephemeral` | tiny glue used by exactly one consumer | used by three — the SQL is inlined and recomputed three times |
| → `materialized_view` | the warehouse maintains it and it is queried constantly | the SQL exceeds what the adapter's MV supports |

Measure the full refresh before choosing incremental. Incremental buys build time and costs
correctness risk; take that trade knowingly.

### 4. Reduce data scanned

The largest single lever on cloud warehouses, because you are billed for bytes scanned or
compute-seconds.

- **Filter early.** Push `where` into the staging model, not the mart. A filter in the
  bottom CTE scans everything first.
- **Enumerate columns.** `select *` on a columnar warehouse reads every column. Naming five
  of forty columns can cut the scan by 80%+.
- **Partition and cluster** on the column you filter by — usually the date. Details below.
- **Aggregate before joining**, not after. Resolving a fan-out in a CTE before the join
  reduces both the scan and the join cost.
- **Kill the accidental cross join.** A join key with a null or a wrong grain on both sides
  produces a row explosion. It shows up as a model that suddenly takes 40x longer.

### 5. Tests

Tests are often a third of a build and are almost never tuned.

```yaml
# Expensive full-table reconciliation → nightly, not every CI run
- dbt_utils.equality:
    compare_model: ref('fct_orders_legacy')
    config: {tags: ['nightly']}

# Scope to the window that matters
- not_null:
    config: {where: "ordered_at >= dateadd(day, -30, current_date)"}
```

```bash
dbt build --exclude tag:nightly          # CI and hourly runs
dbt test --select tag:nightly            # once a day
```

The specific patterns to watch:

- **`relationships` between two large tables** — a full anti-join. Scope it with `where:` to
  a recent window, or run it nightly.
- **`unique` on a very large table** — a full group-by. Usually worth keeping; if not,
  scope it.
- **`dbt_utils.equality`** — compares every column of two full tables. Nightly only.
- **`accepted_values` on a high-cardinality column** — this is the wrong test; use a
  `relationships` test to a dimension.

### 6. Warehouse sizing

Bigger warehouses are often *cheaper* per job, because cost is size × time and a 2x
warehouse frequently finishes in under half the time on scan-bound work. Test it — do not
assume in either direction. Route dbt to its own warehouse so it does not contend with BI
queries, and set auto-suspend low (60s) so idle time is not billed.

## Per-warehouse

### Snowflake

```sql
{{ config(
    materialized='incremental',
    cluster_by=['ordered_date'],
    snowflake_warehouse='TRANSFORMING_L',    -- a bigger warehouse for this model only
    transient=true                            -- no Fail-safe storage cost
) }}
```

- **Cluster on the filter column** (usually the date) once a table passes ~1 TB. Below that,
  micro-partition pruning generally handles it. Clustering has an ongoing maintenance cost.
- **`transient=true`** on rebuildable models removes Fail-safe storage — real savings on
  large tables you can always rebuild.
- **Per-model warehouse sizing** with `snowflake_warehouse` — one XL for the one heavy model
  rather than an XL for the whole run.
- **Query Profile** in the UI is the tool: look for "Bytes spilled to remote storage" (the
  warehouse is too small) and a low partition-pruning ratio (clustering or filter problem).

### BigQuery

```sql
{{ config(
    materialized='incremental',
    incremental_strategy='insert_overwrite',
    partition_by={'field': 'ordered_date', 'data_type': 'date', 'granularity': 'day'},
    cluster_by=['customer_id', 'order_status'],
    require_partition_filter=true
) }}
```

- **Partitioning is the whole game** — you are billed for bytes scanned, and a partition
  filter is the only thing that reduces it.
- **`require_partition_filter=true`** stops a downstream analyst full-scanning the table by
  accident. High-value guardrail.
- **`insert_overwrite`** is dramatically cheaper than `merge` on large partitioned tables.
- **Cluster on up to 4 columns**, ordered most-filtered first.
- The **INFORMATION_SCHEMA.JOBS** view gives per-query bytes billed — the ground truth for
  cost attribution.

### Databricks / Spark

```sql
{{ config(
    materialized='incremental',
    file_format='delta',
    incremental_strategy='merge',
    partition_by=['ordered_date'],
    liquid_clustering=true,
    clustered_by=['customer_id']
) }}
```

- **Liquid clustering** where available — it replaces partitioning and avoids the small-file
  problem that fine-grained partitioning creates.
- **`OPTIMIZE` and `VACUUM`** on a schedule via a post-hook or a separate job. Delta tables
  degrade without compaction.
- Do not partition on a high-cardinality column; you get thousands of tiny files and every
  read slows down.

### Redshift

```sql
{{ config(
    materialized='table',
    dist='customer_id',       -- co-locate rows that get joined together
    sort=['ordered_at']       -- the filter column
) }}
```

- **Distribution key** is the biggest lever: `dist` on the join key eliminates data movement.
  `dist='all'` for small dimensions replicates them to every node.
- **Sort key** on the column you filter by, so zone maps can skip blocks.
- **`VACUUM` and `ANALYZE`** after large loads, or the planner works from stale statistics.

### Postgres

```sql
{{ config(
    materialized='table',
    indexes=[
      {'columns': ['order_id'], 'unique': True},
      {'columns': ['ordered_at']},
      {'columns': ['customer_id', 'ordered_at']}
    ]
) }}
```

- **Indexes are the lever** — Postgres has no columnar pruning. Index the join and filter
  columns.
- `EXPLAIN (ANALYZE, BUFFERS)` on the compiled SQL is the diagnostic.
- Check `work_mem` and `maintenance_work_mem`; a sort spilling to disk is often the whole
  problem.
- Native partitioning for very large fact tables, though this is where Postgres stops being
  the right warehouse.

## Diagnosing one slow model

1. **Read the compiled SQL.** `target/compiled/...` — the problem is usually visible.
2. **Get the query plan** from the warehouse. dbt cannot tell you what the optimizer did.
3. **Check for row explosion.** Run each CTE's row count in isolation; a step that multiplies
   is the bug.
4. **Check the filter.** Is it pushed down, or applied after a full scan?
5. **Check the join keys.** Nulls on both sides of a join, or a type mismatch forcing a cast
   on every row, are common and invisible in the SQL text.
6. **Check the data volume trend.** Sometimes nothing is wrong and the table simply grew —
   that is a materialization decision, not a bug.

## Cost attribution

```bash
python scripts/run_results_analyzer.py --run-results target/run_results.json \
    --manifest target/manifest.json --top 20 --json > timings.json
```

Execution time is a good proxy for compute cost on warehouses billed by compute-second
(Snowflake, Databricks). On BigQuery, bytes-billed is the real metric — join the analyzer's
node timings against `INFORMATION_SCHEMA.JOBS` on the query label to attribute cost per
model.

Tag models by cost centre so the bill can be split:

```yaml
models:
  analytics:
    marts:
      finance:
        +tags: [cost_center_finance]
        +query_tag: "dbt:finance"     # Snowflake: appears in QUERY_HISTORY
```

## Anti-patterns

- Optimizing a model that is not on the critical path. Zero wall-clock improvement.
- Making everything incremental. Complexity and correctness risk on tables that rebuild in
  thirty seconds.
- Clustering or partitioning a small table. Maintenance cost, no benefit.
- `select *` through the DAG on a columnar warehouse.
- Running expensive reconciliation tests on every CI build.
- Adding threads when wall-clock already equals the critical path.
- Never running a full refresh, so nobody notices the incremental result diverged.
- Optimizing before measuring. The slow model is rarely the one people assume.

Reference: [references/performance_and_cost.md](../../../references/performance_and_cost.md).
