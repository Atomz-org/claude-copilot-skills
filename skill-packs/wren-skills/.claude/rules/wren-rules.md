# WrenAI Rules

Binding rules for the WrenAI semantic-layer integration in this repository.

## Ownership

1. **Two generators, disjoint files, regenerate-never-edit.** WrenAI's importer owns
   `wren_project.yml`, `models/`, `relationships.yml`, `knowledge/rules/general.md`,
   `knowledge/sql/*`, and `AGENTS.md`. `scripts/wren_context_sync.py` owns
   `knowledge/rules/ontology-concepts.md`, `column-contracts.md`, `column-semantics.md`,
   `semantic-metrics.md`, `knowledge/caveats/adapter-drift.md`, `knowledge/caveats/pii.md`,
   and every view under `views/` carrying the
   `source: dbt_metric` marker — a hand-authored view in the same directory has no
   marker and is reported `stale`, never touched. Hand-authored knowledge goes in
   **other** filenames under `knowledge/` — both generators leave unknown files alone and
   report them as `stale`, never delete them.
2. **One regeneration path.** `python3 scripts/use_case_sync.py --use-case <slug>
   --stage wren`. A direct importer run bypasses the enrichment, the sanitizers for the
   upstream defects (external/patches/), and the validate/build gate.
3. **Derived state stays out of the tree.** `wren/target/`, `.wren/`, `wren/mcp.json`,
   and `wren/.wren-home/` are gitignored; `wren context build` recreates
   `target/mdl.json` from committed YAML in one command, and the sync rewrites the
   MCP config (absolute, per-clone paths) on every run.

## Definitions

4. **MetricFlow is the metric's source of truth** (analytics rule 42). Each metric and
   saved query compiles to an MDL **view of the same name** — filter, ratio legs,
   offsets, and windows included — and `semantic-metrics.md` narrates the same
   definitions. `SELECT * FROM <metric>` through the engine *is* the metric; changing
   one means changing the dbt semantic layer and regenerating, never editing the
   projection. The equivalence gate (`tests/test_wren_semantic_equivalence.py`) holds
   the two to the same numbers.
5. **Types come from the catalog, never from guesses** (analytics rule 5). A metric
   whose type or parameters have no faithful SQL compilation is skipped and counted in
   the payload — an approximated definition is a wrong contract that plans
   successfully. Catalog types also enter the generated SQL as casts, because
   wren-core registers parameterized DECIMAL as Utf8 inside view planning
   (external/patches/).

## Gates

6. **`wren dry-plan` and `wren context validate` are the no-warehouse gates.** Both run
   with no database and no credentials; there is no reason a wren/ change reaches review
   unvalidated.
7. **Unavailable is not failed.** No `wren` CLI, no manifest, or no `catalog.json` makes
   the stage skip with the remedy named. A gate that goes red on a correct state gets
   switched off within a week.
8. **Upstream defects get a patch file, not a fork-drift.** The submodule stays pinned to
   upstream; a defect found here lands as a workaround in the bridge plus a ready-to-send
   patch under `external/patches/`, removed when the pinned wheel ships the fix.

## Egress

9. **`wren genbi deploy` ships app bundles — possibly including snapshot data — to
   Vercel/Cloudflare.** That is data egress: never run it without the user's explicit,
   per-deploy confirmation, and never with real-warehouse snapshots unless the user has
   said so for that dataset.
