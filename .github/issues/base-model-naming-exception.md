`connector_alignment_check.py` reports:

```
[warn ] naming: `fortnox_base_v2_invoices` is not a staging model (`fortnox_bi_<table>_staging`)
        nor an adapter (`fortnox_erp_bi_<concept>`)
```

### Why this is open rather than fixed

The model is correct as written. `base_` is a recognised dbt convention for a pre-staging
model, and this one earns it: it applies `fortnox_start_year_filter(...)` **once** for the
five staging models that read it, instead of each repeating the filter.

```
packages/fortnox/models/staging/fortnox_bi_dim_customers_staging.sql
packages/fortnox/models/staging/fortnox_bi_dim_suppliers_staging.sql
packages/fortnox/models/staging/fortnox_bi_fact_invoice_rows_staging.sql
packages/fortnox/models/staging/fortnox_bi_fact_invoices_staging.sql
packages/fortnox/models/staging/fortnox_bi_fact_vouchers_staging.sql
```

Renaming it to satisfy the heuristic is six files of churn for no behavioural change, and it
would make the shared-filter intent less obvious, not more.

The checker learns conventions from the project's busiest connector
(`new_connector.detect()`), so it only knows the two shapes that connector uses. A
legitimate third shape is invisible to it.

### Options

1. **Accept permanently.** Teach the checker a `base_` prefix as a third recognised shape,
   so it stops reporting and the convention becomes explicit. Risk: it stops flagging models
   that are genuinely misnamed with a `base_` prefix.
2. **Accept per-model.** Add a small allowlist (e.g. `.alignment-ignore`) so exceptions are
   named and reviewable rather than silently tolerated.
3. **Rename** to `fortnox_bi_v2_invoices_staging` and update the five referencing models.

Recommended: **2** — an exception that is written down is auditable; one absorbed into the
rule is not. It is currently recorded as an accepted warning in `CLAUDE.md`, which is
documentation rather than enforcement.

### Done when

The finding either stops being reported, or is recorded somewhere the checker itself reads.
