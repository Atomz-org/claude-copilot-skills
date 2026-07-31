---
name: dbt-skill
description: Canonical dbt skill entrypoint for this repository. Routes dbt requests to the right focused skill and enforces dbt Core operating rules.
---

# dbt Skill

This is the canonical skill entrypoint for dbt work in this repository.

## Routing

- Start with [analytics-request-framing](../analytics-request-framing/SKILL.md).
- Continue with the stage-appropriate focused skills in this folder.
- Use specialist dbt agents from `../agents/` when decomposition is needed.

## Use-case path policy

All new dbt use-cases must be created under:

- `skill-packs/dbt-skills/use-cases/<slug>/`

Do not create new dbt use-cases under the repository root `use-cases/` path.

## Compatibility

`senior-analytics-engineer` remains as a compatibility alias and should route here.

## Examples

This skill routes; the focused skill does the work. What you should see is a named
destination, not a generic answer.

| Ask Claude | Routes to | Command |
|---|---|---|
| "we need a revenue mart" | `analytics-request-framing` — always first, even when the ask sounds complete | `/new-use-case` |
| "what entities do we need for subscriptions?" | `data-modeling` | `/data-model` |
| "build fct_orders" | `dbt-model-design` | `/dbt-model` |
| "what tests should this have?" | `testing-and-documentation`, then `dbt-unit-testing` if there is logic | `/dbt-test` |
| "why did the run fail?" | `troubleshooting-dbt` | `/dbt-debug` |
| "two dashboards disagree on revenue" | `semantic-layer-metricflow` — one definition, not a third table | `/dbt-semantic` |
| "this build got slow" | `performance-and-cost` | — |
| "add Shopify to the enhanza project" | `connector-onboarding` | `/new-connector` |

**Worked example**

> "we need a table showing customer churn"

```
Route : analytics-request-framing first — no model before a use-case spec.
Why   : "churn" has no grain and no named consumer yet. One row per customer, or per
        customer per month? Churned on cancellation date or end of paid period?
Output: skill-packs/dbt-skills/use-cases/customer-churn/use-case-spec.md
        with a Build / Narrowed build / Not a dbt problem / Blocked verdict.
Then  : /data-model if the subject area needs more than one model, otherwise /dbt-model.
```

Skipping straight to `/dbt-model` here is the failure mode this entrypoint exists to
prevent — the SQL gets written at a grain nobody agreed on.
