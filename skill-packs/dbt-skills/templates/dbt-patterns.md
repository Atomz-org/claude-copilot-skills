# dbt File Patterns — copy-paste starting points

Working shapes for every file type in a dbt Core project. Adapt to the project's existing
conventions; consistency with the project beats consistency with this file.

---

## Staging model

```sql
-- models/staging/shopify/stg_shopify__orders.sql
with

source as (
    select * from {{ source('shopify', 'orders') }}
),

renamed as (
    select
        -- ids
        id                                             as order_id,
        customer_id,

        -- strings
        lower(trim(financial_status))                  as payment_status,
        currency                                       as currency_code,

        -- numerics
        cast(total_price as {{ dbt.type_numeric() }})  as order_amount,

        -- booleans
        coalesce(test, false)                          as is_test_order,

        -- timestamps
        cast(created_at as timestamp)                  as ordered_at,

        -- metadata
        _fivetran_synced                               as _loaded_at

    from source
    where not coalesce(_fivetran_deleted, false)   -- soft deletes never leave staging
)

select * from renamed
```

## Intermediate model — resolving fan-out

```sql
-- models/intermediate/finance/int_orders_with_line_totals.sql
{{ config(materialized='ephemeral') }}

with

orders as (
    select * from {{ ref('stg_shopify__orders') }}
),

line_items as (
    select * from {{ ref('stg_shopify__order_lines') }}
),

line_totals as (
    -- Collapse N lines to 1 row per order BEFORE the join, so the order grain
    -- survives. Summing across the fanned-out join instead inflates every total.
    select
        order_id,
        count(*)             as line_item_count,
        sum(line_amount)     as gross_line_amount,
        sum(discount_amount) as discount_amount
    from line_items
    group by 1
),

final as (
    select
        orders.order_id,
        orders.customer_id,
        orders.ordered_at,
        coalesce(line_totals.line_item_count, 0)   as line_item_count,
        coalesce(line_totals.gross_line_amount, 0) as gross_line_amount
    from orders
    left join line_totals on orders.order_id = line_totals.order_id
)

select * from final
```

## Incremental mart

```sql
-- models/marts/finance/fct_orders.sql
{{
    config(
        materialized='incremental',
        unique_key='order_id',
        incremental_strategy='merge',
        on_schema_change='append_new_columns',
        cluster_by=['ordered_date']
    )
}}

with

orders as (
    select * from {{ ref('int_orders_with_line_totals') }}

    {% if is_incremental() %}
    -- Lookback = 3 days. Measured p99 arrival lag is 38h (spec section 4); window is
    -- p99 x 2. Anchored to max() in `this`, NOT current_date — a skipped run must not
    -- leave a permanent hole.
    where ordered_at >= (
        select {{ dbt.dateadd('day', -3, 'max(ordered_at)') }} from {{ this }}
    )
    {% endif %}
),

final as (
    select
        order_id,
        customer_id,
        order_amount                    as order_amount_usd,
        ordered_at,
        cast(ordered_at as date)        as ordered_date
    from orders
)

select * from final
```

## Microbatch incremental (dbt 2.0)

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
-- No is_incremental() filter: dbt injects the batch boundaries itself.
```

## Snapshot

```yaml
# snapshots/shopify_orders_snapshot.yml   (dbt 2.0)
snapshots:
  - name: shopify_orders_snapshot
    relation: source('shopify', 'orders')     # the RAW source, never a model
    config:
      schema: snapshots                        # shared, NOT environment-suffixed
      unique_key: id                           # never change after the first run
      strategy: timestamp                      # never change after the first run
      updated_at: updated_at
      invalidate_hard_deletes: true
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

## `sources.yml`

```yaml
version: 2

sources:
  - name: shopify
    description: Raw Shopify tables landed by Fivetran.
    database: raw
    schema: shopify
    loaded_at_field: _fivetran_synced      # a WAREHOUSE LOAD timestamp, not updated_at
    freshness:
      warn_after:  {count: 12, period: hour}
      error_after: {count: 24, period: hour}
    tables:
      - name: orders
        description: One row per order. `_fivetran_deleted = true` marks soft deletes.
        freshness:
          warn_after:  {count: 1, period: hour}
          error_after: {count: 6, period: hour}
        columns:
          - name: id
            description: Shopify order id. Primary key.
            data_tests: [unique, not_null]
      - name: currency_rates
        freshness: null      # explicit opt-out — a one-time load, not an oversight
```

## `schema.yml` with a contract

