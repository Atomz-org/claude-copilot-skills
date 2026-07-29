---
name: semantic-layer-metricflow
description: Build and query the dbt Core semantic layer with MetricFlow — semantic models over marts, entities/dimensions/measures, all five metric types (simple, ratio, derived, cumulative, conversion), the time spine, saved queries and exports, validation with mf validate-configs, and answering business questions with mf query instead of ad-hoc SQL. Use when a metric needs one canonical definition, when two dashboards disagree on the same number, when asked to build metrics or semantic models, or when answering "what was revenue by region last quarter".
---

# Semantic Layer and MetricFlow

One definition per metric, in version control, queryable. This is the fix for "the two
dashboards disagree".

**dbt Core scope.** MetricFlow is open source: install `dbt-metricflow`, get the `mf` CLI,
define semantic models and metrics in YAML, validate them, and query them locally or in a
job. The **hosted Semantic Layer API** — the JDBC/GraphQL/Arrow endpoint BI tools connect
to — is dbt Cloud only. On Core, serve BI by materializing metric output into a mart
(`saved_queries` with exports, or `mf query --explain` SQL wrapped in a model).

## Install

```bash
python -m pip install "dbt-metricflow[snowflake]"   # [bigquery] [postgres] [duckdb] [databricks] [redshift] [trino]
mf --help
```

Match `dbt-metricflow` to your dbt Core minor version. A mismatch produces parse errors
that look like YAML problems and waste an afternoon.

## Build order

1. **Semantic models sit on marts, never staging.** The semantic layer describes the
   business; staging describes a source system.
2. **Entities** — the join keys. Wrong entities means every multi-model query fails or
   fans out.
3. **Dimensions** — how the business slices. Every time dimension needs a granularity.
4. **Measures** — the aggregatable numbers.
5. **Metrics** — what people ask for.
6. **Time spine** — required for cumulative metrics, offsets, and `join_to_timespine`.

## Semantic model

```yaml
# models/semantic/_semantic_models.yml
semantic_models:
  - name: orders
    description: Order facts. One row per order.
    model: ref('fct_orders')
    defaults:
      agg_time_dimension: ordered_at

    entities:
      - name: order              # primary — this model's grain
        type: primary
        expr: order_id
      - name: customer           # foreign — joins to the customers semantic model
        type: foreign
        expr: customer_id

    dimensions:
      - name: ordered_at
        type: time
        type_params:
          time_granularity: day        # REQUIRED on every time dimension
      - name: order_status
        type: categorical
      - name: is_first_order
        type: categorical
        expr: case when order_sequence_number = 1 then true else false end

    measures:
      - name: order_total
        agg: sum
        expr: order_amount_usd
        agg_time_dimension: ordered_at
      - name: order_count
        agg: count
        expr: order_id
      - name: distinct_customers
        agg: count_distinct
        expr: customer_id
      - name: is_large_order
        agg: sum_boolean
        expr: order_amount_usd > 500

  - name: customers
    model: ref('dim_customers')
    defaults:
      agg_time_dimension: first_ordered_at
    entities:
      - name: customer
        type: primary
        expr: customer_id
    dimensions:
      - name: region
        type: categorical
      - name: customer_segment
        type: categorical
      - name: first_ordered_at
        type: time
        type_params: {time_granularity: day}
```

Entity types:

| Type | Meaning |
|---|---|
| `primary` | uniquely identifies each row — the model's grain |
| `foreign` | points at another semantic model's primary entity |
| `unique` | unique here but not the grain (a natural key alongside a surrogate) |
| `natural` | the business key on an SCD2 table, used with `validity_params` |

Aggregations: `sum`, `min`, `max`, `count`, `count_distinct`, `average`, `median`,
`percentile`, `sum_boolean`.

MetricFlow joins semantic models automatically through shared entities — `customer` is
`foreign` in orders and `primary` in customers, so `revenue by customer__region` just
works. You never write the join.

## The five metric types

