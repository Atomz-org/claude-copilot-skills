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
