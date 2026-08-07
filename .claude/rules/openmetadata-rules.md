# OpenMetadata Rules

Binding rules for the OpenMetadata discovery-tier integration in this repository.

## Direction

1. **The pipeline is one way, and the catalog never wins.** Git is the source of
   truth for every model, description, definition, tag, and lineage edge.
   `scripts/openmetadata_sync.py` writes to the server; nothing reads the server
   and writes into this repository. Where the catalog and an artifact disagree,
   the artifact is right and the push is stale — regenerate, do not "fix" the
   catalog.
2. **Nothing is merged back, so nothing may be clobbered.** The dbt ingestion
   config sets `dbtUpdateDescriptions: false` and `dbtUpdateOwners: false`, and
   the push writes a column description only where the server has none. A
   unidirectional pipeline that overwrites human curation on every run is a
   deletion tool with a nicer name.

## Ownership

3. **The bridge never creates a Table.** `openmetadata-ingestion[dbt]` owns
   tables, descriptions, owners, dbt tests, and model-level lineage, configured
   by the generated `openmetadata/ingestion/dbt.yaml`. This bridge owns only
   what dbt cannot say: deep column lineage, the glossary, facet tags, and dlt
   provenance. Two generators, disjoint outputs — the same rule as the Wren
   bridge. A missing table means the connector has not run; pushing the bundle
   will not create it.
4. **One regeneration path.** `python3 scripts/use_case_sync.py --use-case <slug>
   --stage openmetadata`. It runs last because it projects `index.json`,
   `column-memory.json`, and `column-annotations.json`, all refreshed by earlier
   stages; running it earlier projects the previous generation.
5. **Everything under `<use-case>/openmetadata/` is generated.** Hand-edit
   nothing there. `openmetadata.yml` at the use-case root is the hand-authored
   input, and it is the only one.

## Definitions

6. **The service name is declared, never derived** (analytics rule 5). An
   OpenMetadata table FQN is `service.database.schema.table` and `service` names
   a Database Service registered on the server — a fact no dbt artifact holds.
   It lives in `openmetadata.yml`, `OPENMETADATA_DB_SERVICE` overrides it, and a
   use-case without one **skips**. A guessed service name produces a bundle whose
   every FQN resolves to nothing.
7. **An endpoint that resolves to no dbt node is dropped and counted.** Column
   lineage comes from parsed SQL, and a parse yields names that are not relations
   (`NULL`, an unnest alias, a struct field). They are reported in
   `bundle/column-lineage.json`'s `dropped` block, never emitted as edges to
   invented tables.
8. **No glossary term asserts a business definition nobody wrote.** A concept
   term's description states its core class, its suppliers, and its contract
   width — facts the repository holds. A conformed column's term carries the
   project's own recorded definition or says it has none. Prose invented to fill
   a required `description` field is the invented definition an ontology is
   famous for.
9. **`PII.None` is never written.** `PII.Sensitive` and `PII.NonSensitive` are
   OpenMetadata system tags; there is no third member, so `pii: direct` maps to
   `PII.Sensitive`, `quasi` and `indirect` get `ColumnPII.*` tags of our own, and
   `pii: none` is expressed by the absence of a PII tag. Unhiding or reclassifying
   a column means changing `column-annotations.json` and regenerating.
10. **An unannotated column gets no tag.** The absence of a `ColumnAdditivity`
    tag means nobody decided; it does not mean `Additive`. The generated
    `openmetadata/knowledge/catalog.md` states the uncovered count on every run
    for exactly this reason.

## Gates

11. **`--check` compares the bundle byte for byte.** The bundle is a committed
    artifact, so the stage is a real CI gate and not a note saying the gate could
    not run. `--check` never pushes.
12. **Nothing run-dependent goes in the bundle.** A dlt warehouse is gitignored
    and rebuildable, so it is read only behind `--with-warehouse`; a bundle that
    read one by default would differ between a machine that had built it and a
    fresh clone, and `--check` would be permanently red.
13. **Unavailable is not failed.** No `openmetadata.yml`, no manifest, no
    `openmetadata-ingestion` for the payload validation, no `duckdb` for the dlt
    warehouse — each skips with the remedy named.
14. **Pins move together, and the gate proves it.** The `external/OpenMetadata`
    submodule tag, `SERVER_PIN` in `scripts/openmetadata_sync.py`, and the
    `openmetadata-ingestion` wheel are one version (the wheel carries a fourth
    component: server `1.13.3` is wheel `1.13.3.0`).
    `scripts/sync_submodules.py --check` fails when the submodule tag and
    `SERVER_PIN` disagree, so bumping one without the other cannot merge.
    Upstream defects get a workaround in the bridge plus a ready-to-send patch
    under `external/patches/`, never a fork of a submodule.
15. **Upstream's schemas and vocabulary are read, never restated.**
    `check_against_pinned_spec` reads the enum members and required fields from
    `external/OpenMetadata`; `check_vocabulary` reads the `om:` terms from
    `external/OpenMetadataStandards`. Both **skip** when the submodule is not
    initialised — the normal state of a fresh clone — and a skip is reported, never
    counted as a pass. The RDF alignment uses upstream's terms and never redeclares
    them: redeclaring a term upstream owns makes this repository an authority on
    somebody else's ontology, which is how the two drift.

## Egress

16. **`--push` is data egress and is never implicit.** The `openmetadata` sync
    stage emits and pushes nothing. `scripts/openmetadata_sync.py --push` sends
    the bundle to the server named by `OPENMETADATA_SERVER_URL`: never without
    explicit, per-push user confirmation, and `--dry-run` first when the target
    is unfamiliar. `OPENMETADATA_SERVER_URL` and `OPENMETADATA_AUTH_TOKEN` live
    in the environment only — no generator, config file, or MCP registration ever
    writes a token to disk.
17. **There is no delete path, deliberately.** The bridge only PUTs and PATCHes.
    A generator that can delete a catalog entity from a bad artifact read is one
    regression away from emptying a production catalog.
