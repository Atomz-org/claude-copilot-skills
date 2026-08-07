# OpenMetadata integration

OpenMetadata is this repository's **discovery tier**: the human-facing catalog over the
same dbt use-cases WrenAI and Lightdash serve. WrenAI serves governed SQL and metric
definitions; Lightdash serves exploration and an in-app AI analyst; OpenMetadata serves
search, glossary, governance tags, and lineage a BI user can click through.

The pipeline is **unidirectional**. Git is the source of truth; the catalog is a
destination. Nothing reads the server and writes into this repository.

```
ontology artifacts ──► openmetadata/ bundle ──►(explicit push)──► OpenMetadata ──► BI users
   (committed)            (committed)              (never in CI)                 └─► agents
```

## How it is included, and why this shape

- **Bridge** is `scripts/openmetadata_sync.py`, run as the `openmetadata` stage of
  `use_case_sync.py` — sequenced last, after `wren` and `lightdash`, because it
  projects the widest set of artifacts (`index.json`, `column-memory.json`,
  `column-annotations.json`) and running it earlier would publish the previous
  generation.
- **Runtime** is `openmetadata-ingestion[dbt]==1.13.3.0`, matching server
  `1.13.3-release`. **Optional**, and used for two things only: upstream's dbt
  connector, and validating the emitted payloads against the server's own generated
  models. It is deliberately *not* the client — the wheel must match the server
  version exactly (the constraint `openmetadata-dbt-action` states in its own README),
  and a bridge that hard-depends on that pin breaks on every server upgrade. The push
  is `urllib` against the documented REST API and has no dependency to drift.
- **Agent surface** is `skill-packs/openmetadata-skills/` (skill `openmetadata-catalog`,
  command `/query-catalog`, rules `.claude/rules/openmetadata-rules.md`), plus the
  server's own MCP endpoint registered from
  `<use-case>/openmetadata/knowledge/mcp.md`.
- **Configuration** is one hand-authored file per use-case, `openmetadata.yml`.
- **Source** is eight shallow submodules under `external/`, pinned and listed below.
  Nothing is forked and nothing is vendored: the deployment topology, the JSON
  schemas, and the RDF vocabulary all stay upstream's to change, and this repository
  records which commit of each it was built against.

## The submodules, and which ones are load-bearing

| Submodule | Pinned at | Read by | Shallow clone |
| --- | --- | --- | --- |
| `external/OpenMetadata` | tag `1.13.3-release` | `check_against_pinned_spec` — validates every emitted payload against the JSON schemas | 403 MB |
| `external/OpenMetadataStandards` | `main` | `check_vocabulary` — validates every `om:` term in the RDF alignment against the OWL ontology | 18 MB |
| `external/openmetadata-dbt-action` | `main` | reference — the workflow shape `ingestion/dbt.yaml` reproduces | <1 MB |
| `external/openmetadata-demo` | `main` | reference — the API-lineage and MCP patterns | 7 MB |
| `external/openmetadata-ai-sdk` | `main` | reference — the agent-surface shape `/query-catalog` mirrors | 2 MB |
| `external/openmetadata-sqllineage` | `master` | reference — evaluated, not adopted (see below) | 3 MB |
| `external/openmetadata-retention` | `main` | reference — evaluated, not adopted | <1 MB |
| `external/collate-dbt-artifacts-parser` | `main` | reference — evaluated, not adopted | 1 MB |

Every one is `shallow = true` in `.gitmodules`, so `actions/checkout` and
`git submodule update --init --depth 1` fetch one commit. **OpenMetadata is 403 MB even
shallow** (16,531 files) — that is the real cost of this integration and it is stated
rather than discovered. `scripts/sync_submodules.py --init` clones only what is
missing.