```yaml
metrics:
  # 1. SIMPLE — one measure, optionally filtered
  - name: revenue
    label: Revenue
    description: Gross order revenue in USD, excluding cancelled orders.
    type: simple
    type_params:
      measure:
        name: order_total
        fill_nulls_with: 0
        join_to_timespine: true      # emit a row for every period, including empty ones
    filter: "{{ Dimension('order__order_status') }} != 'cancelled'"

  # 2. RATIO — numerator / denominator, each a metric or a measure
  - name: average_order_value
    label: Average Order Value
    type: ratio
    type_params:
      numerator: revenue
      denominator: order_count

  - name: emea_revenue_share
    type: ratio
    type_params:
      numerator:
        name: revenue
        filter: "{{ Dimension('customer__region') }} = 'EMEA'"
        alias: emea_revenue
      denominator: revenue

  # 3. DERIVED — arithmetic over other metrics, with optional time offsets
  - name: revenue_growth_mom
    label: Revenue Growth MoM (%)
    type: derived
    type_params:
      expr: (revenue - revenue_prev_month) * 100.0 / nullif(revenue_prev_month, 0)
      metrics:
        - name: revenue
        - name: revenue
          alias: revenue_prev_month
          offset_window: 1 month       # duration back
          # offset_to_grain: month     # OR: the start of the period. Different thing.

  # 4. CUMULATIVE — running or windowed accumulation
  - name: revenue_trailing_28d
    type: cumulative
    type_params:
      measure: order_total
      window: 28 days                  # window and grain_to_date are mutually exclusive
  - name: revenue_mtd
    type: cumulative
    type_params:
      measure: order_total
      grain_to_date: month
  - name: ending_balance
    type: cumulative
    type_params:
      measure: balance
      period_agg: last                 # first | last | average — for non-additive measures

  # 5. CONVERSION — did an entity that did A go on to do B within a window
  - name: visit_to_purchase_rate
    label: Visit → Purchase Rate
    type: conversion
    type_params:
      conversion_type_params:
        entity: user
        calculation: conversion_rate   # or `conversions` for the raw count
        base_measure:
          name: visits
          fill_nulls_with: 0
        conversion_measure:
          name: purchases
        window: 7 days
        constant_properties:           # the attribute must match across both events
          - base_property: session__utm_campaign
            conversion_property: session__utm_campaign
```

### Filter syntax — the most common error

Filters use Jinja objects, not raw column names:

```yaml
filter: "{{ Dimension('order__order_status') }} != 'cancelled'"
filter: "{{ TimeDimension('order__ordered_at', 'month') }} >= '2024-01-01'"
filter: "{{ Entity('customer') }} is not null"
filter: "{{ Metric('revenue', group_by=['customer']) }} > 1000"
```

**The `entity__dimension` double underscore is mandatory.** A bare `order_status` is the
single most frequent MetricFlow error, and the message is not obvious about it.

### Details that save hours

- `fill_nulls_with: 0` turns an empty period into a zero. Without it, gaps break
  `offset_window` arithmetic and charts render holes.
- `join_to_timespine: true` emits a row for every spine period, not just periods with data.
- `offset_window: 1 month` (a duration back) and `offset_to_grain: month` (the start of the
  period) are different and easy to swap.
- Derived `expr` is real SQL. Always `nullif` the denominator.
- `percentile` requires `percentile: 0.95` and optionally `use_discrete_percentile: true`.
- A `cumulative` metric with both `window` and `grain_to_date` is an error, not a merge.

## Time spine — required, and the most common failure

```sql
-- models/marts/metricflow_time_spine.sql
{{ config(materialized='table') }}
{{ dbt_utils.date_spine(
    datepart="day",
    start_date="cast('2019-01-01' as date)",
    end_date="dateadd(year, 2, current_date)"
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

- Cumulative metrics, `offset_window`, and `join_to_timespine` all fail without it.
- **The spine must extend past the maximum date in your fact data**, or the tail of every
  cumulative metric silently truncates. Extend it into the future.
- A second spine at `month` grain is only worth adding if day-grain rollups are measurably
  slow — MetricFlow rolls up from `day` otherwise.
- Custom calendars (fiscal 4-4-5, retail weeks) go in as extra columns on the spine with
  `custom_granularities`.

## Saved queries and exports — the dbt Core BI path

`saved_queries` is how you get metric output into a table on Core, since there is no hosted
API for BI tools to hit.

```yaml
saved_queries:
  - name: weekly_revenue_by_region
    description: Feeds the exec revenue dashboard.
    query_params:
      metrics: [revenue, order_count, average_order_value]
      group_by:
        - TimeDimension('metric_time', 'week')
        - Dimension('customer__region')
      where:
        - "{{ Dimension('customer__region') }} is not null"
    exports:
      - name: weekly_revenue_by_region
        config:
          export_as: table            # table | view
          schema: bi_marts
