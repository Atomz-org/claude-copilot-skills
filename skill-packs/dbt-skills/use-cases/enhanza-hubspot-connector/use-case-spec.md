# Use-Case Spec — HubSpot connector for Enhanza Analytics

**Slug:** `enhanza-hubspot-connector` · **Requested by:** Enhanza Analytics team · **Author:** Analytics Engineering · **Date:** 2026-07-31
**Status:** Draft
**Verdict:** **Narrowed build** — onboard as connector #10 into the existing `enhanza-analytics` use-case. This is not a standalone use-case.

> Every unknown is marked `[NEEDS INPUT]`. No HubSpot table name, row count, freshness SLA,
> or business definition is invented in this document.

## 0. Framing decisions already taken

Three questions were asked before design and answered by the requester:

| Question | Answer | What it rules out |
|---|---|---|
| Where does HubSpot land? | Connector into `enhanza-analytics` | A separate dbt project and a separate DAG |
| Who lands the raw data? | Enhanza's own ingestion job, `hubspot_api_<uid>` per tenant | `fivetran/dbt_hubspot` as an installed dependency |
| How far does it reach into the unified layer? | CRM-native **plus** `dim_customers` and `dim_company` adapters | Mapping deals into `fact_orders` / revenue |

### On the reference repository

[`fivetran/dbt_hubspot`](https://github.com/fivetran/dbt_hubspot) is a **reference, not a
dependency**. It cannot be installed here:

- it requires a Fivetran HubSpot connection and ships its own `sources.yml` against
  Fivetran's schema, which is not what `hubspot_api_<uid>` will contain;
- it is single-tenant — there is no `uid` var anywhere in its 147 models, and Enhanza builds
  every tenant from one project;
- its output models are named `hubspot__*`, which collides with neither of this project's
  two naming conventions (`hubspot_bi_*` source-aligned, `hubspot_erp_bi_*` adapter).

What it is genuinely useful for, and should be read for:

- **which HubSpot objects carry analytic weight** — deals, deal stages, contacts, companies,
  tickets, engagements (calls/meetings/notes/tasks), email campaigns and email events;
- **the deal-stage history pattern** — `hubspot__deal_stages` reconstructs stage transitions
  from a property-history table rather than from the deal record, which is the non-obvious
  part of modeling a CRM pipeline;
- **field-level naming** for HubSpot's property soup.

---

## 1. The decision

> Every **week**, the **Enhanza tenant's sales or revenue owner** will **see CRM pipeline
> and customer records alongside ERP-booked revenue in app.enhanza.com** based on
> **`hubspot_bi_*` models plus HubSpot's rows in `erp_bi_dim_customers`**, instead of
> **switching to the HubSpot UI, which no ERP-side number can be compared against.**

**What breaks today without this:** a tenant running HubSpot as its CRM and Fortnox (or any
other ERP) as its ledger has no place where both appear. There is no unified customer list
that includes prospects who have not yet been invoiced.

**Honest scope note.** The decision above is satisfied by the *presence* of HubSpot data in
the unified customer dimension. It does **not** require deal-to-invoice reconciliation, and
this spec deliberately excludes it — see §8.

---

## 2. Consumer

| Item | Value |
|---|---|
| Consumer (concrete) | app.enhanza.com, via the Cube semantic layer — same consumer as the parent use-case |
| Consumer type | app endpoint / semantic layer |
| Owner (person or channel) | **[NEEDS INPUT]** — Enhanza data and product teams named collectively in the parent spec; no individual owner recorded |
| Read cadence | **[NEEDS INPUT]** |
| Will appear in `exposures:` as | inherits the parent use-case's exposure; **no new exposure** — a connector does not add a consumer, it adds a source to existing ones |
| Needs an enforced contract? | **No new contract.** Contracts live on `logic_bi_*` (15 of 17 enforced). This connector adds no `logic_bi` model. |
| Freshness the consumer actually needs | **[NEEDS INPUT]** — parent spec records "as soon as the warehouse and dbt layers refresh", which it correctly flags as not a testable SLA |

The consumer is inherited, not new. That is what makes this a connector and not a use-case.

---

## 3. Grain

Declared per layer, matching the parent use-case's structure.

| Layer | Grain | Primary key |
|---|---|---|
| `hubspot_bi_<model>_staging` | one row per HubSpot object record, per tenant | HubSpot object `id`, unique **within a tenant dataset only** |
| `hubspot_bi_<model>` | same as staging | same |
| `hubspot_erp_bi_dim_customers` | one row per HubSpot **company**, per tenant | `CustomerId` = `OrgId \|\| '-' \|\| id` |
| `hubspot_erp_bi_dim_company` | one row per tenant HubSpot account/portal | `OrgId` |
| `erp_bi_dim_customers` | one row per customer **per source system** | `CustomerERP` = `CustomerId \|\| '-ds_hubspot'` |

### The grain that will surprise someone

`erp_bi_dim_customers` **does not deduplicate**. A tenant running HubSpot and Fortnox has the
same real-world customer twice:

```
1041-ds_fortnox    (from the ERP)
1041-ds_hubspot    (from the CRM)
```

This is by design and is inherited from the parent use-case, where it is already recorded as
an open `[NEEDS INPUT]`. Adding HubSpot makes it more visible but does not create it. Any
count of customers in the logic layer that does not group by `DataSource` will now be
inflated for HubSpot tenants.

| Item | Value |
|---|---|
| Can the same entity appear twice? | Yes — once per connector supplying it. Never twice within one connector. |
| On update — new row or overwrite? | Overwrite. No snapshot is proposed; HubSpot property history is **not** captured. |
| History needed, or current state only? | Current state only in this scope. Deal-stage history is where the CRM value actually is — see §8. |
| Timezone | **[NEEDS INPUT]** — HubSpot timestamps are UTC epoch millis; the project's convention is unrecorded |
| Currency | HubSpot deals carry a per-deal currency. `default_currency` in the registry is a **tenant fallback only** — see §6 assumption 6 |

---

## 4. Sources

Raw table names are **[NEEDS INPUT]**. Enhanza's own ingestion job defines them, and no
`hubspot_api` dataset exists yet — `grep -ril hubspot` across the repository returns nothing.
The objects below are what the reference package covers and are therefore what to *ask for*;
they are not a claim about what Enhanza will land.

| Object (expected) | Real table name | PK | Load cadence | `loaded_at_field` | Known dirtiness | Already staged? |
|---|---|---|---|---|---|---|
| Companies | `[NEEDS INPUT]` | `[NEEDS INPUT]` | `[NEEDS INPUT]` | `[NEEDS INPUT]` | HubSpot allows duplicate companies by design; merges leave tombstones | No |
| Contacts | `[NEEDS INPUT]` | `[NEEDS INPUT]` | `[NEEDS INPUT]` | `[NEEDS INPUT]` | Heavy PII; merge audit trail; opt-out flags | No |
| Deals | `[NEEDS INPUT]` | `[NEEDS INPUT]` | `[NEEDS INPUT]` | `[NEEDS INPUT]` | Deleted deals may soft-delete | No |
| Deal ↔ company / contact associations | `[NEEDS INPUT]` | `[NEEDS INPUT]` | `[NEEDS INPUT]` | `[NEEDS INPUT]` | N:M — **fan-out risk** | No |
| Deal property history | `[NEEDS INPUT]` | `[NEEDS INPUT]` | `[NEEDS INPUT]` | `[NEEDS INPUT]` | Required for stage history; often not synced | No |
| Tickets | `[NEEDS INPUT]` | `[NEEDS INPUT]` | `[NEEDS INPUT]` | `[NEEDS INPUT]` | Service Hub only | No |
| Engagements (calls/meetings/notes/tasks) | `[NEEDS INPUT]` | `[NEEDS INPUT]` | `[NEEDS INPUT]` | `[NEEDS INPUT]` | High volume | No |
| Account / portal details | `[NEEDS INPUT]` | `[NEEDS INPUT]` | `[NEEDS INPUT]` | `[NEEDS INPUT]` | Needed for `dim_company` — **may not be landed at all** | No |

**Warehouse location:** BigQuery, `<project>.hubspot_api_<uid>.<table>`, one dataset per
tenant. Source name in `sources.yml` is `hubspot_api`, **not** `hubspot` — every staging
model calls `source('<x>_api', ...)` and a bare `source('hubspot', ...)` will not resolve.

**Source of truth when HubSpot and the ERP disagree:** **[NEEDS INPUT] — and it is not
needed for this scope.** Because no revenue concept is mapped, there is nothing to
reconcile. The moment `fact_orders` is added (§8), this becomes a blocking business-policy
decision, and reversing it later means a rebuild.

**Measured arrival lag:** **[NEEDS INPUT]** — not needed; no incremental model is proposed.
All adapters are `ephemeral`, matching every existing connector.

---

## 5. Planned model inventory

| Layer | Path | Models |
|---|---|---|
| Source declaration | `dbt_project/models/sources.yml` | 1 `hubspot_api` block with `loaded_at_field` + `freshness` |
| Staging | `dbt_project/models/staging/hubspot/hubspot_bi_<model>_staging.sql` | one per landed raw table, columns enumerated |
| Source-aligned | `dbt_project/models/hubspot_bi/hubspot_bi_<model>.sql` | one-liners with `{{ auto_config() }}` |
| ERP adapters | `dbt_project/models/staging/hubspot/hubspot_erp_bi_{dim_customers,dim_company}.sql` | **exactly 2** |
| Unified layer | — | **zero changes.** `erp_union()` picks HubSpot up from the registry |
| Registry | `macros/config/global_configs.sql` | 1 entry, alphabetically between `fortnox` and `seventime` |
| Project config | `dbt_project.yml` | `is_hubspot_enabled: false` + connector tag |

### The two mappings that are easy to get wrong

**1. `dim_company` is the tenant's own company, not HubSpot "companies".**

Every existing adapter reads the tenant's *own* organisation record — `upsales_api.self`,
`visma_eaccounting_api.companysettings` — and emits three columns:

```sql
select
  cast(OrgId as string) as OrgId
  , OrgName
  , City
  , {{ add_erp_fields(columns=['OrgId']) }}
from main
```

The natural-looking mapping *HubSpot companies → `dim_company`* is **wrong** and would put
every customer organisation into a dimension that is supposed to hold one row per tenant.

**2. HubSpot companies → `dim_customers`; contacts have no home.**

`erp_bi_dim_customers` is organisation-shaped — it has `OrganisationNumber`, `VATNumber`,
`TermsOfPayment`. HubSpot **companies** fit it; HubSpot **contacts** are people and do not.
There is no `dim_contacts` in the unified layer, so contacts stay source-aligned in
`hubspot_bi_*`. Do not force them into `dim_customers`.

### The adapter contract

`hubspot_erp_bi_dim_customers` must emit **44 columns in the exact order** of
`fortnox_erp_bi_dim_customers.sql`, before `add_erp_fields()`. `shopify_erp_bi_dim_customers.sql`
is the closest precedent — a non-ERP source padding roughly two-thirds of the schema with
typed NULLs — and should be copied as the starting point.

`union_queries()` emits a **positional** `UNION ALL`. A column in the wrong position with a
compatible type unions cleanly and **silently transposes the data**. A missing column fails
loudly. The dangerous failure is the quiet one.

---

## 6. Assumptions and the tests they become

| # | Assumption | If wrong | Test it becomes | State |
|---|---|---|---|---|
| 1 | HubSpot company id is unique within a tenant dataset | Fan-out on every `CustomerERP` join | `unique` + `not_null` on the staging PK | to add |
| 2 | The adapter's 44 columns match Fortnox in count, order, and type | Data silently transposed across the union | `dbt build --select tag:unified+` with **both** `is_hubspot_enabled` and `is_fortnox_enabled` true | to add — the only test that catches it |
| 3 | HubSpot aliases its org id to `ErpOrgId` | Rows vanish from company-scoped queries with **no error** | `not_null` on `ErpOrgId` in the adapter | to add — parent spec records this as missing on **all** connectors |
| 4 | The registry claim matches the adapters on disk | A claimed concept contributes nothing, or `model_is_provided()` lies | `pytest tests/test_enhanza_connector_registry.py` | ✅ exists, must stay green |
| 5 | The source is loaded before the dbt run | Marts rebuild on stale CRM data | `freshness:` with `loaded_at_field` on `hubspot_api` | to add — parent spec records this as missing on all 17 existing sources; **ship HubSpot with it** |
| 6 | The registry currency matches what HubSpot reports | Mis-valued rows across the unified layer | `accepted_values` on `DefaultCurrency` | **omit `default_currency`** — see below |
| 7 | Contact PII is masked or excluded at staging | GDPR exposure in a multi-tenant warehouse | PII tag + a singular test asserting no raw email/phone past staging | to add — **new for this connector**, see §7 |
| 8 | Deal ↔ company associations are N:M | Duplicate deals per company after any join | `dbt_utils.unique_combination_of_columns` on the association staging model | to add |

**On assumption 6:** omit `default_currency` from the registry entry rather than guessing it.
`add_erp_fields()` emits a NULL `DefaultCurrency` for sources without one — the same
deliberate choice already made for `favrit` and `tempo`. HubSpot is not an accounting system
and has no tenant-level default currency; deals carry their own. A wrong currency silently
mis-values every row, and in this scope nothing needs one. **[NEEDS INPUT]** only if a
revenue concept is added later.

---

## 7. PII — the gate this connector adds that the others did not

Every existing connector is an ERP or POS: invoices, vouchers, articles. HubSpot is the first
**marketing/CRM** source, and contacts are personal data of *identifiable individuals who are
not the tenant's customers of record* — prospects, form-fills, newsletter subscribers.

Rule 17 binds: PII is declared at the source and tagged at every model that carries it, and
masking/hashing/exclusion happens **in staging, not in the mart**.

| Field class | Handling | Decision owner |
|---|---|---|
| Contact email, phone, first/last name | **[NEEDS INPUT]** — hash, mask, or exclude | Enhanza data protection owner **[NEEDS INPUT]** |
| Email event records (opens, clicks) | Behavioural data tied to an individual — in scope for GDPR | same |
| Opt-out / consent flags | Must survive to any model that drives outreach | same |

This is **not** a blocker for the `dim_customers` / `dim_company` adapters — those carry
company-level data. It **is** a blocker for landing `hubspot_bi_contacts` and any email-event
model. Recommend shipping the company-level adapters first and gating contacts behind this
decision.

---

## 8. Explicitly out of scope

Named so nobody assumes they were forgotten:

| Excluded | Why | What it would take |
|---|---|---|
| `fact_orders` / `fact_order_rows` from closed-won deals | HubSpot deal amount is pipeline value; ERP invoice total is booked revenue. They will disagree. | A written source-of-truth ruling **before** modeling — business policy, not engineering |
| Deal-stage history | Needs a property-history table that may not be synced, and a snapshot or event-grain fact | Confirm the source table exists; then an SCD decision per rule 12 |
| Dedup of a customer across HubSpot and an ERP | Inherited open question from the parent use-case; not created by this connector | A logic-layer party-resolution decision |
| CRM-native registry claims (`fact_opportunities`, `fact_activities`) | Upsales claims four such concepts that have **no union model and no adapter** — a latent version of the `xledger fact_vouchers` defect. Do not add a tenth connector to that pile. | Build `erp_bi_fact_opportunities` first, or leave CRM concepts source-aligned |

---

## 9. Quality gates

```bash
# 1. Registry invariants — no warehouse needed
python3 -m pytest tests/test_enhanza_connector_registry.py -q

# 2. Parse and compile with only HubSpot on
cd skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project
dbt parse --vars '{"uid": "<tenant>", "is_hubspot_enabled": true, "is_erp_enabled": true}'
dbt build --select tag:hubspot --vars '{"uid": "<tenant>", "is_hubspot_enabled": true}'

# 3. THE ONE THAT MATTERS — HubSpot unioned with Fortnox.
#    Adapter column drift is invisible until two sources are enabled together.
dbt build --select tag:unified+ \
  --vars '{"uid": "<tenant>", "is_hubspot_enabled": true, "is_fortnox_enabled": true, "is_erp_enabled": true}'

# 4. Freshness
dbt source freshness --select source:hubspot_api
```

`dbt build`, not `dbt run` then `dbt test`.

**Definition of done** is the checklist in
[enhanza-analytics/CONNECTORS.md](../enhanza-analytics/CONNECTORS.md#definition-of-done),
plus the row added to
[enhanza-analytics/source-contract.md](../enhanza-analytics/source-contract.md), plus §7's
PII decision recorded.

**Rollback path:** revert the registry entry — the connector becomes invisible to the unified
layer immediately, with no rebuild required, because every adapter is `ephemeral` and gated
on `is_hubspot_enabled`. No `--full-refresh` needed.

---

## 10. Verdict

**Narrowed build.**

Build: `hubspot_api` source with freshness, staging models per landed table, `hubspot_bi_*`
source-aligned models, and exactly two ERP adapters (`dim_customers` from HubSpot companies,
`dim_company` from the tenant account record), plus a registry entry claiming those two
concepts and nothing else.

Dropped, with reasons in §8: revenue mapping, deal-stage history, cross-source customer
dedup, and CRM-native registry claims.

Blocked until answered: the raw table names (§4) and the contact-PII handling (§7). Neither
blocks the company-level adapters; both block landing contacts.

**Why this is not a new use-case:** the decision, the consumer, and the exposure are all
inherited from `enhanza-analytics`. The Shopify connector shipped in `5683bba` without a
use-case spec — it updated `source-contract.md` and shipped models. This document exists to
record the framing decisions in §0 and the two mapping traps in §5, and should be folded into
`enhanza-analytics/source-contract.md` when the connector lands.
