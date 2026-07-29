# Dimensional Modeling

Kimball-style dimensional design, expressed in dbt Core. Loaded on demand by the
[data-modeling](../.claude/skills/data-modeling/SKILL.md) skill.

## The four-step design process

Apply to **one business process at a time**. Never design two at once — that is how
grains get blended.

1. **Select the business process.** A verb the business performs and measures: *a
   valuation is issued*, *an order is placed*, *a subscription renews*. Not a department,
   not a report, not a dashboard.
2. **Declare the grain.** One sentence, in business language, before anything else. "One
   row per valuation issued per vehicle." The grain is a commitment: everything in the
   fact must be true at exactly that level.
3. **Identify the dimensions.** Everything the business says "by" about. Each becomes a
   foreign key on the fact.
4. **Identify the facts (measures).** Numeric, and true at the declared grain. A measure
   that is not true at the grain does not belong in the table — it belongs in a different
   fact at a different grain.

Step 2 before step 4 is not negotiable. Choosing measures first produces a table whose
grain is "whatever the join happened to produce".

### The grain test

Write the grain sentence, then check every column against it:

| Column | True at "one row per valuation per vehicle"? |
|---|---|
| `valuation_amount` | yes — it is the valuation |
| `vehicle_mileage_at_valuation` | yes — as of the event |
| `dealer_total_inventory` | **no** — true at dealer grain; it will be double-counted |

The third row is the most common defect in a fact table. A dealer-grain measure on a
valuation-grain fact is summed once per valuation, and the total is meaningless.

## Fact tables

### Transaction fact

One row per event. The default and the most useful.

```sql
{{ config(materialized='incremental', unique_key='valuation_sk',
          incremental_strategy='merge', on_schema_change='append_new_columns') }}

with valuations as (
    select * from {{ ref('int_valuations_enriched') }}
    {% if is_incremental() %}
      -- lookback anchored to the table's own max, never current_date
      where issued_at >= (select dateadd(day, -3, max(issued_at)) from {{ this }})
    {% endif %}
),

final as (
    select
        {{ dbt_utils.generate_surrogate_key(['valuation_id']) }} as valuation_sk,

        -- foreign keys to dimensions
        vehicle_id,
        customer_id,
        dealer_id,
        cast(issued_at as date)                                 as issued_date,

        -- degenerate dimension: an identifier with no attributes of its own
        valuation_reference,

        -- measures, all additive at this grain
        valuation_amount_usd,
        vehicle_mileage,
        1                                                       as valuation_count,

        issued_at
    from valuations
)

select * from final
```

Notes that matter:

- `valuation_count` as a literal `1` looks redundant but makes "count of valuations" an
  additive `sum()` rather than a `count()`, which is what makes it composable in a
  semantic layer and in a rollup.
- The degenerate dimension stays on the fact. Creating `dim_valuation_reference` with one
  attribute — its own key — is a table that does nothing.

### Periodic snapshot fact

One row per entity per period, capturing state. Answers "what was the balance on the
last day of each month".

Grain: *one row per vehicle per day in inventory*. Grows at entities × periods, so it is
almost always incremental and partitioned on the period column.

Measures here are typically **semi-additive**: `inventory_value` sums across vehicles but
not across days. Summing it over a month gives a number with no meaning.

### Accumulating snapshot fact

One row per entity, with a column per milestone. Rows are **updated in place** as the
entity moves through the pipeline.

```sql
{{ config(materialized='incremental', unique_key='vehicle_sale_sk',
          incremental_strategy='merge') }}

select
    {{ dbt_utils.generate_surrogate_key(['vehicle_id', 'sale_attempt_number']) }}
        as vehicle_sale_sk,
    vehicle_id,

    -- milestone timestamps; null until the milestone happens
    acquired_at,
    inspected_at,
    listed_at,
    first_offer_at,
    sold_at,

    -- lag measures, computed once instead of by every consumer
    datediff(day, acquired_at, listed_at)   as days_to_list,
    datediff(day, listed_at,   sold_at)     as days_on_lot,
    datediff(day, acquired_at, sold_at)     as days_to_sale
from {{ ref('int_vehicle_lifecycle') }}
```

This is the pattern for any funnel or pipeline with known stages. It replaces a pile of
self-joins with column arithmetic. Requires `merge` — rows change after they are written,
which means `append` is wrong and `insert_overwrite` needs the whole partition.

### Factless fact

One row per event, no numeric measures. Two legitimate uses:

- **Event tracking** — "which vehicles were viewed", counted with `count(*)`.
- **Coverage / eligibility** — which combinations were *possible*, so you can find what
  did **not** happen. `fct_dealer_vehicle_eligibility` left-joined against sales gives you
  vehicles a dealer could have sold and did not. There is no other clean way to ask that.

## Dimension tables

### The standard shape

