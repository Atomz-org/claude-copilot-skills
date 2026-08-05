---
description: Frame a data request into a written use-case spec before any model is built
argument-hint: <the data request, in the requester's words>
---

Frame this data request: **$ARGUMENTS**

Load the `analytics-request-framing` skill. Write
`skill-packs/dbt-skills/use-cases/<slug>/use-case-spec.md` from
[templates/use-case-spec.md](../../templates/use-case-spec.md).

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

**Stop here on any verdict other than Build.** Everything below scaffolds derived artifacts
for a use-case that is going to exist; a "not a dbt problem" verdict that still leaves an
ontology directory behind is worse than no verdict, because the next person finds the
directory and assumes the answer was yes.

## 6. Scaffold the derived artifacts

Only after the spec is written — the scaffolder refuses without it, which is
[rule 1](../rules/analytics-engineering-rules.md) enforced by a script rather than by memory.

```bash
python3 scripts/use_case_sync.py --init <slug>
```

Three files, none of which assert anything about the domain yet:

| File | What it is |
|---|---|
| `ontology/ontology.yml` | the use-case's IRI namespace, and its own concept classes |
| `ontology/connectors.yml` | the connector catalogue — empty, and the extension point |
| `ontology/reference/README.md` | the values sample data will be allowed to use |

`connectors.yml` starts empty on purpose. A row here is a claim that a source system exists,
and the generator will not make that claim for you ([rule 5](../rules/analytics-engineering-rules.md)).
Connectors arrive through `/new-connector`.

## 7. Sync everything derived, and say what could not run

```bash
python3 scripts/use_case_sync.py --use-case <slug> --graphify-update
```

One pass over every derived artifact, in dependency order:

| Stage | Produces | Needs |
|---|---|---|
| `ontology` | `ontology/connectors/*.ttl`, `topology/*.ttl` | `connectors.yml` |
| `index` | `ontology/index.json` — the machine-facing projection | same pass as the Turtle |
| `seeds` | `dbt_project/seeds/sample/*.csv` | a manifest, `sqlglot`, reference data |
| `graphify` | the code graph, rebuilt | `--graphify-update` |
| `graph` | the dbt lineage merged into `graphify-out/graph.json` | a manifest |
| `alignment` | the verdict on convention drift | a dbt project |

A fresh use-case has no manifest, so most of these report `skip` with the reason — that is
the correct output, not a failure. **Report which stages ran and which skipped.** A summary
that says "synced" when four of six stages skipped is the kind of statement that gets
believed once and never again.

**Never run `graphify update` after this command.** graphify has no SQL parser, so its AST
pass extracts nothing from a `.sql` file and drops the node rather than keeping it isolated —
a rebuild after the merge deletes all 359 dbt models and their 1288 edges, and leaves a graph
that still looks populated because the source nodes survive. That is why the rebuild is a
stage inside the driver, sequenced ahead of the merge, and why `--graphify-update` exists
instead of a second command.

---

## Rules that bind here

[Rules 1–5](../rules/analytics-engineering-rules.md): no model before a use-case spec; name
the decision; name the consumer before the model; declare the grain in one sentence; never
invent a number or a name.

## Output

Write the file, then summarize in chat:

- the decision sentence and the verdict;
- the grain and its primary key;
- what is `[NEEDS INPUT]` and who can answer it;
- which sync stages ran, and which skipped and why;
- the recommended next command (`/new-connector` for the first source, then
  `/dbt-model <concept>`), or why there is no next step.
