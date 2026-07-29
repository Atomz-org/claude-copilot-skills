---
name: dbt-unit-testing
description: Write dbt Core unit tests — fixed-input/fixed-output tests that verify SQL logic without warehouse data. Covers the unit_tests YAML spec, dict/csv/sql input formats, fixture files, mocking refs and sources, overrides for macros/vars/env_vars, and the special cases (incremental models, ephemeral dependencies, versioned models, per-warehouse data types). Use when a model has CASE statements, window functions, regex, date arithmetic, or fan-out-resolving joins, when practicing test-driven development on a model, or when asked "how do I unit test this model".
---

# dbt Unit Testing

A unit test runs your model against rows **you** write and asserts the exact output. It
proves the logic is right. Data tests prove the data is valid. You need both, and neither
substitutes for the other.

Requires dbt 1.8+. Unit tests run against models only — not sources, seeds, or snapshots.

## When a model needs one

| Model contains | Unit test |
|---|---|
| `case when` with more than two branches | **Required** — test every branch, including the fallthrough |
| A window function | **Required** — partition and frame boundaries are where the bugs are |
| Date arithmetic, timezone conversion, fiscal periods | **Required** — month-end, DST, and year boundaries |
| Regex or string parsing | **Required** — test the malformed input, not just the clean one |
| A join that resolves fan-out | **Required** — one parent with three children must produce one row |
| A `coalesce` chain with business meaning | **Required** — test which fallback wins |
| `is_incremental()` branching | **Required** — the branch is invisible in normal testing |
| Straight renames and casts (staging) | Not needed — there is no logic to get wrong |

Rule of thumb: **if you had to think about the SQL, unit test it.**

## The spec

```yaml
unit_tests:
  - name: test_order_status_mapping        # required, unique in the project
    model: fct_orders                      # required, must be a model
    description: >                         # optional but expected
      Maps raw Shopify statuses to business statuses. A refund overrides a
      fulfilled status; unknown statuses fall through to 'unknown', not null.

    given:                                 # required: at least one input
      - input: ref('int_orders_with_line_totals')
        rows:
          - {order_id: '1', financial_status: 'paid',     fulfillment_status: 'fulfilled'}
          - {order_id: '2', financial_status: 'refunded', fulfillment_status: 'fulfilled'}
          - {order_id: '3', financial_status: 'pending',  fulfillment_status: null}
          - {order_id: '4', financial_status: 'weird_new_value', fulfillment_status: null}

    expect:                                # required
      rows:
        - {order_id: '1', order_status: 'fulfilled'}
        - {order_id: '2', order_status: 'refunded'}
        - {order_id: '3', order_status: 'pending'}
        - {order_id: '4', order_status: 'unknown'}

    config:                                # optional
      tags: [unit, finance]
      meta: {owner: finance-analytics}
    # enabled: true                        # defaults true in 2.0
```

Optional top-level keys beyond those: `overrides` (macros, vars, env_vars) and `versions`
(`include` / `exclude`) for versioned models.

### The rules that trip people up

1. **`expect` compares only the columns you list.** Extra columns in the model output are
   ignored. Assert the columns the test is about, not every column — a test that lists all
   forty columns breaks on every unrelated change.
2. **Every `ref`/`source` in the model must appear in `given`**, or dbt errors. Even if the
   test does not care about that input, stub it with an empty or one-row list.
3. **Columns you omit from an input row become null.** Supply every column the model's logic
   reads; omit the rest.
4. **Row order does not matter** in the comparison.
5. **Types matter, and dict inputs are the weak point.** See the type section below.

## Input formats

### `dict` (default) — inline, best for small focused tests

```yaml
given:
  - input: ref('stg_shopify__orders')
    format: dict
    rows:
      - {order_id: '1', order_amount: 100.00, ordered_at: '2024-01-15 10:30:00'}
```

### `csv` — inline or from a fixture file, best for many rows

```yaml
given:
  - input: ref('stg_shopify__orders')
    format: csv
    rows: |
      order_id,order_amount,ordered_at
      1,100.00,2024-01-15 10:30:00
      2,250.50,2024-01-16 14:22:00
```

```yaml
given:
  - input: ref('stg_shopify__orders')
    format: csv
    fixture: orders_january        # tests/fixtures/orders_january.csv
```