```sql
{{ config(materialized='table') }}

with vehicles as (
    select * from {{ ref('stg_inventory__vehicles') }}
),

final as (
    select
        vehicle_id,                    -- business key, tested unique + not_null

        -- attributes, enumerated; never select *
        vin,
        make,
        model,
        trim_level,
        model_year,
        body_style,
        fuel_type,

        -- flags as booleans, not 'Y'/'N'
        is_certified_preowned,

        -- a derived band, so every consumer buckets identically
        case
            when model_year >= year(current_date) - 2 then 'near-new'
            when model_year >= year(current_date) - 6 then 'used'
            else 'older'
        end as vehicle_age_band
    from vehicles
)

select * from final
```

### The unknown member

Every dimension that a fact can point at optionally needs a row for "we don't know". The
alternative is a null foreign key, which drops rows from every `inner join` a consumer
writes and skews every count.

```sql
final as (
    select vehicle_id, vin, make, ... from vehicles

    union all

    select
        '-1'          as vehicle_id,
        'UNKNOWN'     as vin,
        'Unknown'     as make,
        ...
)
```

and on the fact side, `coalesce(vehicle_id, '-1')`. Document it in the description — an
undocumented `-1` row will eventually be counted as a real vehicle in a board deck.

### Junk dimension

Four boolean flags on a fact is four columns of low information. Collapse them:

```sql
-- dim_valuation_flags: one row per distinct combination, not one per fact row
select
    {{ dbt_utils.generate_surrogate_key(
        ['is_trade_in', 'is_financed', 'is_certified', 'channel']) }} as valuation_flag_sk,
    is_trade_in, is_financed, is_certified, channel
from (select distinct is_trade_in, is_financed, is_certified, channel
      from {{ ref('int_valuations_enriched') }})
```

Worth it when the combination count is small (dozens) and the fact is large. Not worth it
below a few million fact rows — you have added a join to save nothing.

### Role-playing dimension

One physical `dim_date`, referenced multiple times. Do **not** build `dim_order_date` and
`dim_ship_date`; alias at query time, or expose named views:

```sql
-- models/marts/core/dim_date.sql  — built once
-- consumers alias it:
from {{ ref('fct_sales') }} sales
left join {{ ref('dim_date') }} order_date on sales.order_date  = order_date.date_day
left join {{ ref('dim_date') }} ship_date  on sales.shipped_date = ship_date.date_day
```

In MetricFlow this is handled by declaring multiple time dimensions on the semantic model
rather than by duplicating the dimension.

### Mini-dimension

When a dimension has a few rapidly changing attributes and many static ones, SCD2 on the
whole table explodes: forty static columns rewritten because one score changed daily.

Split: `dim_customer` (static, SCD1/SCD2) + `dim_customer_scoring_band` (the volatile
attributes, banded into ranges). The fact carries **both** keys. Banding is what makes it
work — a continuous credit score gives you a row per value, defeating the purpose.

### Bridge table

Resolves many-to-many. The allocation factor is the part people leave out:

```sql
select
    vehicle_id,
    feature_id,
    1.0 / count(*) over (partition by vehicle_id) as allocation_factor
from {{ ref('stg_inventory__vehicle_features') }}
```

Without `allocation_factor`, summing a vehicle's value across features counts the vehicle
once per feature. With it, the allocated total reconciles to the unallocated total. Which
one the business wants is a policy decision — write it in the spec.

## Slowly changing dimensions in dbt Core

### Type 1 — overwrite

The default. Just a model. History is not recoverable; make sure nobody needs it before
choosing this.

### Type 2 — a snapshot

```yaml
# snapshots/vehicles_snapshot.yml
snapshots:
  - name: vehicles_snapshot
    relation: source('inventory', 'vehicles')
    config:
      schema: snapshots
      unique_key: vehicle_id
      strategy: check
      check_cols: [trim_level, condition_grade, list_price, dealer_id]
      # timestamp strategy is cheaper and safer when the source has a reliable
      # updated_at; check is for sources that lie about it or lack one
      hard_deletes: new_record   # dbt 2.0: records deletions instead of leaving
                                 # the last row looking current forever
```

dbt adds `dbt_valid_from`, `dbt_valid_to` (null on the current row), `dbt_scd_id`, and
`dbt_updated_at`.

Building the dimension on top:

```sql
-- current state
select * from {{ ref('vehicles_snapshot') }} where dbt_valid_to is null

-- as-was: the row that was current when the fact happened
select f.valuation_sk, f.valuation_amount_usd, v.condition_grade
from {{ ref('fct_valuations') }} f
left join {{ ref('vehicles_snapshot') }} v
       on f.vehicle_id = v.vehicle_id
      and f.issued_at >= v.dbt_valid_from
      and f.issued_at <  coalesce(v.dbt_valid_to, '9999-12-31')
```

That second join is the entire point of SCD2, and it is also where it goes wrong:

- **Forgetting the date predicate** silently fans out — one fact row per historical
  version. Totals inflate by the average number of versions per entity.
- **`coalesce(dbt_valid_to, ...)`** is required; `<` against null matches nothing and the
  current row disappears.
- **Half-open intervals** (`>=` / `<`) — using `<=` on both sides double-counts facts at
  the exact changeover timestamp.

Test the snapshot itself:

