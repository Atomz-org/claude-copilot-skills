---
description: Write the test plan for a dbt model — data tests plus unit tests — before merge
argument-hint: <model, selector, or path>
---

Write the test plan for: **$ARGUMENTS**

Load `testing-and-documentation`, and `dbt-unit-testing` if the model contains logic.

---

## 1. Both kinds, always

| | Data tests | Unit tests |
|---|---|---|
| Question | Is the data in the warehouse valid? | Is the SQL logic correct? |
| Input | whatever is in the table now | fixed rows you write |
| Catches | nulls, duplicates, orphans, bad domains | wrong CASE branch, off-by-one date math, wrong window frame, fan-out |
| Misses | **a formula that is wrong but produces plausible values** | anything about the actual data |

A model with only data tests can compute revenue wrongly for a year and pass every build.
A model with only unit tests breaks the day the source starts sending nulls.

## 2. Work from the spec, not the SQL

Every material assumption in `use-cases/<slug>/use-case-spec.md` becomes a test:

| Assumption | Test |
|---|---|
| Every order has a customer | `relationships` |
| Status is one of five values | `accepted_values` |
| We exclude internal test accounts | singular test |
| Refunds are never positive | `dbt_utils.accepted_range` with `max_value: 0` |
| Revenue reconciles to the ledger ±0.5% | singular reconciliation test |
| One row per order per day | `dbt_utils.unique_combination_of_columns` |
| Orders arrive within 3 days | `dbt_utils.recency` on the source |
| SCD2 has no overlapping windows | `dbt_utils.mutually_exclusive_ranges` |

Testing only what the SQL happens to do tests the implementation, not the requirement.

## 3. Minimum bar

- [ ] `unique` + `not_null` on the primary key — every model, no exceptions
- [ ] `relationships` on every foreign key (`where: <col> is not null` if nullable)
- [ ] `accepted_values` on every closed-domain column
- [ ] A description stating the grain
- [ ] Contracted models: `data_type` on every column
- [ ] **A unit test for every CASE, window function, regex, date math, or fan-out-resolving join**
- [ ] Incremental models: a unit test covering the `is_incremental()` branch, with `input: this` mocked

## 4. Scaffold, then write the semantics

```bash
dbt docs generate
python scripts/schema_yml_generator.py --manifest target/manifest.json \
    --model <model> --catalog target/catalog.json --infer-tests

python scripts/unit_test_generator.py --manifest target/manifest.json \
    --model <model> --catalog target/catalog.json --adapter <adapter>
```

Both generators supply **structure, not semantics**. The unit-test generator stubs every
`ref`/`source` so you never hit "input not mocked" — but **you write the expected output by
hand**, from the requirement. Expected output derived with the model's own expression proves
only that the expression equals itself.

Test the edges, not the happy path: nulls, zero, negative, empty string, the unknown enum
value, the boundary date, the duplicate key, the missing parent.

## 5. Set severity deliberately

```yaml
- unique:
    config:
      severity: error                          # error blocks; warn does not
      where: "ordered_at >= '2023-01-01'"      # scope, don't delete
      store_failures: true                     # so failures are investigable
      tags: [nightly]                          # expensive tests out of CI
```

- A test permanently at `warn` is either an ignored defect or a bad test. Resolve it.
- Never delete a failing test. Scope it with `where:` and record why in a comment.
- `store_failures: true` on anything you'd need to investigate — "42 rows failed" is not
  actionable; a table of the 42 rows is.

## 6. Watch test cost

Tests are often 20–40% of build time. Tag the expensive ones out of CI:

| Pattern | Fix |
|---|---|
| `relationships` between two large tables | scope with `where:` to a recent window, or tag `nightly` |
| `dbt_utils.equality` on full tables | `nightly` only |
| `accepted_values` on high cardinality | wrong test — use `relationships` to a dimension |

## 7. Run and audit

```bash
dbt build --select <model>+
dbt test --select <model> --store-failures
dbt test --select test_type:unit
python scripts/test_coverage_reporter.py --manifest target/manifest.json \
    --layer marts --min-coverage 0.9 --strict
```

The coverage reporter ranks gaps by **downstream blast radius**, not alphabetically. Fix in
that order — an untested model feeding six dashboards outranks twelve untested leaf models.

---

## Rules that bind here

[Rules 28–32](../rules/analytics-engineering-rules.md): no model merges without tests; test
the business rule, not just the schema; unit tests cover the logic and data tests cover the
data; severity is set intentionally; every failing test is reproducible.

## Output

- the `schema.yml` and `unit_tests:` YAML;
- a table of assumption → test, showing every spec assumption is covered;
- which tests are `nightly` and why;
- coverage before and after;
- the merge verdict: **Merge**, **Merge after** (a short blocking list), or **Do not merge**.
