---
name: incremental-and-snapshots
description: Make large dbt Core tables buildable and capture history that sources destroy — incremental materialization, unique_key, is_incremental() filters and lookback windows, merge/delete+insert/insert_overwrite/append/microbatch strategies per warehouse, on_schema_change, backfills, and snapshots for SCD Type 2. Use when a model is too slow or expensive to rebuild, when a source overwrites values you will need later, or when asked "should this be incremental", "how do I backfill", "why are there duplicates", or "how do I track changes over time".
---

# Incremental Models and Snapshots

Two different problems that both involve time. **Incremental** is about not rebuilding what
you already built. **Snapshots** are about capturing what the source is about to destroy.

## Should this be incremental?

Incremental buys build time and costs correctness risk. Take the trade only when the
numbers justify it.

| Situation | Answer |
|---|---|
| Full refresh under ~5 minutes | **No.** The complexity is not worth it. |
| Full refresh costs real money and runs many times a day | **Yes**, if the source is append-mostly |
| Rows mutate frequently across the whole history | **Probably not** — a `merge` scanning everything saves little |
| Immutable event log, high volume | **Yes**, the ideal case: `append` or `insert_overwrite` |
| The table is a dimension of current state | **No** — a `table` rebuild is simpler and always correct |
| You have not measured the full-refresh cost | **Not yet.** Measure it. |

Measure first:

```bash
dbt build --select fct_orders --full-refresh
python scripts/run_results_analyzer.py --run-results target/run_results.json --top 5
```

## The shape

```sql
{{
    config(
        materialized='incremental',
        unique_key='order_id',
        incremental_strategy='merge',
        on_schema_change='append_new_columns'
    )
}}

with source_data as (
    select * from {{ ref('int_orders_with_line_totals') }}

    {% if is_incremental() %}
        -- Lookback = 3 days. Measured p99 arrival lag is 38h (use-case spec §4).
        -- Compare against max(ordered_at) in `this`, NOT current_date: a skipped run
        -- must not create a permanent hole.
        where ordered_at >= (
            select {{ dbt.dateadd('day', -3, 'max(ordered_at)') }} from {{ this }}
        )
    {% endif %}
)

select * from source_data
```

Four things this gets right, and each of them is a common bug when missed:

1. **`unique_key` is set.** Without it, `merge` cannot match and you get duplicates.
2. **The filter is inside `{% if is_incremental() %}`**, so `--full-refresh` scans
   everything and reproduces the table exactly.
3. **The window is anchored to `max()` in `{{ this }}`**, not `current_date`. Anchoring to
   the clock means a missed run leaves a permanent gap.
4. **The lookback is sized from measured arrival lag**, with the measurement cited. A
   guessed window silently drops late rows forever.

Measure the arrival lag before choosing the window:

```sql
select
    percentile_cont(0.50) within group (order by datediff('hour', ordered_at, _loaded_at)) as p50_lag_h,
    percentile_cont(0.99) within group (order by datediff('hour', ordered_at, _loaded_at)) as p99_lag_h,
    max(datediff('hour', ordered_at, _loaded_at))                                          as max_lag_h
from {{ ref('stg_shopify__orders') }}
where _loaded_at >= dateadd(day, -30, current_date)
```

Set the window to roughly `p99_lag × 2`, and re-measure quarterly. It drifts.

## Strategies

| Strategy | What it does | Needs `unique_key` | Best for | Adapters |
|---|---|---|---|---|
| `append` | inserts, no dedup | no | immutable event logs | all |
| `merge` | upsert on the key | **yes** | mutable records, the general default | Snowflake, BigQuery, Databricks, Spark, Redshift (1.6+) |
| `delete+insert` | delete matching keys, then insert | **yes** | Postgres/Redshift where merge is unavailable or slower | Postgres, Redshift, Snowflake |
| `insert_overwrite` | replaces whole partitions | no (uses partitions) | large partitioned event tables — the cheapest at scale | BigQuery, Databricks, Spark |
| `microbatch` | dbt splits the range into per-period batches automatically | no (uses `event_time`) | large time-series, easy retries and backfills | 2.0, most adapters |

### merge

```sql
{{ config(
    materialized='incremental',
    unique_key='order_id',
    incremental_strategy='merge',
    merge_exclude_columns=['created_at']       -- never overwrite the original insert time
) }}
```

`unique_key` can be a list: `unique_key=['order_id', 'line_number']`. If it is not
genuinely unique in the incoming batch, most warehouses raise a nondeterministic-merge
error — and BigQuery in particular will fail hard. Dedup in the model before the merge.

### insert_overwrite (BigQuery / Databricks / Spark)

```sql
{{ config(
    materialized='incremental',
    incremental_strategy='insert_overwrite',
    partition_by={'field': 'ordered_date', 'data_type': 'date', 'granularity': 'day'},
    partitions=["date_sub(current_date(), interval 3 day)", "current_date()"]
) }}
```

