# Incremental Strategies

Per-adapter behavior, the filter patterns, and every way an incremental model goes wrong.

## Strategy matrix

| Strategy | Snowflake | BigQuery | Databricks/Spark | Postgres | Redshift | Needs `unique_key` |
|---|---|---|---|---|---|---|
| `append` | ✅ | ✅ | ✅ | ✅ | ✅ | no |
| `merge` | ✅ (default) | ✅ (default) | ✅ (default, Delta) | — | ✅ 1.6+ | **yes** |
| `delete+insert` | ✅ | — | ✅ | ✅ (default) | ✅ (default) | **yes** |
| `insert_overwrite` | — | ✅ | ✅ | — | — | no (uses partitions) |
| `microbatch` | ✅ 2.0 | ✅ 2.0 | ✅ 2.0 | ✅ 2.0 | ✅ 2.0 | no (uses `event_time`) |

## `append`

```sql
{{ config(materialized='incremental', incremental_strategy='append') }}

select * from {{ ref('stg_events') }}
{% if is_incremental() %}
    where event_at > (select max(event_at) from {{ this }})
{% endif %}
```

Fastest — a plain insert with no matching. Correct **only** for genuinely immutable data.

Fails when: a row is ever updated (the old version stays forever), or the same batch is
processed twice (duplicates, with no key to dedupe on). Every `append` model needs a
`unique`/`unique_combination_of_columns` test, because that is your only defense.

## `merge`

```sql
{{ config(
    materialized='incremental',
    unique_key='order_id',
    incremental_strategy='merge',
    merge_exclude_columns=['created_at'],       -- never overwrite the original insert time
    merge_update_columns=['status','amount']    -- OR: update only these (mutually exclusive
                                                --     with merge_exclude_columns)
) }}
```

The general-purpose default: upsert on `unique_key`. Handles updates correctly.

`unique_key` can be a list: `unique_key=['order_id','line_number']`.

**The failure:** if `unique_key` is not unique **within the incoming batch**, the merge is
nondeterministic. BigQuery hard-errors; other warehouses may silently pick an arbitrary row.
Dedupe before the merge:

```sql
qualify row_number() over (partition by order_id order by updated_at desc, _loaded_at desc) = 1
```

Order by enough columns to break every tie, or the result varies between runs.

## `delete+insert`

```sql
{{ config(materialized='incremental', unique_key='order_id',
          incremental_strategy='delete+insert') }}
```

Deletes rows whose key appears in the new batch, then inserts the batch. Same net effect as
merge; the default where merge is unavailable (Postgres, older Redshift).

Not atomic on some adapters — there is a window where the deleted rows are gone and the new
ones are not yet in. Rarely matters for analytics; matters if something reads the table
continuously.

## `insert_overwrite`

```sql
-- BigQuery: static partitions — predictable, cheapest
{{ config(
    materialized='incremental',
    incremental_strategy='insert_overwrite',
    partition_by={'field':'ordered_date','data_type':'date','granularity':'day'},
    partitions=["date_sub(current_date(), interval 3 day)", "current_date()"]
) }}

-- BigQuery: dynamic partitions — dbt discovers which partitions the query produced
{{ config(
    materialized='incremental',
    incremental_strategy='insert_overwrite',
    partition_by={'field':'ordered_date','data_type':'date','granularity':'day'}
) }}
```

Replaces **entire partitions** rather than matching rows. Dramatically cheaper than merge on
large partitioned tables — the standard choice for high-volume event data on BigQuery and
Databricks.

**The trap: any row you do not re-emit for a partition is deleted.** The query must produce
the *complete* contents of every partition it touches. A filter that accidentally narrows the
result silently deletes real data.

Verify on one partition before running it wide.

## `microbatch` (dbt 2.0)

The modern answer for large time-series. dbt splits the range into per-period batches and
runs them independently — so retries, backfills, and parallelism are all first-class instead
of hand-rolled.

```sql
{{ config(
    materialized='incremental',
    incremental_strategy='microbatch',
    event_time='ordered_at',
    batch_size='day',            -- hour | day | month | year
    lookback=3,                  -- reprocess the last 3 batches for late-arriving data
    begin='2023-01-01',
    concurrent_batches=true
) }}

select * from {{ ref('stg_shopify__orders') }}
-- No is_incremental() filter: dbt injects the batch boundaries.
```

Upstream models declare `event_time` too, and dbt filters them per batch automatically:

```yaml
models:
  - name: stg_shopify__orders
    config:
      event_time: ordered_at
```

```bash
dbt run --select fct_orders --event-time-start 2024-01-01 --event-time-end 2024-02-01
dbt retry     # re-runs only the failed batches
```

Advantages over hand-written incremental logic: no `is_incremental()` filter to get wrong,
per-batch retry, backfills without custom vars, and batches can run in parallel. If you are
on 2.0 and the model is time-series shaped, prefer this.

## Filter patterns

### Max-timestamp with lookback (the standard)

```sql
{% if is_incremental() %}
where ordered_at >= (
    select {{ dbt.dateadd('day', -3, 'max(ordered_at)') }} from {{ this }}
)
{% endif %}
```

Anchored to `max()` in `{{ this }}`, **not `current_date`**. A skipped run must not create a
permanent hole. This single detail causes more silent data loss than any other incremental
mistake.

### Sizing the lookback

Measure, do not guess:

