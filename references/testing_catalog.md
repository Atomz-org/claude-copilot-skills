# Testing Catalog

Every test type dbt Core offers, what each one catches, and what it cannot.

## The four kinds

| Kind | Defined in | Runs against | Catches |
|---|---|---|---|
| Generic (built-in) | `schema.yml` | real data | nulls, duplicates, orphans, bad domains |
| Generic (package/custom) | `schema.yml` | real data | ranges, regex, distributions, invariants |
| Singular | `tests/*.sql` | real data | one specific business rule |
| Unit | `unit_tests:` YAML | fixtures | the SQL logic itself |

Data tests validate the **data**. Unit tests validate the **logic**. A model with only data
tests can compute revenue wrongly for a year and pass every build, because "unique and not
null" says nothing about whether the number is right.

## Built-in generic tests

```yaml
columns:
  - name: order_id
    data_tests: [unique, not_null]

  - name: customer_id
    data_tests:
      - relationships:
          to: ref('dim_customers')
          field: customer_id
          config:
            where: "customer_id is not null"   # nullable FK — otherwise it fails on legit nulls

  - name: order_status
    data_tests:
      - accepted_values:
          values: [pending, paid, fulfilled, refunded, cancelled]
          quote: true      # false for numeric or boolean domains
```

| Test | Catches | Common cause when it fails |
|---|---|---|
| `unique` | duplicate keys | a join fan-out, or soft-deleted/versioned source rows |
| `not_null` | missing keys | a left join that now misses, or rows dropped upstream |
| `accepted_values` | unexpected domain values | the source system added an enum value — check downstream CASE statements for a silent fallthrough |
| `relationships` | orphan FKs | the parent is filtered more tightly than the child, or was rebuilt late |

## `dbt_utils` tests

```yaml
data_tests:
  - dbt_utils.unique_combination_of_columns:
      combination_of_columns: [order_id, snapshot_date]

  - dbt_utils.expression_is_true:
      expression: "net_amount_usd <= gross_amount_usd"

  - dbt_utils.equality:
      compare_model: ref('fct_orders_legacy')
      compare_columns: [order_id, order_amount_usd]
      config: {tags: ['nightly']}          # expensive — never in CI

  - dbt_utils.recency:
      datepart: hour
      field: ordered_at
      interval: 6

  - dbt_utils.fewer_rows_than:
      compare_model: ref('stg_shopify__orders')

columns:
  - name: order_amount_usd
    data_tests:
      - dbt_utils.accepted_range: {min_value: 0, inclusive: true}
      - dbt_utils.not_null_proportion: {at_least: 0.99}
      - dbt_utils.at_least_one

  - name: valid_from
    data_tests:
      - dbt_utils.mutually_exclusive_ranges:
          lower_bound_column: valid_from
          upper_bound_column: valid_to
          partition_by: customer_id
          gaps: not_allowed          # allowed | not_allowed | required
```

`mutually_exclusive_ranges` is the SCD2 test — it catches overlapping validity windows, which
is the classic snapshot-consumption bug.

## `dbt_expectations` tests

```yaml
data_tests:
  - dbt_expectations.expect_table_row_count_to_be_between:
      min_value: 1000
      max_value: 100000

  - dbt_expectations.expect_table_row_count_to_equal_other_table:
      compare_model: ref('stg_shopify__orders')

columns:
  - name: email
    data_tests:
      - dbt_expectations.expect_column_values_to_match_regex:
          regex: "^[^@]+@[^@]+\\.[^@]+$"
  - name: order_amount_usd
    data_tests:
      - dbt_expectations.expect_column_mean_to_be_between: {min_value: 20, max_value: 500}
      - dbt_expectations.expect_column_values_to_be_of_type: {column_type: numeric}
  - name: currency_code
    data_tests:
      - dbt_expectations.expect_column_value_lengths_to_equal: {value: 3}
  - name: event_sequence
    data_tests:
      - dbt_expectations.expect_column_values_to_be_increasing:
          sort_column: event_at
          group_by: [session_id]
```

Use these for **distributional and format** assertions that the built-ins cannot express.
`expect_column_mean_to_be_between` is a cheap early-warning signal for upstream logic changes.

## Singular tests

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
select
    mart.day, mart.amount as mart_amount, ledger.amount as ledger_amount,
    abs(mart.amount - ledger.amount) / nullif(ledger.amount, 0) as pct_diff
from mart join ledger using (day)
where abs(mart.amount - ledger.amount) / nullif(ledger.amount, 0) > 0.005
```

Returns rows on failure; zero rows is a pass. Use when the assertion is specific to one
place. Written twice in similar form → make it a custom generic test.

Other high-value singular tests:

```sql
-- No overlapping SCD2 validity windows
select customer_id from {{ ref('dim_customers_scd') }} a
where exists (
    select 1 from {{ ref('dim_customers_scd') }} b
    where a.customer_id = b.customer_id
      and a.dbt_scd_id != b.dbt_scd_id
      and a.valid_from < coalesce(b.valid_to, '9999-12-31')
      and b.valid_from < coalesce(a.valid_to, '9999-12-31')
)

-- Exactly one current row per key
select customer_id from {{ ref('dim_customers_scd') }}
where is_current group by customer_id having count(*) != 1

-- Internal test accounts leaked into the mart
select order_id from {{ ref('fct_orders') }}
where customer_email like '%@internal.example.com'

-- Day-over-day row count collapse
with daily as (
    select ordered_date, count(*) as n from {{ ref('fct_orders') }} group by 1
)
select * from (
    select ordered_date, n, lag(n) over (order by ordered_date) as prev
    from daily
) where prev is not null and n < prev * 0.5
```

## Custom generic tests

```sql
-- tests/generic/test_positive_or_null.sql
{% test positive_or_null(model, column_name) %}
select {{ column_name }} from {{ model }}
where {{ column_name }} is not null and {{ column_name }} < 0
{% endtest %}

