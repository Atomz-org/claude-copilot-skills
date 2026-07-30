# Data Model Canvas — Enhanza multi-source ERP

The conceptual model behind the dbt project: what the entities are, how a concept survives
being sourced from nine different ERP systems, and where the keys come from.

Companion documents: [bus-matrix.md](bus-matrix.md) for coverage per connector,
[source-contract.md](source-contract.md) for what the sources guarantee, and
[CONNECTORS.md](CONNECTORS.md) for how to add the tenth system.

## The shape of the problem

This is not "a warehouse on a source system". It is one dbt project that builds a different
warehouse for every tenant, from whichever subset of nine ERP systems that tenant has
connected. Two consequences drive every modeling decision:

1. **A model must decide at compile time whether it exists.** A tenant on Tripletex alone
   has no Fortnox models at all. That is the `enabled` config, computed from
   `is_<source>_enabled` run vars via `source_is_enabled()` / `model_is_provided()`.
2. **A concept has nine possible definitions and must end with one.** Fortnox, Tripletex,
   and Visma each have a customer, with different columns, different id spaces, and
   different semantics. Conformance is the whole job.

## Layers

| Layer | Location | Grain | Conformance obligation |
|---|---|---|---|
| Raw | `<source>_api_<uid>` in BigQuery | source-native | none |
| Staging | `models/staging/<source>/*_staging.sql` | 1:1 with a raw table | rename, cast, coerce — nothing else |
| Source BI | `models/<source>_bi/` | 1:1 with staging | user-facing per source; no conformance |
| ERP adapter | `models/staging/<source>/<source>_erp_bi_<concept>.sql` | one row per source record | **must match every other source's adapter for the concept, column for column** |
| Unified | `models/staging/erp/erp_bi_<concept>.sql` | one row per record per source | union across enabled sources, driven by the registry |
| Logic | `models/logic_bi/` | business grain | 17 models, 15 with enforced contracts |
| Semantic | Cube | metric | consumed by app.enhanza.com |

The Source BI layer is where `{{ auto_config() }}` lives — a one-line model whose entire
body the macro generates, emitting both the `config()` and
`select * from {{ ref(model_name + '_staging') }}`. It keeps ~250 files to one line each,
at the cost of making the lineage invisible to static analysis.

## Entities

### Conformance anchor: organization

`dim_company` / `logic_bi_dim_organisations` is the tenant-and-legal-entity dimension that
nearly every fact joins to. Its conformed key is **`ErpOrgId`**, aliased from each source's
native column by `global_configs → erp_columns_rename_and_cast_list → dim_company`:

```
'ErpOrgId|FortnoxId|SeventimeId|TripletexId|VismaId|UpsalesId' : None
```

| Property | Value |
|---|---|
| Grain | one row per legal entity per source system |
| Conformed key | `ErpOrgId` |
| Sources | Fortnox, SevenTime, Tripletex, Upsales, Visma eAccounting, Visma e-conomic |
| SCD type | Type 1 — overwritten. **[NEEDS INPUT]** whether org attribute history matters |

A connector added without its own alias in that list produces rows with a null `ErpOrgId`.
Nothing fails; the rows simply stop appearing in company-scoped queries.

### Cross-source key construction

Two tenants' Fortnox and Tripletex both have a customer with id `1041`. The union would
collide them. `add_erp_fields()` prevents that by emitting, for every column ending in `Id`
that is not in `global_configs('id_erp_exceptions')`:

```sql
CustomerId || '-ds_fortnox' as CustomerIdERP
```

| Property | Value |
|---|---|
| Surrogate key | `<Column>ERP = <Column>Id || '-ds_<source>'` |
| Stability | derived from the source id and the connector name only — neither mutates, so the key is safe under rule 9 |
| Exceptions | `id_erp_exceptions` — BAS account classes, `ErpOrgId`, and other already-global ids |
| Also emitted | `DataSource` (display name) and `DefaultCurrency` (registry, NULL when unstated) |

`DefaultCurrency` being NULL for Favrit and Tempo is deliberate — see
[source-contract.md](source-contract.md). A guessed currency mis-values every row silently;
a NULL fails a `not_null` test the moment one is added.

### Conformed dimensions

Eleven, listed with per-source coverage in [bus-matrix.md](bus-matrix.md):
`dim_accounts`, `dim_articles`, `dim_company`, `dim_cost_centers`, `dim_customers`,
`dim_employees`, `dim_financial_years`, `dim_projects`, `dim_stockpoints`,
`dim_supplier_invoice_files`, `dim_suppliers`.

`logic_bi_dim_customers_suppliers` conforms customers and suppliers into one party
dimension — the same organization is frequently both, and keeping them apart double-counts
the relationship.

### Business processes

Nineteen unified facts. Only seven span more than one source today; the other twelve are
Fortnox-only facts sitting behind a union that makes the second source cheap to add. The
distinction matters when reading a metric: a `fact_*` name is not evidence of multi-tenant
coverage.

The logic layer reduces these to seven business-grain facts: `logic_bi_fact_sales`,
`fact_invoices`, `fact_balance`, `fact_profit_loss`, `fact_salaries`,
`fact_time_reporting`, `fact_warehouses`.

`logic_bi_fact_sales` is the widest model in the project and the one to read first — it
references eight `erp_bi_*` models, the `categories_x_mapping` bridge, and two Upsales
models directly. Those last two are a layer violation worth noting: a mart reaching past
the unified layer into a single connector's staging models couples the mart to Upsales,
and the same logic will need repeating for the next CRM connector.

## Relationships and optionality

| Relationship | Cardinality | Optionality | Consequence |
|---|---|---|---|
| organization → invoice | 1:N | invoice's org is mandatory | inner join; a null `ErpOrgId` silently drops the row |
| customer → invoice | 1:N | optional (cash sales) | left join; needs an unknown member row **[NEEDS INPUT: does one exist?]** |
| invoice → invoice row | 1:N | rows optional | left join; header-grain measures must not be summed at row grain |
| order → order row | 1:N | **broken for Favrit** — rows exist with no header | see [bus-matrix.md](bus-matrix.md) |
| article → invoice row | 1:N | optional (free-text lines) | left join |
| category ↔ article | N:M | optional | resolved by the `categories_x_mapping` bridge |

## Keys and testing state

| Item | State |
|---|---|
| Contracts enforced | 15 of 17 logic_bi models |
| `primary_key` constraints | declared on the contracted models |
| `foreign_key` constraints | 28 declared in `logic_bi/schema.yml` |
| `relationships` tests | **zero** |

The last row is the gap. BigQuery does not enforce `foreign_key` constraints —
`warn_unenforced: False` in the schema says so explicitly — so the 28 declarations are
documentation that no build ever checks. A dbt `relationships` test is what actually
verifies the join, and none exist. That is the single highest-value test to add: every
unified fact's `ErpOrgId` and `CustomerIdERP` against its dimension.

## Open modeling decisions

| Decision | Status |
|---|---|
| SCD strategy for any dimension | none chosen; no snapshots on any connector source. Mutable source values are being overwritten today. |
| Unknown member rows for optional FKs | **[NEEDS INPUT]** |
| `dim_voucher_series` conformance | supplied by two sources with no union model |
| `fact_orders` for Favrit | order rows with no header |
| Currency normalization | `DefaultCurrency` is a per-source constant, not a transaction rate. Any cross-currency measure needs a rate table. **[NEEDS INPUT]** |
