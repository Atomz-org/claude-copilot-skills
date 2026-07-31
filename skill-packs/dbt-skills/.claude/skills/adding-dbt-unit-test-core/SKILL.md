---
name: adding-dbt-unit-test-core
description: Add dbt unit tests for logic-heavy models with deterministic fixtures and edge-case assertions.
---

# Adding dbt Unit Tests (Core)

## When required

Add unit tests for models with CASE logic, windows, regex, date math, or fan-out-sensitive joins.

## Steps

```bash
dbt parse
python scripts/unit_test_generator.py --manifest target/manifest.json --model <model> --adapter <adapter>
```

Then replace generated placeholders with explicit expected outputs.

## Coverage expectations

- Happy path and edge path fixtures.
- Null behavior and boundary timestamps.
- Duplicate or conflicting parent rows when join fan-out is possible.

## dbt Core translation notes

- Keep unit tests local, deterministic, and executable in Core CLI pipelines.

## Examples

How this gets called in Claude Code, and what it should hand back.

| Ask Claude | What you get |
|---|---|
| "unit test int_orders_categorized" | The generator run for structure, then expected rows written by hand |
| "does this model need a unit test?" | A yes/no from the SQL — CASE, window, regex, date math, or fan-out join means yes |
| `/dbt-test fct_orders` | The full plan: data tests for the data, unit tests for the logic |

**Worked example**

> "unit test the order size buckets"

```bash
dbt parse
python scripts/unit_test_generator.py --manifest target/manifest.json \
    --model int_orders_categorized --adapter snowflake
```

```yaml
unit_tests:
  - name: test_order_size_buckets
    model: int_orders_categorized
    given:
      - input: ref('stg_shopify__orders')
        rows:
          - {order_id: 1, total_amount: 0}        # boundary: zero
          - {order_id: 2, total_amount: 99.99}    # boundary: just under
          - {order_id: 3, total_amount: 100.00}   # boundary: exactly at
          - {order_id: 4, total_amount: null}     # null path
    expect:
      rows:
        - {order_id: 1, size_bucket: 'small'}
        - {order_id: 2, size_bucket: 'small'}
        - {order_id: 3, size_bucket: 'medium'}
        - {order_id: 4, size_bucket: 'unknown'}
```

```bash
dbt test --select int_orders_categorized,test_type:unit
```

Row 3 is the one that catches a `>` written where `>=` was meant. Deriving the expected
values with the model's own CASE expression proves only that the expression equals itself
— write them by hand.
