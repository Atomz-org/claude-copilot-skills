# dlt integration — infrastructure progress

Status of bringing [dlt-hub/dlthub-ai-workbench](https://github.com/dlt-hub/dlthub-ai-workbench)
capabilities into this repository against **open-source `dlt`**, with no dltHub Platform
account and no paid tier.

Every figure below was measured on this repository. Where a capability could not be
ported, the reason is stated rather than the gap being left implicit.

## Delivery status

| Layer | Branch | Delivers | State |
|---|---|---|---|
| 01 | `feat/no-ticket-dlt-01-foundation` | agent cost attribution, end to end on a demo use-case | **merged** — PR #73, `a348278` |
| 02 | `feat/no-ticket-dlt-02-toolkit-pack` | the five runnable workbench toolkits as a skill pack | in progress |
| 03 | *not branched* | ontology from a dlt-inferred schema | planned |
| 04 | *not branched* | data-quality and performance, built on OSS dlt | planned |

## Topology — sequential to `main`, not a stack

Each layer branches off `main` and merges before the next begins. It is not a four-layer
stack, and that is a decision rather than an omission:

```
main ──● 01 agent-costs (runs end-to-end) ──┐ merge
main ────────────● 02 dlt-skills pack + mirror ──┐ merge
main ──────────────────────● 03 ontology ← dlt schema ──┐ merge
main ────────────────────────────────● 04 data-quality
```

A stacked layer touching `skill-packs/` cannot satisfy both constraints this repository
already enforces:

- [`scripts/stack_lint.py`](../../scripts/stack_lint.py) requires generated artifacts —
  `ontology/index.json`, `ontology/**/*.ttl`, `.claude/**`, `references/**`,
  `templates/**` — to live in the **top** layer only.
- [`scripts/activate_skill_stack.sh`](../../scripts/activate_skill_stack.sh) requires a
  pack asset to exist in **both** the pack and its root mirror, because skills link to
  them with one relative path that must resolve in each location.

Layer 02 adds a pack *and* its mirror, so as a middle layer it would violate the first
rule to satisfy the second. Layer 03 regenerates `ontology/index.json` and the Turtle
files, which stack hygiene forbids outside the top layer.

Sequential ordering also makes each merge independently usable: layer 01 runs today with
nothing above it, and the `/find-source` skill added in 02 loads as soon as 02 lands
rather than waiting for 04.

A further reason applies to any branch here that touches generated paths: propagation is
by **merge, never rebase**. The generated-file merge driver means "leave `%A` alone", and
under `git rebase` the roles invert, so a regenerated artifact is silently discarded.
See [`docs/BRANCHING_STRATEGY.md`](../../docs/BRANCHING_STRATEGY.md).

## Layer 01 — agent costs (merged)

dltHub ships `agent-costs` as a Platform product whose page publishes no schema, no code,
and no CLI. This is therefore not a port: it is the same problem solved against OSS `dlt`
+ DuckDB, with every decision the page leaves open made explicitly.

- [`scripts/dlt_agent_costs.py`](../../scripts/dlt_agent_costs.py) — reader, rate card,
  pipeline, and three marts
- [`tests/test_dlt_agent_costs.py`](../../tests/test_dlt_agent_costs.py) — 9 tests
- [`use-cases/agent-costs-demo/`](use-cases/agent-costs-demo/) — 2 traces and a rate card

Measured on the committed demo, `dlt 1.29.1` into `duckdb 1.5.5`:

```
traces      2 file(s), 6 usage event(s)
priced      5/6  — 1 event(s) have no declared rate

[by_model]    demo-large  turns=2  cost=0.5798
              demo-small  turns=3  cost=0.0099
              unpriced-model  turns=1  cost=unpriced
[by_session]  sess-alpha  turns=3  cost=0.5819
              sess-beta   turns=3  cost=0.0078
[by_branch]   feat/pipeline  turns=3  cost=0.5819
              fix/parser     turns=3  cost=0.0078
```

`_dlt_loads` and `_dlt_version` in the resulting database are what distinguish a real
pipeline run from a script that wrote a DuckDB file; a test asserts both are present.

Four decisions, each easy to get wrong while still producing a confident-looking number:

- **An unpriced model is `null`, never `0.0`.** Zero sums, so a dashboard fed zeros
  reports a model as free rather than as unmeasured. The demo carries one deliberately
  unpriced model so the abstain path cannot be quietly removed.
- **Cache reads are priced apart from fresh input.** They dominate token volume on real
  traces and cost a fraction; folding them together overstates spend by about an order of
  magnitude.
- **A rate card must cite its `source` and carry all four token kinds**, or loading it
  exits ([rule 5](../../.claude/rules/analytics-engineering-rules.md)). The arithmetic is
  identical with invented prices, so the citation is the only real check — and it is
  loaded into `model_pricing` beside every row it priced, not left in a file. The demo
  card is labelled `SYNTHETIC` in the file itself and a test fails if that word is
  removed.
- **The grain is one row per assistant turn** ([rule 4](../../.claude/rules/analytics-engineering-rules.md)),
  because a session-level row cannot attribute a mid-session model switch — the normal
  case.

`dlt` is an optional dependency, the same shape as `sqlglot` in `dbt_column_lineage.py`:
readers and pricing work without it and only `--run` declines. The warehouse is
gitignored; the traces and the rate card that produce it are committed.

## Layer 02 — the toolkit pack (in progress)

The workbench ships 13 directories under `workbench/`. Ten appear in its README's toolkit
table, and that table's own **Availability** column is what decides portability here:

| Toolkit | Workflow entry | Availability | Ported |
|---|---|---|---|
| `quick-start` | `/quick-start` | runnable | yes |
| `bootstrap` | `/init-workspace` | runnable | yes |
| `rest-api-pipeline` | `/find-source` | runnable | yes |
| `sql-database-pipeline` | `/find-source` | runnable | yes |
| `data-exploration` | `/explore-data` | runnable | yes |
| `filesystem-pipeline` | `create-filesystem-pipeline` | Sign up | no |
| `dlthub-platform` | `setup-runtime` | Sign up | no |
| `transformations` | `annotate-sources` | Sign up | no |
| `data-quality` | `setup-data-quality` | Sign up | no |
| `performance` | `optimize-performance` | Sign up | no |

Five runnable, five gated. `find-source` backs two toolkits, so it is one skill rather
than two.

Upstream's per-toolkit layout is `.claude-plugin/` + `rules/` + `skills/`, which already
matches this repository's pack convention — compare
[`skill-packs/wren-skills/.claude-plugin/plugin.json`](../wren-skills/.claude-plugin/plugin.json).
The work is therefore a pack plus its root mirror, and one entry in
[`scripts/activate_skill_stack.sh`](../../scripts/activate_skill_stack.sh).

**A gate is known to be weak here.** CI's `baseline` job checks activation drift with
`git diff --exit-code`, which inspects tracked files only — so a brand-new pack mirror is
untracked and passes even when it should not. Layer 02 is the first change that adds
exactly such a mirror, so it is the first change that would exercise the hole.

## Layers 03 and 04 — planned

**03 — ontology from a dlt-inferred schema.** dlt infers a schema at load time; this
repository already turns a schema into an ontology through
`raw_taxonomy.py` → `column_annotations.py` → `ontology_generator.py`. Feeding the first
from the former is the open-source answer to the `ontology-semantic-layer` blueprint. It
needs 02's pack **merged**, not stacked beneath it, and against `main` it can regenerate
`ontology/index.json` and the `.ttl` files freely.

**04 — data quality and performance.** Both toolkits are Sign-up-gated upstream, so
neither can be read, and neither will be described as a port. The gating is dltHub's
packaging rather than a technical dependency in both cases:

- `performance` is parallelism, workers, buffers, and batching — OSS `dlt` configuration.
- `data-quality` maps onto `dlt`'s schema contracts.

These will therefore be **built from `dlt`'s open-source surface**, and the PR will say so.

## Rules this work follows

- **Never invent a number or a name** ([rule 5](../../.claude/rules/analytics-engineering-rules.md)).
  A rate card without a cited source is refused. A toolkit that cannot be read is not
  described as ported.
- **Declare the grain** ([rule 4](../../.claude/rules/analytics-engineering-rules.md)) —
  one row per assistant turn, stated before the schema.
- **Unavailable is not failed.** No `dlt` installed makes `--run` decline with the remedy
  named; the readers and pricing still work and their tests still run. A gate that goes
  red on a correct state gets switched off within a week.
- **Derived state stays out of the tree.** The DuckDB warehouse is gitignored and
  rebuildable in one command; the traces and rate card that produce it are committed.
  Same split, same reason, as the graphify fragment versus the dbt manifest.
