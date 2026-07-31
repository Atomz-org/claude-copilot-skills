---
name: dbt-model-design
description: Design and write dbt Core models — source definitions, the staging/intermediate/mart layering, grain and primary keys, join fan-out, dimensional patterns (facts, dimensions, SCD, bridge tables), materialization choice, macros, and the SQL itself. Use when a use-case spec exists and it is time to build, when refactoring an existing model, or when asked "where should this logic go", "should this be a view or a table", "why does this model duplicate rows", or "how do I model X".
---

# dbt Model Design

The build step. Precondition: a use-case spec with a decision, a named consumer, and a
stated grain. Without a grain, go back to
[analytics-request-framing](../analytics-request-framing/SKILL.md).

## Where the grain comes from

For a fact, dimension, or bridge, you do not invent the grain here — you implement one
already decided in the data model canvas. Check `skill-packs/dbt-skills/use-cases/<slug>/data-model-canvas.md`
first.

| You have | Do |
|---|---|
| A canvas row | Copy grain, PK, and SCD type verbatim into the blueprint |
| No canvas, one model, obvious grain | Proceed; record the grain in the blueprint |
| No canvas, several models or a shared dimension | Load [data-modeling](../data-modeling/SKILL.md) first |

## Clarify first

Confirm these before writing SQL. If any is unknown, **ask** — do not assume. Ask only the
two or three that most change the output; if the user says "just draft it", proceed and
list the assumptions at the top.

- **Grain** — "one row per X per Y", and the primary key that enforces it.
- **Consumer** — a dashboard, a downstream model, a sync. Decides naming, contract, and cadence.
- **Source of truth** — when two sources disagree about the same fact, which wins. Business
  policy, not an engineering choice.
- **History or current state** — a `dim_` holds current state; history needs a snapshot or
  an event-grain fact. Asked for with the same words, built completely differently.
- **Volume and freshness** — decides materialization, and whether incremental is even on the table.

## Layers

Work is assigned to exactly one layer. The boundary rules are what keep a project
navigable at 400 models.

| Layer | Naming | Materialization | Does | Never does |
|---|---|---|---|---|
| Sources | `sources.yml` | — | declares raw tables, freshness, source PK tests | — |
| Staging | `stg_<source>__<entity>` | `view` | rename, cast, coerce booleans, trim, light filtering, 1:1 with one source table | join, aggregate, apply business logic |
| Intermediate | `int_<entity>_<verbed>` | `ephemeral` or `view` | reusable joins, fan-out resolution, heavy aggregation, pivots | get queried by a BI tool |
| Marts | `fct_<entity>`, `dim_<entity>` | `table` or `incremental` | business meaning, consumer-facing names and grain | expose source column names, duplicate another mart's logic |

Two rules follow from the table and are worth stating separately:

- **Logic that two marts both need lives in intermediate.** Two marts computing "active
  customer" differently is a defect, not a variation.
- **A mart never `ref`s another mart's internals.** That creates hidden coupling and a
  rebuild-order dependency nobody documented. Extract to intermediate.

## Sources

```yaml
# models/staging/shopify/_shopify__sources.yml
version: 2
sources:
  - name: shopify
    database: raw
    schema: shopify
    loaded_at_field: _fivetran_synced
    freshness:
      warn_after:  {count: 12, period: hour}
      error_after: {count: 24, period: hour}
    tables:
      - name: orders
        description: One row per order. `_fivetran_deleted = true` marks soft deletes.
        columns:
          - name: id
            data_tests: [unique, not_null]
      - name: order_lines
      - name: customers
```

`{{ source('shopify', 'orders') }}` appears in exactly one model — its staging model.
Nothing else in the project touches a source directly.

## Staging

One staging model per source table. Thin, boring, and the only place a source column name
appears.

