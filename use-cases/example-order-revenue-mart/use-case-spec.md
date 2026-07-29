# Use-Case Spec — Order Revenue Mart

**Slug:** `example-order-revenue-mart` · **Requested by:** Priya Raman (Finance)
**Author:** Analytics Engineering · **Date:** 2026-07-20
**Status:** Approved · **Verdict:** Build

> This is a worked example on synthetic data. It exists to calibrate the expected level of
> specificity. Note that `[NEEDS INPUT]` markers survive into an approved spec — they are
> tracked gaps, not blockers.

---

## 1. The decision

> Every **Monday morning**, the **Finance Analytics lead** will **reallocate the weekly
> regional marketing budget** based on **trailing-4-week revenue and order count per
> region**, instead of **a manually maintained spreadsheet rebuilt from three CSV exports**.

**What breaks today without this:** the spreadsheet takes ~3 hours each Monday, and it has
disagreed with the NetSuite ledger twice this quarter. The second disagreement (2026-05-11,
1.8% overstated) caused a budget decision that was reversed the following week.

---

## 2. Consumer

| Item | Value |
|---|---|
| Consumer | `https://bi.example.com/dashboards/42` — Executive Revenue Dashboard |
| Consumer type | dashboard |
| Owner | Priya Raman, priya@example.com |
| Read cadence | Monday 08:00 UTC, plus ad hoc during month-end close |
| `exposures:` entry | `executive_revenue_dashboard`, maturity `high` |
| Needs an enforced contract? | **Yes** — the BI dataset is maintained by a different team and cannot be fixed in the same PR |
| Freshness the consumer needs | data through Sunday 23:59 UTC, available by Monday 06:00 UTC |

---

## 3. Grain

> One row per **order**, at its **current status**.

| Item | Value |
|---|---|
| Primary key | `order_id` |
| Can the same entity appear twice? | No. A status change updates the row rather than adding one |
| On update — new row or overwrite? | Overwrite, via `merge` on `order_id` |
| History needed? | **Not for this use case.** Finance asked for current state. Status history is captured separately in `shopify_orders_snapshot` for a future cohort analysis |
| Timezone | UTC everywhere. Shopify emits UTC; BI renders local |
| Currency | USD. Multi-currency orders are converted at the order-date rate upstream |

**Pressure test:** Finance initially asked for "orders by week". That is ambiguous between
one row per order and one row per order per status change. Confirmed on 2026-07-21 that they
want current status only — a refunded order should appear once, as refunded, not twice.

---

## 4. Sources

| Source table | Real name | PK | Load cadence | `loaded_at_field` | Known dirtiness | Already staged? |
|---|---|---|---|---|---|---|
| Shopify orders | `raw.shopify.orders` | `id` | Fivetran, ~15 min | `_fivetran_synced` | soft deletes via `_fivetran_deleted`; `test = true` rows | No |
| Shopify order lines | `raw.shopify.order_lines` | `id` | Fivetran, ~15 min | `_fivetran_synced` | orders occasionally have zero lines (upstream defect, ~0.3%) | No |
| Shopify customers | `raw.shopify.customers` | `id` | Fivetran, ~15 min | `_fivetran_synced` | mutable — plan tier overwrites | No |
| NetSuite postings | `raw.netsuite.revenue_postings` | `posting_id` | nightly batch 02:00 UTC | `[NEEDS INPUT]` — the connector's load column is undocumented; asked Data Platform 2026-07-22 | month-end adjusting entries post up to 5 days late | No |

**Source of truth when Shopify and NetSuite disagree:** **NetSuite wins** for reported
revenue; Shopify is the operational record. Decided by Priya Raman, 2026-07-21. This mart
reports the Shopify figure and reconciles against NetSuite with a 0.5% tolerance test —
a breach is a signal to investigate, not to silently adjust.

### Measured arrival lag — Shopify orders

```sql
select
    percentile_cont(0.50) within group (order by datediff('hour', created_at, _fivetran_synced)) as p50_h,
    percentile_cont(0.99) within group (order by datediff('hour', created_at, _fivetran_synced)) as p99_h,
    max(datediff('hour', created_at, _fivetran_synced))                                          as max_h
from raw.shopify.orders
where _fivetran_synced >= dateadd(day, -30, current_date)
```

| Metric | Value | Measured |
|---|---|---|
| p50 lag | 0.3 h | 2026-07-21 |
| p99 lag | 38 h | 2026-07-21 |
| max observed | 61 h | 2026-07-21 |
| **Chosen lookback** | **3 days** (p99 × 2, rounded up) | re-measure 2026-10 |

The p99 of 38h is driven by orders placed during Fivetran's Sunday maintenance window.

---

## 5. Model scope

| Layer | Model | Materialization | Grain |
|---|---|---|---|
| Source | `shopify.orders`, `.order_lines`, `.customers` | — | as landed |
| Staging | `stg_shopify__orders` | view | 1:1 with source |
| Staging | `stg_shopify__order_lines` | view | 1:1 with source |
| Staging | `stg_shopify__customers` | view | 1:1 with source |
| Intermediate | `int_orders_with_line_totals` | ephemeral | one row per non-test order |
| Mart | `dim_customers` | table | one row per customer, current state |
| Mart | `fct_orders` | **incremental** | one row per order |
| Mart | `metricflow_time_spine` | table | one row per day |

