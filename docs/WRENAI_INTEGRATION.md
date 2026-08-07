# WrenAI integration

This repository includes [WrenAI](https://github.com/PackMaaan/WrenAI) — the open-source
semantic layer / GenBI engine — as its serving tier: a dbt use-case's models, ontology,
column contracts, and MetricFlow metrics are projected into a Wren MDL project that an
agent (or a human) queries through governed SQL — one semantic layer, two consumers:
BI through `wren query`, agents through the per-use-case MCP server the sync emits.

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
| **Metric views** — the whole definition (filter, ratio, offset, window) compiled to SQL | manifest `metrics` + `saved_queries` + `catalog.json` | `views/<metric>/metadata.yml` |
| MCP server config (live for duckdb, profile remedy otherwise) | resolved CLI + project paths | `wren/mcp.json` + `.wren-home/` (gitignored, per-clone) |

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

Why views and not cubes: a cube carries `AGG(column)` and silently drops the metric's
filter, ratio, offset, and window — measured here, the cube's `order_total` and the
metric `revenue` disagreed by 4.4%, both internally consistent. The compiled view *is*
the metric: `SELECT * FROM revenue` returns the filtered series for BI and agents
alike, `wren context validate` dry-plans it with no warehouse, and
`tests/test_wren_semantic_equivalence.py` holds every view row-for-row equal to a
hand-written oracle of its MetricFlow definition. Full analysis:
`docs/SEMANTIC_LAYER_ALIGNMENT.md`.

Upstream defects worked around (each: bridge workaround + patch in `external/patches/`):

- importer crash on model-level dbt tests (`column_name: None` breaks a sort) —
  rows hidden from `run_results.json` for the import's duration.
- importer dies on multi-connector alias collisions (21 on enhanza) — manifest
  rewritten for the import's duration; `identifier` pins the physical relation.
- wren-core registers parameterized `DECIMAL(p, s)` as Utf8 inside view planning —
  generated SQL casts measures to their own catalog type.
- the `[mcp]` extra resolves mcp 2.x, which removed `mcp.server.fastmcp` —
  `mcp<2` pinned in requirements.txt.

## Running it

```bash
# regenerate a use-case's wren/ project (skips name their remedy)
python3 scripts/use_case_sync.py --use-case example-order-revenue-mart --stage wren

# the end-to-end demo: dbt build -> import+enrich -> validate/build -> governed query
# cross-checked for exact row equality against DuckDB directly. Local, no Docker, no keys.
./skill-packs/wren-skills/demo/run_wren_demo.sh

# the same two assertions, inside a container, offline (--network=none).
# exits 3 and names the remedy when podman is unavailable.
./skill-packs/wren-skills/demo/run_wren_podman_demo.sh
```

Measured on `example-order-revenue-mart`: 13 models (8 dbt + 5 raw sources), 3
relationships from dbt tests, 8 metric views (7 metrics + 1 saved query) compiled from
MetricFlow, validate clean, the governed revenue-by-region query equal to direct DuckDB
row for row, and `sum(revenue)` through the view equal to the metric definition
(277,183.41 — not the raw measure's 289,470.66). Regeneration is idempotent (second
run: 0 changed files) and `--check` writes nothing. `tests/test_wren_context_sync.py`
and `tests/test_wren_semantic_equivalence.py` pin all of it.

Measured on `enhanza-analytics` (the multi-connector proof): 176 models imported
(272 dropped for missing column info — stated in the payload, never silent), 101
relationships, 58 ontology concepts and the conformed column contracts in the Wren
knowledge layer, 0 metric views (no MetricFlow semantic models there yet — correctly
counted, not invented), and the whole project served over MCP (`list_models`: 176).
Regenerate its catalog with the full connector var set:
`dbt docs generate --target demo --vars <all is_*_enabled> --exclude "*meta_data*"`
(the meta models run BigQuery SQL through `run_query()` at compile time).

### In a container, with podman

`run_wren_podman_demo.sh` makes the same two exact assertions as the local demo, inside
a container, with no network. podman rather than Docker: rootless, daemonless, no
Desktop licence. The commands are CLI-compatible so `docker` works, but `Containerfile`
is podman's native filename and podman is what this was verified against.

The image is the **serving tier** — dbt plus the wren CLI — not the WrenAI application.
There is no compose stack to bring up: the pinned submodule ships no docker assets
because upstream is CLI-first on the 0.13.x line.

Three things cost a build each to learn, all on Apple Silicon:

| Symptom | Cause |
|---|---|
| `error: linker 'cc' not found` | `wren-core-py` publishes **x86_64-only** Linux wheels — no aarch64 manylinux build through 0.7.3 — so pip silently falls back to compiling the Rust core |
| `qemu: uncaught target signal 11` at `wren --version` | the x86_64 wheel does not survive `--platform=linux/amd64` emulation; the image builds in ~3.5 min and dies only when run |
| `statfs <path>: operation not permitted` | podman cannot bind-mount `~/Documents` (TCC), and its `statfs` does not resolve the `/tmp` → `/private/tmp` symlink |
| `signal: 9, SIGKILL` against a random crate | cargo runs one rustc per core and a stock `podman machine` has 2 GiB; the compile is OOM-killed. `CARGO_BUILD_JOBS` bounds it, the preflight checks `MemTotal` |
| `workdir "/work" does not exist on container` | podman 5.8.5, for a directory that does exist. `WORKDIR` in the image already sets it — the `--workdir` flag is redundant and removing it is the fix |

So the Containerfile is a multi-stage build that compiles the core natively for the host
and discards the Rust toolchain (slow once, cached after), and the runner stages the
use-case with `mktemp -d` + `pwd -P` and mounts it read-only. Staging is one code path on
every OS, and it is what makes the read-only guarantee real — the container never
receives the working tree, so nothing it does can dirty it. The runner asserts that
afterwards.

`tests/test_wren_podman_demo.py` pins the contract without building anything: the
image's pins may not drift from `requirements.txt`, `--no-index` keeps an unsatisfiable
pin loud instead of silently resolving from PyPI, and an absent podman exits **3** per
rule 7 — matching `scripts/skill_map_scan.py` where Node is absent.

## Day-to-day agent workflow

```bash
wren skills get usage            # the CLI serves its own workflow guides
wren dry-plan --sql '...'        # plan through MDL, no database — the cheap gate
wren query --sql '...'           # governed execution
wren query --sql 'select * from revenue'   # the compiled metric view IS the metric
# agents: register the per-use-case server the sync emitted (wren/mcp.json) —
# the sync prints the exact `claude mcp add` line; duckdb targets come up live
```

Binding rules: `skill-packs/wren-skills/.claude/rules/wren-rules.md` (ownership,
regeneration, gates, and the `wren genbi deploy` egress rule).