```sql
-- models/staging/shopify/stg_shopify__orders.sql
with

source as (
    select * from {{ source('shopify', 'orders') }}
),

renamed as (
    select
        -- ids
        id                                  as order_id,
        customer_id,

        -- strings
        lower(trim(financial_status))       as payment_status,
        lower(trim(fulfillment_status))     as fulfillment_status,

        -- numerics
        cast(total_price as {{ dbt.type_numeric() }})  as order_amount,
        cast(total_tax   as {{ dbt.type_numeric() }})  as tax_amount,
        currency                            as currency_code,

        -- booleans
        coalesce(test, false)               as is_test_order,

        -- timestamps
        cast(created_at   as timestamp)     as ordered_at,
        cast(processed_at as timestamp)     as processed_at,

        -- metadata
        _fivetran_synced                    as _loaded_at
    from source
    where not coalesce(_fivetran_deleted, false)     -- soft deletes never leave staging
)

select * from renamed
```

Conventions that pay off: group columns by type with comments, one transformation per line,
put every rename in the `renamed` CTE. Filtering soft deletes here is correct — filtering
*business* rows here is not, because a downstream model may legitimately need them.

## Intermediate

Where fan-out gets resolved and expensive logic gets computed once.

```sql
-- models/intermediate/finance/int_orders_with_line_totals.sql
with

orders as (
    select * from {{ ref('stg_shopify__orders') }}
),

line_items as (
    select * from {{ ref('stg_shopify__order_lines') }}
),

line_totals as (
    -- collapse N lines to 1 row per order BEFORE joining, so the grain survives
    select
        order_id,
        count(*)                       as line_item_count,
        sum(quantity)                  as unit_count,
        sum(line_amount)               as gross_line_amount,
        sum(discount_amount)           as discount_amount,
        count(distinct product_id)     as distinct_product_count
    from line_items
    group by 1
),

final as (
    select
        orders.order_id,
        orders.customer_id,
        orders.ordered_at,
        orders.order_amount,
        coalesce(line_totals.line_item_count, 0)     as line_item_count,
        coalesce(line_totals.gross_line_amount, 0)   as gross_line_amount,
        coalesce(line_totals.discount_amount, 0)     as discount_amount
    from orders
    left join line_totals on orders.order_id = line_totals.order_id
)

select * from final
```

## Marts

```sql
-- models/marts/finance/fct_orders.sql
{{
    config(
        materialized='incremental',
        unique_key='order_id',
        incremental_strategy='merge',
        on_schema_change='append_new_columns',
        cluster_by=['ordered_at']
    )
}}

with

orders as (
    select * from {{ ref('int_orders_with_line_totals') }}
    {% if is_incremental() %}
        -- 3-day lookback: measured max arrival lag is 38 hours (see spec §4)
        where ordered_at >= (select dateadd(day, -3, max(ordered_at)) from {{ this }})
    {% endif %}
),

customers as (
    select * from {{ ref('dim_customers') }}
),

final as (
    select
        orders.order_id,
        orders.customer_id,
        customers.customer_segment,
        customers.country_code,
        orders.line_item_count,
        orders.order_amount                                   as order_amount_usd,
        orders.gross_line_amount - orders.discount_amount     as net_line_amount_usd,
        orders.ordered_at,
        cast(orders.ordered_at as date)                       as ordered_date
    from orders
    left join customers on orders.customer_id = customers.customer_id
)

select * from final
```

Note: the projection enumerates columns. `select *` in a mart's final projection means a
new upstream column appears silently in a dashboard.

## The SQL shape

Every model, the same shape:

1. `{{ config(...) }}` if needed.
2. **Import CTEs** — one per `ref`/`source`, doing nothing but `select * from`.
3. **Logic CTEs** — named for what they contain.
4. A `final` CTE.
5. `select * from final`.

`select *` is acceptable in import CTEs and in that last line. Nowhere else.

Also: qualify every column when more than one table is in scope; no subquery nested more
than one level; comment *why*, never *what*.

## Join and fan-out discipline

For every join, write the expected cardinality down before you write the join.