```sql
select
    percentile_cont(0.50) within group (order by datediff('hour', ordered_at, _loaded_at)) as p50_h,
    percentile_cont(0.99) within group (order by datediff('hour', ordered_at, _loaded_at)) as p99_h,
    max(datediff('hour', ordered_at, _loaded_at))                                          as max_h
from {{ ref('stg_shopify__orders') }}
where _loaded_at >= dateadd(day, -30, current_date)
```

Set the window to about `p99 × 2`. Re-measure quarterly — arrival lag drifts as upstream
systems change.

### Load-timestamp watermark

```sql
{% if is_incremental() %}
where _loaded_at > (select max(_loaded_at) from {{ this }})
{% endif %}
```

Filters on when the row *landed* rather than when the event happened. Handles arbitrarily
late-arriving data with no lookback window. Requires a reliable pipeline load timestamp, and
requires `merge` so that a re-landed row updates rather than duplicates.

### Partition-bounded

```sql
{% if is_incremental() %}
where ordered_date >= (select max(ordered_date) from {{ this }})
{% endif %}
```

For `insert_overwrite`. Coarser, and gives the warehouse a clean partition filter.

### Var-driven backfill

```sql
{% if is_incremental() and not var('backfill_start', false) %}
    where ordered_at >= (select {{ dbt.dateadd('day', -3, 'max(ordered_at)') }} from {{ this }})
{% elif var('backfill_start', false) %}
    where ordered_at between '{{ var("backfill_start") }}' and '{{ var("backfill_end") }}'
{% endif %}
```

```bash
dbt run --select fct_orders --vars '{"backfill_start":"2024-01-01","backfill_end":"2024-02-01"}'
```

## `on_schema_change`

| Value | Behavior |
|---|---|
| `ignore` (**default**) | new upstream columns are silently dropped |
| `append_new_columns` | adds new columns; existing rows get null |
| `sync_all_columns` | adds new, **drops removed**, applies type changes |
| `fail` | errors on any drift |

**Always set it explicitly.** The default silently discards new columns, which teams discover
weeks later when a dashboard shows nulls. `append_new_columns` is the right default;
`sync_all_columns` only where a dropped column is definitely intended.

Adding a column still needs one `--full-refresh` to backfill historical rows — the config
only governs the table's shape going forward.

## Testing an incremental model

Three things, all necessary:

**1. Unit test both branches.**

```yaml
unit_tests:
  - name: test_fct_orders_full_refresh
    model: fct_orders
    overrides: {macros: {is_incremental: false}}
    given: [{input: ref('int_orders'), rows: [{order_id: '1', ordered_at: '2024-01-15'}]}]
    expect: {rows: [{order_id: '1'}]}

  - name: test_fct_orders_incremental_window
    model: fct_orders
    overrides: {macros: {is_incremental: true}}
    given:
      - input: ref('int_orders')
        rows:
          - {order_id: '1', ordered_at: '2024-01-15'}   # inside the window
          - {order_id: '2', ordered_at: '2023-06-01'}   # outside it
      - input: this
        rows: [{order_id: '0', ordered_at: '2024-01-14'}]
    expect: {rows: [{order_id: '1'}]}
```

`input: this` mocks the model's existing table, which the filter reads. Without it the
lookback cannot be exercised at all — and this is the least-observed code in most projects.

**2. Grain tests.**

```yaml
data_tests:
  - dbt_utils.unique_combination_of_columns:
      combination_of_columns: [order_id]
```

**3. The full-refresh invariant, on a schedule.**

```sql
-- analyses/audit_fct_orders_incremental.sql
{{ audit_helper.compare_relations(
     a_relation=ref('fct_orders'),
     b_relation=api.Relation.create(schema='audit', identifier='fct_orders_full'),
     primary_key='order_id'
) }}
```

Build a full-refresh copy into an audit schema monthly and compare. This is the only thing
that catches slow divergence.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Duplicates accumulating | No `unique_key`, or one that is not unique | Set/fix, then `--full-refresh` once |
| Rows missing after a slow load | Lookback shorter than actual arrival lag | Re-measure; widen; backfill the gap |
| Permanent hole after a skipped run | Filter anchored to `current_date` | Anchor to `max()` in `{{ this }}`; backfill |
| Old rows never update | `append` on mutable data | Switch to `merge` |
| New column always null | `on_schema_change: ignore` | `append_new_columns` + full refresh |
| Partitions deleted after backfill | `insert_overwrite` with an incomplete partition query | Emit complete partitions |
| First run fails on `{{ this }}` | `{{ this }}` outside `is_incremental()` | Keep it inside the guard |
| Nondeterministic merge error | Duplicate keys in the incoming batch | Dedupe with `qualify row_number()` |
| Counts differ from `--full-refresh` | Any of the above | Diagnose before shipping another run |
| Model got slower over time | Full-table scan in the subquery for `max()` | Ensure the table is clustered/partitioned on that column |

## Decision guide

```
Is a full refresh under ~5 minutes?              → not incremental. Use `table`.
Is the data immutable (an event log)?
  On BigQuery/Databricks with partitions?        → insert_overwrite
  On dbt 2.0?                                   → microbatch
  Otherwise                                      → append, plus a uniqueness test
Does the data mutate?
  Recent rows only?                              → merge with a measured lookback
  Arbitrarily old rows?                          → merge on a load-timestamp watermark
  On Postgres/Redshift?                          → delete+insert
Is it high-volume time-series on dbt 2.0?       → microbatch, always
```
