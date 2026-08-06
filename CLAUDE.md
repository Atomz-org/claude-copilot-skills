# Unified Operating Manual

Repository name: `code-skills`

This repository combines:

- Git workflow automation and reusable scaffold operations
- Senior analytics-engineering methods for dbt Core projects
- RTK-style toolkit routing, graph state, and memory capture
- The WrenAI semantic-layer serving tier over dbt use-cases (`docs/WRENAI_INTEGRATION.md`)

## Graphify-first rule

**This section is the single source of truth for graph navigation in this repository.**
Any other copy — a user-level protocol file, a source manual under `docs/source-manuals/` —
is superseded by it. State the rule here or not at all.

This project uses graph-based navigation when graph outputs are present.

Rules:
- For codebase questions, run `graphify query "<question>"` when `graphify-out/graph.json` exists.
- For relationships, use `graphify path "<A>" "<B>"`.
- For focused concepts, use `graphify explain "<concept>"`.
- If `graphify-out/wiki/index.md` exists, use it for broad navigation first.
- Read `graphify-out/GRAPH_REPORT.md` only for broad architecture review or when scoped queries are insufficient.
- After meaningful code edits, run `graphify update .` to keep graph state current.

CLI behavior, verified against the installed graphify:
- Traversal is fixed at BFS depth=2. `--depth` is accepted and **silently ignored** — do not
  rely on it to narrow a query.
- `--budget N` is the working lever. Raise it when output reports `TRUNCATED`, or narrow the
  question instead.

### TOON context pipeline