| Symptom | Cause | Fix |
|---|---|---|
| Row count multiplied | Joined a 1:N table without aggregating first | Aggregate to the join grain in its own CTE |
| Totals inflated | Same fan-out, `sum()` applied after the join | Same fix. Never `sum()` across a fanned-out join |
| Rows vanished | `inner join` to an incomplete right side | `left join`, and decide what a null means |
| Duplicate PKs after a "1:1" join | The right side is not unique on that key — usually versioned or soft-deleted rows | Test the right side's uniqueness independently |
| Row count varies between runs | `row_number()` with a non-deterministic `order by` | Add enough tiebreaker columns to make it total |
| `distinct` at the top of a mart | Someone is hiding a fan-out | Find the fan-out; `distinct` is a symptom, not a fix |

## Dimensional patterns

The shapes below are the summary. Grain declaration, additivity, SCD types 0–6, bridges
with allocation factors, the unknown member, and the conformed-dimension rules are in
[data-modeling](../data-modeling/SKILL.md) and
[references/dimensional_modeling.md](../../../references/dimensional_modeling.md). If you
are choosing *which* tables to build rather than how to build one, start there.


**Fact** — one row per event or transaction. Additive measures, foreign keys to dimensions,
a timestamp. `fct_orders`, `fct_page_views`, `fct_subscription_events`.

**Dimension** — one row per entity, current state. Descriptive attributes, a stable primary
key. `dim_customers`, `dim_products`.

**Slowly changing dimension (Type 2)** — history of attribute changes. Built with a
`snapshot`, not a model; see [incremental-and-snapshots](../incremental-and-snapshots/SKILL.md).

**Bridge / many-to-many** — one row per pair. `bridge_customer_accounts`. Use when the
relationship itself has attributes, or when either side would otherwise fan out.

**Accumulating snapshot** — one row per entity, with a column per milestone timestamp
(`ordered_at`, `paid_at`, `shipped_at`, `delivered_at`). Answers "how long between stages"
without self-joins. Naturally an incremental `merge` model.

**Periodic snapshot** — one row per entity per period, capturing state at that moment.
`fct_daily_account_balances`. Grows fast; almost always incremental.

**One Big Table** — a wide denormalized mart. Legitimate when the consumer is a BI tool
that joins badly, or a feature table for ML. Costs you: every upstream change touches it,
and it is the easiest place to accidentally fan out.

## Surrogate keys

When the grain has no single natural key:

```sql
{{ dbt_utils.generate_surrogate_key(['order_id', 'line_number']) }} as order_line_sk
```

- Hash the columns that **define the grain**, nothing more. Adding a mutable attribute
  makes the key change when that attribute changes.
- Null-safe: `generate_surrogate_key` coalesces nulls to a placeholder, so `(1, null)` and
  `(1, '')` do not collide.
- Test it with `unique` + `not_null`. A surrogate key that is not tested is decorative.

## Materialization

| Choose | When | Cost |
|---|---|---|
| `view` | default; cheap to build, always current | every downstream query re-executes the logic |
| `table` | queried more than it is built; downstream joins are slow | full rebuild each run |
| `incremental` | a measured full refresh is too slow or too expensive | complexity, and a real risk of divergence |
| `ephemeral` | small glue used by exactly one downstream model | inlined per consumer; not queryable; harder to debug |
| `materialized_view` | the warehouse can maintain it incrementally and it is queried constantly | adapter-specific limits on what SQL is allowed |

Default to `view` for staging, `ephemeral` or `view` for intermediate, `table` for marts.
Escalate to `incremental` only after measuring the full-refresh cost. Detail in
[references/materializations.md](../../../references/materializations.md).

## Macros

Logic used three times becomes a macro. Used once, it stays inline — a macro that hides a
single simple expression makes the project harder to read.

```sql
-- macros/cents_to_dollars.sql
{% macro cents_to_dollars(column_name, decimal_places=2) -%}
    round( ({{ column_name }} / 100.0)::numeric, {{ decimal_places }} )
{%- endmacro %}
```

Good macro candidates: repeated `case` mappings, warehouse-specific date arithmetic,
column-list generation, per-adapter dispatch. Details in
[references/jinja_and_macros.md](../../../references/jinja_and_macros.md).

## Refactoring an existing model

