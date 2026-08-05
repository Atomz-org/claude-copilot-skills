Every source block in `enhanza-analytics` declares tables and (since the column-contract
work) columns, but **none declares `loaded_at_field` or a `freshness:` block**.
`connector_alignment_check.py` reports this as `no-freshness` for 8 connectors:

```
8 [warn ] no-freshness: source block has no `loaded_at_field`; freshness is an undocumented SLA
```

### Why this is open rather than fixed

The freshness SLA is a fact about each upstream pipeline — how often that connector's
loader actually lands data — not a number anyone can derive from this repository.
In `.claude/rules/analytics-engineering-rules.md`, rule 14 requires it and rule 5 forbids
inventing it. A guessed `warn_after` is worse than none: it either fires constantly and gets
muted, or never fires and reads as a working SLA.

### What is needed

Per connector, from whoever owns its ingestion:

| | |
|---|---|
| `loaded_at_field` | the column carrying the load timestamp (e.g. `enz_sync_ts`) |
| `warn_after` | how late is unusual |
| `error_after` | how late means the data is not usable |

### Shape

```yaml
  - name: fortnox_api
    loaded_at_field: enz_sync_ts
    freshness:
      warn_after: {count: 6, period: hour}
      error_after: {count: 24, period: hour}
```

Affected: fortnox, seventime, tempo, tripletex, upsales, visma_eaccounting, visma_economic,
and the root `models/sources.yml` block.

### Done when

`python3 scripts/connector_alignment_check.py --use-case enhanza-analytics --manifest <path>`
reports 0 `no-freshness` warnings, and `dbt source freshness` runs against a real target.