```yaml
data_tests:
  - dbt_utils.unique_combination_of_columns:
      combination_of_columns: [vehicle_id, dbt_valid_from]
```

Irreversible constraints, worth repeating: snapshot the **raw source**, and never change
`unique_key`, `strategy`, or `check_cols` after the first run. There is no migration path
and no error message — the history simply becomes wrong.

### Type 3 — previous-value columns

```sql
select
    customer_id,
    segment                                     as current_segment,
    lag(segment) over (partition by customer_id
                       order by valid_from)     as previous_segment,
    segment_changed_at
from {{ ref('customers_snapshot') }}
where dbt_valid_to is null
```

One step of history, fixed width. Legitimate when the requirement is literally "compare
to prior segment" and will not grow.

### Type 6 — hybrid

An SCD2 table that also carries the *current* value on every historical row:

```sql
select
    s.*,
    c.segment as current_segment    -- same value on every row for this customer
from {{ ref('customers_snapshot') }} s
join (select customer_id, segment from {{ ref('customers_snapshot') }}
      where dbt_valid_to is null) c using (customer_id)
```

Lets one query answer both "revenue by the segment they were in then" and "revenue by the
segment they are in now" — the two questions that produce different numbers and start
arguments.

## The date dimension

Build it once. It is the most-joined table in any warehouse.

```sql
{{ config(materialized='table') }}

with dates as (
    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('2015-01-01' as date)",
        end_date="dateadd(year, 2, current_date)"
    ) }}
)

select
    date_day,
    {{ dbt_utils.generate_surrogate_key(['date_day']) }} as date_sk,
    extract(year    from date_day)          as calendar_year,
    extract(quarter from date_day)          as calendar_quarter,
    extract(month   from date_day)          as calendar_month,
    date_trunc('month', date_day)           as month_start_date,
    extract(dayofweek from date_day)        as day_of_week,
    case when extract(dayofweek from date_day) in (0, 6)
         then false else true end           as is_weekday,

    -- fiscal calendar: the reason you cannot just use date functions
    case when extract(month from date_day) >= 2
         then extract(year from date_day) + 1
         else extract(year from date_day) end as fiscal_year
from dates
```

Extend to two years in the future — facts with forward-dated rows (scheduled deliveries,
contract end dates) fall out of the join otherwise, and it looks like missing data.

MetricFlow needs its own `metricflow_time_spine` model at the smallest granularity you
report on; the date dimension and the time spine are different objects with different
jobs.

## Naming

| Object | Convention |
|---|---|
| Transaction fact | `fct_<process>` — `fct_valuations`, `fct_sales` |
| Periodic snapshot | `fct_<entity>_<period>` — `fct_inventory_daily` |
| Accumulating snapshot | `fct_<entity>_lifecycle` |
| Dimension | `dim_<entity>` — singular entity, plural not required |
| Bridge | `bridge_<a>_<b>` |
| Aggregate/rollup | `agg_<fact>_by_<dims>` |
| Surrogate key | `<entity>_sk` |
| Business key | `<entity>_id` |
| Date FK on a fact | `<verb>ed_date` — `ordered_date`, `issued_date` |

## Design review checklist

- [ ] Exactly one business process per fact table.
- [ ] Grain written as one sentence, in the model description.
- [ ] Every measure is true at the declared grain.
- [ ] Additivity recorded per measure — additive, semi-additive, non-additive.
- [ ] Every foreign key has a `relationships` test to its dimension.
- [ ] Every dimension has `unique` + `not_null` on its key.
- [ ] Optional relationships have an unknown member, not a null FK.
- [ ] Dimensions shared between processes are genuinely conformed — same key, same
      definition, one table.
- [ ] SCD type chosen per dimension and written down, not defaulted to.
- [ ] SCD2 joins use a half-open date predicate with `coalesce` on `dbt_valid_to`.
- [ ] Many-to-many resolved with a bridge, with an allocation factor if totals must
      reconcile.
- [ ] Degenerate dimensions kept on the fact.
- [ ] No dimension exists that nobody slices by.

Run the automated half of this with:

```bash
python scripts/dimensional_model_validator.py --manifest target/manifest.json --strict
python scripts/erd_generator.py --manifest target/manifest.json --layer marts
```

## Anti-patterns

- **Mixed-grain fact.** A dealer-level measure on a valuation-level fact. Split the table.
- **Fact joined to fact.** Facts join through conformed dimensions, never directly. A
  fact-to-fact join fans out on every shared key.
- **Snowflaking by reflex.** Normalizing `dim_vehicle` into make/model/trim tables saves
  storage that costs nothing and adds joins that cost every query.
- **Null foreign keys.** Use the unknown member.
- **Smart keys.** A surrogate key encoding date or type (`20240115_VEH_001`) becomes a
  parsing dependency and eventually a wrong parse.
- **`select *` in a dimension.** A new upstream column reaches a dashboard with no review.
- **Type 2 by default on every dimension.** Every consumer now needs a date predicate, and
  most of them will forget.
- **An aggregate table with no relationship to its base fact.** `agg_` tables must be
  derivable from the fact, and worth a test that proves they still reconcile.