1. **Blast radius first.**
   ```bash
   python scripts/model_dependency_analyzer.py --manifest target/manifest.json \
       --model fct_orders --direction down --depth 99
   ```
2. **Check governance.** Contracted or versioned? Route through the `data-contract-owner`
   agent before touching it.
3. **Capture current behavior in a unit test** before changing anything, so the refactor
   proves equivalence rather than asserting it.
4. **Change one thing at a time**, running `dbt build --select <model>+` between each.
5. **Prove equivalence** with `audit_helper`, not by eye:
   ```sql
   -- analyses/audit_fct_orders.sql
   {{ audit_helper.compare_relations(
        a_relation=api.Relation.create(database='ANALYTICS', schema='marts', identifier='fct_orders'),
        b_relation=ref('fct_orders'),
        primary_key='order_id'
   ) }}
   ```
   `compare_all_columns` gives a per-column match rate, which localizes a difference far
   faster than a row diff.

## Anti-patterns

- Business logic in staging — it gets copied to the next staging model and then they drift.
- A mart referencing a source directly, or another mart's internals.
- `select *` in a mart's final projection.
- `incremental` chosen before the full-refresh cost was ever measured.
- `ephemeral` on a model that three others depend on — the SQL is inlined and recomputed
  three times.
- A model with no primary key, or an untested one.
- `distinct` used to paper over a fan-out.
- One 400-line model instead of three readable ones. Compilation is free; comprehension is not.
- Deeply nested subqueries instead of CTEs.
- A `dim_` used where the consumer actually needed history.

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| `/dbt-model fct_orders` | Blueprint before SQL — grain, PK, join plan with cardinalities, materialization and its reason |
| "why does this model duplicate rows?" | The fan-out located in the join plan, not `distinct` bolted onto the final select |
| "where should this logic go?" | A layer verdict: staging quarantines the source, intermediate holds reusable joins, marts express meaning |
| "view or table?" | View by default; table when it is read more than it is built — with the reason written down |

**Worked example**

> "why is fct_orders returning more rows than orders?"

```
Grain claimed : one row per order. PK: order_id.
Actual        : dbt test --select fct_orders → unique_fct_orders_order_id, 312 failures.

Join plan, written out — this is the step that was skipped
  stg_shopify__orders        1 row per order          base
  stg_shopify__customers     1 per customer   N:1     safe
  stg_shopify__order_lines   N per order      1:N     ← the fan-out
  stg_shopify__refunds       N per order      1:N     ← and a second one

Two 1:N joins against an order-grain base multiply, not add: an order with 3 lines and
2 refunds becomes 6 rows. Every column still looks plausible.

Fix — resolve each 1:N to the base grain before joining
  int_order_lines_by_order   sum(line_amount), count(*) as line_count   → 1:1
  int_refunds_by_order       sum(refund_amount)                         → 1:1
  fct_orders joins both 1:1. Grain preserved by construction, not by distinct.
```

```sql
-- models/marts/fct_orders.sql
{{ config(materialized='table') }}  -- read hourly by BI, built nightly

with orders as (select * from {{ ref('stg_shopify__orders') }}),
     lines  as (select * from {{ ref('int_order_lines_by_order') }}),
     refunds as (select * from {{ ref('int_refunds_by_order') }}),

final as (
    select
        orders.order_id,                                  -- PK, enumerated: no select *
        orders.customer_id,
        orders.ordered_at,
        lines.line_count,
        orders.total_amount,
        coalesce(refunds.refund_amount, 0) as refund_amount
    from orders
    left join lines   on orders.order_id = lines.order_id     -- LEFT: an order may have no lines
    left join refunds on orders.order_id = refunds.order_id
)

select * from final
```

```bash
dbt build --select int_order_lines_by_order+ 
dbt test --select fct_orders        # unique + not_null on order_id must pass
```

`distinct` on the original would have removed the duplicate rows and kept the wrong
totals — the failure mode that passes review.

Next: [testing-and-documentation](../testing-and-documentation/SKILL.md), or
[incremental-and-snapshots](../incremental-and-snapshots/SKILL.md) if the table is large.
