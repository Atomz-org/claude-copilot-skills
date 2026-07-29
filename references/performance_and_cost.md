# Performance and Cost Reference

Where dbt build time and warehouse spend actually go, and how to reduce them without
guessing.

## Measure before optimizing

```bash
python scripts/run_results_analyzer.py --run-results target/run_results.json \
    --manifest target/manifest.json --top 20

python scripts/run_results_analyzer.py --run-results target/run_results.json \
    --compare prod/run_results.json --slower-than 1.5
```

Four numbers:

| Number | Meaning |
|---|---|
| Total wall-clock | what the job actually takes |
| Sum of node times | total work. Much larger than wall-clock ⇒ parallelism is working |
| **Critical path** | the longest dependency chain. Wall-clock **cannot** go below this |
| Model time vs test time | tests are often 20–40% and are almost never tuned |

**Optimizing a model off the critical path changes wall-clock by zero.** This is the single
most common wasted optimization.

## Time distribution

| Phase | Typical | Notes |
|---|---|---|
| Parse | seconds | partial parsing handles it |
| Compile | seconds | slow only with heavy introspective macros |
| Model execution | the bulk | the warehouse — SQL and table design |
| Test execution | 20–40% | scope, tag, schedule |
| `docs generate` | minutes on wide projects | run once daily, not per build |

dbt itself is essentially never the bottleneck.

## The levers, ranked

### 1. Delete unused models

The cheapest model is the one that does not exist.

```bash
python scripts/dbt_project_auditor.py --manifest target/manifest.json --only orphan_models
```

A mart with no downstream model and no exposure costs build time, test time, and review time
on every single run, forever. Delete it or claim a consumer for it.

### 2. Threads

```bash
dbt build --threads 12
```

4–8 in dev, 8–16 in prod. Raise until the warehouse becomes the bottleneck; past that,
queries queue and you pay contention for nothing. Threads cannot beat the critical path.

### 3. Materialization

| Change | Wins when | Backfires when |
|---|---|---|
| `view` → `table` | queried more than built | built often, read rarely |
| `table` → `view` | rarely queried, expensive to build | downstream joins get slow |
| `table` → `incremental` | measured full refresh is too slow | small tables — complexity, no gain |
| → `ephemeral` | tiny, single-consumer | three consumers ⇒ recomputed three times |
| → `materialized_view` | constantly queried, simple SQL | SQL exceeds the adapter's MV limits |

### 4. Reduce data scanned

The largest lever on cloud warehouses.

- **Filter early** — push `where` into staging, not the mart. A filter in the bottom CTE
  scans everything first.
- **Enumerate columns** — `select *` on a columnar warehouse reads every column. Naming 5 of
  40 can cut the scan 80%+.
- **Partition/cluster on the filter column**, usually the date.
- **Aggregate before joining**, not after.
- **Kill the accidental cross join** — a null or mis-grained join key produces a row
  explosion. It shows up as a model that suddenly takes 40x longer.

### 5. Tests

```yaml
- dbt_utils.equality:
    compare_model: ref('fct_orders_legacy')
    config: {tags: ['nightly']}

- not_null:
    config: {where: "ordered_at >= dateadd(day, -30, current_date)"}
```

```bash
dbt build --exclude tag:nightly       # CI and hourly
dbt test --select tag:nightly         # daily
```

| Expensive pattern | Why | Fix |
|---|---|---|
| `relationships` on two large tables | full anti-join | scope with `where:`, or nightly |
| `dbt_utils.equality` | compares every column of two full tables | nightly only |
| `unique` on a very large table | full group-by | usually keep; scope if needed |
| `accepted_values` on high cardinality | wrong test | `relationships` to a dimension |
| Many `not_null` on one model | each is a query | keep to the columns that matter |

### 6. Dev-only filters

```sql
{% if target.name != 'prod' %}
    where ordered_at >= {{ dbt.dateadd('day', -7, 'current_date') }}
{% endif %}
```

Cuts dev build time by an order of magnitude, costs nothing in production. The
highest-value-per-character change in most projects.

### 7. Warehouse sizing

Bigger is often *cheaper* per job, because cost is size × time and a 2x warehouse frequently
finishes in under half the time on scan-bound work. Test it — do not assume in either
direction. Route dbt to its own warehouse so it does not contend with BI, and auto-suspend at
60s.

## Per-warehouse tuning

### Snowflake

```sql
{{ config(cluster_by=['ordered_date'], transient=true,
          snowflake_warehouse='TRANSFORMING_L', query_tag='dbt:fct_orders') }}
```

- Cluster above roughly 1 TB; below that micro-partition pruning handles it, and clustering
  has ongoing maintenance cost.