-- with arguments and a default
{% test recent_enough(model, column_name, max_age_days=7) %}
select max({{ column_name }}) as most_recent from {{ model }}
having max({{ column_name }}) < {{ dbt.dateadd('day', -max_age_days, 'current_date') }}
{% endtest %}
```

```yaml
- name: ordered_at
  data_tests:
    - recent_enough: {max_age_days: 3}
```

## Test configuration

```yaml
- unique:
    config:
      severity: error          # error blocks the build; warn does not
      error_if: ">100"
      warn_if: ">0"
      where: "ordered_at >= '2023-01-01'"
      store_failures: true
      store_failures_as: table   # or view
      limit: 500
      tags: [nightly]
      enabled: "{{ target.name == 'prod' }}"
      alias: unique_orders_pk
```

| Setting | Guidance |
|---|---|
| `severity` | `error` by default. A permanent `warn` is either an ignored defect or a bad test — resolve it |
| `error_if` / `warn_if` | for tests where a few failures are tolerable and a hundred are not |
| `where` | **scope a test, do not delete it.** Pre-migration rows are known-bad; exclude them explicitly and keep the test live for everything since |
| `store_failures` | on anything you would need to investigate. "42 rows failed" is not actionable; a table of the 42 rows is |
| `tags` | split fast CI tests from expensive nightly ones |
| `limit` | cap stored failures on a large table |

## Unit tests

```yaml
unit_tests:
  - name: test_refund_overrides_fulfilled_status
    model: fct_orders
    description: A refunded order reports 'refunded' even when fulfillment succeeded.
    given:
      - input: ref('int_orders_with_line_totals')
        rows:
          - {order_id: '1', financial_status: 'refunded', fulfillment_status: 'fulfilled'}
    expect:
      rows:
        - {order_id: '1', order_status: 'refunded'}
```

Formats: `dict` (default), `csv` (inline or `fixture:`), `sql` (inline or `fixture:`).
Optional keys: `config`, `overrides` (`macros`, `vars`, `env_vars`), `versions`
(`include`/`exclude`).

Full treatment in the `dbt-unit-testing` skill. The rules that matter:

- Every `ref`/`source` in the model must appear in `given`, even as an empty list.
- `expect` compares only the columns you list.
- Omitted input columns become null.
- Types matter; when a comparison fails inexplicably, switch to `format: sql` and cast.
- Write expected output **by hand** — deriving it with the model's own expression proves
  nothing.

## Source tests and freshness

```yaml
sources:
  - name: shopify
    loaded_at_field: _fivetran_synced
    freshness:
      warn_after:  {count: 12, period: hour}
      error_after: {count: 24, period: hour}
      filter: "_fivetran_synced >= dateadd(day, -7, current_date)"   # limit the scan
    tables:
      - name: orders
        freshness: {warn_after: {count: 1, period: hour}, error_after: {count: 6, period: hour}}
        columns:
          - name: id
            data_tests: [unique, not_null]
      - name: currency_rates
        freshness: null       # explicit opt-out — a one-time load
```

- `freshness: null` is a **decision**; a missing block is an undocumented SLA.
- `loaded_at_field` must be a **warehouse load timestamp**, not a source-system `updated_at`.
  Using `updated_at` means a dead pipeline looks fresh as long as one old row was recently
  edited.
- `filter:` limits the freshness scan on very large tables.
- Testing the source's PK catches duplicates before they enter staging.

## From assumption to test

| Assumption | Test |
|---|---|
| Every order has a customer | `relationships` |
| Status is one of five values | `accepted_values` |
| We exclude internal test accounts | singular |
| Refunds are never positive | `accepted_range` with `max_value: 0` |
| Revenue reconciles to the ledger ±0.5% | singular reconciliation |
| One row per order per day | `unique_combination_of_columns` |
| Orders arrive within 3 days | `dbt_utils.recency` on the source |
| Row count is stable day over day | `expect_table_row_count_to_be_between` |
| Email is well-formed | `expect_column_values_to_match_regex` |
| SCD2 has no overlaps | `mutually_exclusive_ranges` |
| The mart never exceeds its source | `fewer_rows_than` |

## Test performance

Tests are often 20–40% of build time and are almost never tuned.

| Expensive pattern | Fix |
|---|---|
| `relationships` between two large tables | scope with `where:` to a recent window, or tag nightly |
| `dbt_utils.equality` on full tables | nightly only |
| `unique` on a very large table | usually worth keeping; scope if not |
| `accepted_values` on a high-cardinality column | wrong test — use `relationships` to a dimension |
| Many `not_null` tests on one model | each is a separate query; keep them to the columns that matter |

```bash
dbt build --exclude tag:nightly       # CI and hourly
dbt test --select tag:nightly         # once a day
```

## Coverage

```bash
python scripts/test_coverage_reporter.py --manifest target/manifest.json \
    --layer marts --min-coverage 0.9 --strict
```

Ranked by downstream blast radius, not alphabetically — an untested model feeding six
dashboards outranks twelve untested leaf models. Coverage as a bare percentage is a vanity
metric; coverage weighted by what depends on the model is not.

## Anti-patterns

- `not_null` on every column — noise gets muted.
- `severity: warn` used to merge a failing test.
- Deleting a failing test instead of scoping it with `where:` and recording why.
- `relationships` on a nullable FK with no `where:` guard.
- Expensive reconciliation tests on every CI build.
- Only data tests on a model full of business logic.
- Unit-test expectations derived from the model's own expression.
- A test suite slower than the build itself.