**Two of the eight are load-bearing, and they earn it.** Before they were pinned, the
RDF alignment was written from documentation and got two things wrong that no test
could catch: the ontology namespace (`https://open-metadata.org/schema/`, actually
`.../ontology/`) and the asset-to-term relation (`om:glossaryTerm`, which does not
exist — `om:GlossaryTerm rdfs:subClassOf skos:Concept` and `om:Table rdfs:subClassOf
dcat:Dataset`, so the correct relation is DCAT's own `dcat:theme`). Both now fail the
emit. The remaining six are references: pinned so a reader can check a claim about
upstream against the commit the claim was made from, not read at runtime.

`skill-packs/openmetadata-skills/deploy/README.md` runs upstream's own compose file
**from the pinned submodule** rather than forking it or fetching it over the network.

## Two phases, and keeping them apart is the design

| | Runs | Writes | Gated by |
| --- | --- | --- | --- |
| **emit** (default) | every sync, offline, deterministic | `<use-case>/openmetadata/` | `--check`, byte for byte |
| **push** (`--push`) | never automatically | the server | explicit per-push confirmation |

The bundle is a committed artifact, exactly like `wren/` and `lightdash/knowledge/`.
That is what makes the stage a real CI gate instead of a note saying the gate could not
run — a stage whose only verification is "it reached a server nobody has" is the one
stage in this pipeline nothing can hold, and the bundle is exactly the part that goes
stale silently.

## What the bridge writes, and what it refuses to

| Bundle file | Holds | Derived from |
| --- | --- | --- |
| `ingestion/dbt.yaml` | upstream's dbt connector workflow | manifest/catalog/run_results paths |
| `bundle/column-lineage.json` | `AddLineageRequest` per table pair | `column-memory.json` bindings |
| `bundle/glossary.json` | concept and conformed-column terms | `index.json`, `column-annotations.json` |
| `bundle/classifications.json` | classifications and tags per facet | `column-annotations.json` `facets` |
| `bundle/tag-applications.json` | which tag lands on which column FQN | annotations + the manifest |
| `bundle/dlt-provenance.json` | dlt load columns and system tables | declared columns, or a dlt warehouse |
| `rdf/openmetadata-alignment.ttl` | the topology and column lineage in OpenMetadata's own RDF vocabulary | `index.json` + the ontology |
| `knowledge/*.md` | what to read before asking the catalog | everything above |

**It never creates a Table entity.** `openmetadata-ingestion[dbt]` already builds
tables, descriptions, owners, dbt tests, and model-level lineage from
manifest/catalog/run_results — that is what the connector is for. Re-deriving them here
would be a second source of truth fighting the connector field by field on every
ingest, so the mechanical layer is handed back to upstream as a generated workflow
config and this bridge owns only what dbt cannot say. Same rule as the Wren bridge
("enriches, never duplicates") and the Lightdash bridge ("never writes a metric"). A
missing table means the connector has not run; pushing the bundle will not create it.

Five refusals, each a way the catalog would read as authoritative while being wrong:

- **The service name is declared, never derived** (rule 5). An OpenMetadata table FQN
  is `service.database.schema.table`, and `service` names a Database Service registered
  on the server — a fact that appears nowhere in `manifest.json`. Guessing it produces
  a bundle whose every FQN resolves to nothing: the push 404s on the lucky day and
  attaches lineage to a same-named service on the unlucky one. No `openmetadata.yml`
  means the stage skips, with the file to write named.
- **An endpoint that resolves to no dbt node is dropped and counted.** Column lineage is
  parsed SQL, and a parse yields names that are not relations. Measured on
  enhanza-analytics: 87 of 92 distinct `source_model` values resolve to a manifest node;
  the other five — `NULL` (66 bindings), `author`, `attributes`,
  `DefaultDeliveryTypes`, `DefaultTemplates` — are parse artifacts, reported in the
  `dropped` block and never emitted as edges to invented tables.
- **`PII.None` is not written.** `PII.Sensitive` and `PII.NonSensitive` are
  OpenMetadata system tags; a third one is not. `pii: direct` maps to `PII.Sensitive`;
  `quasi` and `indirect` get `ColumnPII.*` tags of our own, because folding them into
  `NonSensitive` would state the opposite of what the annotation says; `pii: none` is
  the absence of a PII tag.
- **An unannotated column gets no tag.** 183 of enhanza's 272 conformed columns are
  unannotated. Tagging them `Additive` by default would put a number on a dashboard
  with a governance label next to it that nobody decided — the exact defect
  `column-annotations.json` exists to prevent. `knowledge/catalog.md` states the
  uncovered count on every run.
- **No glossary term asserts a business definition nobody wrote.** `description` is
  required on a glossary term and nothing here records what a concept *means* in prose
  — that is a human deliverable. A concept term states its core class, its suppliers,
  its adapters, and its contract width, and says outright that no business definition
  is asserted. Conformed-column terms carry the project's own recorded definition,
  which is why the 89 annotated columns produce genuinely useful terms and the other
  183 produce none.

There is also **no delete path**, deliberately: the bridge only PUTs and PATCHes. A
generator that can delete a catalog entity from a bad artifact read is one regression
away from emptying a production catalog.

## Lineage the standard connector cannot give you

The dbt connector builds lineage from `parent_map`: table to table. This repository
already resolves every conformed column through the whole chain — `select *`
passthroughs, renames, union branches — back to the raw source column, with the
transform class and the hop count (`scripts/dbt_column_lineage.py`, stored in
`ontology/column-memory.json`). Projecting that is the reason the bridge exists.

Measured on enhanza-analytics: **1024 bindings become 844 column-level lineage edges
across 110 table pairs**, transform classes `derived` 413 / `direct` 338 / `renamed`
174 / `union` 28, and **93 columns have more than one upstream source**. Those 93 are
one `ColumnLineage` with several `fromColumns` rather than several conflicting edges —
the shape the spec models natively, and the correct one for a union.

## The same lineage, in the vocabulary a knowledge graph speaks

`rdf/openmetadata-alignment.ttl` restates the alignment and the column lineage using
upstream's own terms, so a SPARQL consumer can read it without knowing this
repository's ontology. Three relations carry it, all already standard:

- `dcat:theme` — adapter table to its concept's glossary term.
- `om:hasColumn` — table to each conformed column it carries.
- `om:fromColumn` — conformed column to each raw column it came from. Upstream declares
  it `rdfs:subPropertyOf prov:used`, so the deep lineage arrives as **PROV provenance**
  for free.

It **uses** upstream's terms and never redeclares them. An earlier draft declared
`om:Table a owl:Class` in its own header, on the reasoning that a consumer meeting a
term has nowhere to look it up. That was right while the vocabulary was a guess and
wrong once it is pinned: redeclaring a term upstream already defines makes this file an
authority on somebody else's ontology, which is exactly how the two drift.

Measured on enhanza-analytics: **5,527 triples, 603 KB**, rdflib-clean, 953
`om:fromColumn` arcs over 29 glossary terms and 57 tables. That is the largest single
artifact in the use-case and the size is a deliberate trade, not an oversight: it is
bounded by the column contract rather than by an enumeration, and it is the only copy
of the lineage in a form a SPARQL or PROV consumer can read. Column IRIs are
`asset:`-prefixed rather than absolute — measured, absolute IRIs spent 63% of a 727 KB
file re-stating the same namespace ~3,500 times.

## The dlt load columns

A dlt-loaded warehouse carries columns no source system declares and no analyst
recognises: `_dlt_id`, `_dlt_load_id`, `_dlt_parent_id`, `_dlt_list_idx`,
`_dlt_root_id`, plus the `_dlt_loads` / `_dlt_version` / `_dlt_pipeline_state`
bookkeeping tables. Untagged they read as ordinary columns — `_dlt_list_idx` is an
integer that looks summable and `_dlt_id` is a string that looks like a business key.

The bridge gives each one a definition, a `DataProvenance.DltSystemColumn` tag, a
`ColumnRole.Identifier` tag (none of the five is a quantity), and a glossary term. The
*definitions* are a closed documented set and are always emitted; the *applications*
need evidence, from either:

- **what the dbt project declares** — free, committed, deterministic. A source contract
  listing `_dlt_load_id` is found without opening anything.
- **a dlt-loaded DuckDB warehouse**, behind `--with-warehouse`. Off by default, and
  that is a correctness decision: a warehouse is gitignored and rebuilt by
  `dlt_agent_costs.py --run`, so a committed bundle that read one would differ between a
  machine that had built it and a fresh clone, and `--check` would be permanently red.
  Same rule that keeps cache counters out of `column-memory.json`'s provenance block.

Measured against this repository's own dlt pipeline (`agent-costs-demo`, 5 tables):
**3 system tables tagged and 4 dlt columns found across the 2 data tables**. The payload
names which evidence it used, because a bundle reporting zero because nothing was read
must not read the same as one reporting zero because the warehouse has none.

## The sibling repositories, and what was taken from each

| Repository | What this integration took |
| --- | --- |
| [OpenMetadata](https://github.com/open-metadata/OpenMetadata) | the JSON schemas the bundle is written against — `addLineage`, `createGlossaryTerm`, `createClassification`, `tagLabel`, `dbtPipeline` — and the dbt connector itself |
| [OpenMetadataStandards](https://github.com/open-metadata/OpenMetadataStandards) | the RDF/OWL vocabulary and JSON-LD contexts under `rdf/`, which `rdf/openmetadata-alignment.ttl` projects this repository's topology into |
| [openmetadata-dbt-action](https://github.com/open-metadata/openmetadata-dbt-action) | the canonical dbt path — `metadata ingest -c <config>` over manifest/catalog/run_results — and the wheel-must-match-server pin, which the generated `ingestion/dbt.yaml` reproduces |
| [openmetadata-demo](https://github.com/open-metadata/openmetadata-demo) | the API-driven lineage and MCP patterns (`api-lineage-cicd`, `mcp`), which is why the push is REST rather than a custom connector |
| [ai-sdk](https://github.com/open-metadata/ai-sdk) | the agent surface shape — MCP tools over search, lineage traversal, and glossary — mirrored in `/query-catalog` without adding the `data-ai-sdk` dependency |

Three were evaluated and **not** adopted. They are still pinned, because a claim about
upstream is only checkable against the commit it was made from:

- **[openmetadata-sqllineage](https://github.com/open-metadata/openmetadata-sqllineage)**
  parses SQL to column lineage with a `sqlfluff` backend. This repository already
  resolves column lineage with sqlglot *through the dbt DAG*, which sqllineage cannot
  do: it reads one statement, while `column-memory.json` walks `select *` passthroughs
  and union branches across models to the raw source column. Adding it would be a
  second, shallower lineage source disagreeing with the first.
- **[openmetadata-retention](https://github.com/open-metadata/openmetadata-retention)**
  is an upstream demo application, marked work-in-progress, for expiring datasets on a
  server. Retention is a server-side policy, and this repository writes to the server
  and owns nothing on it.
- **[collate-dbt-artifacts-parser](https://github.com/open-metadata/collate-dbt-artifacts-parser)**
  gives typed dbt artifact objects. `scripts/_manifest.py` already reads these
  artifacts across every analyzer here, and a second reader would be a second opinion
  about what a manifest says.

## Running it

```bash
# the submodules (shallow; OpenMetadata alone is 403 MB)
python3 scripts/sync_submodules.py --init
python3 scripts/sync_submodules.py --check     # pins agree, no drifted checkout

# the one regeneration path (the whole bundle)
python3 scripts/use_case_sync.py --use-case enhanza-analytics --stage openmetadata

# the CI gate form — the bundle is committed, so this compares bytes
python3 scripts/use_case_sync.py --all --stage openmetadata --check

# a local server (upstream's compose at the pinned release; podman needs ~8 GiB)
# see skill-packs/openmetadata-skills/deploy/README.md

# 1. the mechanical layer — tables, dbt tests, model-level lineage
pip install 'openmetadata-ingestion[dbt]==1.13.3.0'
metadata ingest -c skill-packs/dbt-skills/use-cases/<slug>/openmetadata/ingestion/dbt.yaml

# 2. count the requests without sending any
python3 scripts/openmetadata_sync.py --use-case <slug> --push --dry-run

# 3. the enrichment layer — ONLY after explicit confirmation (rule 16)
python3 scripts/openmetadata_sync.py --use-case <slug> --push
```

Measured dry-run for enhanza-analytics: **399 requests** — 5 classifications, 22 tags,
1 glossary, 147 glossary terms, 110 lineage edges, 57 table-tag patches, and 57
read-then-patch pairs for the 436 column tags.

Order matters and is not cosmetic: a lineage edge whose endpoint table does not exist
is rejected, and a tag label naming a classification that does not exist is rejected.
Both are the correct signal that the connector has not run — which is precisely why the
bridge does not create tables to paper over it.

## Credentials

`OPENMETADATA_SERVER_URL`, `OPENMETADATA_AUTH_TOKEN`, and the optional
`OPENMETADATA_DB_SERVICE` live in the environment only. No generator, config file, or
MCP registration ever writes a token to disk; every generated file uses
`${OPENMETADATA_AUTH_TOKEN}`, and a test asserts it.