### `sql` — a select statement, best when you need explicit casts

```yaml
given:
  - input: ref('stg_shopify__orders')
    format: sql
    rows: |
      select '1'::varchar as order_id,
             100.00::numeric(28,6) as order_amount,
             '2024-01-15 10:30:00'::timestamp as ordered_at
```

```yaml
given:
  - input: ref('stg_shopify__orders')
    format: sql
    fixture: orders_typed          # tests/fixtures/orders_typed.sql
```

Use `sql` whenever a type mismatch is causing trouble — it is the only format where you
control the cast exactly.

## Data types by warehouse

dbt builds the fixture with `select ... union all`, and the warehouse infers each column's
type from the literal. This is where most unit-test failures come from.

| Warehouse | The traps |
|---|---|
| **Snowflake** | `'2024-01-15'` is a varchar, not a date — cast in `sql` format or expect a comparison failure. `numeric` precision defaults are wide; a `numeric(28,6)` column compared against `100.0` can mismatch on scale. Unquoted identifiers uppercase. |
| **BigQuery** | Strictest of all: no implicit casts. `INT64` vs `NUMERIC` vs `FLOAT64` must match exactly. `STRUCT` and `ARRAY` columns require `sql` format. `DATE` vs `DATETIME` vs `TIMESTAMP` are three different types and will not compare. |
| **Postgres** | `numeric` vs `float8` mismatches. An empty string is not null. Rich `::` casting makes `sql` format easy. |
| **Redshift** | `varchar(256)` truncation on long test strings. No native `boolean` in some paths — use `true`/`false` literals, not `1`/`0`. Prefer `sql` format for anything typed. |
| **Databricks / Spark** | `DECIMAL` scale must match. Nulls in a `union all` need explicit `cast(null as <type>)`. Fixtures on complex types (`MAP`, `STRUCT`) require `sql` format. |
| **DuckDB** | Most permissive — usually just works. Convenient for developing tests locally before running them against the real adapter. |

The general fix: **when a unit test fails with a type or comparison error, switch that
input to `format: sql` and cast explicitly.** It resolves the great majority of them.

For null typing:

```yaml
given:
  - input: ref('stg_orders')
    format: sql
    rows: |
      select '1' as order_id, cast(null as numeric(28,6)) as discount_amount
```

## Special cases

### Incremental models

Unit tests run against the *full-refresh* path by default. Test the incremental branch by
overriding `is_incremental`:

```yaml
unit_tests:
  - name: test_fct_orders_full_refresh
    model: fct_orders
    overrides:
      macros:
        is_incremental: false
    given:
      - input: ref('int_orders_with_line_totals')
        rows: [{order_id: '1', ordered_at: '2024-01-15'}]
    expect:
      rows: [{order_id: '1'}]

  - name: test_fct_orders_incremental_lookback
    model: fct_orders
    overrides:
      macros:
        is_incremental: true
    given:
      - input: ref('int_orders_with_line_totals')
        rows:
          - {order_id: '1', ordered_at: '2024-01-15'}   # inside the 3-day window
          - {order_id: '2', ordered_at: '2023-06-01'}   # outside it
      - input: this                                     # mock the existing table
        rows: [{order_id: '0', ordered_at: '2024-01-14'}]
    expect:
      rows: [{order_id: '1'}]
```

`input: this` mocks the model's own existing table, which is what the `is_incremental()`
filter reads. Without it, the test cannot exercise the lookback at all. **The incremental
branch is otherwise completely untested** — this is the single highest-value unit test in
most projects.

### Ephemeral dependencies

An `ephemeral` upstream model is inlined as a CTE, so it cannot be mocked directly. Mock
**its** inputs instead, and it will compute from them:

```yaml
given:
  # int_orders_cleaned is ephemeral — mock what IT reads
  - input: ref('stg_shopify__orders')
    rows: [{order_id: '1', financial_status: 'paid'}]
```

This means an ephemeral model in the chain makes unit tests harder to write and harder to
read. If a model is heavily unit-tested, consider making it a `view` instead.

### Versioned models

```yaml
unit_tests:
  - name: test_revenue_logic
    model: fct_orders
    versions:
      include: [2, 3]       # only these versions
      # exclude: [1]        # or all except these
    given: [...]
    expect: [...]
```