```yaml
version: 2

models:
  - name: fct_orders
    description: >
      One row per order at its current status. Excludes internal test accounts.
      Amounts are USD at the order-date rate.
    config:
      contract: {enforced: true}
      group: finance
      access: public
      tags: [finance, daily]
    columns:
      - name: order_id
        description: Primary key.
        data_type: varchar                   # required on every column when enforced
        constraints:
          - type: not_null
        data_tests: [unique, not_null]

      - name: customer_id
        description: FK to dim_customers. Null for guest checkouts (~3% of orders).
        data_type: varchar
        data_tests:
          - relationships:
              to: ref('dim_customers')
              field: customer_id
              config:
                where: "customer_id is not null"

      - name: order_status
        description: "{{ doc('order_status') }}"
        data_type: varchar
        data_tests:
          - accepted_values:
              values: [pending, paid, fulfilled, refunded, cancelled]

    data_tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: [order_id, snapshot_date]
```

## Model versions

```yaml
models:
  - name: fct_orders
    latest_version: 2
    config:
      contract: {enforced: true}
      access: public
    columns:
      - name: order_id
        data_type: varchar
      - name: currency_code
        data_type: varchar
    versions:
      - v: 1
        deprecation_date: 2026-09-30 00:00:00+00:00   # ALWAYS set this
        columns:
          - include: all
            exclude: [currency_code]
      - v: 2
```

## Unit test

```yaml
unit_tests:
  - name: test_refund_overrides_fulfilled_status
    model: int_orders_with_line_totals
    description: A refunded order reports 'refunded' even when fulfillment succeeded.
    given:
      - input: ref('stg_shopify__orders')
        rows:
          - {order_id: '1', payment_status: 'refunded', is_test_order: false}
          - {order_id: '2', payment_status: 'paid',     is_test_order: false}
          - {order_id: '3', payment_status: 'weird_new_value', is_test_order: false}
      - input: ref('stg_shopify__order_lines')   # every ref must be mocked, even empty
        rows: []
    expect:
      rows:                                       # written BY HAND from the requirement
        - {order_id: '1', order_status: 'refunded'}
        - {order_id: '2', order_status: 'paid'}
        - {order_id: '3', order_status: 'unknown'}

  # Incremental: the least-observed code in most projects.
  - name: test_fct_orders_incremental_window
    model: fct_orders
    overrides:
      macros:
        is_incremental: true
    given:
      - input: ref('int_orders_with_line_totals')
        rows:
          - {order_id: '1', ordered_at: '2024-01-15'}   # inside the lookback
          - {order_id: '2', ordered_at: '2023-06-01'}   # outside it
      - input: this                                     # mocks the existing table
        rows: [{order_id: '0', ordered_at: '2024-01-14'}]
    expect:
      rows: [{order_id: '1'}]

  # When types cause inexplicable comparison failures, use format: sql and cast.
  - name: test_typed_fixture
    model: fct_orders
    given:
      - input: ref('int_orders_with_line_totals')
        format: sql
        rows: |
          select cast('1' as varchar) as order_id,
                 cast(100.00 as numeric(28,6)) as order_amount,
                 cast('2024-01-15 10:30:00' as timestamp) as ordered_at
    expect:
      rows: [{order_id: '1'}]
```

## Singular test

```sql
-- tests/assert_revenue_reconciles_to_ledger.sql
{{ config(severity='error', store_failures=true, tags=['reconciliation','nightly']) }}

with mart as (
    select ordered_date as day, sum(order_amount_usd) as amount
    from {{ ref('fct_orders') }}
    where order_status != 'cancelled'
    group by 1
),
ledger as (
    select posting_date as day, sum(amount_usd) as amount
    from {{ ref('stg_netsuite__revenue_postings') }}
    group by 1
)
select mart.day, mart.amount as mart_amount, ledger.amount as ledger_amount
from mart join ledger using (day)
where abs(mart.amount - ledger.amount) / nullif(ledger.amount, 0) > 0.005
```

## Custom generic test

```sql
-- tests/generic/test_positive_or_null.sql
{% test positive_or_null(model, column_name) %}
select {{ column_name }}
from {{ model }}
where {{ column_name }} is not null and {{ column_name }} < 0
{% endtest %}
```

## Docs block

```markdown
{% docs order_status %}
The current fulfillment state of the order.

| Value | Meaning |
|---|---|
| `pending` | Created, payment not captured |
| `paid` | Payment captured, not yet fulfilled |
| `fulfilled` | Shipped and confirmed by the carrier |
| `refunded` | Fully or partially refunded |
| `cancelled` | Cancelled before fulfillment |

A refunded order retains its original `order_amount_usd`; net revenue subtracts refunds
in `fct_order_revenue`.
{% enddocs %}
```