**Reused existing models:** none — this is the first Shopify domain in the project.

**Materialization reasoning:**

- `fct_orders` is incremental because a measured full refresh takes 9m14s and runs hourly.
  Incremental runs take ~35s. The trade is accepted; the full-refresh invariant is verified
  monthly via `analyses/audit_fct_orders_incremental.sql`.
- `dim_customers` is a table: 180k rows, rebuilds in 8s, and three downstream joins against
  it are measurably faster than against a view.
- `int_orders_with_line_totals` is ephemeral because exactly one model consumes it. If a
  second consumer appears, it becomes a view.

---

## 6. Assumptions and the tests they become

| # | Assumption | What breaks if wrong | How we find out | Test |
|---|---|---|---|---|
| 1 | Every non-guest order has a customer in `dim_customers` | Revenue by region silently loses rows | orphan `customer_id` | `relationships` with `where: customer_id is not null` |
| 2 | `order_status` is one of six values | The BI status filter drops orders into no bucket | a new Shopify enum | `accepted_values` incl. `unknown` |
| 3 | Internal test accounts are marked `test = true` | Test orders inflate revenue | test-account revenue appears | filter in staging + `is_test_order` excluded in intermediate |
| 4 | Orders arrive within 3 days of being placed | Late orders are permanently missing from the mart | monthly full-refresh comparison | `dbt_utils.recency` on the source + the audit analysis |
| 5 | Shopify revenue reconciles to NetSuite within 0.5% | The exec dashboard contradicts the ledger — this already happened twice | daily reconciliation | singular test, `nightly` tag |
| 6 | `net_line_amount_usd` never exceeds `order_amount_usd` | A discount sign error inverts margins | invariant violated | `dbt_utils.expression_is_true`, severity `warn` |
| 7 | ~3% of orders are guest checkouts with a null `customer_id` | If this jumps, the region breakdown becomes unrepresentative | null proportion drifts | `dbt_utils.not_null_proportion` at `at_least: 0.90` |

---

## 7. Quality gates

| Gate | Rule | Severity | Owner |
|---|---|---|---|
| Source freshness (orders) | warn 1h / error 6h | error | Data Platform |
| Source freshness (customers) | warn 12h / error 24h | error | Data Platform |
| Primary key | `unique` + `not_null` on `order_id` | error | Analytics Eng |
| Referential integrity | `relationships` on `customer_id` | error | Analytics Eng |
| Domain | `accepted_values` on `order_status` | error | Analytics Eng |
| Range | `order_amount_usd >= 0` | **warn** — negatives occur legitimately during refund reprocessing | Analytics Eng |
| Reconciliation | vs NetSuite, 0.5% tolerance | error, `nightly` | Finance |
| Logic correctness | unit tests on `int_orders_with_line_totals` | error | Analytics Eng |

---

## 8. Feasibility verdict

**Verdict: Build.**

**Evidence:** decision sentence complete with a named role and cadence; consumer is a real
dashboard with an owner; grain confirmed with the requester; all four sources exist with
known PKs; arrival lag measured. Estimated 3 days of work.

**Open gap:** the NetSuite `loaded_at_field` is unknown, so `stg_netsuite__revenue_postings`
ships without a freshness block and the reconciliation test runs on a nightly tag rather
than gating the build. Tracked with Data Platform; does not block phase 1.

---

## 9. Delivery

| Item | Value |
|---|---|
| Build command | `dbt build --select +fct_orders` |
| CI selector | `state:modified+ --defer --state prod/` |
| Estimated build time | 35s incremental, 9m14s full refresh |
| Rollback | revert the commit; `fct_orders` needs `--full-refresh` (9m14s, ~$1.80) |
| Owner group | `finance` — finance-data@example.com |
| Alert routing | `#finance-data` for test failures; `#data-platform` for freshness |

| Phase | Ships | Depends on |
|---|---|---|
| 1 | staging, intermediate, `dim_customers`, `fct_orders`, tests, exposure | — |
| 2 | semantic models and the `revenue` / `order_count` / `average_order_value` metrics | phase 1 |
| 3 | NetSuite reconciliation test gating the build | NetSuite `loaded_at_field` from Data Platform |

---

## 10. Approval

| Role | Name | Date | Decision |
|---|---|---|---|
| Analytics engineering | A. Engineer | 2026-07-21 | Approved |
| Data/business owner | Priya Raman | 2026-07-21 | Approved |
| Consumer owner | Priya Raman | 2026-07-21 | Approved |

---

## 11. Outcome

| Item | Value |
|---|---|
| Shipped on | 2026-07-24 (phase 1) |
| Actual build time | 41s incremental — slightly over the estimate |
| Is the consumer using it? | Yes; the spreadsheet was retired 2026-07-28 |
| What we got wrong in this spec | We assumed every order had at least one line item. ~0.3% do not, which made `line_item_count` null rather than zero until `coalesce` was added. Assumption 8 should have existed |
| Tests added after an incident | `dbt_utils.accepted_range` on `line_item_count` with `min_value: 0` |
