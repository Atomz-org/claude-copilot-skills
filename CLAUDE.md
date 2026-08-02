# Unified Operating Manual

Repository name: `code-skills`

This repository combines:

- Git workflow automation and reusable scaffold operations
- Senior analytics-engineering methods for dbt Core projects
- RTK-style toolkit routing, graph state, and memory capture

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

**Route a script through TOON only when it was measured to help.** Measured here:

| Command | text | TOON | |
|---|---|---|---|
| `connector_alignment_check.py --connector erp` (28 findings) | 7447 | **2624** | −64.8% |
| `dbt_manifest_to_graphify.py --dry-run` | **271** | 639 | +136% |

The checker wins because its findings are a uniform record list: the message template and
the shared path prefix are each stated once instead of 28 times, so
`scripts/hooks/toon_graphify_pipe.py` rewrites bare invocations to
`--format json | graph_to_toon`. The emitter loses because its text output is already four
lines of counts — it is deliberately **not** in that hook's `_TOON_SCRIPTS`, and adding it
would cost tokens. `--format json` still exists there for machine consumption.

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

Coverage is stated, never implied: 223 of 359 models parse, 131 are macro-only and resolved
structurally, 5 fail and are named. `--with-columns` roughly doubles the graph
(3058 → 6382 nodes), so it is a flag rather than a default.

**Anything inferred by parsing can be confidently wrong**, which is why
`tests/test_dbt_column_lineage.py` pins each resolver bug found while building it:

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

## Use-case derived artifacts — one command

A use-case is one hand-written thing and five derived ones. `scripts/use_case_sync.py` runs
all five in dependency order and reports each as `ok`, `changed`, or `skip` with a reason:

```bash
python3 scripts/use_case_sync.py --init <slug>                       # scaffold a use-case
python3 scripts/use_case_sync.py --use-case <slug> --graphify-update # regenerate everything
python3 scripts/use_case_sync.py --all --check                       # the CI gate form
```

| Stage | Produces | Needs |
|---|---|---|
| `ontology` | `ontology/connectors/*.ttl`, `topology/*.ttl` | `connectors.yml` |
| `index` | `ontology/index.json` — the machine-facing projection | same generator pass |
| `seeds` | `dbt_project/seeds/sample/*.csv` | manifest, sqlglot, reference data |
| `graphify` | the code graph, rebuilt | `--graphify-update` |
| `graph` | dbt lineage merged into `graphify-out/graph.json` | manifest |
| `alignment` | the convention-drift verdict | a dbt project |

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

### Serving it later — `index.json`

`ontology/index.json` is a flat projection of the same facts the Turtle asserts: four
uniform record lists (`connectors`, `concepts`, `models`, `mappings`) plus `gaps` and a
`provenance` block, with `mcp_tools` naming the key that backs each tool. Both artifacts come
out of one generator pass, and `test_index_and_turtle_agree_on_every_model` fails if they
diverge.

It exists because the eventual consumer answers one question per call, and `rdflib` is
optional here — a server that parsed Turtle at request time would fail to start wherever the
parser is absent. It is deliberately **not** JSON-LD: a `@context` covering these keys would
have to reify `models` and `mappings` into graph shapes they do not have, and one covering
only the prefixes would parse while dropping nearly every statement. The graph stays in the
`.ttl` files. Details in the use-case's `ontology/README.md`.

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
warnings. Details in the pack's `references/findings.md`.

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
./scripts/activate_skill_stack.sh dbt-skills && git status --short
```

Unexpected modifications in that output mean an edit landed in a generated path.

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
