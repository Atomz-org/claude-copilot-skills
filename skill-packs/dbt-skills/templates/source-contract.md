# Source Contract — <source_name>.<table_name>

The agreement between whoever lands this data and whoever models it. Fill it in **before**
building on the source; a mart on an undocumented source is rework waiting to happen.

---

## 1. Identity

| Item | Value |
|---|---|
| Source system | |
| Landed by (EL tool / job) | |
| Warehouse location | `<database>.<schema>.<table>` |
| Owner of the pipeline | person or channel |
| Owner of the source system | person or channel |
| dbt `sources.yml` entry | `models/staging/<source>/_<source>__sources.yml` |

## 2. Grain and keys

| Item | Value |
|---|---|
| Grain | one row per `<entity>` |
| Primary key | |
| Is the PK actually unique? | verified how, and when |
| Natural/business key (if different) | |
| Foreign keys | |

## 3. Freshness

| Item | Value |
|---|---|
| `loaded_at_field` | **must be a warehouse load timestamp, not a source `updated_at`** |
| Actual load cadence | |
| `warn_after` | |
| `error_after` | |
| Consumer's real need | |
| Behavior on weekends/holidays | |
| Who is paged on an `error_after` breach | the EL team, not analytics |

Using a source-system `updated_at` as `loaded_at_field` means a dead pipeline looks fresh
forever, as long as one old row was recently edited.

## 4. Mutability

| Item | Value |
|---|---|
| Are rows updated in place? | |
| Which columns mutate? | |
| Are rows hard-deleted? | |
| Soft-delete marker | e.g. `_fivetran_deleted` |
| **Does a snapshot need to capture history?** | if yes, snapshot the RAW source |
| Is the table ever truncated and reloaded? | |
| Backfill behavior — does history get restated? | |

## 5. Known dirtiness

| Issue | Scope | Handling | Handled where |
|---|---|---|---|
| Soft-deleted rows | | filtered | staging |
| Test/internal rows | | | |
| Pre-migration records | | | |
| Duplicate loads | | | |
| Nulls in a "required" column | | | |
| Encoding / whitespace | | | |

## 6. Schema stability

| Item | Value |
|---|---|
| Who can change this schema? | |
| Notice given for a breaking change? | |
| How changes are announced | |
| Has the schema changed unannounced before? | |
| Columns we depend on (the actual contract surface) | |

## 7. Columns we depend on

| Column | Type | Meaning | Nullable | Notes |
|---|---|---|---|---|
| | | | | |

Anything not listed here is not part of the contract — we can survive it changing.

## 8. Volume

| Item | Value |
|---|---|
| Current row count | |
| Daily growth | |
| Earliest reliable date | |
| Retention in the source system | |

## 9. Sensitivity

| Item | Value |
|---|---|
| Contains PII? | which columns |
| Legal basis / policy | |
| Masking applied | where, and by whom |
| Access restriction | |

## 10. Arrival lag — required before any incremental model

```sql
select
    percentile_cont(0.50) within group (order by datediff('hour', <event_ts>, <loaded_at>)) as p50_h,
    percentile_cont(0.99) within group (order by datediff('hour', <event_ts>, <loaded_at>)) as p99_h,
    max(datediff('hour', <event_ts>, <loaded_at>))                                          as max_h
from <source>
where <loaded_at> >= dateadd(day, -30, current_date)
```

| Metric | Value | Measured on |
|---|---|---|
| p50 | | |
| p99 | | |
| max | | |
| Lookback window chosen (≈ p99 × 2) | | |

Re-measure quarterly. Arrival lag drifts as upstream systems change, and a stale window
drops late rows permanently.

## 11. `sources.yml`

```yaml
sources:
  - name: <source_name>
    description: <what this system is, who owns it>
    database: <db>
    schema: <schema>
    loaded_at_field: <load_timestamp>
    freshness:
      warn_after:  {count: <n>, period: hour}
      error_after: {count: <n>, period: hour}
    tables:
      - name: <table>
        description: <grain, soft-delete marker, known dirtiness>
        columns:
          - name: <pk>
            description: <meaning>
            data_tests: [unique, not_null]
```

## 12. Sign-off

| Role | Name | Date |
|---|---|---|
| Pipeline owner | | |
| Source system owner | | |
| Analytics engineering | | |
