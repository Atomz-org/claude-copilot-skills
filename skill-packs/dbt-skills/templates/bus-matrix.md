# Bus Matrix — <subject area or whole warehouse>

Business processes down the side, dimensions across the top. The cheapest artifact in the
scaffold and the one that prevents the most expensive mistake: two teams building the same
dimension with different keys, after which their stars can never be compared.

One matrix per subject area, or one for the whole warehouse if it fits. Reviewed whenever
a new business process is added — that is a new row, and every `X` in it is a claim that
an existing dimension already fits.

| Field | Value |
|---|---|
| Scope | |
| Owner | |
| Last reviewed | |

---

## The matrix

`X` = this process is measured by this dimension.

| Business process | Fact table | Date | Customer | Product | Location | Channel | Employee |
|---|---|---|---|---|---|---|---|
| Order placed | `fct_orders` | X | X | X | X | X | |
| Order shipped | `fct_shipments` | X | X | X | X | | X |
| Inventory measured | `fct_inventory_daily` | X | | X | X | | |
| Support contacted | `fct_support_cases` | X | X | | | X | X |

Read it two ways:

- **Down a column** — every process sharing a dimension must share **one** definition,
  one key, one table. This is the conformance check.
- **Across a row** — a process with one or two `X`s is a report, not a star schema. Say so
  and write the query instead of adding to the DAG.

## Conformed dimension register

Every dimension above, with the thing that makes conformance real: a single key and a
single owner.

| Dimension | Model | Key | Grain | Owner | Used by |
|---|---|---|---|---|---|
| Date | `dim_date` | `date_day` | one row per calendar day | core | all |
| Customer | `dim_customer` | `customer_id` | one row per customer, current state | | orders, shipments, support |

Conformed dimensions live in a shared domain (`models/marts/core/`), **not** inside the
first mart that needed them. A `dim_customer` under `marts/sales/` gets copied by the next
team within a quarter, and then there are two.

### Conformance conflicts

Where two processes use the "same" dimension differently. Every row here is a blocker
until resolved — build order depends on it.

| Dimension | Process A definition | Process B definition | Resolution | Owner | Status |
|---|---|---|---|---|---|
| Customer | account (finance) | person (marketing) | two dimensions, `dim_account` + `dim_person`, bridged | | open |

Resolutions are one of:

- **One dimension** — the definitions were the same thing described differently.
- **Two dimensions with distinct names** — genuinely different entities. Rename both; do
  not let either keep the ambiguous name.
- **One dimension + a bridge** — a hierarchy (person belongs to account).
- **One dimension + a role-playing alias** — same table, different meaning per join.

## Build order

Most-shared dimensions first, then the process with the most `X`s. Every later process
then reuses rather than defines.

| # | Build | Kind | Depends on | Reused by |
|---|---|---|---|---|
| 1 | `dim_date` | conformed dim | — | everything |
| 2 | `dim_customer` | conformed dim | staging | 3 processes |
| 3 | `fct_orders` | fact | dims 1–2 | — |

## Grain declarations

Restated here so the whole program is reviewable on one page.

| Fact table | Grain — one sentence | Fact type | Primary key |
|---|---|---|---|
| `fct_orders` | one row per order | transaction | `order_id` |
| `fct_inventory_daily` | one row per SKU per location per day | periodic snapshot | `inventory_daily_sk` |

Fact types: transaction / periodic snapshot / accumulating snapshot / factless. See
[references/dimensional_modeling.md](../references/dimensional_modeling.md).

## Coverage gaps

Processes the business cares about that have no fact table, and dimensions with no home.

| Gap | Impact | Owner | Planned |
|---|---|---|---|

---

## Review checklist

- [ ] Every process is a business **verb**, not a department, report, or dashboard.
- [ ] Every fact table has exactly one process and one grain.
- [ ] Every dimension column has one model, one key, one owner.
- [ ] Every conformance conflict is resolved or has a named owner and a date.
- [ ] Conformed dimensions live in the shared domain, not inside a single mart.
- [ ] Processes with one or two `X`s were challenged — report or star?
- [ ] Build order puts shared dimensions before the facts that use them.
