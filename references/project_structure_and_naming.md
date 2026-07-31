# Project Structure, Naming, and SQL Style

Conventions exist so a reviewer can read an unfamiliar model without asking questions.
**If the project already has a convention that differs from this, follow the project's.**
Consistency beats correctness here.

## Directory layout

```
analytics/
├── dbt_project.yml
├── packages.yml
├── package-lock.yml           # commit this
├── selectors.yml
├── requirements.txt           # pinned dbt-core + adapter
├── models/
│   ├── staging/
│   │   ├── shopify/
│   │   │   ├── _shopify__sources.yml     # source defs + freshness
│   │   │   ├── _shopify__models.yml      # docs + tests for these models
│   │   │   ├── _shopify__docs.md         # docs blocks
│   │   │   ├── stg_shopify__orders.sql
│   │   │   └── stg_shopify__customers.sql
│   │   └── stripe/
│   ├── intermediate/
│   │   └── finance/
│   │       ├── _int_finance__models.yml
│   │       └── int_orders_joined_to_payments.sql
│   ├── marts/
│   │   ├── finance/
│   │   │   ├── _finance__models.yml
│   │   │   ├── fct_orders.sql
│   │   │   └── dim_customers.sql
│   │   ├── marketing/
│   │   └── metricflow_time_spine.sql
│   └── semantic/
│       ├── _semantic_models.yml
│       └── _metrics.yml
├── macros/
│   ├── generate_schema_name.sql
│   └── cents_to_dollars.sql
├── tests/
│   ├── generic/
│   │   └── test_positive_or_null.sql
│   └── assert_revenue_reconciles.sql
├── snapshots/
├── seeds/
└── analyses/                  # compiled, never run — audit queries, scratch SQL
```

### YAML file conventions

- **Leading underscore** sorts YAML to the top of a directory listing.
- **One YAML per directory**, not one giant `schema.yml` and not one per model. A giant file
  becomes unreviewable; one-per-model makes cross-model tests awkward to place.
- Name it `_<domain>__models.yml`, `_<source>__sources.yml`, `_<domain>__docs.md`.

### `analyses/`

Compiled by `dbt compile` but never executed against the warehouse by `dbt run`. The right
home for `audit_helper` comparison queries, ad-hoc investigations worth keeping, and any SQL
that should be version-controlled and reviewed but is not a model.

## Naming

### Models

| Layer | Pattern | Examples |
|---|---|---|
| Staging | `stg_<source>__<entity>` | `stg_shopify__orders`, `stg_stripe__charges` |
| Intermediate | `int_<entity>_<verbed>` | `int_orders_joined_to_payments`, `int_payments_pivoted` |
| Fact | `fct_<entity>` | `fct_orders`, `fct_page_views` |
| Dimension | `dim_<entity>` | `dim_customers`, `dim_products` |
| Bridge | `bridge_<a>_<b>` | `bridge_customer_accounts` |
| Report/aggregate | `rpt_<subject>` or `agg_<subject>` | `rpt_weekly_revenue` |

The **double underscore** in `stg_shopify__orders` separates the source from the entity, so
`stg_google_analytics__page_views` parses unambiguously.

Model names are **globally unique** in dbt regardless of directory. Two `orders.sql` files in
different folders is a parse error.

### Columns

| Kind | Convention | Examples |
|---|---|---|
| Primary key | `<entity>_id` | `order_id`, `customer_id` |
| Surrogate key | `<entity>_sk` or `<entity>_key` | `order_line_sk` |
| Foreign key | the parent's PK name, unchanged | `customer_id` in `fct_orders` |
| Boolean | `is_` / `has_` prefix | `is_active`, `has_subscription` |
| Timestamp | `<verb>ed_at` | `ordered_at`, `created_at`, `shipped_at` |
| Date | `<verb>ed_date` | `ordered_date` |
| Amount | include the unit | `amount_usd`, `revenue_usd` |
| Duration | include the unit | `duration_seconds`, `age_days` |
| Count | `<thing>_count` | `order_count`, `line_item_count` |
| Metadata | `_` prefix | `_loaded_at`, `_dbt_updated_at` |

Rules:

- **Always include the unit.** `amount` means nothing; `amount_usd` and `amount_cents` are
  different columns and someone will confuse them.
- **`_at` is a timestamp, `_date` is a date.** Consistency here prevents timezone bugs.
- **Booleans read as a statement.** `is_active`, not `active_flag` or `active_ind`.
- **Never reuse a name for a different meaning.** If `revenue` means gross in one mart and
  net in another, one of them is wrong.
- **snake_case everywhere.** Warehouses disagree about identifier casing; snake_case with
  unquoted identifiers is the only thing that behaves the same on all of them.

### Tags

```yaml
+tags: [daily, finance, pii, nightly]
```

Tag by **cadence** (`hourly`, `daily`, `weekly`), **domain** (`finance`, `marketing`),
**sensitivity** (`pii`), and **cost profile** (`slow`, `nightly`). These are the axes you
actually select on.

## SQL style

### The model shape

