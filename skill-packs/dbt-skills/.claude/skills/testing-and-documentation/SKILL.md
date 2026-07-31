---
name: testing-and-documentation
description: Write dbt Core data tests and documentation — schema.yml structure, built-in generic tests (unique, not_null, accepted_values, relationships), dbt_utils and dbt_expectations tests, custom generic tests, singular tests, severity/where/store_failures config, model and column descriptions, docs blocks, exposures, and coverage auditing. Use when a model is written and needs tests, when reviewing a dbt PR, when documenting models, or when asked "what tests should this have", "how do I test X", or "how do I document this".
---

# Testing and Documentation

Tests are how the data earns trust; documentation is how it gets used. Both go in
`schema.yml` next to the models they describe.

For logic correctness — CASE branches, window frames, date math — you need unit tests, not
data tests. See [dbt-unit-testing](../dbt-unit-testing/SKILL.md). This skill covers
everything else.

## Minimum bar

| Model kind | Required |
|---|---|
| Any model | `unique` + `not_null` on the primary key; a description stating the grain |
| Staging | plus `not_null` on every column a downstream join depends on |
| Any foreign key | plus `relationships` to the parent |
| Any closed-domain column | plus `accepted_values` |
| Any mart | plus a description on every column, and an exposure or downstream model |
| Any contracted model | plus `data_type` on every column |
| Any incremental model | plus a grain test that holds after a merge |

## `schema.yml`

```yaml
version: 2

models:
  - name: fct_orders
    description: >
      One row per order at its current fulfillment status. Excludes internal test
      accounts (`is_test_order`) and orders predating the 2023-01-01 platform migration.
      Amounts are USD, converted at the order-date rate.
    config:
      contract: {enforced: true}
      tags: [finance, daily]
    columns:
      - name: order_id
        description: Primary key. Shopify order id, prefixed `sh_` after the 2024 merge.
        data_type: varchar
        data_tests:
          - unique
          - not_null

      - name: customer_id
        description: FK to dim_customers. Null for guest checkouts (~3% of orders).
        data_type: varchar
        data_tests:
          - relationships:
              to: ref('dim_customers')
              field: customer_id
              config:
                where: "customer_id is not null"   # guest checkouts are legitimate nulls

      - name: order_status
        description: "{{ doc('order_status') }}"
        data_type: varchar
        data_tests:
          - not_null
          - accepted_values:
              values: [pending, paid, fulfilled, refunded, cancelled]

      - name: order_amount_usd
        description: Gross order amount in USD, before refunds. Includes tax and shipping.
        data_type: numeric(28,6)
        data_tests:
          - not_null
          - dbt_utils.accepted_range:
              min_value: 0
              inclusive: true
              config:
                severity: warn
                where: "ordered_at >= '2023-01-01'"

    # model-level tests span multiple columns
    data_tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: [order_id, snapshot_date]
      - dbt_utils.expression_is_true:
          expression: "net_line_amount_usd <= order_amount_usd"
```

`data_tests:` is the current key. `tests:` is the pre-1.8 spelling and still parses, but
new YAML should use `data_tests:` — mixing the two in one project is a readability tax.

## Test catalog

### Built in

| Test | Catches |
|---|---|
| `unique` | duplicate primary keys — usually a join fan-out |
| `not_null` | missing keys, failed left joins, dropped rows upstream |
| `accepted_values` | a source system adding an enum value your CASE does not handle |
| `relationships` | orphan foreign keys — the parent is filtered more tightly than the child |

### `dbt_utils`

| Test | Use |
|---|---|
| `unique_combination_of_columns` | a composite grain with no single key column |
| `accepted_range` | a numeric that must stay within bounds |
| `expression_is_true` | any row-level invariant: `net <= gross`, `end_at > start_at` |
| `not_null_proportion` | a column allowed some nulls but not many (`at_least: 0.95`) |
| `at_least_one` | a column that must not be entirely null |
| `equality` | two relations must match — the reconciliation and refactor-proof test |
| `recency` | the table has rows newer than N periods ago |
| `cardinality_equality` | two columns have the same set of distinct values |
| `fewer_rows_than` | a child never exceeds its parent |
| `not_accepted_values` | forbidden values (e.g. a legacy status that should be migrated) |
| `sequential_values` | no gaps in a sequence |

### `dbt_expectations`

| Test | Use |
|---|---|
| `expect_table_row_count_to_be_between` | detect a truncated or duplicated load |
| `expect_column_values_to_match_regex` | emails, SKU formats, currency codes |
| `expect_column_values_to_be_of_type` | pre-contract type checking |
| `expect_column_mean_to_be_between` | distribution shift on a business metric |
| `expect_column_values_to_be_increasing` | a monotonic counter or event sequence |
| `expect_table_row_count_to_equal_other_table` | strict reconciliation |
| `expect_column_distinct_count_to_be_between` | cardinality drift |

