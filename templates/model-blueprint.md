# Model Blueprint — <model_name>

Written **before** the SQL. If any row below is empty, the model is not ready to build.

---

## 1. Identity

| Item | Value |
|---|---|
| Model name | `<stg_ / int_ / fct_ / dim_>_<entity>` |
| Layer | staging / intermediate / marts |
| File path | `models/<layer>/<domain>/<name>.sql` |
| Owner (group) | |
| Use case | `use-cases/<slug>/use-case-spec.md` |
| Data model | `use-cases/<slug>/data-model-canvas.md` — the row in the grain matrix this implements |
| Kind | fact (transaction / periodic / accumulating / factless) / dimension / bridge / aggregate / staging / intermediate |

## 2. Grain — one sentence

> One row per `<entity>` per `<period>` per `<qualifier>`.

| Item | Value |
|---|---|
| Primary key | |
| Surrogate key needed? | `dbt_utils.generate_surrogate_key([<grain cols>])` |
| Expected row count (order of magnitude) | |
| Growth rate | |

## 3. Inputs

| Input | `ref()` / `source()` | Expected cardinality vs this model | Join key | Join type + why |
|---|---|---|---|---|
| | | 1:1 / 1:N / N:1 | | |

**Fan-out plan** — for every 1:N input, how the grain is preserved:

| Input | Resolution |
|---|---|
| | aggregated to `<grain>` in CTE `<name>` before the join |

Never `sum()` across a fanned-out join. Collapse to the join grain first.

## 4. Output columns

| Column | Type | Source | Transformation | Nullable? | Description |
|---|---|---|---|---|---|
| | | | | | |

Enumerate them. `select *` in a mart means a new upstream column appears silently in a
dashboard.

## 5. Filters and exclusions

| Filter | Reason | Rows removed (est.) | Does a consumer ever need these rows? |
|---|---|---|---|
| | | | |

A filter that removes rows a consumer might need belongs downstream, not in staging.

## 6. Materialization

| Item | Value |
|---|---|
| Materialization | view / table / incremental / ephemeral / materialized_view |
| **Reason** (one line) | |
| Measured full-refresh time | |
| Measured full-refresh cost | |

### If incremental

| Item | Value |
|---|---|
| `unique_key` | |
| `incremental_strategy` | append / merge / delete+insert / insert_overwrite / microbatch |
| Measured p99 arrival lag | |
| Lookback window (≈ p99 × 2) | |
| Filter anchored to | `max()` in `{{ this }}` — **never `current_date`** |
| `on_schema_change` | append_new_columns / sync_all_columns / fail |
| Partition / cluster key | |
| Does `--full-refresh` reproduce it exactly? | verified how, and when |

### If snapshot

| Item | Value |
|---|---|
| Strategy | timestamp / check |
| `updated_at` reliability verified? | |
| `check_cols` | |
| Target schema (shared, not env-suffixed) | |
| Backup taken before any config change? | |

## 7. Tests

| Test | Column | Severity | Reason |
|---|---|---|---|
| `unique` | | error | primary key |
| `not_null` | | error | primary key |
| `relationships` | | error | |
| `accepted_values` | | error | |
| | | | |

**Unit tests** — required if this model contains CASE, a window function, regex, date
math, or a fan-out-resolving join:

| Unit test | Behavior it proves |
|---|---|
| | |

## 8. Documentation

| Item | Value |
|---|---|
| Model description (grain + exclusions + non-obvious) | |
| Shared definitions needing a `docs` block | |
| Columns still undocumented | |

## 9. Impact

| Item | Value |
|---|---|
| Downstream models | (from `model_dependency_analyzer.py --direction down`) |
| Downstream exposures | |
| Contracted? | |
| Versioned? | |
| Breaking change? | which kind, and the mitigation |
| Consumers to notify | |

## 10. Delivery

| Item | Value |
|---|---|
| Build command | `dbt build --select <name>+` |
| Verification | row count, `sum()` of numeric columns, vs previous run |
| Rollback | |
| Estimated build time | |

---

## Pre-build checklist

- [ ] Grain is one sentence and the PK enforces it
- [ ] Every join has a stated cardinality and a fan-out plan
- [ ] Materialization has a written reason
- [ ] Incremental: lookback sized from **measured** lag, anchored to `{{ this }}`
- [ ] Output columns enumerated, not `select *`
- [ ] Tests listed, including a unit test for any real logic
- [ ] Downstream impact checked against the production manifest
- [ ] Rollback path stated