- `transient=true` removes Fail-safe storage on rebuildable models.
- Per-model warehouse sizing: one XL for the one heavy model, not for the whole run.
- Query Profile: "Bytes spilled to remote storage" ⇒ warehouse too small; low pruning ratio ⇒
  clustering or filter problem.
- `QUERY_HISTORY` + `query_tag` attributes cost per model.

### BigQuery

```sql
{{ config(partition_by={'field':'ordered_date','data_type':'date','granularity':'day'},
          cluster_by=['customer_id'], require_partition_filter=true,
          incremental_strategy='insert_overwrite',
          labels={'cost_center':'analytics'}) }}
```

- Partitioning **is** the cost model — you are billed for bytes scanned.
- `require_partition_filter=true` stops accidental full scans by downstream analysts.
- `insert_overwrite` ≫ `merge` on large partitioned tables.
- `maximum_bytes_billed` in the profile as a hard guardrail.
- `INFORMATION_SCHEMA.JOBS` for per-query bytes billed.

### Databricks

```sql
{{ config(file_format='delta', liquid_clustering=true, clustered_by=['customer_id'],
          tblproperties={'delta.autoOptimize.optimizeWrite':'true'}) }}
```

- Liquid clustering over partitioning — avoids the small-file problem.
- Schedule `OPTIMIZE` and `VACUUM`; Delta degrades without compaction.
- Never partition on a high-cardinality column.

### Redshift

```sql
{{ config(dist='customer_id', sort=['ordered_at']) }}
```

- `dist` on the join key eliminates data movement — the biggest lever.
- `dist='all'` for small dimensions.
- `VACUUM` + `ANALYZE` after large loads.

### Postgres

```sql
{{ config(indexes=[{'columns':['order_id'],'unique':True},{'columns':['ordered_at']}]) }}
```

- Indexes are the only lever.
- `EXPLAIN (ANALYZE, BUFFERS)` on the compiled SQL.
- Check `work_mem` — a sort spilling to disk is often the whole problem.

## Diagnosing one slow model

1. **Read the compiled SQL** — `target/compiled/...`. The problem is usually visible.
2. **Get the query plan.** dbt cannot tell you what the optimizer did.
3. **Check for row explosion.** Run each CTE's count in isolation; the step that multiplies
   is the bug.
4. **Check filter pushdown.** Is the filter applied before or after a full scan?
5. **Check join keys.** Nulls on both sides, or a type mismatch forcing a per-row cast — both
   invisible in the SQL text.
6. **Check the volume trend.** Sometimes nothing is wrong and the table grew. That is a
   materialization decision, not a bug.

## Row explosion — the biggest single cause

```sql
-- WRONG: fans out, then sums the fanned-out rows
select o.order_id, sum(o.order_amount) as amount, count(l.line_id) as lines
from orders o
join order_lines l on o.order_id = l.order_id
group by 1
-- order_amount is repeated once per line and summed. Every total is inflated.

-- RIGHT: collapse to the join grain first
with line_counts as (
    select order_id, count(*) as lines from order_lines group by 1
)
select o.order_id, o.order_amount, coalesce(lc.lines, 0) as lines
from orders o
left join line_counts lc on o.order_id = lc.order_id
```

The fanned-out version is both **wrong** and **slow** — it materializes N× the rows before
aggregating. Fixing correctness usually fixes performance too.

## Cost attribution

Execution time is a good proxy on compute-second billing (Snowflake, Databricks). On BigQuery,
bytes-billed is the real metric.

```yaml
models:
  analytics:
    marts:
      finance:
        +tags: [cost_center_finance]
        +query_tag: "dbt:finance"           # Snowflake
        +labels: {cost_center: finance}     # BigQuery
```

Then join the analyzer's node timings against `QUERY_HISTORY` / `INFORMATION_SCHEMA.JOBS` on
the tag or label.

## Build-time budget

A healthy project keeps its production build inside a budget. Rough targets:

| Project size | Target build |
|---|---|
| < 100 models | under 10 min |
| 100–500 models | under 30 min |
| 500+ models | under 60 min, or split by cadence |

Past that, split by cadence: hourly for what needs it, daily for the rest, weekly for
expensive reconciliation. Not everything needs to run every hour, and asking "who actually
needs this hourly" usually removes more time than any SQL tuning.

## Anti-patterns

- Optimizing a model that is not on the critical path.
- Making everything incremental.
- Clustering or partitioning a small table.
- `select *` through the DAG on a columnar warehouse.
- Expensive reconciliation tests on every CI build.
- Adding threads when wall-clock already equals the critical path.
- No dev-only filters, so developers wait for production-sized builds.
- Never running a full refresh, so nobody notices the incremental result diverged.
- Optimizing before measuring. The slow model is rarely the one people assume.
