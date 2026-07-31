# Materializations

What dbt does with your `select`, and when each choice is wrong.

## The five (plus adapter extras)

| Materialization | dbt builds | Rebuild cost | Query cost | Available |
|---|---|---|---|---|
| `view` | `create or replace view` | near zero | logic re-executes per query | all |
| `table` | `create or replace table as` | full rebuild | fast — data is at rest | all |
| `incremental` | table, then merge/insert new rows | only the delta | fast | all |
| `ephemeral` | nothing — inlined as a CTE | none | recomputed per consumer | all |
| `materialized_view` | `create materialized view` | warehouse-maintained | fast | Snowflake, BigQuery, Databricks, Postgres |

## `view`

```sql
{{ config(materialized='view') }}
```

**The default, and correct for most staging and intermediate models.** Costs nothing to
build and is always current.

Wrong when: it is queried far more than it is built; the logic is expensive and every
consumer re-pays for it; or several downstream models each re-execute the same heavy view.

## `table`

```sql
{{ config(materialized='table') }}
```

**The default for marts.** Data is at rest, so downstream queries are fast and predictable.

Wrong when: the table is huge and rebuilds are slow or expensive (go incremental); or nobody
queries it often enough to justify the daily rebuild (go back to a view).

Adapter configs worth knowing:

```sql
-- Snowflake
{{ config(materialized='table', cluster_by=['ordered_date'], transient=true) }}

-- BigQuery
{{ config(materialized='table',
          partition_by={'field':'ordered_date','data_type':'date','granularity':'day'},
          cluster_by=['customer_id']) }}

-- Redshift
{{ config(materialized='table', dist='customer_id', sort=['ordered_at']) }}

-- Postgres
{{ config(materialized='table',
          indexes=[{'columns':['order_id'],'unique':True},{'columns':['ordered_at']}]) }}

-- Databricks
{{ config(materialized='table', file_format='delta', location_root='/mnt/analytics') }}
```

## `incremental`

```sql
{{ config(
    materialized='incremental',
    unique_key='order_id',
    incremental_strategy='merge',
    on_schema_change='append_new_columns'
) }}

select * from {{ ref('int_orders') }}
{% if is_incremental() %}
    where ordered_at >= (select {{ dbt.dateadd('day', -3, 'max(ordered_at)') }} from {{ this }})
{% endif %}
```

Only when a **measured** full refresh is too slow or too expensive. Full detail in
[incremental_strategies.md](incremental_strategies.md).

The invariant: `--full-refresh` must reproduce the incremental result. If it does not, the
model is corrupt.

## `ephemeral`

```sql
{{ config(materialized='ephemeral') }}
```

Creates nothing in the warehouse. dbt inlines the SQL as a CTE in every model that `ref`s it.

**Right for:** small glue logic used by exactly one downstream model.

**Wrong when:**

- Three models `ref` it — the SQL is inlined three times and the warehouse recomputes it
  three times.
- You need to debug it. There is no table to query, and the error message points at the
  consumer's compiled SQL rather than the ephemeral model.
- It is heavily unit-tested — an ephemeral model cannot be mocked directly; you must mock its
  inputs instead.
- It has tests of its own. Tests on an ephemeral model still run, but they run against an
  inlined CTE, which is slower and harder to reason about.

Ephemeral is used more often than it should be. `view` costs nearly nothing and is far easier
to work with.

## `materialized_view`

```sql
-- Snowflake (dynamic table)
{{ config(materialized='dynamic_table', snowflake_warehouse='TRANSFORMING',
          target_lag='1 hour', on_configuration_change='apply') }}

-- BigQuery
{{ config(materialized='materialized_view',
          on_configuration_change='apply',
          enable_refresh=true, refresh_interval_minutes=30) }}

-- Postgres
{{ config(materialized='materialized_view', on_configuration_change='continue') }}
```

The warehouse keeps it current, so dbt does not rebuild it.

Real limits, and they are the reason MVs are used less than people expect:

- **Restricted SQL.** Snowflake MVs allow no joins and no window functions (dynamic tables
  are much more permissive). BigQuery MVs restrict aggregation types.
- **Refresh costs run continuously**, outside your dbt job, and land on a different line of
  the bill.
- **`on_configuration_change`** decides what happens when the config changes:
  `apply` (alter it), `continue` (warn and skip), or `fail`.
- **Testing is awkward** — the object may refresh mid-test.

Use them for a constantly-queried aggregate whose SQL is simple. For anything with real
logic, an incremental table gives you more control.

## Choosing

```
Is it 1:1 with a source, doing renames and casts?          → view (staging)
Is it reusable logic that nothing queries directly?        → view, or ephemeral if tiny
                                                             and single-consumer
Is it a consumer-facing mart?                              → table
  Is a full rebuild measurably too slow or expensive?      → incremental
  Is it queried constantly with simple aggregation SQL?    → materialized_view
Is it history the source destroys?                         → snapshot (not a materialization)
```

## Custom materializations

You can write one, and you almost never should.

```sql
{% materialization insert_only, default %}
  {%- set target_relation = this.incorporate(type='table') -%}
  {% call statement('main') %}
    insert into {{ target_relation }} ({{ sql }})
  {% endcall %}
  {{ return({'relations': [target_relation]}) }}
{% endmaterialization %}
```

Legitimate reasons: a warehouse-specific object type dbt does not support; an unusual write
pattern (audit-log append with no updates ever). Everything else is better served by
configuring an existing materialization. A custom materialization is code your team must
maintain against every dbt upgrade.

## Hooks

```sql
{{ config(
    materialized='table',
    pre_hook="alter session set query_tag = 'dbt:fct_orders'",
    post_hook=[
      "grant select on {{ this }} to role REPORTER",
      "{{ optimize_table(this) }}"
    ]
) }}
```

Project-wide:

```yaml
on-run-start: ["{{ log('Build starting: ' ~ target.name, info=true) }}"]
on-run-end:   ["{{ grant_select_on_schemas(schemas, 'REPORTER') }}"]

models:
  analytics:
    +post-hook: "grant select on {{ this }} to role REPORTER"
```

Prefer the `grants:` config over a grant post-hook — it is declarative and dbt reconciles it:

```yaml
models:
  - name: fct_orders
    config:
      grants:
        select: ['REPORTER', 'ANALYST']
```

Hooks run inside the model's transaction where the adapter supports one. A failing hook fails
the model. Keep them short — anything long belongs in an orchestrator task.

## Configuration precedence

Lowest to highest:

1. `dbt_project.yml` folder-level (`+materialized: view`)
2. Property YAML (`schema.yml` → `config:`)
3. In-file `{{ config() }}`

Set the default at the folder level, override the exception in the model. Check what
actually resolved:

```bash
dbt ls --select fct_orders --output json | python -m json.tool
```

## Anti-patterns

- `table` on everything, including staging. Long builds, no benefit — staging views are
  usually queried once each per run.
- `incremental` before measuring the full-refresh cost.
- `ephemeral` on a model three others depend on.
- `materialized_view` for anything with complex SQL — you hit the adapter's restrictions and
  then fight them.
- A custom materialization where a config would do.
- Grants via post-hook instead of the `grants:` config.
- Clustering or partitioning a small table — ongoing maintenance cost, no benefit.
