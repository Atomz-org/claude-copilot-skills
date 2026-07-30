# Deployment Runbook — Enhanza connector and layer changes

For any change to the connector registry, the unified layer, or a contracted `logic_bi`
model. A change with no rollback path is not a release.

## Risk tiers

| Tier | Change | Blast radius |
|---|---|---|
| Low | a new `<source>_bi_*` model, a new source-aligned staging model | that source's tenants only; nothing unified depends on it |
| Medium | a new connector — registry entry, adapters, `sources.yml` | every `erp_bi_*` union the connector claims, for tenants with it enabled |
| **High** | editing an existing adapter's column list, `erp_columns_rename_and_cast_list`, `add_erp_fields()`, `erp_union()`, or a contracted `logic_bi` model | every tenant, every layer above the change |

`erp_union()` and `add_erp_fields()` are read by every unified model. Treat any edit to
either as high risk regardless of how small it looks.

## Before merge

```bash
# 1. Registry invariants — no warehouse needed, runs in CI
python3 -m pytest tests/test_enhanza_connector_registry.py -q

cd skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project

# 2. Parse with the changed connector alone
dbt parse --vars '{"uid": "<tenant>", "is_<source>_enabled": true, "is_erp_enabled": true}'

# 3. Build the connector in isolation
dbt build --select tag:<source> --vars '{"uid": "<tenant>", "is_<source>_enabled": true}'

# 4. Build it unioned with Fortnox — this is what catches adapter column drift,
#    because a UNION ALL of one source never exercises the column contract
dbt build --select tag:unified+ \
  --vars '{"uid": "<tenant>", "is_<source>_enabled": true, "is_fortnox_enabled": true, "is_erp_enabled": true}'

# 5. Slim CI: only what changed and its children, against the production manifest
dbt build --select state:modified+ --defer --state ./artifacts/prod
```

Step 4 is not optional for a connector change. A `UNION ALL` with a single branch compiles
whatever columns that branch has; the contract is only tested when a second source is on.

`dbt build`, never `dbt run` then `dbt test` — build stops dependents when a test fails
instead of propagating bad data through the DAG first.

## Multi-tenant verification

One project builds every tenant, so "it works" means it works for the enabled combinations,
not for yours. At minimum verify:

| Combination | Why |
|---|---|
| the new connector alone | a tenant that has only this system must get a coherent warehouse |
| the new connector + Fortnox | exercises the union column contract |
| Fortnox alone, unchanged | proves the change did not alter existing tenants |
| all connectors on | catches registry-order and duplicate-key problems |

The third is the regression check that matters most. Compare row counts and
`sum(<measure>)` per `erp_bi_*` model before and after; a registry change that alters an
existing tenant's numbers is a defect, not a feature.

## Rollback

| Change | Rollback |
|---|---|
| New connector | set `is_<source>_enabled: false` and rebuild — no code revert needed, because the registry gates everything. This is the reason the registry pattern is worth the refactor. |
| Registry edit (`included_models`, currency, alias) | revert the commit and rebuild `tag:unified+`. Views rebuild in place; no `--full-refresh` needed for the ephemeral and view layers. |
| Contracted `logic_bi` change | revert the commit, then `dbt build --select logic_bi_<model>+ --full-refresh`. State the full-refresh cost in the PR **before** merging. |
| `add_erp_fields()` / `erp_union()` edit | revert and rebuild every enabled tenant. There is no partial rollback — these macros are compiled into every unified model. |

Because the ERP adapters are `materialized='ephemeral'` and the BI layer defaults to
`view`, most of this project rebuilds without a `--full-refresh`. Confirm the
materialization of anything you are rolling back before promising a cheap revert.

## Post-deploy verification

```bash
# Freshness — currently a no-op: no source declares loaded_at_field. See source-contract.md.
dbt source freshness

# Confirm the new connector actually contributed rows
# (DataSource is emitted by add_erp_fields from the registry display name)
select DataSource, count(*) from <project>.<dataset>.erp_bi_fact_invoices group by 1;

# Confirm no rows lost their organization key — the silent failure mode for a new connector
select count(*) from <project>.<dataset>.erp_bi_dim_company where ErpOrgId is null;
```

The second query is the one to run first after adding a connector. A connector missing its
alias in `erp_columns_rename_and_cast_list → dim_company` produces rows that pass every
existing test and then vanish from every company-scoped query.

## Owner and sign-off

| Item | Value |
|---|---|
| Change owner | **[NEEDS INPUT]** |
| Approver for high-risk tier | **[NEEDS INPUT]** |
| Consumer to notify | app.enhanza.com / Cube semantic layer owners |
| Cube `refreshKey` dependency | `latest_source_sync`, via `get_latest_source_timestamp()` — now registry-driven, so a new connector is included automatically |