```sql
{{ config(materialized='table') }}

with

-- import CTEs: one per ref/source, nothing but a select
orders as (
    select * from {{ ref('stg_shopify__orders') }}
),

customers as (
    select * from {{ ref('stg_shopify__customers') }}
),

-- logic CTEs: named for what they contain
order_totals as (
    -- resolves the line-item fan-out before the join below
    select
        order_id,
        sum(line_amount) as order_amount,
        count(*)         as line_item_count
    from {{ ref('stg_shopify__order_lines') }}
    group by 1
),

final as (
    select
        orders.order_id,
        orders.customer_id,
        customers.customer_name,
        order_totals.order_amount,
        order_totals.line_item_count,
        orders.ordered_at
    from orders
    left join customers    on orders.customer_id = customers.customer_id
    left join order_totals on orders.order_id    = order_totals.order_id
)

select * from final
```

### Rules

1. **Import CTEs at the top**, one per dependency, doing nothing else. Dependencies become
   readable at a glance, and you have one place to add a filter while debugging.
2. **One `select` at the bottom**, always `select * from final`.
3. **`select *` only** in import CTEs and that final line. Never as a mart's projection.
4. **Name CTEs for content**, not `cte1` / `t2` / `tmp`.
5. **Qualify every column** when more than one table is in scope.
6. **Lowercase keywords.** `select`, not `SELECT`.
7. **Leading commas or trailing — pick one** and never mix. Trailing is more common.
8. **One transformation per line** in a projection.
9. **No subquery nested more than one level.** Extract it.
10. **Comment the why**, never the what. "left join because guest checkouts have no
    customer" is useful; "join customers" is not.
11. **`group by 1, 2`** for short groupings; explicit column names past three.
12. **Explicit join type.** Write `left join` / `inner join`, never a bare `join`.

### Formatting

Use `sqlfmt` (dbt's own formatter) or SQLFluff with the `dbt` templater. Enforce it in CI so
formatting never appears in a review diff.

```yaml
# .sqlfluff
[sqlfluff]
templater = dbt
dialect = snowflake
exclude_rules = L034,L044

[sqlfluff:rules:capitalisation.keywords]
capitalisation_policy = lower
```

Pick one and enforce it. Formatting arguments in code review are pure waste.

## The staging model template

```sql
with

source as (
    select * from {{ source('shopify', 'orders') }}
),

renamed as (
    select
        -- ids
        id                              as order_id,
        customer_id,

        -- strings
        lower(trim(financial_status))   as payment_status,
        currency                        as currency_code,

        -- numerics
        cast(total_price as {{ dbt.type_numeric() }})  as order_amount,

        -- booleans
        coalesce(test, false)           as is_test_order,

        -- timestamps
        cast(created_at as timestamp)   as ordered_at,

        -- metadata
        _fivetran_synced                as _loaded_at

    from source
    where not coalesce(_fivetran_deleted, false)
)

select * from renamed
```

Group columns by type with comments. Filter soft deletes here; never filter *business* rows
here, because a downstream model may legitimately need them.

## `dbt_project.yml` configuration

```yaml
models:
  analytics:
    +persist_docs: {relation: true, columns: true}
    staging:
      +materialized: view
      +schema: staging
      +tags: [staging]
    intermediate:
      +materialized: ephemeral
      +schema: intermediate
    marts:
      +materialized: table
      +schema: marts
      finance:
        +schema: finance
        +tags: [finance]
```

Precedence, lowest to highest: `dbt_project.yml` → property YAML (`schema.yml`) → in-file
`{{ config() }}`. Set the default at the folder level and override the exceptions in the
model.

The `+` prefix marks a config key rather than a folder name — without it, dbt reads
`materialized` as a subdirectory.

## Layer rules

| Rule | Why |
|---|---|
| Staging is 1:1 with a source table | one place per source column; renames cannot drift |
| Staging does not join or aggregate | that logic would be duplicated in the next staging model that needs it |
| Only staging references `{{ source() }}` | lineage stays accurate and sources stay swappable |
| Intermediate is never queried by a consumer | you keep the freedom to restructure it |
| Marts do not reference sources or other marts' internals | prevents hidden coupling and rebuild-order surprises |
| Logic needed by two marts lives in intermediate | one definition, not two that drift |
| Marts use business names | the consumer should never see `fivetran_synced` |

## Sizing heuristics

| Metric | Healthy | Investigate |
|---|---|---|
| Model length | under ~150 lines | over 300 — split it |
| CTEs per model | 3–8 | over 12 — extract an intermediate model |
| DAG depth | 4–6 layers | over 8 — probably redundant layers |
| Direct children of one model | under 10 | over 20 — it may be doing too much |
| Columns in a mart | under 50 | over 100 — is it really one grain? |
| Models per person | roughly 20–50 | far more means nobody actually owns them |

These are smells, not rules. A 400-line model with a genuine reason is fine; a 400-line model
because nobody split it is not.

## Anti-patterns

- `models/` flat, with no layers. Unnavigable past about thirty models.
- Layer prefixes without layer discipline — `stg_` models that join three tables.
- Business logic duplicated across marts instead of extracted to intermediate.
- Model names that do not indicate the layer.
- Columns named `date`, `amount`, `status`, or `type` with no qualifier.
- Mixed casing conventions across the project.
- One 3,000-line `schema.yml`.
- Formatting arguments in code review — automate it.
