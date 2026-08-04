# WrenAI Rules

Binding rules for the WrenAI semantic-layer integration in this repository.

## Ownership

1. **Two generators, disjoint files, regenerate-never-edit.** WrenAI's importer owns
   `wren_project.yml`, `models/`, `relationships.yml`, `knowledge/rules/general.md`,
   `knowledge/sql/*`, and `AGENTS.md`. `scripts/wren_context_sync.py` owns
   `knowledge/rules/ontology-concepts.md`, `column-contracts.md`, `semantic-metrics.md`,
   `knowledge/caveats/adapter-drift.md`, and `cubes/*`. Hand-authored knowledge goes in
   **other** filenames under `knowledge/` — both generators leave unknown files alone and
   report them as `stale`, never delete them.
2. **One regeneration path.** `python3 scripts/use_case_sync.py --use-case <slug>
   --stage wren`. A direct importer run bypasses the enrichment, the sanitizer for the
   upstream sort defect (external/patches/), and the validate/build gate.
3. **Derived state stays out of the tree.** `wren/target/` and `.wren/` are gitignored;
   `wren context build` recreates `target/mdl.json` from committed YAML in one command.

## Definitions

4. **MetricFlow is the metric's source of truth** (analytics rule 42). The Wren cubes and
   `semantic-metrics.md` are *projections* of `models/semantic/`; changing a metric means
   changing the dbt semantic layer and regenerating, never editing the projection.
5. **Types come from the catalog, never from guesses** (analytics rule 5). A measure or
   dimension whose type cannot be read from `catalog.json` is skipped and counted in the
   payload — an approximated type is a wrong contract that plans successfully.

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
