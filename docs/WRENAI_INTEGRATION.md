# WrenAI integration

This repository includes [WrenAI](https://github.com/PackMaaan/WrenAI) — the open-source
semantic layer / GenBI engine — as its serving tier: a dbt use-case's models, ontology,
column contracts, and MetricFlow metrics are projected into a Wren MDL project that an
agent (or a human) queries through governed SQL and structured cubes.

## How it is included, and why this shape

| Piece | Where | Why this and not the alternative |
|---|---|---|
| Source tree | `external/WrenAI` (git submodule, pinned SHA) | Full source is in the repo at an auditable pin. Vendoring 24 MB of a fast-moving 8-component monorepo would drown this repo's diffs, hide a future AGPL path flip (upstream stages the license text pre-emptively), and redistribute trademarked assets under this repo's name. Clone with `git clone --recurse-submodules`. |
| Runtime | `wrenai==0.13.2` wheel, pinned in `requirements.txt` | Upstream's intended consumption path. Building the Rust core from source needs a toolchain (cargo, maturin, wasm-pack) nothing else here needs. The pin moves together with the submodule SHA. |
| Agent surface | `skill-packs/wren-skills/` (skill `wren-genbi`, command `/wren`, rules) | Follows upstream's own anti-duplication design: the skill is a discovery stub; workflow guides live inside the CLI (`wren skills get <name>`) and are always version-matched to the installed wheel. Nothing is copied that can drift. |
| Bridge | `scripts/wren_context_sync.py`, the `wren` stage of `scripts/use_case_sync.py` | WrenAI already imports dbt natively (`wren context import dbt`). The bridge orchestrates that importer and adds only what dbt alone cannot know — see below. |
| Upstream fixes | `external/patches/` | A defect found here becomes a bridge workaround plus a ready-to-send patch. The submodule never drifts from upstream. |

## What the bridge adds (and what it refuses to)

`wren context import dbt` produces the mechanical layer: one Wren model per dbt model and
source, columns and descriptions from `catalog.json`, relationships from dbt
`relationships` tests. The bridge then enriches from artifacts this repository already
derives — the two generators own **disjoint files**, so either can regenerate without
destroying the other's output, and unknown files (hand-authored knowledge) are reported as
`stale` and never touched:

| Enrichment | Source | Lands in |
|---|---|---|
| Business concepts + coverage gaps | `ontology/index.json` | `knowledge/rules/ontology-concepts.md` |
| Conformed column contracts | `ontology/column-memory.json` | `knowledge/rules/column-contracts.md` |
| Adapter drift caveats | column-memory `drift` | `knowledge/caveats/adapter-drift.md` |
| Metric definitions (canonical: MetricFlow) | manifest `metrics` | `knowledge/rules/semantic-metrics.md` |
| Cubes (measures/dimensions/time, typed) | manifest `semantic_models` + `catalog.json` | `cubes/<name>/metadata.yml` |

Refusals, each a rule before it was code:

- **Types are read from `catalog.json` or the part is skipped and counted** — an
  approximated type is a wrong contract that plans successfully (analytics rule 5).
- **No invented relationships.** Only joins that dbt tests declare exist reach
  `relationships.yml`; the ontology names concepts, not join conditions.
- **Nothing run-dependent enters the committed tree**, so `--check` stays meaningful:
  `wren/target/` and `.wren/` are gitignored and rebuilt by one command.
- **Missing inputs skip with the remedy named** (no manifest → `dbt parse`; no catalog →
  `dbt docs generate`; no CLI → `pip install -r requirements.txt`). The `--all --check`
  gate stays green on a bare runner.

Known upstream defect worked around: wrenai 0.13.2's importer crashes on model-level dbt
tests (`column_name: None` breaks a sort). The bridge hides exactly those rows from
`run_results.json` for the duration of the import and restores the file on any exit;
the one-line fix is staged at `external/patches/wrenai-dbt-import-columnless-tests.patch`.

## Running it

```bash
# regenerate a use-case's wren/ project (skips name their remedy)
python3 scripts/use_case_sync.py --use-case example-order-revenue-mart --stage wren

# the end-to-end demo: dbt build -> import+enrich -> validate/build -> governed query
# cross-checked for exact row equality against DuckDB directly. Local, no Docker, no keys.
./skill-packs/wren-skills/demo/run_wren_demo.sh
```

Measured on `example-order-revenue-mart`: 13 models (8 dbt + 5 raw sources), 3
relationships from dbt tests, 2 cubes projected from the MetricFlow semantic models,
validate clean, and the governed revenue-by-region query equal to direct DuckDB row for
row. Regeneration is idempotent (second run: 0 changed files) and `--check` writes
nothing. `tests/test_wren_context_sync.py` pins all of it.

On `enhanza-analytics` the stage reports `skip — no catalog.json` until the demo target is
built (`dbt build --target demo && dbt docs generate` with the seeded DuckDB); the
enrichment there carries 29 column contracts and 58 ontology concepts into the Wren
knowledge layer.

## Day-to-day agent workflow

```bash
wren skills get usage            # the CLI serves its own workflow guides
wren dry-plan --sql '...'        # plan through MDL, no database — the cheap gate
wren query --sql '...'           # governed execution
wren cube query --cube orders --measures order_count --dimensions order_status
wren serve mcp --transport stdio # optional: expose the project as MCP tools
```

Binding rules: `skill-packs/wren-skills/.claude/rules/wren-rules.md` (ownership,
regeneration, gates, and the `wren genbi deploy` egress rule).