Graph output that is carried forward into LLM context is serialized as TOON
(Token-Oriented Object Notation, https://github.com/toon-format/spec), which declares
fields once and streams uniform rows instead of repeating keys per record:

```bash
# build the serializer once per clone (plain rustc -O, no cargo)
./scripts/build_toon_rs.sh

graphify query "<question>" --budget 800 | rust/toon/bin/graph_to_toon      # text → TOON
rust/toon/bin/graph_to_toon --graph graphify-out/graph.json --community "<x>"  # graph.json → TOON
... | rust/toon/bin/graph_to_toon --decode                                  # TOON → JSON for machines
```

The serializer is `rust/toon/graph_to_toon.rs`; its full functionality contract lives as
comments in that file, and `tests/test_toon_serializer.py` pins the behavior at the CLI
level (`tests/conftest.py` builds the binary on demand where `rustc` exists). TypeScript
call sites route through `src/ai-core/toon-serializer.ts` (`GraphManager.snapshotToToon()`).

It also encodes **arbitrary JSON**, not only graphify output — plain JSON on stdin comes
back as TOON. So a repo script that wants TOON emits `--format json` and pipes; it does not
get its own serializer.

**Route a script through TOON only when it was measured to help.** Every emitter that
offers `--format json` was measured on real enhanza-analytics data. Bytes, not looks:

| Command | text | TOON | | |
|---|---|---|---|---|
| `dbt_column_lineage.py` (40 edges) | 5445 | **3212** | −41% | routed |
| `connector_alignment_check.py` (all connectors) | 1332 | **909** | −31% | routed |
| `dbt_column_lineage.py --column OrgName` | 3378 | **2442** | −27% | routed |
| `dbt_seed_generator.py --dry-run` | 228 | 207 | −9% | rejected, noise |
| `ontology_generator.py --check` | **195** | 225 | +15% | rejected |
| `dbt_column_memory.py --concept dim_articles` | **4042** | 5292 | +30% | rejected |
| `wren_context_sync.py --check` | **145** | 211 | +45% | rejected |
| `use_case_sync.py --check` | **587** | 854 | +45% | rejected |
| `dbt_manifest_to_graphify.py --dry-run` | **271** | 633 | +136% | rejected |
| `dbt_column_memory.py` (default report) | **297** | 694 | +133% | rejected |

The two winners are the two whose payload is *one uniform record list* — drift findings,
and 5-field lineage edges — so field names and the shared path prefix are stated once
instead of once per row. Both are in `scripts/hooks/toon_graphify_pipe.py`'s
`_TOON_SCRIPTS`; `--limit` (default 40) applies to text and json alike, so those byte
counts describe the same rows and TOON is not winning by truncating.

Everything else loses for one reason: its text output is already a handful of lines of
counts, while the JSON form carries more fields than the prose states. A format cannot
rescue output that is not a record list. `--format json` still exists on all of them for
machine consumption.

`dbt_column_memory.py --concept` is the instructive rejection. It first measured as an
82% *win* — which was `--format json` silently ignoring `--concept` and printing the
whole-store summary instead, byte-identical to the run without the flag. The projection
now exists (`concept.found`, `columns`, `suppliers`, `bindings`), the honest number is
+30%, and it stays out. **A measurement through a broken code path measures the broken
path.** Pinned by `test_concept_is_projected_into_json_not_silently_dropped`.

Rejections are pinned too, in `test_measured_losers_stay_unrouted` — otherwise the next
person re-derives the table from scratch.

The committed artifacts stay JSON, and that is also measured: `column-memory.json` is
−54% and `index.json` −33% as TOON, but both are read by machines. The one that would
*not* benefit is the big one — `graphify-fragment.json` gains **1%**, because its nodes
carry four different key-sets, so no single tabular header covers the array.

Two rules that fall out of this:

- **A format cannot rescue an unbounded dump.** Emitting all 332 untested model names cost
  10 KB in TOON; the count plus a 10-name sample costs 200 bytes and answers the same
  question. Cap lists, then serialize.
- **A rewritten command needs `set -o pipefail`.** These scripts signal failure through the
  exit status, and a pipeline reports the *last* command's code — without pipefail a
  failing `--check` gate goes silently green.

`dbt` has no rtk filter, so `artifacts/refresh.sh` routes it through `rtk err`
(408 chars → 68 on a successful parse) and falls back to the raw binary when rtk is absent.

### Enforcement

Enforcement is automatic, not manual — `.claude/settings.json` registers all of it; do not
add duplicate mechanisms:

- `graphify hook-guard` (`PreToolUse` on `Bash|Grep` and `Read|Glob`) injects the
  graph-first reminder at call time.
- `scripts/hooks/toon_graphify_pipe.py` (`PreToolUse` on `Bash`) rewrites bare
  `graphify query|path|explain` commands to pipe through
  `rust/toon/bin/graph_to_toon --passthrough`, and stays silent when the binary is not
  built. Composed commands (existing pipes, redirects) are left alone; `--passthrough`
  forwards unrecognized output unchanged, so the rewrite can never break a command.
- `scripts/hooks/toon_prompt_context.sh` (`UserPromptSubmit`) asserts the pipeline once
  per prompt.

Hook behavior is pinned by `tests/test_toon_pipeline_hooks.py`.

## dbt lineage in the graph

`graphify` has no SQL parser. `.sql` is classified as code, handed to the AST extractor,
and the extractor finds no symbols — so a dbt model enters the graph as an isolated file
node. Measured here: 393 `.sql` nodes, **393 of them at degree 0**, with the whole dbt DAG
absent and the only dbt entity carrying edges being a `schema.yml` node.

dbt already computes that DAG. `scripts/dbt_manifest_to_graphify.py` reads `manifest.json`
and emits a graphify extraction fragment whose node IDs **reproduce graphify's own formula
byte for byte**, so `build_merge` upgrades the existing degree-0 nodes instead of adding
duplicates beside them. Every edge is `EXTRACTED` at confidence 1.0 — dbt compiled it.

```bash
# refresh the manifest, the committed fragment, and the alignment check in one step
./skill-packs/dbt-skills/use-cases/enhanza-analytics/artifacts/refresh.sh

# merge into graphify-out/graph.json
python3 scripts/dbt_manifest_to_graphify.py --manifest <path>/target/manifest.json --merge
```

Two rules decide whether the result is trustworthy:

- **Parse with every connector enabled.** enhanza-analytics gates each connector behind an
  `is_<source>_enabled` var defaulting to false, so `dbt parse` with defaults writes a
  manifest holding a fraction of the project — 72 of 359 models before this was wired up,
  internally consistent and silently partial. `refresh.sh` derives the full var set from
  `dbt_project.yml`; the emitter's coverage gate refuses to emit below 95% of the `.sql`
  files on disk.
- **The fragment is committed, the manifest is not.** 736 KB versus 3.0 MB, churning on
  every model edit, and the fragment is what graphify consumes — so a fresh clone rebuilds
  dbt lineage with no dbt and no warehouse.

`scripts/connector_alignment_check.py` is the gate for new connectors. It imports
`new_connector.detect()` rather than restating conventions, so the scaffolder and the
checker cannot disagree about what the convention is. Run it with `--check` in CI; it needs
no warehouse, no profile, and no parse.

Accepted warnings on enhanza-analytics, do not re-report:

- **`naming: fortnox_base_v2_invoices`.** `base_` is a real dbt convention for a
  pre-staging model, and this one exists to apply the start-year filter once for the five
  staging models that read it. The checker only knows this project's two shapes. Renaming
  it is six files of churn to satisfy a heuristic.
- **`no-freshness` × 8.** Every source needs `loaded_at_field` and a `freshness:` block
  ([rule 14](.claude/rules/analytics-engineering-rules.md)) and **nobody may invent one**
  ([rule 5](.claude/rules/analytics-engineering-rules.md)) — the SLA is a fact about the
  upstream pipeline, not a number to pick. This stays a warning until someone who knows
  each connector's load cadence supplies it.

### Column lineage

dbt Core stops at model-level lineage. `scripts/dbt_column_lineage.py` parses each model's
`raw_code` with **sqlglot** — an optional dependency, the same shape as orjson in
`_manifest.py` — and derives which upstream column each output column came from, classified
`direct` / `renamed` / `derived` / `passthrough` / `union`. Raw code rather than compiled
SQL, because `dbt compile` needs a live warehouse and this project's local profile is duckdb
while its real target is BigQuery.

```bash
python3 scripts/dbt_column_lineage.py --manifest <path> --column OrgName
python3 scripts/dbt_manifest_to_graphify.py --manifest <path> --with-columns --merge
```

Coverage is stated, never implied: 225 of 359 models parse, 134 are macro-only and resolved
structurally, **0 fail**. `--with-columns` roughly doubles the graph
(3058 → 6382 nodes), so it is a flag rather than a default.

**Anything inferred by parsing can be confidently wrong**, which is why
`tests/test_dbt_column_lineage.py` pins each resolver bug found while building it:

- Deleting `{% ... %}` tags and keeping what is between them is wrong for the two block
  forms that carry SQL. `{% if a %} X {% else %} NULL {% endif %} as C` collapses to
  `X NULL as C` — every branch survives and they concatenate — and a `{% set q %}...
  {% endset %}` body is assigned to a *variable*, so keeping it splices a second query into
  the middle of the first. `resolve_jinja_blocks()` keeps the first branch and drops set
  bodies. This was all five of the project's parse failures.
- One substitution cannot be valid everywhere at once. A model with a macro in its select
  list *and* one after its FROM fails all four uniform forms, so a bounded per-occurrence
  pass tries combinations — capped at `MAX_MIXED_MACROS`, and only for a model the uniform
  pass could not read. Measured: **parse failures 5 → 0** on 359 models.

- `find_all(exp.Table)` walks the whole subtree, so an outer SELECT claimed its CTE's base
  table as its own source and invented `src.OrgName` beside the true `src.companyName`.
- sqlglot 30 renamed the `from` arg to `from_`; reading only the old key turned every edge
  `unresolved` in silence.
- A bare macro marker in a select list parses as an *alias* — `City JINJA_EXPR` becomes
  `City AS JINJA_EXPR` and `City` vanishes. A parse succeeding is not enough; the result is
  checked for absorption.
- BigQuery's `unnest(x) r` binds `r` in a `TableAlias.columns` list, not as `.alias`.
  Missing that attributed a non-existent column `r` to the base table, 120 edges of it.

The payoff is `check_adapter_column_drift`: `erp_union()` stacks one adapter per enabled
source, so an adapter that omits a column its peers carry breaks the union **only when two
connectors are enabled at once** — the connector's own build passes and the failure waits
for a tenant with both. It found `visma_economic_erp_bi_dim_articles` calling a column
`isActive` where five peers call it `Active`.

### Column memory — the store an agent actually reads

`scripts/dbt_column_lineage.py` is the primitive; `scripts/dbt_column_memory.py` is what
makes it usable. It fixes three things about the primitive and adds nothing else:

| | |
|---|---|
| **Currency** | `raw_code` is a snapshot from the last `dbt parse`. A model whose file has moved since is re-parsed **from disk** instead. |
| **Cost** | per-model results cached on the model's content hash, so editing one model re-parses one model — **1.6s cold, 0.35s warm** on 359 models. |
| **Depth** | `resolve()` walks the whole chain to the raw source column, through `select *` passthroughs and union branches, and names every transform it crossed. |

```bash
python3 scripts/dbt_column_memory.py --use-case enhanza-analytics --concept dim_articles
python3 scripts/dbt_column_memory.py --use-case enhanza-analytics --write   # the artifact
python3 scripts/dbt_column_memory.py --use-case enhanza-analytics --check   # the CI gate
python3 scripts/dbt_column_memory.py --use-case enhanza-analytics --merge-graphify
```

Freshness is free and exact: every manifest node carries `checksum.checksum`, which is
`sha256(file_bytes.strip())` — dbt's `FileHash.from_contents` strips before hashing.
Measured here: **359 of 359 models match**. Drop the `.strip()` and 36 of 97 mismatch, the
incremental rebuild silently degrades to a full one, and `--check` never goes green.

Package roots resolve from **each package's own `dbt_project.yml name:`**, never by
transforming the directory name. `packages/favrit/` declares `enhanza_favrit`, so a prefix
rule works here and would break silently on the first package where the two diverge — by
reporting all of its models as deleted.

Three rules decide whether the output can be trusted:

- **`select *` is expanded, not skipped.** Most adapters here are
  `select *, {{ add_erp_fields(...) }} from ref(...)` and declare no named column at all.
  Reading named projections only gave 20 of 30 concepts a contract, and the ten it dropped
  included `dim_accounts`, which five connectors supply. A conformance check silent on the
  concepts most likely to drift is worse than none.
- **Incomplete is carried through, but never as silence.** A macro-generated column list
  cannot be named, so the contract says `partial_for` and those connectors stay out of
  `missing_from` — a connector that *might* have the column is not accused of dropping it.
  It is still reported, as `drift.confidence: suspected`. Emitting nothing was a real bug,
  found by onboarding a throwaway connector end to end: an adapter that drops a column
  *and* calls `add_erp_fields(...)` is `partial`, so the drop landed in `unknown_for` and
  this file read "0 drift findings" while `connector_alignment_check.py` reported an error
  on the same adapter. Two detectors disagreeing is worse than one being wrong, because the
  quiet one is the one people read.
- **Nothing run-dependent goes in the artifact.** Cache counters and manifest timestamps in
  `provenance` made the file change when the project had not, so `--check` was permanently
  red. Run statistics are printed, never written.

The artifact is `ontology/column-memory.json` (448 KB, committed); the cache is
`.dbt-column-cache/` (gitignored, rebuildable in 1.6s). Same split, same reasons, as the
graphify fragment versus the manifest.

**It is regenerated automatically.** `scripts/hooks/dbt_column_memory_watch.py` runs on
`PostToolUse` for `Edit|Write|MultiEdit` and rebuilds the store when the edited file is a
`.sql`/`.yml` under a `dbt_project/`. It probes with `--stale-only` first (no parser, no
ontology, ~0.3s) and only then rebuilds. It **never blocks** — PostToolUse fires after the
edit has landed, so a non-zero exit cannot undo anything and can only break the agent's next
step for an unrelated reason. `use_case_sync.py`'s `columns` stage is the same work at
review time.

### Source column contracts — the one input nobody can derive

Adding a connector has exactly **one** genuinely unknown input: the raw table's column list.
Every other column in the project is a rename of it. That one unknown was also the only thing
nobody wrote down — measured before this: **200 source tables declared in `sources.yml`, zero
of them declaring `columns:`.** The raw schema existed only inside whatever somebody hand-typed
into a staging model, which is why adapter drift was detectable downstream but not preventable
upstream.

```bash
python3 scripts/dbt_column_memory.py --use-case <slug> --emit-source-columns --write
./skill-packs/dbt-skills/use-cases/<slug>/artifacts/refresh.sh   # dbt re-reads them
```

Bootstrapped here: **804 columns across 99 tables in 12 files, 1200 insertions and 0
deletions**, dbt parse clean. Then `check_source_columns` in
`scripts/connector_alignment_check.py` makes them load-bearing — staging reading a column its
source does not declare is an `error`.

A source contract is a statement of **what this project depends on, not an inventory of what
the API returns**. Declare the ten fields staging reads, not the forty available. Upstream can
then add fields freely, and removing one you declared becomes a detectable breaking change
instead of a warehouse error at 3am.

Four rules, each of which was a bug first:

- **Insert text, never round-trip the YAML.** These files carry Jinja in load-bearing
  positions — `schema: fortnox_api_{{ var('demo_uid', var('uid')) }}` — and a YAML library
  either rejects it or re-emits it quoted so dbt stops rendering it. A round-trip also drops
  every comment. The gate is that the diff is **insertions only**.
- **Key by `(source, table)`, never by table alone.** Two `sources.yml` here declare three
  and five sources; nothing stops two of them exposing a `customers`. It does not collide
  today and is one added table away from writing one source's columns under another's table,
  silently.
- **A table that already declares `columns:` is left alone.** The generated list bootstraps a
  contract a human then owns; overwriting a hand-authored one makes the generator the
  authority on a fact it only inferred.
- **A source with no contract is skipped, not failed.** Most of a project has no contract the
  day this lands, and a gate that goes red on a correct state gets switched off within a week.

Order of work follows from this. Read the contract **before** writing the adapter, not after:
`--concept <name>` gives the column list in order plus the raw field each existing connector
mapped. Staging then has one job — land those names — and the adapter becomes mechanical.

### Where the column contract goes, and why it is three places

Not three copies of one fact — three consumers that cannot read each other's format:

| Destination | Holds | Why not the others |
|---|---|---|
| `ontology/column-memory.json` | contracts, bindings, drift | the store of record; reviewable diff |
| `graphify-out/graph.json` | contract + drift nodes, edged to the adapter models | the Graphify-first rule makes `graphify query` the first move, so a contract outside the graph is a contract nobody finds during orientation |
| AgentMemory | the contract, the drift, and a locator | survives the session; BM25-findable by concept and column name |

The graphify fragment reuses `dbt_manifest_to_graphify.node_id()`, so its 57 edges attach to
adapter model nodes that already exist — measured: **+29 nodes, +57 edges, 0 duplicates, all
359 dbt models still present**. Merge it with `--merge-graphify`, and the same ordering rule
applies: **never run `graphify update` afterwards.**

`--remember` writes **contracts, drift, and one locator — never the edge set.** `:3111` is a
single global store with no namespace and BM25 recall, so 1024 mechanical binding records
would bury the decisions it exists to hold. Every record is phrased with the words the
question would use. `--remember-bindings` adds the resolved bindings, capped at 120.

## Use-case derived artifacts — one command

A use-case is one hand-written thing — the spec plus the dbt project — and a set of derived
ones. `scripts/use_case_sync.py` runs every stage in dependency order and reports each as
`ok`, `changed`, or `skip` with a reason:

```bash
python3 scripts/use_case_sync.py --init <slug>                       # scaffold a use-case
python3 scripts/use_case_sync.py --use-case <slug> --graphify-update # regenerate everything
python3 scripts/use_case_sync.py --all --check                       # the CI gate form
```

| Stage | Produces | Needs |
|---|---|---|
| `taxonomy` | `ontology/conceptual-model.json` — what the project *should* build | `sources.yml`, `taxonomy.yml` |
| `columns` | `ontology/column-memory.json` — the column contract | manifest, sqlglot |
| `annotations` | `ontology/column-annotations.json` — what each column *means* | `annotations.yml`, column-memory |
| `ontology` | `ontology/connectors/*.ttl`, `topology/*.ttl` | `connectors.yml`, annotations |
| `index` | `ontology/index.json` — the machine-facing projection | same generator pass |
| `seeds` | `dbt_project/seeds/sample/*.csv` | manifest, sqlglot, reference data |
| `graphify` | the code graph, rebuilt | `--graphify-update` |
| `graph` | dbt lineage + connector/concept topology merged into `graphify-out/graph.json` | manifest |
| `alignment` | the convention-drift verdict | a dbt project |
| `wren` | `wren/` — the WrenAI semantic-layer project | manifest, catalog.json, wrenai CLI |

The `wren` stage is sequenced last on purpose: it projects the artifacts the earlier
stages just refreshed (`index.json`, `column-memory.json`), so running it earlier would
enrich from the previous generation.

`columns → annotations → ontology` is one chain, and it is the whole path from raw data to
a served semantic layer:

```
raw layer ─ taxonomy ─┐
                      ├─ columns ─ annotations ─ ontology ─ wren ─ BI / MCP
dbt models ───────────┘             (decisions)   (RDF+index)  (knowledge)
```

Each link reads the one before it. Annotations are keyed on the conformed columns
`columns` derives; the ontology projects them into `topology/column-semantics.ttl` and
`index.json`'s `column_semantics`; the `wren` stage turns that into
`knowledge/rules/column-semantics.md` and `knowledge/caveats/pii.md`. Run `ontology` first
— where it used to sit — and every artifact still regenerates, every stage still reports
`ok`, and the ontology describes the previous generation's columns.

`/new-use-case` and `/new-connector` both end here. The gate is the existing test suite —
`tests/test_use_case_sync.py` asserts the committed artifacts are current — so **do not add
a separate CI step for it**.

**Never run `graphify update` after a dbt merge.** graphify has no SQL parser, so its AST
pass extracts nothing from a `.sql` file and drops the node rather than keeping it at degree
0; a rebuild after the merge deletes all 359 models and their 1288 edges while leaving a
graph that still looks populated, because the source nodes have no file to be re-extracted
from. Measured here: 366 model nodes with the correct order, 0 with the wrong one. That is
why the rebuild is a stage sequenced *before* the merge rather than a line in a runbook, and
why `--all --graphify-update` rebuilds once for the repository instead of once per use-case.

The `graph` stage merges four fragments in sequence, all manifest- or artifact-derived
and all protected by the same rebuild-before-merge ordering:

1. **dbt lineage** (`dbt_manifest_to_graphify.py`) — the model DAG.
2. **connector/concept topology** (`ontology_generator.py --merge-graphify`) — one node
   per connector and per conformed concept, connectors edging `supplies` /
   `plans_to_supply` into the concepts and the adapter model nodes edging `implements`
   into the concepts they realise, built from the same in-memory pass that renders
   `index.json` without rewriting it.
3. **semantic layer** (`semantic_layer_to_graphify.py`) — `joins_to` edges from dbt
   `relationships` tests (child → parent, with the FK columns and a unique-test-derived
   cardinality as edge attributes), plus semantic-model / metric / saved-query nodes
   edged `describes` / `measures` / `composes` / `bundles`. Manifest-derived, never
   read from `wren/` — `relationships.yml` is the wren importer's projection of the
   same tests, and this stage runs before `wren`. Measured on enhanza: **0 of the 101
   FK pairs were recoverable from `parent_map`** — a fact model does not `ref()` the
   dim it joins to, so before this fragment the join topology was invisible to
   `graphify query` entirely.
4. **column contracts** (`dbt_column_memory.py --merge-graphify`) — previously a manual
   command outside the stage, which left its merge unprotected by the ordering rule.
The relation carries the implemented-versus-planned distinction because a flat edge loses
it: naive traversal once answered "ten connectors supply Account" when five were catalogue
expectations. graphify's detector puts `.ttl` in no category at all, so without this merge
the topology is invisible during orientation — and the same never-update-after rule covers
it.

Three further rules decide whether the output can be trusted:

- **A missing input skips; it does not fail.** A fresh use-case has no manifest and four of
  five stages need one. A gate that goes red on a correct state gets switched off inside a
  week, taking the real failures with it. `--check` distinguishes "would change" from "could
  not run", and a summary that says "synced" while four stages skipped is a false statement.
- **A refusal is reported on the stage that was refused.** Regenerating without sqlglot
  produces the same classes with none of the 91 column mappings — a diff that reads as
  tidying. Both `ontology` and `index` decline and say so; `--force` accepts the loss.
- **The namespace is pinned, never derived.** `ontology/ontology.yml` holds each use-case's
  IRI root and its own concept classes, so renaming a directory cannot silently reissue
  every identifier the ontology has published. The shared ERP/CRM vocabulary stays in
  `scripts/ontology_generator.py`; a domain's own concepts go in its `ontology.yml`.

### The other direction — ontology before models

Every artifact above is derived from `manifest.json`, so all of them describe what the dbt
project **is**. That is the right direction for keeping an ontology honest and the wrong
one for building a project: rule 6 wants the conceptual model to precede the physical one,
and a model derived from the manifest cannot exist until the models do.

`scripts/raw_taxonomy.py` runs the other way. Its inputs are the raw layer and the
use-case spec; its output declares what the project **should** build:

```bash
python3 scripts/raw_taxonomy.py --use-case <slug> --propose   # candidates + evidence
python3 scripts/raw_taxonomy.py --use-case <slug>             # ontology/conceptual-model.json
python3 scripts/raw_taxonomy.py --use-case <slug> --plan      # entities with no dbt model yet
```

The two directions meet at `--plan`: every declared entity is either realised by a dbt
model or reported as an open gap, so the conceptual model is falsifiable the same way
`test_every_declared_dbt_model_exists` makes the generated Turtle falsifiable. Agent
surface: skill `raw-layer-ontology`, command `/raw-ontology`.

**One input is hand-authored and it is the only one.** Whether `tblCust01` is a Customer,
which column identifies it, and what one row means are judgements no schema contains.
`--propose` emits candidates *with their evidence*; a human confirms them into
`ontology/taxonomy.yml`; everything downstream is derived. Same split, same reason, as
`connectors.yml`.

Three rules, each enforced rather than documented:

- **An attribute that is not a declared source column does not exist** (rule 5). This
  artifact is written before anything can check it, so an entity attribute tracing to no
  column in `sources.yml` is reported and kept out — otherwise the output is a beautiful
  description of a warehouse nobody can build. This is why source column contracts are a
  prerequisite, not a nicety.
- **A grain is declared or the entity is incomplete** (rule 4). No schema supplies "one row
  per customer per tenant", so the taxonomy carries it and an entity without one fails.
  Silence here is what makes a measure double-count three layers down while every test
  passes.
- **A proposal never overwrites a decision.** `--propose` refuses when `taxonomy.yml`
  exists. Name matching is evidence for a human, and rewriting a curated mapping would make
  the guess authoritative over the judgement — the same rule that stops the source-column
  emitter touching a table that already declares `columns:`.

A fourth rule was a bug first, found by running the pipeline end to end on a two-entity
demo: **a gap is a concept this domain asked for**, meaning one its own `ontology.yml`
declares. Counting every concept in the shared ERP/CRM vocabulary as a gap buried the one
that mattered under 56 nobody had requested — rule 3, and the same unbounded-dump problem
as the untested-model list. The shared ones are now `shared_vocabulary_unused`: a count
plus a ten-name sample.

Measured against this repo's raw layer: **200 declared tables across 12 `sources.yml`, 807
declared columns, 40 concepts matched by name, 97 tables matched nothing** (each reported,
never guessed at). The key-shape heuristic earns its keep and was wrong first: requiring a
stem before `Number`/`Code` meant `accounts.Number` — the account number — was not a
candidate while `OrgId` and `SalaryCode` were. With a bare stem allowed, the top-ranked
candidate for `dim_accounts`, `dim_customers`, and `dim_articles` is `Number`,
`CustomerNumber`, `ArticleNumber`. A bare `Id` stays excluded: it identifies a row in
whichever table it sits in and names no entity.

**No `taxonomy.yml` is committed for enhanza-analytics, deliberately.** Only 10 of its 359
models state a grain anywhere, so authoring one would mean inventing ~40 grain sentences —
rule 5, and the exact failure this script exists to prevent. The tool ships; the taxonomy
is a human deliverable, and the stage skips with the remedy named until someone writes it.

### Column annotations — what a column *means*

`column-memory.json` records which raw column feeds which conformed column. Nothing recorded
what the conformed column **is**, and three binding rules need exactly that: additivity per
measure (rule 11), PII declared and tagged (rule 17), `accepted_values` on every closed
domain (rule 28). Measured before this existed: **272 conformed columns, 1 accepted_values
test in the entire project**, and nothing anywhere recording additivity or PII.

```bash
python3 scripts/column_annotations.py --use-case <slug> --propose --evidenced-only  # bootstrap
python3 scripts/column_annotations.py --use-case <slug> --propose    # candidates + evidence
python3 scripts/column_annotations.py --use-case <slug>              # the artifact
python3 scripts/column_annotations.py --use-case <slug> --coverage   # what is unannotated
```

Annotated here: **89 of 272 conformed columns** — 78 whose every facet the project already
evidenced, plus 11 measures whose additivity is a decision, each recorded with its reason.
5 columns carry PII; 9 may not be summed the way their names suggest. The remaining 183 are
in `--coverage`'s backlog, unannotated rather than guessed at.

`--propose --evidenced-only` is what makes the first run produce an artifact instead of a
page of blanks: it emits exactly the columns whose facets are already backed — a description
the project wrote in its own `schema.yml`, a role derived from a cast or a name, and for a
measure an additivity that followed from its definition. Everything else is left out, and
a column absent from the file is honestly unannotated.

The consequence was concrete: `wren/knowledge/rules/column-contracts.md`, the file an agent
reads before writing SQL, lists `QuantityInStock` beside `TotalToPay` as bare names — so the
agent cannot know that summing the first across time is wrong, or that `RecipientEmail` must
not reach a shared dashboard.

Four decisions shape the artifact:

- **Facets, not a tree.** A column is several things at once — `TotalToPay` is a measure
  *and* additive *and* currency-denominated *and* not PII. A single hierarchy has to pick one
  of those as the parent and loses the rest, so `role` / `additivity` / `pii` / `unit` /
  `domain` are independent.
- **Annotated at the conformed column, not per model.** Conformance already asserts
  `ArticleNumber` means the same thing in Fortnox and Shopify. Measured: **272 decisions
  cover 952 (column, connector) pairs**, and a per-model annotation would let one column be a
  measure in one connector and a dimension in another — the drift the conformed layer exists
  to prevent.
- **Evidence, never invention.** Candidates come from cast types, name shapes, existing
  `accepted_values` tests, and the project's own column descriptions — **97 definitions
  harvested** rather than paraphrased. A closed domain with no cited source is refused
  (rule 5): a wrong enum passes every `accepted_values` test, because it generated them.
- **Abstain rather than guess.** 49 of 272 columns abstain, and `additive` is never proposed
  — it is what a reader already assumes, so proposing it removes the prompt to decide while
  adding nothing.

Six derivation rules were wrong first and are pinned. The last four were found by reading
the project's own descriptions next to what the deriver had proposed for the same column —
which is the argument for harvesting definitions rather than paraphrasing them:

- **A regex cannot read a cast.** `cast(nullif(c.city,'') as string) City` is the ordinary
  form here, and a `[^()]*` body stops at the inner paren — so the simple case read and every
  wrapped one silently lost its type. Balanced-paren scan instead: type coverage 179 of 272.
- **An identifier suffix outranks a numeric cast.** `OrderNumber` is an `int64` and summing
  it is meaningless. The Swedish accounting reference states the same rule for account
  numbers: *"They are identifiers, not quantities; arithmetic on them is always a bug."*
- **A definition outranks a name shape.** `Account` carries no suffix and casts to `numeric`,
  so nothing in its name or type stops it being read as a measure — only its own description,
  *"BAS account number, consists of four digits"*, does. Same signal makes `AccountClass` a
  dimension rather than a quantity.
- **A BAS account number is not a bank account.** The bank-identifier shape matched a bare
  `AccountNumber`, so all four of this project's were classed as **direct PII** — putting the
  chart of accounts behind a masking rule. `BankAccount`, Bankgiro, Plusgiro and IBAN still
  match; the bare form does not.
- **A price per unit is non-additive at every grain.** Nothing in `AmountPerUnit` reads as a
  rate, so the name shapes left it additive by omission; *"Price per unit (day, hour etc.)"*
  is what makes summing it meaningless. Its unit is currency, not a count.
- **`Discount` contains `count`.** Matching quantity words as substrings proposed
  `PriceAfterDiscount` as a quantity. Words, not substrings.

The one enum this project declares, Shopify's `FinancialStatus`, is **not** a conformed
column, so the annotated set has zero closed domains — and `AccountClass`, which obviously
has one, gets none: the class *names* live in a warehouse lookup this repo cannot read, and
BAS class names transliterated from memory would be exactly the invented enum rule 5
forbids. Refusing there is the rule working, not a gap in it.

Shaped after the annotation and taxonomy skills the request cited — poly-hierarchical facets
rather than one tree, per-item confidence with an explicit abstain, evidence bound to every
node, and refuse-to-overwrite-a-decision.

### Generating the fields nobody wrote down

Every generator here stops at the same wall, correctly: `raw_taxonomy.py` refuses to write a
grain, `column_annotations.py` abstains on additivity and PII. That leaves real work undone
— **183 of 272 conformed columns unannotated, and no `taxonomy.yml` at all**.
`scripts/lm_propose.py` closes it with a language model without giving up rule 5:

```bash
python3 scripts/lm_propose.py --use-case <slug> --target annotations --prepare --out batch.json
python3 scripts/lm_propose.py --use-case <slug> --target annotations --apply answers.json
python3 scripts/lm_propose.py --use-case <slug> --target annotations --review   # then --promote
```

Four decisions, and the module is mostly the last one:

- **The script assembles the evidence; the model only decides.** Each item ships the cast
  types, the raw source columns the value traces to, the sibling columns of its concept, and
  the project's own descriptions. A model asked "what is `AmountPerUnit`?" recalls; one
  handed `favrit_api__orderline.unit_price` classifies. Only the second is checkable.
- **Output is a proposal, never an artifact.** `ontology/proposals/*.lm.yml`, every entry
  `source: lm` with its confidence and cited evidence, `reviewed: false`. `--promote` moves
  only what a human marked, holds anything below `--min-confidence`, and never touches a
  column the hand-authored file already decides.
- **No hidden API call.** The default backend is the agent running it — `--prepare` writes
  the questions, `--apply` reads the answers — which is how graphify's own skill works here.
  `--backend anthropic` exists for unattended runs and skips when the key or the package is
  absent.
- **Five refusals at `--apply`, each a way a generated field is wrong while reading well.**

Measured on the first real batch: 24 items answered, **24 accepted, 0 dropped**; a
deliberately fabricated batch of 4 was **rejected 4 for 4**. Two of those five refusals
exist because the first version of the fabricated batch *passed*:

| Refusal | The answer it caught |
|---|---|
| id not in the batch | a column name that exists in no artifact |
| definition restates the name | `Unit` → "The unit." |
| closed domain with no source | `TermsOfDelivery` → five invented Incoterm codes |
| evidence names nothing in the item | "I know how ERP systems model this" |
| answer contradicts its own casts | `Manufacturer` (string in every connector) → additive currency measure |

The grounding check is the subtle one and was wrong twice. Matching the item as **text** let
prose ground on the JSON *key* `source_model`; matching the item's own **name** let "the
Incoterms standard defines these terms" ground on `terms`. It now matches values only, minus
the item's own name, **as written** — `fortnox_api__articles` grounds, a loose `article` does
not. It cannot catch a plausible misreading of real evidence; that is what review is for.

Real output worth reading: `DiscountType` gained the project's **second** closed domain
(`PERCENT | AMOUNT`, cited to the project's own description), which in turn made `Discount`
**non-additive** — its unit is decided by another column, so summing it mixes percentages
with amounts. And `ChargeHours`, which the deriver had proposed as *currency* from its name,
is `duration`: the lineage says `seventime_api__timelogs.invoiceableTime`.

### Ambiguous bindings, and why a contract may not be built from one

Found by trying to use the source contracts: `fortnox_api.accounts` declared `Amount`,
`Date`, `Total` and `VAT` — voucher columns.

The cause is one line of SQL, not a sloppy bootstrap. `select Amount from st, fy, e, a, ee`
references a column **unqualified with five tables in scope**; the resolver resolves it
against each, which its docstring states as a deliberate choice — *"reported against each,
because guessing one is worse than saying so"*. For lineage that is right: every candidate
is visible. For a contract it is fatal, because "accounts has an `Amount` column" is exactly
the claim nobody established.

So the resolver keeps its behaviour and now **says** it: `ColumnEdge.ambiguous` marks a
binding that is one of N guesses. Two consumers read the same flag, and the symmetry is the
point:

- `--emit-source-columns` will not **write** a contract from an ambiguous binding.
- `check_source_columns` will not **fail** one with it. Blaming `accounts` for a bare
  `Amount` five tables could own is the same guess pointed the other way.

A contract also answers a different question from lineage — "what do we read", not "what fed
this output column" — so `qualified_source_reads()` collects every *qualified* reference
anywhere in the statement, including join keys and filters a projection never mentions.
Without it `accounts` came out with **one** column while its own SQL demonstrably reads
three: `a.OrgId` and `a.Year` appear only in a JOIN.

Measured on enhanza-analytics: **295 ambiguous bindings refused, 252 columns pruned across 7
files**, dbt parse clean, alignment check unchanged at 0 errors / 9 accepted warnings.
`--prune` deletes only from blocks carrying the generated banner — the same ownership marker
as WrenAI's `source: dbt_metric` — never from a hand-authored one, and never adds.

Two rules that were bugs first:

- **A block that loses every column withdraws; it does not become `columns:` with nothing
  under it.** dbt refuses to parse the project. Found by running the prune for real: one
  `seventime` table lost all twelve and the whole parse failed.
- **Normalise the edge width at construction, not at each unpack.** A cache written before
  the flag existed, and a hand-built lineage in a test, both hold 4-tuples.

The remaining thinness is honest rather than fixed: where a project never qualifies a
reference, nothing in the SQL says which table owns the column. Measured, of 305 fanned-out
references only **41** are resolvable by elimination against qualified evidence elsewhere.
A precise thin contract is what ontology-first generation needs — an entity built from the
broad one would carry `VAT` on `dim_accounts`.

### The models the ontology declares, and an eval that runs them

Every generator above derives an artifact *from* the dbt project. `scripts/ontology_to_dbt.py`
runs the other way: it reads what the ontology says exists and writes the business-layer
models nobody built. Measured: **58 concepts, 27 with an `erp_bi_*` union, 8 with a
`logic_bi_*` model** — nineteen unions with no consumer-facing model, and nothing said so,
because a model that does not exist produces no lineage, no test, and no error.

```bash
python3 scripts/ontology_to_dbt.py --use-case <slug> --dry-run   # the gap
python3 scripts/ontology_to_dbt.py --use-case <slug> --write     # 19 models here
python3 scripts/eval_dbt_models.py --use-case <slug>             # built on DuckDB
```

The generated model is a faithful projection, never invented logic: the conformed columns
whose meaning is recorded, gated on the ontology's supplier list. Direct-PII columns are
withheld (rule 17) and counted — 2 each from `dim_customers`, `fact_orders`, `fact_offers`.
Tests come from the facets; **no `unique`**, because no grain is declared for these concepts
and asserting a key nobody chose is what rule 5 forbids.

`eval_dbt_models.py` is shaped after dlt-hub's `run-eval` skill, which scores a description
against labelled cases and sorts results into named failure classes. Three of its properties
are why it is worth copying:

- **Cases are labelled from outside the run.** Every expectation — promised columns, declared
  enums, PII class, supplier set — comes from `index.json` and `column-annotations.json`,
  never from the relation being judged. An eval that reads its expectations off its subject
  measures nothing.
- **Failures are classified, not counted.** `contract-miss` on four models and
  `attribution-gap` on one are two bugs with two owners.
- **Unavailable is not failed.** run-eval rebuilds a stale workspace before judging it; the
  analogue here is establishing a fixture that exists.

The classification was wrong first, and instructively. The first full run scored **1 of 19**
— and sixteen of those failures were in an *upstream staging* model the generated one merely
depends on, most of them the sample seeds' one-scalar-string-per-column meeting SQL that
unnests an array or indexes a JSON document. Blaming the generator for an absent CSV is how
an eval stops being believed. After splitting `no-sample` and `upstream-unbuildable` out of
`unbuildable`: **19 cases, 4 scored, 2 passed, 2 failed, 15 reported-not-scored.**

Both surviving failures are real, and neither is visible to dbt, the alignment checker, or a
human reading either:

- **`label-mismatch`** — the ontology publishes `Visma eAccounting`; the union writes
  `Visma e-Accounting`. An agent filtering by the published name gets **zero rows and no
  error**. Exact agreement is the pass; the loose comparison exists only to tell this apart
  from a supplier that contributed nothing.
- **`ambiguous-sql`** — `Ambiguous reference to column name "Date" (use: "st.Date" or
  "fy.Date")`. BigQuery resolves an unqualified column with several tables in scope, DuckDB
  refuses. The *same* ambiguity that made a source contract claim columns nobody
  established, arriving independently as a portability defect.

Agent surface: skill `model-eval`.

### Where the annotations go — the ontology, then the serving tier

An annotation nothing carries forward reaches neither BI nor an agent, which are the two
consumers that need it. Three projections, all from the one artifact:

| Destination | Holds | Why |
|---|---|---|
| `ontology/topology/column-semantics.ttl` | one `conn:ConformedColumn` per column, facets as triples | the ontology is where a concept's meaning already lives; **869 triples, rdflib-clean** |
| `ontology/index.json` → `column_semantics` | the same facets, flat | backs the `describe_column` MCP tool; `rdflib` is optional here, so a server cannot parse Turtle at request time |
| `wren/knowledge/rules/column-semantics.md` + `caveats/pii.md` | the aggregation contract and the disclosure rule, in prose | what an agent reads before it writes `SUM(...)` |

The Turtle **declares the vocabulary it uses** — `conn:ConformedColumn`, `conn:role`,
`conn:additivity`, `conn:pii` — rather than assuming it, because a consumer meeting
`conn:additivity` for the first time has nowhere else to look it up. Index and Turtle come
out of one pass and `test_index_and_turtle_agree_on_every_annotated_column` fails if they
diverge, exactly as for models and mappings.

`column-semantics.md` **leads with the prohibitions**, because those are the part a name
cannot convey: `Price` is per unit and `QuantityInStock` is a level, so both look summable
and both produce a plausible wrong number. It also states what it does not cover — a file
listing 89 columns and silent about the other 183 reads as complete, and an agent then
assumes defaults for the rest.

### Serving it later — `index.json`

`ontology/index.json` is a flat projection of the same facts the Turtle asserts: four
uniform record lists (`connectors`, `concepts`, `models`, `mappings`,
`column_semantics`) plus `gaps` and a
`provenance` block, with `mcp_tools` naming the key that backs each tool. Both artifacts come
out of one generator pass, and `test_index_and_turtle_agree_on_every_model` fails if they
diverge.

It exists because the eventual consumer answers one question per call, and `rdflib` is
optional here — a server that parsed Turtle at request time would fail to start wherever the
parser is absent. It is deliberately **not** JSON-LD: a `@context` covering these keys would
have to reify `models` and `mappings` into graph shapes they do not have, and one covering
only the prefixes would parse while dropping nearly every statement. The graph stays in the
`.ttl` files. Details in the use-case's `ontology/README.md`.

## WrenAI serving tier

WrenAI is included as this repository's semantic-layer serving tier: source pinned as a
submodule at `external/WrenAI`, runtime as the `wrenai` wheel pinned in `requirements.txt`
(the two move together), agent surface as `skill-packs/wren-skills/` (skill `wren-genbi`,
command `/wren`). Full architecture and rationale: `docs/WRENAI_INTEGRATION.md`.

Three rules decide whether a change here is correct:

- **The bridge enriches; it never duplicates.** `wren context import dbt` is upstream's
  and produces the mechanical layer. `scripts/wren_context_sync.py` adds only what dbt
  cannot know — ontology concepts, column contracts, drift caveats, MetricFlow
  projections — into files the importer does not own. The two generators' file sets are
  disjoint, and hand-authored knowledge in other filenames is reported `stale`, never
  touched or deleted.
- **Metrics compile to MDL views, typed from `catalog.json` or skipped and counted**
  (rule 5: never invent). A metric's view carries its whole MetricFlow definition —
  filter, ratio, offset, window — so `SELECT * FROM revenue` *is* the metric, for BI
  and for agents over the per-use-case MCP server (`wren/mcp.json`, emitted by the
  sync). Measured on example-order-revenue-mart: 13 models, 3 relationships, 8 metric
  views, validate clean, view revenue = 277,183.41 (the filtered metric, not the
  289,470.66 raw measure the old cube projection shipped), every view row-for-row
  equal to a hand-written oracle (`tests/test_wren_semantic_equivalence.py`) —
  `./skill-packs/wren-skills/demo/run_wren_demo.sh` re-proves this end to end, locally,
  with no Docker and no API keys. Analysis: `docs/SEMANTIC_LAYER_ALIGNMENT.md`.
- **An upstream defect becomes a bridge workaround plus a patch in `external/patches/`,
  never a fork-drift.** The wrenai 0.13.2 importer crash on model-level dbt tests is the
  worked example: rows are hidden from `run_results.json` only for the import's duration
  and restored on any exit, pinned by `tests/test_wren_context_sync.py`.

Guides are never copied out of the CLI: `wren skills get <name>` serves them
version-matched to the installed wheel, which is why the skill is a discovery stub.
`wren genbi deploy` is data egress and needs explicit per-deploy user confirmation
(`wren-rules.md` rule 9).

## Harness cartography — skill-map

`graphify` maps the **code**; `skill-map` maps the **harness** — skills, commands,
and agents as one graph, with name collisions, dead references, reserved-name
shadowing, and per-node token weight. Two graphs, two purposes; neither
substitutes for the other.

```bash
python scripts/skill_map_scan.py --summary                # counts + collisions
python scripts/skill_map_scan.py --check --max-errors 1   # the CI gate form
```

Deterministic and LLM-free **by construction**, not by convention: upstream
skill-map ships a probabilistic layer that queues LLM jobs, and the allowlist in
`scripts/skill_map_scan.py` rejects all four of its verb families (`jobs`,
`agent`, `findings`, `refresh`). `tests/test_skill_map_pack.py` fails if one is
ever added. No API key; exit `3` and a recorded `skip` where Node is absent.

A scan touches two paths, both already accounted for: `.skill-map/` (transient
SQLite state) is gitignored, and `.skillmapignore` (which files become nodes) is
**committed**, so the gate means the same thing in every checkout. It excludes
`graphify-out/`, which CI builds immediately before scanning and a laptop
usually lacks.

Pack: `skill-packs/skill-map/` (skill `harness-mapping`, command `/skill-map`).
Wraps `@skill-map/cli` at a pinned version rather than vendoring the upstream
monorepo — analyzers decide which issues exist, so the pin is what keeps the
gate's verdict stable.

Two rules decide whether a reading of the output is correct:

- **Every finding is doubled.** Pack and activated mirror are both scanned. A
  finding in only one tree is drift, and a different problem.
- **Fix the pack, never the mirror.**

Accepted, do not re-report: the `senior-analytics-engineer` alias collision,
`/review` shadowed by the Claude Code built-in, and agent `tools`-as-string
warnings. Details in the pack's `.claude/skills/harness-mapping/references/findings.md`.

## The architecture page

[public/code-skills-architecture.html](public/code-skills-architecture.html) is the
hand-authored view of the whole system: the three-lane data flow, the ten derivation
stages with what each one refuses to do, five layers, and the deployment surface. It is
self-contained — no CDN, no webfont — because it is also published under a CSP that
blocks every external host.

A hand-authored page rots, so one mechanism holds it:

- **Numbers are pinned or declared as snapshots, never left ambiguous.** Every figure
  derived from a *committed* artifact carries `data-metric` and is checked against that
  artifact by `tests/test_architecture_diagram.py` — 19 connectors, 378 dbt models, 1024
  bindings, 569 declared source columns. The dbt model count comes from
  `graphify-fragment.json` rather than the manifest, for the same reason the fragment is
  committed at all. Figures that need a rebuild — test count, graph size — are **not**
  pinned: a gate that goes red because somebody added a test is a gate that gets switched
  off, so the footer names the command that re-derives each instead.

The PR comment used to project this layer stack — `scripts/pr_decision_diagram.py`
classified each changed path onto it and drew the layers that moved. **That section is
removed**, by the rule the renderer already applies to itself: it once deleted a fixed
gate-chain diagram for being identical on every PR, and the layer stack was the same
defect one step weaker — only the highlighting varied, and most PRs lit the same two
layers, so it restated the Files-changed tab. It also cost a classification rule per
naming convention here, which is upkeep for a section nobody read.

What the comment still draws is the part a reviewer *cannot* read off the file list: the
impact subgraph of the PR's own diff. The page's `data-layer` attributes stay as section
markers; nothing consumes them, so nothing can drift from them.

## Agent and command topology

Canonical dbt skill entrypoint: `dbt-skill` (compatibility alias: `senior-analytics-engineer`).

- Agents: `.claude/agents/`
	- Meta: `repo-maintainer`, `skill-author`, `submodule-integrator`
	- Analytics: `senior-analytics-engineer`, `data-modeler`, `dbt-model-designer`, `data-contract-owner`, `analytics-quality-guardian`, `semantic-layer-architect`, `dbt-troubleshooter`
- Skills: `.claude/skills/` (dbt stage-by-stage method)
- Commands: `.claude/commands/`
	- Namespaced canonical paths:
		- Infra: `.claude/commands/infra/`
		- Analytics: `.claude/commands/analytics/`
	- Backward compatibility command files remain in `.claude/commands/`

## Generated paths — edit the pack, not the mirror

`scripts/activate_skill_stack.sh` materialises the active pack into the paths agents load.
These roots are **generated output**, and a direct edit is reverted on the next activation:

- `.claude/agents/`, `.claude/skills/`, `.claude/commands/`, `.claude/rules/`, `.claude/hooks/`
	- Source: `skill-packs/<pack>/.claude/`
- `references/`, `templates/`
	- Source: `skill-packs/<pack>/`

Both the pack copy and the root mirror must exist: skills and agents link to these assets
with a single relative path (`../../references/x.md`) that has to resolve in the pack *and*
after activation.

Exceptions maintained directly at repository level, because no pack owns them:
`.claude/commands/analytics/`, `.claude/commands/infra/`.

After changing any pack asset:

```bash
./scripts/activate_skill_stack.sh dbt-skills wren-skills && git status --short
```

Unexpected modifications in that output mean an edit landed in a generated path.

## Script core — three shared modules, no fourth

Everything in `scripts/` is a standalone CLI that runs on the standard library. Three
private modules carry what more than one of them needs, and nothing else belongs there:

| Module | Owns |
|---|---|
| `_manifest.py` | reading dbt's JSON artifacts; the `Manifest` wrapper; `die` |
| `_miniyaml.py` | YAML for the subset these files use, PyYAML when present |
| `_paths.py` | the repository root, use-case lookup, dbt project resolution |

`_paths.py` replaced four copies of `use_case_dir`, two of `project_root_of`, and
twenty-three `Path(__file__).resolve().parent.parent` bootstraps. Two decisions in it
are load-bearing and both were bugs first:

- **The root is a parameter, never a closure.** `new_connector`, `use_case_sync`, and
  `wren_context_sync` are all driven against a throwaway tree by
  `monkeypatch.setattr(module, "REPO", tmp_path)`. A helper that read a module global at
  call time searched the real repository instead — five tests failed on it. Each of
  those modules keeps a one-line binding that forwards its own `REPO`.
- **Nothing is cached.** The glob is a directory listing three levels deep over a handful
  of packs, while `use_case_sync.py --init <slug>` creates a use-case and syncs it *in
  the same process*. A cache populated before the `mkdir` reports the new use-case as
  missing — a correctness bug traded for an unmeasurable saving.

The two `use_case_dir` behaviours that existed are both kept, as two named functions
rather than one function with a flag: `use_case_dir` returns `Optional[Path]`,
`require_use_case_dir` exits 2 and lists the known slugs.

## Running the tests

`python -m pytest -q` — that exact command, from the repository root, is what all six CI
call sites run and what `tests/test_wren_context_sync.py` pins.

It runs **across cores when `pytest-xdist` is installed and serially when it is not**.
Measured on a 10-core machine: 97s at 70% CPU serial, **34s** parallel, three
consecutive runs identical. The suite is subprocess-bound — nearly every test shells out
to a script in `scripts/` — so a third of the machine was idle.

The wiring is two files, and the split is forced by pytest, not chosen:

- `_pytest_parallel.py`, named in `pytest.ini`'s `addopts` via `-p`. Only
  `pytest_load_initial_conftests` is early enough to add `-n`, and pytest fires it
  *while* loading conftests — so the same hook in a `conftest.py` never runs. It stayed
  silently at 97s until this moved to a `-p` plugin. `-n auto` in `addopts` directly
  would make bare `pytest` fail with "unrecognized arguments" wherever xdist is absent.
- `conftest.py` at the root, which assigns each test an xdist group.

**Grouping is correctness, not tuning.** Distribution is `loadgroup` with each test
grouped by its filename, reproducing `loadfile`'s guarantee, except that three files
share one group: `test_dbt_column_memory.py`, `test_dbt_column_memory_watch.py`, and
`test_use_case_sync.py`. The first two define the *same* end-to-end test — append a
probe comment to a real `.sql`, rebuild, assert, restore in a `finally` — so on separate
workers they mutate one `.sql` and one `column-memory.json` concurrently. Measured: two
reproducible failures, and four un-restored `-- hook test probe` lines accumulated in a
committed dbt model, because each worker's `finally` restored the *other's* probe as if
it were the original. The third file joins them because its `columns` stage runs
`--check` against that same artifact.

Those tests were always order-dependent; running serially was hiding it. The grouping
costs no wall time — the three total ~16s, under the ~23s of `test_dbt_sample_build.py`,
which bounds the run anyway.

Escape hatches: `-n`/`--dist` on the command line wins, `-p no:xdist` disables it, and
`CODE_SKILLS_NO_XDIST=1` forces serial for bisecting a flake.

## RTK and memory integration

- RTK registry and routes: `src/ai-core/rtk-setup.ts` and `src/ai-core/dbt-integration.ts`
- Graph state helper: `src/ai-core/graph-manager.ts`
- Memory store helper: `src/ai-core/memory-store.ts`
- File-backed memory updates: `.claude/commands/infra/update-memory.sh`
- Context sync pipeline: `scripts/sync_context.sh`

## dbt-labs translated skill pack

dbt-labs/dbt-agent-skills capabilities are translated for dbt Core and included in:

- `.claude/skills/dbt-labs-core-translation/SKILL.md`
- `.claude/skills/using-dbt-for-analytics-engineering-core/SKILL.md`
- `.claude/skills/running-dbt-commands-core/SKILL.md`
- `.claude/skills/building-dbt-semantic-layer-core/SKILL.md`
- `.claude/skills/adding-dbt-unit-test-core/SKILL.md`
- `.claude/skills/working-with-dbt-mesh-core/SKILL.md`
- `.claude/skills/troubleshooting-dbt-job-errors-core/SKILL.md`

## dbt Core non-negotiables

Reference file: `.claude/rules/analytics-engineering-rules.md`.

High-priority rules:
- No model before a use-case spec.
- Declare grain before SQL.
- Use only `source()` and `ref()`.
- Use `dbt build`, not run-then-test.
- No merge without tested keys and required unit tests.

## Working pattern

1. Frame request.
2. Model entities and grain.
3. Design dbt layers.
4. Build and test with selectors.
5. Run analyzers from `scripts/`.
6. Sync memory and graph context.

```bash
./scripts/sync_context.sh "dbt build for <selector>"
```

## AgentMemory guidance

AgentMemory holds what the repository cannot: the reasoning behind a decision. Setup and
the REST contract are in `docs/INTEGRATIONS.md`.

**It does not capture anything on its own.** The server reports `Sessions: 0,
Observations: 0` — it observes nothing unless something writes to it deliberately. A
fact not written by `sync_context.sh --decision` does not exist in the next session.

### What goes where

Three stores, three jobs. Putting a fact in the wrong one is how it goes stale:

- **graphify** — code structure. Regenerated from the AST, so it cannot be wrong for
  long. Never record structure in memory; query the graph.
- **git** — what changed and when. Never mirror a commit summary into memory; it
  duplicates `git log` and breaks on the next amend or rebase.
- **AgentMemory** — why. A choice between real alternatives and why the loser lost, a
  constraint discovered the hard way, a correction to something previously believed.

### Writing

```bash
./scripts/sync_context.sh "<summary>" --decision "<why>"
```

Without `--decision` nothing is mirrored, on purpose. Recall is **BM25, not embeddings**
(`Embeddings: bm25-only`), so a decision is only findable by its own words — phrase it
with the terms a future question would use. "merge over delete+insert for fct_orders,
source late-arrives 3 days" is findable; "fixed the incremental" is not.

### Reading

The `agentmemory` MCP server is registered globally in `~/.claude.json`; `GET
/agentmemory/memories` and `POST /agentmemory/smart-search` on `:3111` are the direct
REST equivalents. Recall before assuming why a prior choice was made — and treat what
comes back as what was true when written, not as current fact. Verify a named file,
flag, or command still exists before acting on it.

### Never smoke-test by hand

`:3111` is a single global store with no per-request namespace, so an ad-hoc `curl`
lands in the same corpus the agent reads back. Use `./scripts/agentmemory_smoke.sh`,
which deletes what it writes and verifies the deletion.
