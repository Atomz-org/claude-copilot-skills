# Use-Case Spec — <name>

**Slug:** `<slug>` · **Requested by:** <name> · **Author:** <name> · **Date:** <YYYY-MM-DD>
**Status:** Draft | Approved | Rejected
**Verdict:** Build | Narrowed build | Not a dbt problem | Blocked

> Every unknown is marked `[NEEDS INPUT]`. Never invent a table name, a row count, a
> freshness SLA, or a business definition — design around the gap and name who can fill it.

---

## 1. The decision

> Every `<cadence>`, `<role>` will `<action>` based on `<output>`, instead of
> `<what they do today>`.

If this sentence cannot be completed:

| Situation | The right response |
|---|---|
| Nobody acts on it | Reporting request — write the query, do not add a mart |
| Somebody looks but never acts | Ask what would change their mind. If nothing, decline |
| The action already happens without this | The value is speed or confidence — size that, or drop it |
| Genuinely exploratory | Scratch query. Promote to a model if it is asked twice |

**What breaks today without this:**

---

## 2. Consumer

| Item | Value |
|---|---|
| Consumer (concrete — a URL, a model, a sync) | |
| Consumer type | dashboard / notebook / model / reverse-ETL / ML |
| Owner (person or channel) | |
| Read cadence | |
| Will appear in `exposures:` as | |
| Needs an enforced contract? | yes / no — and why |
| Freshness the consumer actually needs | |

**A mart with no named consumer does not get built.**

---

## 3. Grain

> One row per `<entity>` per `<period>` per `<qualifier>`.

| Item | Value |
|---|---|
| Primary key | `<column>`, or a surrogate over `[<cols>]` |
| Can the same entity appear twice? | when, and why |
| On update — new row or overwrite? | |
| History needed, or current state only? | history ⇒ snapshot or event-grain fact |
| Timezone for all date/time columns | |
| Currency / unit convention | |

Pressure test: is this "one row per order" or "one row per order per status change"?
People ask for both with the same words, and they are different tables.

---

## 4. Sources

| Source table | Real name | PK | Load cadence | `loaded_at_field` | Known dirtiness | Already staged? |
|---|---|---|---|---|---|---|
| | `[NEEDS INPUT]` | | | | | |

**Source of truth when two sources disagree:** `<which one wins, and who decided>`
This is business policy, not an engineering choice. Reversing it later means a rebuild.

**Measured arrival lag** (needed before any incremental model):

| Metric | Value |
|---|---|
| p50 lag | |
| p99 lag | |
| max observed lag | |
| Chosen lookback window | p99 × 2 = |

---

## 5. Model scope

| Layer | Models | Materialization | Grain |
|---|---|---|---|
| Sources | | — | |
| Staging | `stg_<source>__<entity>` | view | 1:1 with source |
| Intermediate | `int_<entity>_<verbed>` | ephemeral / view | |
| Marts | `fct_<entity>` / `dim_<entity>` | table / incremental | |

**Reused existing models:** (check before building — do not create a second staging model)

**Materialization reasoning:**

---

## 6. Assumptions and the tests they become

| # | Assumption | What breaks if wrong | How we find out | Test |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |

An assumption nobody tests is a future incident with a name already on it.

---

## 7. Quality gates

| Gate | Rule | Severity | Owner |
|---|---|---|---|
| Source freshness | warn after / error after | error | |
| Primary key | `unique` + `not_null` | error | |
| Referential integrity | `relationships` on `<fk>` | error | |
| Domain | `accepted_values` on `<col>` | error | |
| Business rule | | | |
| Reconciliation | vs `<system>`, tolerance `<x%>` | | |
| Logic correctness | unit test on `<model>` | error | |

---

## 8. Feasibility verdict

**Verdict:** Build | Narrowed build | Not a dbt problem | Blocked

**Evidence:**

**If narrowed — what is dropped and why:**

**If not a dbt problem — where it belongs instead:**

**If blocked — the blocker and its owner:**

---

## 9. Delivery

| Item | Value |
|---|---|
| Build command | `dbt build --select <selector>` |
| CI selector | `state:modified+` |
| Estimated build time | |
| Rollback path | |
| Full-refresh cost (if incremental) | |
| Owner (group) | |
| Alert routing | |

**Phasing:**

| Phase | Ships | Depends on |
|---|---|---|
| 1 | | |
| 2 | | |

---

## 10. Approval

| Role | Name | Date | Decision |
|---|---|---|---|
| Analytics engineering | | | |
| Data/business owner | | | |
| Consumer owner | | | |

---

## 11. Outcome — filled in after delivery

| Item | Value |
|---|---|
| Shipped on | |
| Actual build time | |
| Is the consumer using it? | |
| What we got wrong in this spec | |
| Tests added after an incident | |
