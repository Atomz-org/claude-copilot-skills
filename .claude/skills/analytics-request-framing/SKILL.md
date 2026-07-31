---
name: analytics-request-framing
description: Turn a vague data request into a written use-case spec with a named consumer, a stated grain, source contracts, quality gates, and a build/don't-build verdict. Use at the START of any dbt or analytics request — before designing models, writing SQL, or adding to the DAG. Triggers on "we need a table/mart/dashboard for X", "can you pull", "why don't these numbers match", "make a model for", or any data request that has not yet been written down.
---

# Analytics Request Framing

Always first. The most expensive analytics mistake is building the right model at the
wrong grain for a consumer who never asked for it.

## Output

`skill-packs/dbt-skills/use-cases/<slug>/use-case-spec.md`, from
[templates/use-case-spec.md](../../../templates/use-case-spec.md). Nothing gets modeled
until this exists and the verdict is Build.

## The four questions

Answer these before anything else. If a request survives all four, it is real work.

### 1. What decision changes?

Complete this sentence with no hedging:

> Every `<cadence>`, `<role>` will `<action>` based on `<output>`, instead of `<what they
> do today>`.

If you cannot complete it, one of these is true, and each has a different answer:

| Situation | The right response |
|---|---|
| Nobody acts on it | It is a reporting request. Write the query, send the numbers, do not add a mart. |
| Somebody looks at it but never acts | Ask what would change their mind. If nothing, decline the model and say why. |
| The action already happens without this data | The value is speed or confidence, not the decision. Size that, or drop it. |
| It is genuinely exploratory | Do the analysis in a scratch query. Promote it to a model only if it gets asked twice. |

Declining is a successful outcome. A DAG full of unused marts costs build time, review
time, and trust every single day.

### 2. Who consumes it, and how?

Name the consumer concretely: a dashboard with a URL, a downstream model, a reverse-ETL
sync, a notebook someone actually opens. "The business" is not a consumer.

This determines:

- whether the model needs a **contract** (an external consumer you cannot fix in the same PR does);
- the **freshness SLA** (a daily-read dashboard does not need hourly builds);
- the **column naming** (a BI-facing mart uses business names, not source-system names);
- whether it goes in `exposures:` (it does).

**A mart with no named consumer does not get built.**

### 3. What is the grain?

One sentence: **"one row per `<entity>` per `<period>` per `<qualifier>`"**.

Then name the primary key that enforces it. If there is no single column, the key is a
surrogate over the grain columns.

Get this wrong and everything downstream is wrong in a way that passes every test. Pressure
test it:

- Can the same entity appear twice? Under what circumstance?
- What happens to the grain when a record is updated — new row, or overwrite?
- Is it "one row per order" or "one row per order per status change"? These are different
  tables and people ask for them with the same words.
- Does the consumer need history, or only current state? History means a snapshot or an
  event-grain fact, not a `dim_`.

### 4. Where does the data come from, and can we trust it?

For each source table, get:

| Item | Why it matters |
|---|---|
| Real schema and table name | `[NEEDS INPUT]` if unknown — never guess one |
| Primary key | Test it at the source; duplicates upstream become duplicates everywhere |
| Load cadence and `loaded_at_field` | Sets the freshness SLA and the achievable model cadence |
| Known dirtiness | Soft deletes, test rows, pre-migration records, duplicate loads |
| Whether it is already staged | Reuse the existing `stg_` model; do not build a second one |

When two sources disagree about the same fact, **ask which one wins before modeling**. This
decision is business policy, not an engineering choice, and reversing it later means
rebuilding.

## Feasibility verdict

Give one of four, with evidence:

| Verdict | Meaning |
|---|---|
| **Build** | Decision, consumer, grain, and sources are all real. Proceed to design. |
| **Narrowed build** | The full ask is not feasible; a smaller version is. State exactly what is dropped and why. |
| **Not a dbt problem** | The fix belongs in the source system, the EL job, the BI layer, or a one-off query. Name where. |
| **Blocked** | A source does not exist, a definition is contested, or nobody owns the decision. Name the blocker and the owner. |

"Not a dbt problem" is common and worth saying plainly:

- The source data is wrong → fix the source system; a mart that cleans bad data hides the bug.
- The number is needed once → write the query.
- The question is "why did X happen" → it is an analysis, not a model.
- Two dashboards disagree → the fix is one metric definition (`semantic-layer-metricflow`),
  not a third table.
- It needs prediction or causal inference → hand to data science; the deliverable here is a
  feature-ready mart with point-in-time correctness stated.

## Quality gates

Every material assumption becomes a test later, so capture them now with their failure mode:

| Assumption | What breaks if wrong | Test it becomes |
|---|---|---|
| Every order has a customer | Revenue by segment loses rows silently | `relationships` |
| Status is one of five values | A CASE falls through to a wrong bucket | `accepted_values` |
| Orders arrive within 3 days | Incremental lookback is too short; rows are lost forever | freshness + `dbt_utils.recency` |
| Revenue reconciles to finance ±0.5% | The exec dashboard contradicts the ledger | singular reconciliation test |

## Ask, don't assume

Ask the two or three questions whose answers change the design — usually the grain, the
consumer, and the source-of-truth tiebreak. Ask them in one batch, not one at a time.

**Never invent** a table name, a row count, a freshness SLA, or a business definition. Mark
it `[NEEDS INPUT]` and keep designing around it. If the user says "just draft it", proceed
and list every assumption at the top of the spec.

## Definition of done

- The decision sentence is complete, with a named human role.
- The consumer is named concretely and will appear in `exposures:`.
- The grain is one sentence, with its primary key.
- Every source has a real name or a `[NEEDS INPUT]` marker.
- Assumptions are listed with their failure modes and the tests they become.
- The verdict is one of the four, with evidence.

## Examples

| Ask Claude | What you get |
|---|---|
| `/new-use-case churn dashboard` | The four questions answered into a spec file, plus a verdict |
| "can you pull last month's revenue?" | "Not a dbt problem" — a query and the numbers, no mart added |
| "we need a table for X" | The grain and consumer settled first, even when the ask sounds complete |

**Worked example**

> "we need a customer churn table"

```
1. Decision  Every month, the retention lead will target win-back offers based on
             customers who churned last month, instead of a manual CRM export.
2. Consumer  Looker dashboard "Retention · Churn" → goes in exposures:
3. Grain     One row per customer per month. PK: surrogate(customer_id, month).
             Pressure test: churn dated at cancellation, or at paid-period end?
             → [NEEDS INPUT] — the two differ by up to 30 days.
4. Sources   raw.stripe.subscriptions [NEEDS INPUT: loaded_at_field], stg_customers ✓

Assumptions → tests
  Every subscription has a customer  → relationships
  Status is one of five values       → accepted_values

Verdict: Narrowed build. Ship monthly churn on cancellation date; the paid-period
variant waits on the definition. Blocker owner: retention lead.
```

Both `[NEEDS INPUT]` markers stay in the spec. Guessing either one produces a number that
looks right and reconciles to nothing.

Next: [dbt-model-design](../dbt-model-design/SKILL.md).
