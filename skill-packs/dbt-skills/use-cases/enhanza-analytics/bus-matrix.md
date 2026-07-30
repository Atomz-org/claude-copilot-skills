# Bus Matrix — Enhanza unified ERP layer

Business processes down the side, conformed dimensions across the top, and — because this
project is multi-tenant across nine source systems — a second matrix showing which
connector actually supplies each one.

Both matrices are **generated from the project, not asserted**: a ✅ means a
`<source>_erp_bi_<concept>.sql` adapter exists on disk *and*
`global_configs('all_available_sources')` claims it. `tests/test_enhanza_connector_registry.py`
fails if those two ever disagree. Regenerate after adding a connector:

```bash
python3 -c "
import sys; sys.path.insert(0,'tests')
from test_enhanza_connector_registry import REGISTRY, UNION_CONCEPTS, ADAPTERS
..."   # see the test module for the accessors
```

## Conformed dimensions by source

| Conformed dimension | favrit | fortnox | seventime | tempo | tripletex | upsales | visma_ea | visma_ec | xledger |
|---|---|---|---|---|---|---|---|---|---|
| `dim_accounts` | | ✅ | | | ✅ | | ✅ | ✅ | ✅ |
| `dim_articles` | | ✅ | ✅ | | | ✅ | ✅ | ✅ | |
| `dim_company` | | ✅ | ✅ | | ✅ | ✅ | ✅ | ✅ | |
| `dim_cost_centers` | | ✅ | | | ✅ | | ✅ | | ✅ |
| `dim_customers` | | ✅ | ✅ | | ✅ | ✅ | ✅ | ✅ | |
| `dim_employees` | | ✅ | | | | | | | |
| `dim_financial_years` | | ✅ | ✅ | | ✅ | ✅ | ✅ | ✅ | ✅ |
| `dim_projects` | | ✅ | | | ✅ | | ✅ | | ✅ |
| `dim_stockpoints` | | ✅ | | | | | | | |
| `dim_supplier_invoice_files` | | ✅ | | | | | | | |
| `dim_suppliers` | | ✅ | | | ✅ | | | ✅ | |

`dim_company` is the conformance anchor. It is the tenant/organization dimension nearly
every fact joins to, and `fortnox_bi_dim_company` is the highest-degree node in the whole
repository. Its surrogate key is `ErpOrgId`, aliased in
`global_configs('erp_columns_rename_and_cast_list')` from each source's native id column
(`FortnoxId`, `SeventimeId`, `TripletexId`, `VismaId`, `UpsalesId`). **A new connector must
add its own id column to that alias list**, or its rows arrive with a null `ErpOrgId` and
disappear from every company-scoped query without failing a test.

## Business processes by source

| Business process (fact) | favrit | fortnox | seventime | tempo | tripletex | upsales | visma_ea | visma_ec | xledger |
|---|---|---|---|---|---|---|---|---|---|
| `fact_absence_transactions` | | ✅ | | | | | | | |
| `fact_attendance_transactions` | | ✅ | | | | | | | |
| `fact_budgets` | | ✅ | | | | | | | |
| `fact_employee_wages` | | ✅ | | | | | | | |
| `fact_incoming_goods` | | ✅ | | | | | | | |
| `fact_invoice_payments` | | ✅ | | | | | | | |
| `fact_invoice_rows` | | ✅ | ✅ | | | | ✅ | ✅ | |
| `fact_invoices` | | ✅ | ✅ | | ✅ | | ✅ | ✅ | |
| `fact_offers` | | ✅ | ✅ | | | | | | |
| `fact_order_rows` | ✅ | ✅ | | | | ✅ | | | |
| `fact_orders` | | ✅ | | | | ✅ | | ✅ | |
| `fact_purchase_orders` | | ✅ | | | | | | | |
| `fact_salary_transactions` | | ✅ | | | | | | | |
| `fact_stockbalance` | | ✅ | | | | | | | |
| `fact_stocktakings` | | ✅ | | | | | | | |
| `fact_supplier_invoice_rows` | | ✅ | | | | | | | |
| `fact_supplier_invoices` | | ✅ | | | | | | | |
| `fact_time_reporting_registrations` | | ✅ | ✅ | ✅ | | | | | |
| `fact_vouchers` | | ✅ | | | ✅ | | ✅ | ✅ | |

## What this says about coverage

**Fortnox is the reference implementation.** It supplies all 11 conformed dimensions and
all 19 business processes; every other connector is a subset. When adding Spiris, NetSuite,
or Shopify, the Fortnox adapter for a concept is the column contract to match — start from
`models/staging/fortnox/fortnox_erp_bi_<concept>.sql`.

**Fifteen of nineteen processes are Fortnox-only.** They are not really "unified" yet; they
are single-source facts that happen to sit behind a union. That is fine — the union is what
makes the second source cheap — but do not read a `fact_*` name as evidence that a metric
covers every tenant. Only `fact_invoices`, `fact_invoice_rows`, `fact_vouchers`,
`fact_orders`, `fact_order_rows`, `fact_offers`, and `fact_time_reporting_registrations`
span more than one source today.

**Two gaps worth a decision:**

| Gap | Consequence |
|---|---|
| `dim_voucher_series` is supplied by Fortnox *and* Tripletex but has no `erp_bi_dim_voucher_series` union model | Two sources define the same dimension with no conformed table, so a voucher-series analysis cannot span them. **[NEEDS INPUT]** — build the union, or state that it is intentionally source-scoped. |
| Favrit supplies `fact_order_rows` but not `fact_orders` | Order lines with no order header for Favrit tenants. Any measure computed at header grain silently excludes Favrit. **[NEEDS INPUT]** |

## Source-aligned models outside the unified layer

These are exposed per source and never unioned, so they carry no conformance obligation.
Listed so a reader does not mistake their absence from the matrices for a gap.

| Source | Source-aligned only |
|---|---|
| favrit | `dim_accounting`, `dim_ratings`, `dim_user_locations` |
| fortnox | `dim_assets_types`, `dim_bundle_articles`, `dim_expenses`, `dim_labels`, `dim_meta_data`, `dim_pricelists`, `dim_prices`, `dim_supplier_items`, `dim_voucher_series`, `fact_asset_rows`, `fact_assets`, `fact_contract_rows`, `fact_contracts`, `fact_employee_schedules`, `fact_invoice_accruals`, `fact_locked_period`, `fact_offer_rows`, `fact_production_orders`, `fact_rolling_sum`, `fact_supplier_invoice_accruals` |
| seventime | `fact_work_orders` |
| tripletex | `dim_voucher_series` |
| upsales | `fact_activities`, `fact_appointments`, `fact_opportunities`, `fact_opportunity_rows` |