Without a `versions` key the test runs against every version, which is usually wrong — the
versions differ precisely because their logic differs.

### Macro, var, and env_var overrides

```yaml
overrides:
  macros:
    is_incremental: false
    dbt_utils.current_timestamp: "'2024-01-15 12:00:00'"   # freeze time
  vars:
    exclude_test_accounts: true
    start_date: '2024-01-01'
  env_vars:
    DBT_ENVIRONMENT: 'ci'
```

Freezing time is essential for any model using `current_date` or `current_timestamp` —
without it the test passes today and fails on the first of next month.

## Writing a good unit test

**Test one behavior per test.** `test_refund_overrides_fulfilled_status` beats
`test_fct_orders`. When it fails you know what broke from the name alone.

**Write the expected output by hand.** Deriving it with the same expression the model uses
proves only that the expression equals itself. This is the most common way a unit test
becomes worthless.

**Cover the edges, not the happy path.** The happy path already works — that is why the
model got written. Test: null inputs, zero, negative, empty string, the unknown enum value,
the boundary date, the duplicate key, the missing parent.

**Minimal fixtures.** Three rows that each prove something beat thirty rows that prove one
thing. Include only the columns the logic reads.

## Test-driven development on a model

This works well in dbt and is worth using for anything with real logic:

1. Write the unit test with the expected output first, from the spec.
2. `dbt test --select test_name` — it fails, because the model does not exist yet or does
   not implement the rule.
3. Write the minimum SQL to pass it.
4. Add the next edge case; repeat.
5. Only then run against real data with `dbt build`.

The payoff is that the expected output comes from the *requirement* rather than from
whatever the SQL happens to produce.

## Scaffolding

```bash
python scripts/unit_test_generator.py --manifest target/manifest.json \
    --model int_order_items --catalog target/catalog.json \
    --adapter snowflake --format dict --out models/intermediate/_int__unit_tests.yml
```

The generator reads the model's `refs` and `sources` from the manifest, stubs every one of
them (so you never hit "input not mocked"), pulls column names and types from the catalog
where available, and emits adapter-appropriate placeholder literals. Fill in the values and
the expected output yourself — the generator supplies structure, not semantics.

## Running

```bash
dbt test --select fct_orders                     # data + unit tests for the model
dbt test --select "fct_orders,test_type:unit"    # unit tests only
dbt test --select test_type:unit                 # every unit test in the project
dbt test --select tag:unit
dbt build --select state:modified+               # CI: unit tests run as part of build
```

Unit tests are fast — they build tiny fixture CTEs rather than scanning tables — so run
every one of them in CI. There is no reason to scope them.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Unit test ... references ... which is not mocked` | An input missing from `given` | Add every `ref`/`source`, even as an empty list |
| Values differ but look identical | Type mismatch (`'100'` vs `100`, varchar date vs date) | Switch that input to `format: sql` and cast |
| Passes locally, fails in CI | Different adapter, or a time-dependent expression | Override `current_timestamp`; run the test on the same adapter |
| Fails after adding an unrelated column | `expect` lists all columns | List only the columns the test asserts |
| Cannot mock an upstream model | It is ephemeral | Mock its inputs instead |
| Test passes but production is wrong | The expected output was derived from the model's own logic | Rewrite the expectation by hand from the requirement |
| BigQuery type errors on nulls | Untyped `null` in a `union all` | `cast(null as <type>)` in `sql` format |
| Incremental test does not exercise the filter | `this` not mocked, or `is_incremental` not overridden | Add both |

## Anti-patterns

- Only data tests on a model full of business logic. A wrong formula that produces
  plausible values passes every data test.
- Expected output computed with the model's own expression.
- One giant unit test asserting forty columns — it fails for unrelated reasons and gets
  disabled.
- A fixture with fifty rows copied from production, including PII.
- No unit test on the `is_incremental()` branch, which is the least-observed code in the
  project.
- Testing the happy path only.
- Real production values in fixtures — fixtures are committed to git and read by everyone.

Next: [semantic-layer-metricflow](../semantic-layer-metricflow/SKILL.md) or
[ops-and-deployment](../ops-and-deployment/SKILL.md).