Replaces entire partitions rather than matching rows — the cheapest strategy on large
partitioned tables. The catch: **any row you do not re-emit for a partition is deleted**.
The query must produce the *complete* contents of every partition it touches.

### microbatch (dbt 2.0)

The modern answer for large time-series. dbt slices the range into batches, runs them
independently, and lets you retry or backfill a window without hand-written date logic.

```sql
{{ config(
    materialized='incremental',
    incremental_strategy='microbatch',
    event_time='ordered_at',
    batch_size='day',
    lookback=3,
    begin='2023-01-01',
    concurrent_batches=true
) }}

select * from {{ ref('stg_shopify__orders') }}
-- No is_incremental() filter needed: dbt injects the batch boundaries itself.
```

Upstream models declare `event_time` too, and dbt filters them per batch automatically.

```bash
dbt run --select fct_orders --event-time-start 2024-01-01 --event-time-end 2024-02-01
dbt retry            # re-runs only the failed batches
```

## `on_schema_change`

| Value | Behavior |
|---|---|
| `ignore` (default) | new upstream columns are silently dropped from the incremental result |
| `append_new_columns` | adds new columns; existing rows get null for them |
| `sync_all_columns` | adds new, **drops removed**, and applies type changes |
| `fail` | errors on any drift |

**Set it explicitly.** The default silently discards new columns, which people discover
weeks later. `append_new_columns` is the right default for most teams; `sync_all_columns`
only where you are certain a dropped column is intended.

Adding a column still requires a `--full-refresh` to backfill historical rows — the config
only affects the table's shape going forward.

## Backfills

```bash
# Whole table
dbt build --select fct_orders --full-refresh

# Bounded window, via a var the model reads
dbt build --select fct_orders --vars '{"backfill_start": "2024-01-01", "backfill_end": "2024-02-01"}'

# Microbatch: first-class
dbt run --select fct_orders --event-time-start 2024-01-01 --event-time-end 2024-02-01
```

Before any production backfill: know the cost, know how long the table is inconsistent
during it, and know the rollback. On `insert_overwrite`, a backfill that emits incomplete
partitions **deletes** the rows it did not re-emit — verify the query returns complete
partitions on a single day first.

## The invariant that must hold

> `dbt build --select <model> --full-refresh` must reproduce the incremental result.

If it does not, the model is corrupt and every number from it is suspect. Check it
deliberately:

```sql
-- analyses/audit_fct_orders_incremental.sql
{{ audit_helper.compare_relations(
     a_relation=ref('fct_orders'),                                          -- incremental
     b_relation=api.Relation.create(schema='audit', identifier='fct_orders_full'),
     primary_key='order_id'
) }}
```

Run it after any change to the incremental logic, and on a monthly schedule regardless.

## Incremental failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Duplicates accumulating | No `unique_key`, or one that is not unique | Set/fix it, then `--full-refresh` once |
| Rows missing after a slow load | Lookback shorter than actual arrival lag | Re-measure lag; widen the window; backfill the gap |
| Permanent hole after a skipped run | Filter anchored to `current_date` instead of `max()` in `{{ this }}` | Anchor to `this`; backfill the gap |
| Old rows never update | `append` on mutable data | Switch to `merge` |
| New column always null | `on_schema_change: ignore` | Set `append_new_columns` and full-refresh |
| Partitions deleted after a backfill | `insert_overwrite` with an incomplete partition query | The query must emit complete partitions |
| First run fails on `{{ this }}` | `{{ this }}` referenced outside `is_incremental()` | It does not exist on the first run — keep it inside the guard |
| Merge is nondeterministic (BigQuery hard-errors) | Duplicate `unique_key` values in the incoming batch | Dedup before the merge |

## Snapshots

Use a snapshot when a **mutable source overwrites values you will need later** — an order's
status, a customer's plan tier, a price. Once the source overwrites it, it is gone; a
snapshot is the only way to answer "what was it on 2024-03-01".

```yaml
# snapshots/shopify_orders_snapshot.yml   (dbt 2.0 YAML form)
snapshots:
  - name: shopify_orders_snapshot
    relation: source('shopify', 'orders')
    config:
      schema: snapshots
      unique_key: id
      strategy: timestamp
      updated_at: updated_at
      invalidate_hard_deletes: true
      dbt_valid_to_current: "'9999-12-31'::timestamp"
```

```sql
-- snapshots/shopify_orders_snapshot.sql   (classic form, all versions)
{% snapshot shopify_orders_snapshot %}
{{ config(
    target_schema='snapshots',
    unique_key='id',
    strategy='timestamp',
    updated_at='updated_at',
    invalidate_hard_deletes=true
) }}
select * from {{ source('shopify', 'orders') }}
{% endsnapshot %}
```

dbt adds `dbt_valid_from`, `dbt_valid_to`, `dbt_scd_id`, and `dbt_updated_at`. The current
row has `dbt_valid_to` null (or the sentinel, if configured).

### Strategy