### Singular tests

Any SQL that returns rows on failure. Lives in `tests/`, one file per test.

```sql
-- tests/assert_revenue_reconciles_to_ledger.sql
-- Fails if daily mart revenue diverges from the finance ledger by more than 0.5%.
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
    mart.day,
    mart.amount    as mart_amount,
    ledger.amount  as ledger_amount,
    abs(mart.amount - ledger.amount) / nullif(ledger.amount, 0) as pct_diff
from mart
join ledger using (day)
where abs(mart.amount - ledger.amount) / nullif(ledger.amount, 0) > 0.005
```

Use a singular test when the assertion is specific to one place. If you write the same
shape twice, make it a custom generic test instead.

### Custom generic tests

```sql
-- tests/generic/test_positive_or_null.sql
{% test positive_or_null(model, column_name) %}
select {{ column_name }}
from {{ model }}
where {{ column_name }} is not null and {{ column_name }} < 0
{% endtest %}
```

```yaml
- name: order_amount_usd
  data_tests:
    - positive_or_null
```

Generic tests take `model` and `column_name` plus any extra kwargs you declare. They live
in `tests/generic/` or `macros/`.

## Test configuration

```yaml
- unique:
    config:
      severity: error          # error blocks the build; warn does not
      error_if: ">100"         # escalate only past a threshold
      warn_if: ">0"
      where: "ordered_at >= '2023-01-01'"    # scope, don't delete
      store_failures: true                    # failing rows land in a table
      limit: 500                              # cap what gets stored
      tags: [nightly]                         # so you can select it separately
```

- **Severity is a decision.** A test permanently at `warn` is either a real defect being
  ignored or a bad test. Resolve it — do not leave it.
- **`where:` scopes a test; deleting it removes the guarantee.** Pre-migration rows are
  known-bad — exclude them explicitly and keep the test live for everything since.
- **`store_failures: true`** on anything you would need to investigate. A log line saying
  "42 rows failed" is not actionable; a table of the 42 rows is.
- **`error_if` / `warn_if`** for tests where a handful of failures is tolerable and a
  hundred is not.
- **Tags** let you split fast CI tests from expensive nightly reconciliation:
  `dbt test --exclude tag:nightly` in CI, `dbt test --select tag:nightly` overnight.

## From assumption to test

Every material assumption in the use-case spec becomes a test. This is the mechanism that
turns framing into a guarantee:

| Assumption | Test |
|---|---|
| Every order has a customer | `relationships` on `customer_id` |
| Status is one of five values | `accepted_values` |
| We exclude internal test accounts | singular: zero rows where `email like '%@internal.example.com'` |
| Refunds are never positive | `dbt_utils.accepted_range` with `max_value: 0` |
| Revenue reconciles to the ledger ±0.5% | singular reconciliation test |
| One row per order per day | `dbt_utils.unique_combination_of_columns` |
| Orders arrive at most 3 days late | `dbt_utils.recency` on the source |
| Order count never drops more than 30% day over day | `dbt_expectations.expect_table_row_count_to_be_between` |

## Documentation

A description that restates the model name is worse than none — it looks like documentation
and is not. A good description answers three things:

1. **The grain** — "one row per order per fulfillment status".
2. **What is excluded** — filters, test accounts, date cutoffs.
3. **The non-obvious** — why a join is left, what a null means, which source wins a conflict.

```yaml
description: >
  One row per subscription per calendar month, for months in which the subscription was
  active for at least one day. Excludes internal accounts and trials that never converted.
  `mrr_usd` is the amount billed in that month, not the annualized run rate — for ARR,
  use `dim_subscriptions.arr_usd`.
```

### Docs blocks

Shared definitions live in one place, so a term cannot mean two things:

```markdown
{% docs order_status %}
The current fulfillment state of the order, from the Shopify `fulfillment_status` field.

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

```yaml
- name: order_status
  description: "{{ doc('order_status') }}"
```

Use a docs block whenever a definition appears in more than one model, or whenever it needs
more than a sentence.

### `persist_docs`

```yaml
models:
  analytics:
    +persist_docs: {relation: true, columns: true}
```

Pushes descriptions into the warehouse's own comment fields, so analysts see them in their
SQL editor and BI tool rather than only in the dbt docs site. Low cost, high adoption impact.

### Exposures

```yaml
exposures:
  - name: executive_revenue_dashboard
    type: dashboard             # dashboard | notebook | analysis | ml | application
    maturity: high              # high | medium | low
    url: https://bi.example.com/dashboards/42
    owner: {name: Priya Raman, email: priya@example.com}
    description: >
      Board-level weekly revenue, read by the exec team every Monday 08:00 UTC.
      Breaking this is a P1.
    depends_on:
      - ref('fct_orders')
      - ref('dim_customers')
      - metric('revenue')
