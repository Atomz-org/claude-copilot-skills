---
description: Frame a data request into a written use-case spec before any model is built
argument-hint: <the data request, in the requester's words>
---

Frame this data request: **$ARGUMENTS**

Load the `analytics-request-framing` skill. Write
`use-cases/<slug>/use-case-spec.md` from
[templates/use-case-spec.md](../../../templates/use-case-spec.md).

---

## 1. Read the project first

Before asking anything, look at what exists:

```bash
cat dbt_project.yml packages.yml 2>/dev/null
dbt ls --resource-type model --output name 2>/dev/null | head -50
dbt ls --resource-type source --output name 2>/dev/null
```

Half of all requests are already answerable with an existing model. Check before designing
a new one, and say so if it is.

## 2. The four questions

Answer these in the spec. Each has a wrong answer that ends the engagement early — which
is a successful outcome, not a failure.

1. **What decision changes?** Complete the sentence with no hedging:
   > Every `<cadence>`, `<role>` will `<action>` based on `<output>`, instead of `<today>`.

   Cannot complete it → reporting request, exploratory analysis, or a fix elsewhere. Say
   which, write the query if that is the answer, and stop.

2. **Who consumes it, and how?** A dashboard with a URL, a downstream model, a sync. "The
   business" is not a consumer. **A mart with no named consumer does not get built.**

3. **What is the grain?** One sentence — "one row per `<entity>` per `<period>`" — plus the
   primary key that enforces it. Pressure test it: is this "one row per order" or "one row
   per order per status change"? People ask for both with the same words.

4. **Where does the data come from, and can we trust it?** Real table names, PKs, load
   cadence, known dirtiness. When two sources disagree, **ask which one wins before
   modeling** — that is business policy, and reversing it later means a rebuild.

## 3. Ask, don't assume

Ask only the two or three whose answers change the design — usually the grain, the
consumer, and the source-of-truth tiebreak. Ask them **in one batch**.

**Never invent** a table name, a row count, a freshness SLA, or a business definition. Mark
it `[NEEDS INPUT]` and keep designing around it. If the user says "just draft it", proceed
and list every assumption at the top of the spec.

## 4. Turn assumptions into tests

Every material assumption goes in section 6 with its failure mode and the test it becomes.
This is the mechanism that turns framing into a guarantee — an assumption nobody tests is a
future incident with a name already on it.

## 5. Give a verdict

| Verdict | Meaning |
|---|---|
| **Build** | Decision, consumer, grain, and sources are all real |
| **Narrowed build** | State exactly what is dropped and why |
| **Not a dbt problem** | Name where it belongs: the source system, the EL job, the BI layer, a one-off query, or data science |
| **Blocked** | Name the blocker and its owner |

"Not a dbt problem" is common and worth saying plainly. A DAG full of unused marts costs
build time, review time, and trust on every single run.

---

## Rules that bind here

[Rules 1–5](../../rules/analytics-engineering-rules.md): no model before a use-case spec; name
the decision; name the consumer before the model; declare the grain in one sentence; never
invent a number or a name.

## Output

Write the file, then summarize in chat:

- the decision sentence and the verdict;
- the grain and its primary key;
- what is `[NEEDS INPUT]` and who can answer it;
- the recommended next command (`/dbt-model <concept>`), or why there is no next step.