## Exposure

```yaml
exposures:
  - name: executive_revenue_dashboard
    type: dashboard              # dashboard | notebook | analysis | ml | application
    maturity: high
    url: https://bi.example.com/dashboards/42
    owner: {name: Priya Raman, email: priya@example.com}
    description: >
      Board-level weekly revenue, read every Monday 08:00 UTC. Breaking this is a P1.
    depends_on:
      - ref('fct_orders')
      - metric('revenue')
```

## Macro with adapter dispatch

```sql
-- macros/safe_divide.sql
{% macro safe_divide(numerator, denominator) -%}
    {{ return(adapter.dispatch('safe_divide', 'my_project')(numerator, denominator)) }}
{%- endmacro %}

{% macro default__safe_divide(numerator, denominator) -%}
    {{ numerator }} / nullif({{ denominator }}, 0)
{%- endmacro %}

{% macro bigquery__safe_divide(numerator, denominator) -%}
    safe_divide({{ numerator }}, {{ denominator }})
{%- endmacro %}
```

## `generate_schema_name`

```sql
-- macros/generate_schema_name.sql
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- set default_schema = target.schema -%}
    {%- if target.name == 'prod' and custom_schema_name is not none -%}
        {{ custom_schema_name | trim }}
    {%- else -%}
        {{ default_schema }}
    {%- endif -%}
{%- endmacro %}
```

Verbatim schema names are only safe where prod is a separate **database**; in a shared
database they mean a dev run writes into production's `marts`. The `== 'prod'` test above
is what keeps that safe, so do not loosen it to "always verbatim". When more than one
environment legitimately needs verbatim names, use the opt-in allowlist variant in the
worked example at
`skill-packs/dbt-skills/use-cases/example-order-revenue-mart/dbt_project/macros/generate_schema_name.sql`,
which makes each target declare its isolation and then verifies the claim at parse time.

## Semantic model and metrics

```yaml
semantic_models:
  - name: orders
    model: ref('fct_orders')                # a MART, never a staging model
    defaults:
      agg_time_dimension: ordered_at
    entities:
      - {name: order, type: primary, expr: order_id}
      - {name: customer, type: foreign, expr: customer_id}
    dimensions:
      - name: ordered_at
        type: time
        type_params: {time_granularity: day}    # REQUIRED on every time dimension
      - {name: order_status, type: categorical}
    measures:
      - {name: order_total, agg: sum, expr: order_amount_usd}
      - {name: order_count, agg: count, expr: order_id}

metrics:
  - name: revenue
    label: Revenue
    description: Gross order revenue, USD, excluding cancelled orders.
    type: simple
    type_params:
      measure: {name: order_total, fill_nulls_with: 0, join_to_timespine: true}
    filter: "{{ Dimension('order__order_status') }} != 'cancelled'"
    #        ^^^ the entity__dimension prefix is mandatory

  - name: revenue_growth_mom
    type: derived
    type_params:
      expr: (revenue - revenue_prev_month) * 100.0 / nullif(revenue_prev_month, 0)
      metrics:
        - {name: revenue}
        - {name: revenue, alias: revenue_prev_month, offset_window: 1 month}
```

## Time spine

```sql
-- models/marts/metricflow_time_spine.sql
{{ config(materialized='table') }}
{{ dbt_utils.date_spine(
    datepart="day",
    start_date="cast('2019-01-01' as date)",
    end_date="dateadd(year, 2, current_date)"     -- must run PAST your fact data
) }}
```

```yaml
models:
  - name: metricflow_time_spine
    time_spine:
      standard_granularity_column: date_day
    columns:
      - name: date_day
        granularity: day
```

## `selectors.yml`

```yaml
selectors:
  - name: nightly_finance
    description: Finance marts and upstream, excluding slow reconciliation tests.
    definition:
      union:
        - {method: tag, value: finance}
        - {method: path, value: models/marts/finance, parents: true}
      exclude:
        - {method: tag, value: slow}

  - name: ci_changed
    definition: {method: state, value: modified, children: true}
```

## `audit_helper` equivalence check

```sql
-- analyses/audit_fct_orders.sql
{{ audit_helper.compare_all_columns(
     a_relation=api.Relation.create(database='LEGACY', schema='reporting',
                                    identifier='orders_summary'),
     b_relation=ref('fct_orders'),
     primary_key='order_id'
) }}
```

Start with `compare_all_columns` — per-column match rates turn "the numbers differ" into
"revenue matches on 99.97% of rows" in one query.
