# Start here — a plain-language tour

This page is for anyone opening the repository for the first time — including someone who
does not write code. Nothing below assumes you know dbt, SQL, or data engineering. Every
term that could be jargon is in the [glossary](#glossary) at the bottom.

## What this repository is

Think of it as a **teaching kitchen** for data pipelines. It contains three kinds of
things:

1. **A rulebook** — written methods for doing analytics engineering well, phrased so both
   people and AI assistants can follow them. They live in `skill-packs/` and
   `.claude/rules/`.
2. **A toolbox** — small programs that check work automatically: "does every table have
   tests?", "did someone break a promise a report depends on?", "is the data late?". They
   live in `scripts/`.
3. **A working miniature** — one complete, runnable data project small enough to run on a
   laptop in about forty seconds, with no accounts and no passwords. It lives in
   [skill-packs/dbt-skills/use-cases/example-order-revenue-mart/](../skill-packs/dbt-skills/use-cases/example-order-revenue-mart/README.md).

The rulebook says how work should be done, the toolbox proves whether it was done that
way, and the miniature shows what "done" looks like.

## The one command

If you remember a single thing from this page, make it this:

```bash
./scripts/check.sh
```

It answers one question — **"would this change be accepted?"** — by running the same seven
checks that run automatically when a change is submitted for review (a *pull request*),
in the same order. A pass on your laptop means a pass at review time. When a check
fails, it prints what the check was protecting and the exact command that fixes it, so you
never need prior knowledge of the repository to recover. The longer explanations are in
[DEBUGGING.md](DEBUGGING.md).

## See it work, end to end

```bash
python3 -m venv .venv
.venv/bin/pip install 'dbt-core~=1.9.0' 'dbt-duckdb~=1.9.0'
cd skill-packs/dbt-skills/use-cases/example-order-revenue-mart/dbt_project
./run_local.sh
```

Here is what that run does, in plain words.

The miniature belongs to an imaginary retailer that sells in two places: a **web shop**
(Shopify) and a **physical store with a till** (Demo POS). Each system describes the same
world in its own dialect — the web shop says `financial_status`, the till says `status`;
one calls a sale an *order*, the other a *receipt*. The pipeline's whole job is turning
those dialects into one tidy vocabulary that reports can trust:

| Step you'll see | What it means |
|---|---|
| *seed* | Load the raw data — the messy exports, exactly as the source systems produce them |
| *source freshness* | "Is this data recent enough to build on?" — building on stale data produces numbers that are wrong but look fine |
| *build* | Clean and rename each system's data (staging), then combine it into the answer tables reports read (marts) |
| *tests* | 58 tripwires that fail the build the moment a promise breaks — "every order has exactly one row", "a receipt's status is one of the three we know" |
| *analyzers* | The toolbox reads the run's records and reports on health: missing tests, slow steps, broken layers |

The expected end state is **67 pass, 1 warning, 0 errors** — and the one warning is
deliberate, planted to show what a well-designed warning looks like. The
[example's README](../skill-packs/dbt-skills/use-cases/example-order-revenue-mart/README.md)
explains it.

## How a new data source gets added

Demo POS, the till, was added to the miniature using the repository's own tooling — it is
the worked example of the most common real task, "connect system X". The short version:

1. **Scaffold.** `scripts/new_connector.py` reads how the project already does things and
   generates matching skeleton files — it copies the house style rather than imposing one.
2. **Declare the contract.** Write down exactly which raw columns the project depends on.
   From then on, the source removing one of them is a detectable breaking change instead
   of a 3am surprise.
3. **Clean in one place.** One staging model per raw table does every rename and cast.
   Nothing downstream ever sees a raw column name.
4. **Test the breakable things.** Keys are unique, references resolve, categories stay in
   their known set.
5. **Run the gates.** `connector_alignment_check.py` errors if the new connector does
   anything differently from the existing ones, and `./scripts/check.sh` gives the final
   verdict.

The full walkthrough, including the drift the checker caught while Demo POS was being
onboarded, is in the
[example's README](../skill-packs/dbt-skills/use-cases/example-order-revenue-mart/README.md).

## Where things live

| Path | What it is |
|---|---|
| `skill-packs/` | The rulebook, organized into installable packs. **The editable source of truth** |
| `.claude/` | A generated mirror of the active pack, for the AI harness. Never edit directly |
| `scripts/` | The toolbox — every checker and generator, each runnable on its own |
| `skill-packs/dbt-skills/use-cases/` | Worked examples; one directory per business question |
| `tests/` | Tests for the toolbox and rulebook themselves |
| `docs/` | Documentation, including this page |

One rule protects newcomers from the classic mistake: `.claude/`, `references/`, and
`templates/` at the root are **copies**, rebuilt by `scripts/activate_skill_stack.sh`.
Edit the original under `skill-packs/`, or your change silently vanishes on the next
rebuild. `./scripts/check.sh` catches this ("activation drift") if you forget.

## Glossary

| Term | Plain meaning |
|---|---|
| **dbt** | The open-source tool that runs the pipeline: it builds tables in the right order and tests them |
| **connector** | One upstream system feeding data in — the web shop, the till |
| **source contract** | The written list of raw columns we depend on from a connector |
| **staging** | The cleaning layer: renames and type-fixes, one model per raw table, nothing else |
| **mart** | The answer tables people and dashboards actually read |
| **seed** | A small CSV loaded as a table — here they stand in for the raw systems, so no real accounts are needed |
| **grain** | What one row means ("one row per order"). Most silent data bugs are grain bugs |
| **freshness** | A declared expectation of how recent a source's data must be |
| **manifest** | The machine-readable record dbt writes about the whole project; most of the toolbox reads it |
| **gate** | An automated check that must pass before a change is accepted |
| **pull request** | The formal "please review and merge my change" request; the gates run automatically on every one |

## Where next

- Run the miniature and read its
  [README](../skill-packs/dbt-skills/use-cases/example-order-revenue-mart/README.md) with
  the output in front of you.
- Skim the binding rules in
  [.claude/rules/analytics-engineering-rules.md](../.claude/rules/analytics-engineering-rules.md)
  — 47 short rules, each one a lesson someone learned the hard way.
- Read [WAY_OF_WORKING.md](WAY_OF_WORKING.md) for the working contract, and the repository
  [README](../README.md) for the full inventory.
