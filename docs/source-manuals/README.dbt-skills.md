> **Frozen provenance copy — not live guidance.** The original README from the
> `dbt-skills` source repository, preserved for history per
> [README.md § Feature provenance](../../README.md). It may contradict current behavior and
> must not be followed or edited to match. The live documentation is
> [README.md](../../README.md).

# dbt Skill — How to Use It

A scaffold that turns a business data request into working, tested, documented **dbt Core**
models. This file is the operating manual: how to install it, how to call the agents, what
each one does, and what a real session looks like.

If you want to see it work before reading anything, [skip to the 20-second demo](#the-20-second-demo).

## At a glance

| | |
|---|---|
| 7 agents | one lead, six specialists |
| 14 skills | method for one stage each, loaded on demand |
| 8 commands | `/slash` shortcuts for a fixed procedure |
| 47 rules | non-negotiables, cited by number |
| 11 analyzers | standard-library Python, no warehouse connection |
| 10 templates | spec, canvas, bus matrix, star schema, blueprint, runbooks |
| 15 references | syntax and method depth, loaded on demand |
| 1 runnable example | DuckDB in ~20s, portable to BigQuery and Snowflake |

---

## Install

The scaffold is a `.claude/` directory plus supporting folders. Claude Code discovers
agents, skills, and commands from `.claude/` at your **project root** or in
`~/.claude/`, so pick one:

**Option A — use it on a specific dbt project** (most common)

```bash
cp -r code-skills/.claude   /path/to/your-dbt-project/
cp -r code-skills/scripts   /path/to/your-dbt-project/
cp -r code-skills/templates /path/to/your-dbt-project/
cp -r code-skills/skill-packs/dbt-skills/references /path/to/your-dbt-project/
```

**Option B — make it available everywhere**

```bash
cp -r code-skills/.claude/agents/*   ~/.claude/agents/
cp -r code-skills/.claude/skills/*   ~/.claude/skills/
cp -r code-skills/.claude/commands/* ~/.claude/commands/
```

Copy `scripts/` somewhere stable and adjust the paths in the commands, or keep the whole
scaffold checked out and point at it.

**Option C — work inside this repo**, which is how the worked example runs. Start Claude
Code from **this directory**, not from the repository root:

```bash
cd code-skills && claude
```

Claude Code finds slash commands in `.claude/commands/` at the project root — the directory
you launched it from. Launching from the repo root one level up finds nothing, and
`/new-use-case` comes back as `Unknown command`. Directory-scoped discovery covers skills,
not commands.

Every path inside the commands and agents is relative to *this* directory too (`scripts/`,
`templates/`, `.claude/rules/`), so this is also the only launch point where they resolve.

Verify:

```
> /dbt-audit
```

If the command doesn't autocomplete, Claude Code hasn't found `.claude/commands/` — check
what directory you started it in.

**Requirements.** Python 3.9+ for the scripts (standard library only — no install step).
dbt Core 2.0+ for anything that runs against a warehouse. `dbt-duckdb` if you want to run
the worked example.

---

## The mental model

Five kinds of thing, each with a different job. Confusing them is the main source of
"why didn't it do what I wanted".

| Thing | What it is | How it activates |
|---|---|---|
| **Rules** | 47 non-negotiables — grain, `ref()` only, `dbt build` not run-then-test | Always in force. Agents cite them by number. |
| **Agents** | A specialist with its own instructions and a fresh context window | You ask for it, or the lead delegates to it |
| **Skills** | Method for one stage — how to write a unit test, how to pick an incremental strategy | Loaded on demand when the topic comes up |
| **Commands** | A `/slash` shortcut that runs a fixed procedure | You type `/name` |
| **Scripts** | 11 Python analyzers that read dbt's JSON artifacts | Agents run them; you can too |

The short version: **rules constrain, agents decide, skills inform, commands shortcut,
scripts measure.**

---

## The agents

Seven. One leads, six specialize.

| Agent | Owns | Say something like |
|---|---|---|
| **`dbt-skill`** | Canonical entrypoint (compatibility alias: `senior-analytics-engineer`). The whole request, end to end. Frames it, delegates, synthesizes. | "We need a revenue mart" · "Why don't these two dashboards agree?" |
| **`data-modeler`** | What the tables *are* — entities, ERD, keys, grain, conformed dimensions, SCD strategy | "How should we model vehicle valuations?" · "Star schema or one big table?" · "Draw the ERD" |
| **`dbt-model-designer`** | How each model is *built* — layers, joins, fan-out, materialization, the SQL | "Where does this logic belong?" · "Should this be incremental?" · "Why is this duplicating rows?" |
| **`data-contract-owner`** | Boundaries — sources, freshness, contracts, versions, access, impact analysis | "What breaks if I change this?" · "Add freshness to these sources" · "Does this need a version bump?" |
| **`analytics-quality-guardian`** | Whether it can merge — test plan, coverage, docs, merge verdict | "What tests should this have?" · "Is this ready to merge?" · "Review this PR" |
| **`semantic-layer-architect`** | Metrics — semantic models, all five metric types, time spine, `mf query` | "Define revenue once" · "What was revenue by region last quarter?" |
| **`dbt-troubleshooter`** | Failures — parse/compile errors, failing tests, incremental corruption, slowdowns | "Why did this fail?" · "The build got slow" · "Numbers changed and nobody deployed" |

### How to call one

**1. Just describe the problem.** Each agent's `description` field lists its trigger
phrases, and Claude routes on it. This is the normal path.

```
> Our finance dashboard and the exec deck report different revenue for June.
```
→ routes to `semantic-layer-architect` (two-numbers-disagree is its trigger)

**2. Name it explicitly** when you want a specific one, or when routing picked wrong:

```
> Use the data-modeler agent to design the entities for our car pricing engine.
> Have dbt-troubleshooter look at why fct_orders got slow.
```

**3. Use a command** when you want the fixed procedure rather than a conversation:

```
> /new-use-case sales wants to see subscription churn by plan tier
> /data-model vehicle valuation
> /dbt-model fct_valuations
> /dbt-test fct_valuations
> /dbt-audit
> /dbt-debug fct_orders
> /dbt-semantic average_valuation_gap
> /dbt-build state:modified+
```

Commands are the same knowledge as the agents, run as a checklist instead of a dialogue.
Use a command when you know the stage; describe the problem when you don't.

### What agents can and cannot do

All seven can read, write, and edit files, search the repo, and run shell commands — so
they will actually run `dbt build` and the analyzer scripts, not just describe them.

Only `dbt-skill` can delegate to other agents. The six specialists work
alone and hand results back.

Each agent starts with a **fresh context window**. It sees the task you or the lead gives
it, not your whole conversation. So a delegated task carries its own brief — which is why
the lead writes a use-case spec to a file rather than keeping it in the chat.

---

## How the work flows

The lead agent runs a nine-step loop and delegates the specialized parts:

```
1. Read the project          existing conventions win over any style guide
2. Frame                     -> use-cases/<slug>/use-case-spec.md
3. Model            ────────▶ data-modeler            -> canvas, ERD, grain matrix
4. Contract sources ────────▶ data-contract-owner     -> sources.yml, freshness
5. Design           ────────▶ dbt-model-designer      -> blueprint, then SQL
6. Build                     dbt build --select <model>, layer by layer
7. Test + document  ────────▶ analytics-quality-guardian -> test plan, merge verdict
8. Define metrics   ────────▶ semantic-layer-architect -> semantic models, metrics
9. Ship                      impact check, CI selector, rollback path, owner
                    ────────▶ dbt-troubleshooter       whenever something fails
```

Two hand-offs are worth understanding, because they are where projects usually go wrong:

**`data-modeler` → `dbt-model-designer`.** The modeler decides *which tables exist and
what one row means*. The designer decides *how to build each one*. The contract between
them is the grain matrix — one row per table with its grain sentence and primary key. The
designer copies the grain rather than re-deriving it; if it disagrees, the canvas changes
first. This is what stops two models quietly using two definitions of "customer".

**Everyone → `analytics-quality-guardian`.** Nothing merges without a verdict. It returns
**Merge**, **Merge after** (with the specific missing tests), or **Do not merge** (with the
specific breakage) — not a list of fifteen undifferentiated comments.

Step 3 is skippable, deliberately: one model on one source with an obvious grain doesn't
need a canvas. Several models, or a dimension two teams will share, does.

---

## The 20-second demo

Prove the whole thing works before pointing it at your project. No warehouse account, no
credentials:

```bash
python3 -m venv .venv
.venv/bin/pip install 'dbt-core~=1.9.0' 'dbt-duckdb~=1.9.0'

cd skill-packs/dbt-skills/use-cases/example-order-revenue-mart/dbt_project
./run_local.sh
```

Sixteen steps: seeds the raw tables, checks source freshness, builds every model, runs 40
data tests and 6 unit tests, takes an SCD2 snapshot, proves the incremental result equals a
full refresh, generates the catalog, then runs every analyzer against the artifacts it just
produced.

Expected: **53 pass, 1 warn, 0 errors.** The warning is intentional — a second,
warn-severity `accepted_values` test that fires when the source ships an unmapped status,
so the build stays green and someone still finds out.

The same project runs on BigQuery and Snowflake:

```bash
./run_local.sh bigquery      # needs DBT_BQ_PROJECT + auth
./run_local.sh snowflake     # needs DBT_SF_ACCOUNT + key-pair
```

Only the DuckDB path has been executed here. The other two are configured and reviewed but
need real accounts to verify.

---

## Worked examples

### 1. A new mart, from a vague request

```
> Sales wants a dashboard showing subscription churn by plan tier.
```

`dbt-skill` takes it and does **not** start writing SQL:

1. Reads `dbt_project.yml` and `dbt ls` — half of all requests are already answerable
   with an existing model.
2. Writes `use-cases/subscription-churn/use-case-spec.md` and asks the questions whose
   answers change the design, **in one batch**: what decision changes, who consumes it,
   what is the grain, and which source wins when two disagree.
3. Gives a verdict: **Build**, **Narrowed build**, **Not a dbt problem**, or **Blocked**.

"Not a dbt problem" is a common and successful outcome. If nothing changes based on the
output, it is a reporting request — you get the query and an explanation, not a new mart in
the DAG costing build time and review time forever.

Then: `data-modeler` for the canvas → `dbt-model-designer` for the SQL →
`analytics-quality-guardian` for the merge verdict.

### 2. A modeling question with no code yet

```
> Use the data-modeler agent. We're building a car pricing and valuation engine —
> how should we model it?
```

`data-modeler` will:

- Pull entities out of the spec and filter them with two tests: *can it exist before and
  after the relationship?* and *does the business ask questions "by" it?*
- Draw the ERD with cardinality **and optionality**. The optionality is the part people
  skip, and it is the difference between an `inner join` that silently drops 3% of rows
  and a `left join` with a documented unknown member.
- Force the grain question, because "vehicle valuation" has at least four plausible
  grains — per VIN, per VIN per date, per trim per region per month, per listing — and
  picking wrong means a rebuild.
- Write the canvas, the bus matrix if there is more than one business process, and a star
  schema spec per process.

It will **not** write SQL. That is the next agent's job, and doing it here skips the
blueprint.

See [skill-packs/dbt-skills/use-cases/example-order-revenue-mart/data-model-canvas.md](../../skill-packs/dbt-skills/use-cases/example-order-revenue-mart/data-model-canvas.md)
for a filled-in one, including the entities that were *rejected* and why.

### 3. A failure

```
> The nightly build failed. Here's the log.
```

`dbt-troubleshooter` reads artifacts rather than guessing:

```bash
python scripts/run_results_analyzer.py --run-results target/run_results.json \
    --manifest target/manifest.json --compare prod/run_results.json
```

`run_results.json` already contains the error, the timing, and the node. It gets read
before any code changes. For a slowdown, `--compare` shows what regressed run over run, and
the critical path tells you whether adding threads would do anything — usually it wouldn't.

### 4. "What breaks if I change this?"

```
> I need to drop currency_code from fct_orders.
```

`data-contract-owner`:

```bash
python scripts/model_dependency_analyzer.py --manifest target/manifest.json \
    --model fct_orders --direction down
python scripts/contract_breaking_change_detector.py \
    --base prod/manifest.json --head target/manifest.json --strict
```

Blast radius first, then the breaking-change diff. If the model is contracted or has
consumers, you get a version bump plus a `deprecation_date`, not a silent removal.

The detector is explicit about its blind spot: it **cannot** detect a grain change. The
column list would be identical, every contract would pass, every test would pass, and every
downstream number would be silently wrong. It lists the models whose SQL changed so a human
can check.

### 5. Two dashboards disagree

```
> Finance says June revenue was 2.1M, the exec deck says 1.9M.
```

`semantic-layer-architect` treats this as a definition problem, not a SQL problem: find the
two definitions, decide which is correct with the business, define it **once** in the
semantic layer, and point both consumers at it. A metric redefined in a BI tool is a second
source of truth, and it will drift again.

---

## Running the analyzers yourself

Eleven scripts, standard-library Python, no warehouse connection. They read dbt's JSON
artifacts, so run any `dbt` command first (`dbt parse` is enough).

```bash
python scripts/dbt_project_auditor.py --manifest target/manifest.json --strict
python scripts/dimensional_model_validator.py --manifest target/manifest.json --strict
python scripts/erd_generator.py --manifest target/manifest.json --layer marts --format markdown
python scripts/model_dependency_analyzer.py --manifest target/manifest.json --model fct_orders --direction down
python scripts/test_coverage_reporter.py --manifest target/manifest.json --layer marts --min-coverage 0.9
python scripts/run_results_analyzer.py --run-results target/run_results.json --top 15
python scripts/source_freshness_monitor.py --sources target/sources.json --manifest target/manifest.json
python scripts/schema_yml_generator.py --manifest target/manifest.json --model stg_orders --infer-tests
python scripts/unit_test_generator.py --manifest target/manifest.json --model int_order_items --adapter snowflake
python scripts/semantic_layer_validator.py --path models/ --strict
python scripts/contract_breaking_change_detector.py --base prod/manifest.json --head target/manifest.json --strict
```

`--strict` exits 1 on any error-severity finding, which is how you gate a PR.

Findings are ranked by **blast radius**, not alphabetically — a trivial gap on a model with
twelve dependents outranks a serious one on a leaf nobody queries.

### What each one is for

| Script | Rules / output | Use it when |
|---|---|---|
| `dbt_project_auditor.py` | 20 rules (7 error, 12 warn, 1 info) | Any PR; the general health gate |
| `dimensional_model_validator.py` | 15 star-schema rules (4 error, 8 warn, 3 info) | The PR touches a fact, dimension, or bridge |
| `erd_generator.py` | Mermaid ER diagram | Reviewing a model design, or writing a PR description |
| `model_dependency_analyzer.py` | Lineage, blast radius, cycles, layer violations, Mermaid DAG | Before changing anything with consumers |
| `test_coverage_reporter.py` | Coverage per model and layer | Auditing an inherited project |
| `run_results_analyzer.py` | Failures, slowest models, critical path, regressions | A build failed or got slower |
| `source_freshness_monitor.py` | Breaches, annotated with the marts they block | A scheduled job or a stale dashboard |
| `schema_yml_generator.py` | `schema.yml` skeleton with inferred tests | Starting tests on an undocumented model |
| `unit_test_generator.py` | Unit test scaffold, every ref stubbed and typed | A model has CASE/window/regex/date math |
| `semantic_layer_validator.py` | Semantic model and metric spec errors | Before `mf validate-configs` hits the warehouse |
| `contract_breaking_change_detector.py` | Removed/retyped columns, contract and access breaks | Every PR, against production's manifest |

The two dimensional tools deliberately **do not overlap** the auditor. The auditor covers
PK tests, documentation, hardcoded refs, layer violations. The dimensional validator covers
what it does not: facts joined to facts, untested foreign keys, nullable FKs with no unknown
member, orphan and unconformed dimensions, ratios stored as fact columns, measures named for
another entity, and snapshot/SCD2 configuration.

**They are static analyzers.** They can tell you a `relationships` test is missing; they
cannot tell you it would pass. Only `dbt build` and `mf query` catch semantic problems.

Mixed-grain detection is **name-based**: `dimensional_model_validator.py` flags a measure
named for a different entity (`dealer_total_inventory` on an order-grain fact), but a grain
error with a neutral column name has the same manifest signature as a correct model. That
stays human review, and a fan-out unit test is what actually proves it.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Slash command doesn't autocomplete | `.claude/commands/` not found | Check it's at your project root or `~/.claude/` |
| Agent never triggers | Your phrasing doesn't match its `description` | Name it: "use the data-modeler agent" |
| Wrong agent picked | Two descriptions overlap | Name the one you want |
| Agent asks about things you already said | Delegated agents start with a fresh context | Expected — put durable facts in the use-case spec file, not the chat |
| Script exits 2 | Missing or unreadable artifact | Run `dbt parse` first; check the `--manifest` path |
| Script exits 1 | Findings at error severity | That's the gate working — read the output |
| "It wrote a spec instead of SQL" | Rule 1: no model before a use-case spec | Working as designed. Say "just draft it" to proceed with assumptions listed. |

---

## What changed most recently

Three things landed together and are worth knowing about, because they change how the
scaffold is used rather than just adding to it.

### 1. A data-modeling stage, ahead of the SQL

Previously the scaffold went use-case spec → model blueprint → SQL, with no stage for
deciding *what the models are*. That is now stage 2:

| Added | What |
|---|---|
| `data-modeler` agent | Entities, ERD, keys, grain matrix, bus matrix, SCD strategy |
| `data-modeling` skill | Conceptual → logical → physical, normalization, paradigm choice |
| `/data-model` command | The fixed procedure |
| `dimensional_modeling.md` | Kimball's four steps, fact and dimension types, SCD 0–6, bridges, the date dimension |
| `data_modeling_paradigms.md` | Kimball, Inmon, Data Vault 2.0, OBT, Activity Schema, medallion — and how to choose |
| 3 templates | `data-model-canvas.md`, `bus-matrix.md`, `star-schema-spec.md` |
| 2 analyzers | `erd_generator.py`, `dimensional_model_validator.py` |
| Rules 6–12 | Conceptual model first; one entity one definition; explicit optionality; no keys from mutable attributes; grain before columns; additivity recorded; SCD type chosen |

It is **binding, not advisory**. `/dbt-model` and `dbt-model-designer` now check for a
canvas row before building a fact, dimension, or bridge, and copy its grain rather than
re-deriving it. Skip the stage deliberately — one model on one source with an obvious grain
does not need a canvas — but not by omission.

The ownership split matters: `data-modeler` decides which tables exist and what one row
means; `dbt-model-designer` decides how each one is built. The hand-off is the grain matrix.

### 2. The worked example actually runs

It used to be model files plus a synthetic `manifest.json`. It is now a real dbt project:
`dbt_project.yml`, `profiles.yml`, packages, macros, seeds with a generator, an SCD2
snapshot, and `run_local.sh`. See [the 20-second demo](#the-20-second-demo).

Building it surfaced eight genuine bugs, each now fixed in the code with the reason written
next to it — a hardcoded `merge` strategy that DuckDB rejects on the *second* run, contract
failures from uncast aggregates, a Jinja block-assignment trap, Jinja rendering SQL
comments, macros being unavailable in property YAML, and a seeds-as-sources race. The full
list is in
[skill-packs/dbt-skills/use-cases/example-order-revenue-mart/README.md](../../skill-packs/dbt-skills/use-cases/example-order-revenue-mart/README.md#what-the-real-run-teaches).

The same project runs on BigQuery and Snowflake via the portability layer in
`macros/cross_db.sql`. Only the DuckDB path has been executed here; the other two are
configured and reviewed but need real accounts to verify.

### 3. Rules renumbered 1–47

Data modeling was inserted as rules **6–12**, shifting everything after it. All citations in
the commands and agents were updated. If you had bookmarked a rule number, re-check it:
old 29–34 is now 36–41, old 35–38 is now 42–45.

---

## Where everything lives

| Path | What |
|---|---|
| [.claude/agents/](../../.claude/agents/) | The 7 agents |
| [.claude/skills/](../../.claude/skills/) | 14 skills, loaded on demand |
| [.claude/commands/](../../.claude/commands/) | 8 slash commands |
| [.claude/rules/analytics-engineering-rules.md](../../.claude/rules/analytics-engineering-rules.md) | The 47 rules |
| [scripts/](../../scripts/) | 11 analyzers + 2 shared helpers |
| [templates/](../../templates/) | 10 deliverable shapes — specs, canvas, blueprints, runbooks, checklists |
| [../../skill-packs/dbt-skills/references/](../../skill-packs/dbt-skills/references/) | 15 deep references, loaded on demand |
| [use-cases/](../../use-cases/) | One directory per data request |
| [SKILL.md](../../SKILL.md) | Stage → skill routing table |
| [CLAUDE.md](../../CLAUDE.md) | Project instructions Claude reads automatically |

## The five rules that matter most

Full list in [.claude/rules/analytics-engineering-rules.md](../../.claude/rules/analytics-engineering-rules.md).

- **No model before a use-case spec, no mart without a named consumer.**
- **Declare the grain in one sentence** before writing SQL.
- **`source()` and `ref()` only** — a hardcoded table name is invisible to lineage,
  selection, and state comparison.
- **`dbt build`, never `dbt run` then `dbt test`** — `build` stops dependents when a test
  fails instead of propagating bad data through the DAG.
- **Never invent a number or a table name.** Unknown values are marked `[NEEDS INPUT]` and
  the design continues around them.

## Scope

**In scope:** request framing, data modeling, source contracts, layer design, SQL,
materialization and incremental strategy, snapshots, data and unit testing, documentation,
MetricFlow metrics, governance, CLI and node selection, slim CI, performance, failure
triage, migrations.

**Out of scope:** ingestion and EL tooling, warehouse administration, BI dashboard
building, reverse ETL, and dbt Cloud–specific features (hosted scheduler, Semantic Layer
API, Discovery API, Cloud CI). The scaffold defines the contracts those systems need and
hands them over; it does not build them.
