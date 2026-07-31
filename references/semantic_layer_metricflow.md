# Semantic Layer and MetricFlow Reference

Full YAML spec, the `mf` CLI, and what is and is not available on dbt Core.

## dbt Core vs dbt Cloud

| Capability | Core | Cloud |
|---|---|---|
| Define semantic models and metrics in YAML | ✅ | ✅ |
| `mf validate-configs` | ✅ | ✅ |
| `mf query` / `mf list` locally | ✅ | ✅ |
| Saved queries and exports to a table | ✅ | ✅ |
| **Hosted Semantic Layer API** (JDBC/GraphQL/Arrow for BI tools) | ❌ | ✅ |
| Native Tableau/Looker/Hex/Excel connectors | ❌ | ✅ |

On Core, serve BI by **exporting saved queries into tables** that BI reads. The metric is
still defined once, in YAML, so it stays canonical.

## Install

```bash
python -m pip install "dbt-metricflow[snowflake]"
# [bigquery] [postgres] [duckdb] [databricks] [redshift] [trino]
mf --help
```

Match `dbt-metricflow` to your dbt Core minor version. Mismatches produce parse errors that
look like YAML problems.

## Semantic model

```yaml
semantic_models:
  - name: orders
    description: Order facts. One row per order.
    model: ref('fct_orders')
    defaults:
      agg_time_dimension: ordered_at

    primary_entity: order          # optional; use when no column is the primary entity

    entities:
      - name: order
        type: primary              # primary | foreign | unique | natural
        expr: order_id
      - name: customer
        type: foreign
        expr: customer_id

    dimensions:
      - name: ordered_at
        type: time
        type_params:
          time_granularity: day    # REQUIRED on every time dimension
      - name: order_status
        type: categorical
        description: Current fulfillment status.
      - name: is_first_order
        type: categorical
        expr: case when order_sequence_number = 1 then true else false end

    measures:
      - name: order_total
        agg: sum
        expr: order_amount_usd
        agg_time_dimension: ordered_at
        description: Gross order amount, USD.
      - name: order_count
        agg: count
        expr: order_id
      - name: distinct_customers
        agg: count_distinct
        expr: customer_id
      - name: p95_order_value
        agg: percentile
        expr: order_amount_usd
        agg_params:
          percentile: 0.95
          use_discrete_percentile: false
      - name: large_order_count
        agg: sum_boolean
        expr: order_amount_usd > 500
      - name: revenue_non_additive
        agg: sum
        expr: balance
        non_additive_dimension:
          name: ordered_at
          window_choice: max        # min | max — for balances that must not be summed over time
```

### Entity types

| Type | Meaning |
|---|---|
| `primary` | uniquely identifies each row — the model's grain |
| `foreign` | points at another semantic model's primary entity |
| `unique` | unique here but not the grain |
| `natural` | the business key on an SCD2 table, used with `validity_params` |

MetricFlow joins semantic models automatically through shared entities. You never write the
join.

### Aggregations

`sum`, `min`, `max`, `count`, `count_distinct`, `average`, `median`, `percentile`,
`sum_boolean`.

### SCD Type 2 semantic models

```yaml
  - name: customer_history
    model: ref('dim_customers_scd')
    entities:
      - name: customer
        type: natural
        expr: customer_id
    dimensions:
      - name: valid_from
        type: time
        type_params:
          time_granularity: day
          validity_params: {is_start: true}
      - name: valid_to
        type: time
        type_params:
          time_granularity: day
          validity_params: {is_end: true}
      - name: plan_tier
        type: categorical
```

SCD2 semantic models hold **no measures and no metrics** — they exist to provide
point-in-time-correct dimensions that other models' metrics join against.

## Metric types

### Simple

```yaml
- name: revenue
  label: Revenue
  description: Gross order revenue in USD, excluding cancelled orders.
  type: simple
  type_params:
    measure:
      name: order_total
      fill_nulls_with: 0
      join_to_timespine: true
  filter: "{{ Dimension('order__order_status') }} != 'cancelled'"
  config:
    meta: {owner: finance}
```

### Ratio

```yaml
- name: average_order_value
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
```

### Derived

```yaml
- name: revenue_growth_mom
  type: derived
  type_params:
    expr: (revenue - revenue_prev_month) * 100.0 / nullif(revenue_prev_month, 0)
    metrics:
      - name: revenue
      - name: revenue
        alias: revenue_prev_month
        offset_window: 1 month      # a duration back
        # offset_to_grain: month    # OR: the start of the period. Different.
        # filter: "..."
```

`expr` is real SQL. Always `nullif` the denominator.

### Cumulative

```yaml
- name: revenue_trailing_28d
  type: cumulative
  type_params:
    measure: order_total
    window: 28 days               # window and grain_to_date are MUTUALLY EXCLUSIVE

- name: revenue_mtd
  type: cumulative
  type_params:
    measure: order_total
    grain_to_date: month          # day | week | month | quarter | year

- name: ending_balance
  type: cumulative
  type_params:
    measure: account_balance
    period_agg: last              # first | last | average — for non-additive measures
```

Cumulative metrics **require a time spine**.

### Conversion

```yaml
- name: visit_to_purchase_rate
  type: conversion
  type_params:
    conversion_type_params:
      entity: user
      calculation: conversion_rate      # conversion_rate | conversions
      base_measure:
        name: visits
        fill_nulls_with: 0
      conversion_measure:
        name: purchases
      window: 7 days
      constant_properties:
        - base_property: session__utm_campaign
          conversion_property: session__utm_campaign
```

`constant_properties` requires the attribute to match across both events — the difference
between "someone who saw the campaign later bought" and "someone bought *through* that
campaign".

## Filter syntax

Filters use Jinja objects, never raw column names:

```yaml
filter: "{{ Dimension('order__order_status') }} != 'cancelled'"
filter: "{{ TimeDimension('order__ordered_at', 'month') }} >= '2024-01-01'"
filter: "{{ Entity('customer') }} is not null"
filter: "{{ Metric('revenue', group_by=['customer']) }} > 1000"
```

**The `entity__dimension` double underscore is mandatory.** A bare dimension name is the
single most common MetricFlow error, and the message does not point at it clearly.

Multiple conditions: a YAML list, ANDed together.

```yaml
filter:
  - "{{ Dimension('order__order_status') }} != 'cancelled'"
  - "{{ Dimension('customer__is_internal') }} = false"
```

## Time spine

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
      custom_granularities:
        - name: fiscal_quarter
          column_name: fiscal_quarter
    columns:
      - name: date_day
        granularity: day
```

- Required for cumulative metrics, `offset_window`, `offset_to_grain`, and
  `join_to_timespine`.
- **Must extend past the maximum date in your fact data**, or every cumulative metric
  silently truncates at the tail.
- A coarser second spine (`date_month`) is only worth it if day-grain rollups are measurably
  slow.
- Custom granularities (fiscal 4-4-5, retail weeks) are extra columns on the spine.

## Saved queries and exports

The dbt Core path to BI:

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
      order_by:
        - TimeDimension('metric_time', 'week')
      limit: 10000
    exports:
      - name: weekly_revenue_by_region
        config:
          export_as: table        # table | view
          schema: bi_marts
          alias: weekly_revenue
```

```bash
dbt sl export --saved-query weekly_revenue_by_region      # dbt 1.10+
mf query --saved-query weekly_revenue_by_region
```

Schedule the export after the marts build. BI reads `bi_marts.weekly_revenue`, which is
defined once in YAML — the metric stays canonical even though BI reads a plain table.

## The `mf` CLI

```bash
mf validate-configs                      # full validation, incl. warehouse checks
mf validate-configs --skip-dw            # skip warehouse checks — faster iteration

mf list metrics
mf list dimensions --metrics revenue
mf list entities --metrics revenue
mf list dimension-values --dimension customer__region --metrics revenue

mf query --metrics revenue --group-by metric_time__month
mf query --metrics revenue,order_count \
         --group-by metric_time__quarter,customer__region \
         --where "{{ Dimension('customer__region') }} = 'EMEA'" \
         --order -metric_time__quarter --limit 20
mf query --metrics revenue --group-by metric_time__day \
         --start-time 2024-01-01 --end-time 2024-12-31
mf query --metrics revenue --group-by metric_time__month --explain    # the generated SQL
mf query --metrics revenue --group-by metric_time__month --csv out.csv

mf health-checks
mf tutorial
```

`metric_time` is the universal time dimension — use it rather than a model-specific time
column, so metrics from different semantic models align on one timeline.

## Validation workflow

```bash
dbt parse
python scripts/semantic_layer_validator.py --path models/ --strict   # offline spec check
mf validate-configs
mf query --metrics <m> --group-by metric_time__month --explain
# compare the generated SQL's output against a hand-written query you trust
```

**The last step is not optional.** A metric that validates and returns the wrong number is
worse than no metric, because it carries the semantic layer's authority. Do it once per
metric at definition time and record the check in the metric's description.

## Newer annotation syntax

Recent dbt versions also allow declaring semantics inline on the model's own YAML instead of
a separate `semantic_models:` resource:

```yaml
models:
  - name: fct_orders
    config:
      semantic_model: {enabled: true}
    agg_time_dimension: ordered_at
    primary_entity: order
    columns:
      - name: order_id
        entity: {type: primary}
      - name: ordered_at
        dimension: {type: time}
        granularity: day
      - name: order_status
        dimension: {type: categorical}
    metrics:
      - name: revenue
        type: simple
        agg: sum
        expr: order_amount_usd
    derived_semantics:
      dimensions:
        - name: is_large_order
          type: categorical
          expr: order_amount_usd > 500
```

A column can carry an `entity:` **or** a `dimension:`, never both. `derived_semantics:` is
for dimensions and entities not mapped to a single column.

The classic `semantic_models:` + `metrics:` form works across all MetricFlow-supporting dbt
Core versions, so it is the safe default. Check `dbt --version` and the docs version selector
before using the annotation form.

## Troubleshooting

| Error | Cause |
|---|---|
| `time granularity not specified` | a `type: time` dimension missing `time_granularity` — the most common failure |
| `unable to find dimension X` | missing the `entity__dimension` prefix in a filter |
| `no time spine configured` | a cumulative/offset metric with no `time_spine:` model |
| Cumulative metric truncates recently | the spine ends before the fact data does |
| `entity X not found in semantic model Y` | the foreign entity has no matching primary elsewhere |
| Query fans out / totals inflated | the underlying mart's grain is not what the semantic model assumes |
| `metric_time` unavailable | no `agg_time_dimension` set in `defaults:` or on the measure |
| Metric returns null for recent periods | missing `fill_nulls_with` |
| `mf` version errors on startup | `dbt-metricflow` does not match the dbt Core minor version |
| Two metrics that should match do not | different `filter` clauses — compare with `--explain` |

## Anti-patterns

- Semantic models on staging — the business gets described in source-system terms.
- A metric defined in MetricFlow *and* in the BI tool.
- A time dimension with no granularity.
- A cumulative metric with no spine, or a spine that ends before the data.
- Filters as raw SQL instead of `{{ Dimension(...) }}`.
- Derived metrics dividing without `nullif`.
- Shipping a metric that validated but was never compared to a known-good query.
- Defining forty metrics up front. Define what people ask for; each is a maintenance
  commitment.