| Strategy | Use when | Risk |
|---|---|---|
| `timestamp` | the source has a reliable `updated_at` | if `updated_at` does not move on every change, the change is missed forever |
| `check` | no reliable timestamp; list the columns to watch | a full column comparison every run; slower |

```sql
{{ config(strategy='check', check_cols=['status', 'plan_tier', 'price']) }}
{{ config(strategy='check', check_cols='all') }}   -- any change creates a new row; noisy
```

Prefer `timestamp` and verify the source actually maintains it. `check_cols='all'` on a
wide table produces a new row for every metadata touch.

### Snapshot rules

- **Snapshot the raw source, never a transformed model.** If the transform changes, the
  history becomes uninterpretable. Transform downstream of the snapshot.
- **Never change `unique_key` or `strategy` after the first run.** dbt cannot reconcile the
  existing rows; you must rebuild from scratch and the pre-existing history is lost.
- **Snapshots live in a shared, non-environment-suffixed schema.** A snapshot built in a dev
  schema captures dev-timed history that can never be merged into prod.
- **Snapshots run on their own cadence** — often more frequently than the marts, because a
  change that happens between runs is invisible forever. `dbt snapshot` runs them;
  `dbt build` includes them.
- **Back up before any structural change.** `create table snapshots.x_backup as select *
  from snapshots.x` costs nothing next to losing two years of history.

### Consuming a snapshot

```sql
-- Current state
select * from {{ ref('shopify_orders_snapshot') }} where dbt_valid_to is null

-- State as of a point in time
select * from {{ ref('shopify_orders_snapshot') }}
where '2024-03-01' >= dbt_valid_from
  and ('2024-03-01' < dbt_valid_to or dbt_valid_to is null)

-- A proper SCD2 dimension
select
    {{ dbt_utils.generate_surrogate_key(['id', 'dbt_valid_from']) }} as customer_key,
    id                                     as customer_id,
    plan_tier,
    dbt_valid_from                         as valid_from,
    coalesce(dbt_valid_to, '9999-12-31')   as valid_to,
    dbt_valid_to is null                   as is_current
from {{ ref('shopify_customers_snapshot') }}
```

Test the SCD2 result: no overlapping validity windows per key, exactly one current row per
key, and no gaps. `dbt_utils.unique_combination_of_columns` on `[id, dbt_valid_from]` plus a
singular test for overlaps.

## Snapshots vs incremental

| | Snapshot | Incremental |
|---|---|---|
| Purpose | preserve history the source destroys | avoid rebuilding what is already built |
| Grain | one row per key per validity period | whatever the model's grain is |
| Rebuildable | **no** — the history is the data | yes, `--full-refresh` |
| Source | raw source only | any upstream model |
| Failure mode | missed changes, silently and permanently | duplicates or missing rows, recoverable |

The asymmetry matters: an incremental bug is recoverable with a full refresh; a snapshot
that missed six months of changes is not recoverable at all.

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| "should fct_events be incremental?" | The measured full-refresh cost first — incremental is a decision, not a default |
| "why are there duplicates after last night's run?" | `unique_key` or the lookback window, checked against the invariant below |
| "we need price history" | A snapshot on the *raw source* — a mart cannot recover history it never stored |
| "how do I backfill 2025?" | A bounded window via a var, not `--full-refresh` on a 4 TB table |

**Worked example**

> "fct_orders takes 40 minutes to build — make it incremental"

```sql
-- models/marts/fct_orders.sql
{{ config(
    materialized='incremental',
    unique_key='order_id',              -- required for merge; without it, rows duplicate
    incremental_strategy='merge',
    on_schema_change='append_new_columns'
) }}

select * from {{ ref('int_orders_enriched') }}

{% if is_incremental() %}
  -- Lookback: 3 days. Measured p99 arrival lag is 41 hours (query in the PR body,
  -- re-measured 2026-07); anchored to max() in this table, never current_date.
  where updated_at >= (select dateadd(day, -3, max(updated_at)) from {{ this }})
{% endif %}
```

```bash
# The invariant: the incremental result must equal the full-refresh result
dbt build --select fct_orders --full-refresh
create table analytics.audit.fct_orders_full as select * from analytics.marts.fct_orders;
dbt build --select fct_orders            # incremental path
# then compare — any diff means the model is corrupt, not "close enough"

# Bounded backfill, via a var the model reads — not a 4 TB full refresh
dbt build --select fct_orders --vars '{"backfill_start": "2025-01-01", "backfill_end": "2025-12-31"}'
```

Anchoring the filter to `current_date` instead of `max(updated_at)` in `{{ this }}` is the
common defect: one skipped run silently leaves a permanent hole. And a lookback guessed
rather than measured loses late rows forever — no test catches either.

Next: [testing-and-documentation](../testing-and-documentation/SKILL.md), and
[dbt-unit-testing](../dbt-unit-testing/SKILL.md) — incremental logic needs a unit test
covering the `is_incremental()` branch.
