# Use-Case Spec — Enhanza Analytics

**Slug:** enhanza-analytics
**Requested by:** Enhanza Analytics team
**Author:** Analytics Engineering
**Date:** 2026-07-30 (revised 2026-07-31)
**Status:** Built, gaps open
**Verdict:** Build

## 1. The decision

Every product, finance, or operations analyst will consume governed business metrics from
the dbt/Cube stack based on trusted logic-layer models, instead of hand-built SQL over raw
API extracts.

For the multi-source dimension specifically: every **tenant onboarding a new ERP or POS
system** gets that system's data in the same unified facts as every other tenant, without a
change to the unified layer.

## 2. Consumer

| Item | Value |
|---|---|
| Consumer | app.enhanza.com, via the Cube semantic layer |
| Consumer type | app endpoint / semantic layer |
| Owner | Enhanza data and product teams |
| Freshness need | "as soon as the warehouse and dbt layers refresh" — **not a testable SLA; see §6** |
| Cube cache dependency | `latest_source_sync` → `get_latest_source_timestamp()` |

## 3. Grain

The use case spans layers, so the grain is declared per layer rather than once.

| Layer | Grain |
|---|---|
| Staging | one row per raw source record, per tenant |
| `<source>_bi` | one row per raw source record, per tenant |
| `<source>_erp_bi` | one row per source record, mapped to the common ERP schema |
| `erp_bi_<concept>` | one row per source record **per source system** — the union does not deduplicate |
| `logic_bi_*` | business grain, one per model, declared in `logic_bi/schema.yml` |

The unified grain is the one that surprises people: `erp_bi_dim_customers` holds one row
per customer *per connector*, not one row per customer. A tenant running both Fortnox and
Tripletex has the same real-world customer twice, keyed `1041-ds_fortnox` and
`1041-ds_tripletex`. Deduplication to a real party grain, if it is wanted, is a logic-layer
decision that has not been made. **[NEEDS INPUT]**

## 4. Sources

Nine connectors, ~170 raw tables, one BigQuery dataset per connector per tenant
(`<source>_api_<uid>`). Full state in [source-contract.md](source-contract.md);
per-connector coverage in [bus-matrix.md](bus-matrix.md).

| Connector | Currency | ERP concepts supplied |
|---|---|---|
| Fortnox | SEK | 30 — the reference implementation |
| Visma eAccounting | SEK | 10 |
| Visma e-conomic | DKK | 10 |
| Tripletex | NOK | 9 |
| SevenTime | SEK | 8 |
| Upsales | SEK | 6 |
| Xledger | NOK | 4 |
| Favrit | *(unstated)* | 1 |
| Tempo | *(unstated)* | 1 |

Which sources exist for a run is decided at compile time by `is_<source>_enabled` vars
against `global_configs('all_available_sources')`.

## 5. Model inventory

| Layer | Location | Count |
|---|---|---|
| Staging | `models/staging/<source>/` | ~200 |
| Source BI | `models/<source>_bi/`, `models/fortnox/*` | ~90 |
| Unified | `models/staging/erp/erp_bi_*.sql` | 30 |
| Logic | `models/logic_bi/` | 17 (15 contracted) |
| Demo | `models/demo/` | 42 |

## 6. Assumptions and the tests they become

| # | Assumption | If wrong | Test | State |
|---|---|---|---|---|
| 1 | The registry matches the models on disk | A connector silently contributes nothing, or a claim references a model that does not exist | `tests/test_enhanza_connector_registry.py` | ✅ **in place** |
| 2 | Every `erp_bi_*` union derives its sources from the registry | Onboarding drifts back to editing ~30 files by hand | same suite | ✅ **in place** |
| 3 | Each adapter's columns match every other adapter for that concept | `UNION ALL` transposes data between sources | compile-time failure, plus §4 of [deployment-runbook.md](deployment-runbook.md) | ⚠️ partial — only caught when two sources are enabled together |
| 4 | Every connector aliases its org id to `ErpOrgId` | Rows vanish from company-scoped queries with no error | `not_null` on `ErpOrgId` per adapter | ❌ **missing** |
| 5 | Foreign keys resolve to their dimensions | Orphan facts, silently under-reported | `relationships` tests | ❌ **missing** — 28 `foreign_key` constraints declared, none enforced by BigQuery |
| 6 | Sources are loaded before the dbt run | Marts rebuild on stale data | `freshness:` with `loaded_at_field` | ❌ **missing on all 17 sources** |
| 7 | Source-native ids are unique within a tenant dataset | Fan-out on every `<Column>ERP` join | `unique` on staging PKs | ❌ **missing** |
| 8 | Registry currencies match what each connector reports | Mis-valued revenue across the unified layer | `accepted_values` on `DefaultCurrency` | ❌ **missing** |

Rows 4–8 are the outstanding work. Rows 1–2 were added with the connector-extensibility
refactor and are what make row 3's failure mode loud instead of silent.

## 7. Quality gates

- Registry invariants green: `pytest tests/test_enhanza_connector_registry.py`
- `dbt build --select tag:<source>` green for the connector alone
- `dbt build --select tag:unified+` green with the connector **and** Fortnox enabled
- Contracts enforced on every `logic_bi` model a consumer reads
- Semantic metric validation against the logic layer

## 8. Verdict

**Build** — built and in use. The framing question that had not been answered when this
spec was first written was *"what does it cost to add the tenth connector?"* The answer was
82 hand-written blocks across 30 unified models, plus two registries that had already
drifted out of sync with the code. That is now one registry entry plus the connector's own
adapters, enforced by tests.

## 9. What the spec got wrong

Recorded per the definition of done in [docs/use-cases.md](../../../../docs/use-cases.md).

- **The original grain sentence was wrong.** "One row per business event per organization
  per reporting date" describes no table in the project. The real grains are per layer, and
  the unified layer's per-source duplication was not mentioned at all.
- **The original model inventory was invented.** `erp_unified_fact_sales`, `fact_sales`,
  `dim_customer`, and `dim_company` were listed as examples; the actual names are
  `erp_bi_*` and `logic_bi_*`. Rule 5 exists for this.
- **The README described a project that did not exist** — `local_run_project/`,
  `ported_package/`, and a five-order DuckDB sample with `stg_sales_orders.sql`. None of
  those paths were present. The "PASS=15 WARN=0" validation result referred to that absent
  project, not to the 430-model one.
- **Nobody had checked whether the connector registry matched the code.** Two defects had
  been sitting in it: `favrit` shipped without a registry entry, and `xledger` claimed a
  `fact_vouchers` adapter that was never written.