```

Exposures make `dbt build --select +exposure:executive_revenue_dashboard` work, make the
consumer visible in the DAG, and let the breaking-change detector tell you what a change
reaches. **A mart with no exposure and no downstream model is speculative work.**

## Auditing coverage

```bash
python scripts/test_coverage_reporter.py --manifest target/manifest.json \
    --layer marts --min-coverage 0.9 --strict

python scripts/dbt_project_auditor.py --manifest target/manifest.json --strict
```

The coverage reporter ranks untested models by downstream blast radius, not alphabetically —
an untested model feeding six dashboards outranks twelve untested leaf models. Fix in that
order. Coverage as a bare percentage is a vanity metric.

## Running tests

```bash
dbt build --select fct_orders+           # models and their tests, interleaved — always prefer this
dbt test --select fct_orders             # tests for one model
dbt test --select source:shopify         # source tests only
dbt test --select tag:reconciliation
dbt test --exclude tag:nightly           # fast CI subset
dbt test --select fct_orders --store-failures
dbt build --select state:modified+ --defer --state prod/    # CI
```

`dbt build` interleaves tests with models and stops dependents on failure. `dbt run` then
`dbt test` propagates bad data through the entire DAG before anything fails — never do it.

## Anti-patterns

- `not_null` on every column: noise, and noise gets muted.
- A test suite slower than the build. Scope with `where:`, tag expensive tests, run them
  nightly rather than in CI.
- `severity: warn` used to merge a failing test.
- `relationships` on a nullable FK without `where: <col> is not null` — it fails on
  legitimate nulls.
- Deleting a failing test instead of scoping it with `where:` and recording why.
- Descriptions that repeat the column name back ("order_id: the order id").
- Definitions duplicated across models instead of a shared `docs` block.
- A mart with no exposure — nobody knows who breaks when it changes.
- Data tests as the only tests on a model full of business logic. They cannot catch a wrong
  formula that produces plausible values.

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| `/dbt-test fct_orders` | The minimum bar confirmed, then a test per assumption in the use-case spec |
| "what tests should this have?" | Tests derived from the model's assumptions — not `not_null` on all 40 columns |
| "document this model" | A description that states the grain and what is excluded, and column docs via `{{ doc() }}` |
| "this test fails on legitimate nulls" | `where:` scoping with the reason recorded, rather than `severity: warn` or deletion |

**Worked example**

> `/dbt-test fct_orders`

```yaml
models:
  - name: fct_orders
    description: >
      One row per order. Excludes internal test accounts (customer_id in the
      seed_internal_accounts seed). Refunds are aggregated to order grain, so
      refund_amount is 0 rather than null for unrefunded orders.
    columns:
      - name: order_id
        description: "{{ doc('order_id') }}"          # shared definition, cannot drift
        data_tests: [unique, not_null]                # the minimum bar, always

      - name: customer_id
        data_tests:
          - relationships:                            # assumption: every order has a customer
              to: ref('dim_customers')
              field: customer_id
              config: {where: "customer_id is not null"}   # guest checkout is legitimate

      - name: order_status
        data_tests:
          - accepted_values:                          # assumption: closed domain of five
              values: [pending, paid, fulfilled, cancelled, refunded]
              config: {store_failures: true}          # a sixth value must be inspectable

      - name: refund_amount
        data_tests:
          - dbt_utils.accepted_range: {min_value: 0, inclusive: true}
```

```sql
-- tests/assert_order_revenue_reconciles_to_ledger.sql
-- Assumption from the use-case spec: revenue reconciles to finance within 0.5%.
select date_trunc('month', ordered_at) as month
from {{ ref('fct_orders') }} o
join {{ ref('stg_netsuite__gl_revenue') }} g using (month)
group by 1
having abs(sum(o.total_amount) - max(g.amount)) / nullif(max(g.amount), 0) > 0.005
```

```bash
dbt build --select fct_orders                 # tests run with the model, not after the DAG
python scripts/test_coverage_reporter.py \
    --manifest target/manifest.json --layer marts --min-coverage 0.9
```

Also add an `exposures:` entry — a mart with no exposure means nobody knows who breaks
when it changes. And note what data tests cannot do: `fct_orders` has a CASE-based status
rollup, so it still needs a unit test.

Next: [dbt-unit-testing](../dbt-unit-testing/SKILL.md).