```

```bash
dbt sl export --saved-query weekly_revenue_by_region     # dbt 1.10+
mf query --saved-query weekly_revenue_by_region          # ad hoc
```

Schedule the export in your orchestrator after the marts build. The BI tool reads
`bi_marts.weekly_revenue_by_region`, which is defined once in YAML — so the metric stays
canonical even though the BI tool is reading a plain table.

## Validate before you ship

```bash
dbt parse                                                       # YAML → manifest
python scripts/semantic_layer_validator.py --path models/ --strict   # offline spec check
mf validate-configs                                             # full validation
mf list metrics
mf list dimensions --metrics revenue
mf query --metrics revenue --group-by metric_time__month --order metric_time__month
mf query --metrics revenue --group-by metric_time__month --explain   # the generated SQL
```

**Then check the number.** Run `--explain`, take the generated SQL, and compare one period
against a hand-written query you trust. A metric that validates and returns the wrong number
is worse than no metric, because it carries the authority of the semantic layer. Do this
once, at definition time, and record the check in the metric's description.

## Answering questions with the semantic layer

When someone asks a business question and the metric exists, **query it — do not write
ad-hoc SQL.** Ad-hoc SQL is how the second definition gets born.

```bash
mf list metrics                                # what exists
mf list dimensions --metrics revenue           # what you can group by
mf list entities --metrics revenue

mf query --metrics revenue,order_count \
         --group-by metric_time__quarter,customer__region \
         --where "{{ Dimension('customer__region') }} = 'EMEA'" \
         --order -metric_time__quarter \
         --limit 20

mf query --metrics revenue --group-by metric_time__month --start-time 2024-01-01 --end-time 2024-12-31
mf query --metrics revenue --group-by metric_time__day --csv out.csv
```

Workflow:

1. `mf list metrics` — does it exist? If not, define it rather than answering with ad-hoc
   SQL, unless the question is genuinely one-off.
2. `mf list dimensions --metrics <m>` — is the slice available? If not, the dimension is
   missing from the semantic model, not from the query.
3. Query, then **state the metric definition alongside the number**. A number without its
   definition is how two dashboards start disagreeing.
4. If the answer surprises you, `--explain` and read the SQL before believing it.
5. `metric_time` is the universal time dimension — use it rather than a model-specific
   time column, so metrics from different semantic models align on one timeline.

## When two dashboards disagree

The problem this layer exists to solve. Diagnose in order:

1. **Definition** — different filters (cancelled orders, test accounts, internal customers).
   Nine times in ten, this is it.
2. **Grain / time basis** — order date vs ship date; calendar month vs fiscal 4-4-5.
3. **Timezone** — UTC vs local, and where the day boundary falls.
4. **Freshness** — different snapshots of the same table.
5. **Fan-out** — one joined to a 1:N table and double-counted.

The fix is one MetricFlow definition and both dashboards reading it. Record the *old*
definitions in the metric's `description` — that is what stops the argument recurring in
six months.

## Newer annotation syntax

Recent dbt versions also support declaring semantics inline on the model's own YAML
(`semantic_model: {enabled: true}`, `agg_time_dimension:`, per-column `entity:` /
`dimension:` blocks, and a model-level `metrics:` list) instead of a separate
`semantic_models:` resource. It is the same underlying model — entities, dimensions,
measures, metrics — with less duplication.

The classic `semantic_models:` + `metrics:` form documented above works across all
MetricFlow-supporting dbt Core versions, so it is the safe default. Check
`dbt --version` and the docs version selector before using the annotation form; a column
can carry an `entity:` **or** a `dimension:`, never both.

## Anti-patterns

- Semantic models on staging models — the business gets described in source-system terms.
- A metric defined in MetricFlow *and* in the BI tool. Pick MetricFlow.
- A time dimension with no `time_granularity` — the most common validation failure.
- A cumulative metric with no time spine, or a spine that ends before the data does.
- Filters written as raw SQL instead of `{{ Dimension(...) }}`.
- A derived metric dividing without `nullif`.
- Shipping a metric that validated but was never compared against a known-good query.
- A semantic model over a mart whose grain was never stated — the measures will be wrong and
  nothing will error.
- Defining forty metrics up front. Define the ones people ask for; each one is a maintenance
  commitment.

Reference: [references/semantic_layer_metricflow.md](../../../references/semantic_layer_metricflow.md).
