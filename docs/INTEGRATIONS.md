# Integrations: RTK, Graphify, AgentMemory

This repository ships three integration layers:

- RTK-style routing for toolkits and prompt flows
- Graphify-assisted codebase navigation and relationship analysis
- AgentMemory-compatible persistent memory workflows

It also uses a pack-based skill layout:

- shared: `skill-packs/github-skills/`
- domain: `skill-packs/dbt-skills/`

Marketplace-inspired portability metadata:

- `skill-packs/github-skills/.claude-plugin/plugin.json`
- `skill-packs/dbt-skills/.claude-plugin/plugin.json`

## 1. RTK integration

Core files:

- `src/ai-core/rtk-setup.ts`
- `src/ai-core/dbt-integration.ts`

Example route registration behavior:

- toolkit `dbt-core-analytics` for dbt workflows
- prompts mapped to command-style intents such as `dbt-audit`, `dbt-build`, and `dbt-test`

## 2. Graphify integration

Baseline graph workflow:

```bash
# Generate or refresh graph state if graphify CLI is installed
graphify update .

# Ask scoped questions
graphify query "what models depend on fct_orders"
graphify path "stg_shopify__orders" "fct_orders"
```

### TOON serialization pipeline

Graph output that is carried forward into LLM context is re-serialized as TOON
(Token-Oriented Object Notation, https://github.com/toon-format/spec), which declares
fields once and streams uniform rows instead of repeating keys per record:

```text
[ Graphify AST ] ─(JSON / NODE-EDGE text)→ [ graph_to_toon.py ] ─(TOON)→ [ LLM context ]
[ LLM response ] ─(TOON)→ [ graph_to_toon.py --decode ] ─(JSON)→ [ machine-parsable app ]
```

```bash
# build once per clone (plain rustc -O, no cargo; binary lands gitignored in rust/toon/bin/)
./scripts/build_toon_rs.sh

# graphify query text → TOON
graphify query "what models depend on fct_orders" --budget 800 \
  | rust/toon/bin/graph_to_toon --stats

# graph.json slice → TOON (normalizes rows so they encode tabular)
rust/toon/bin/graph_to_toon --graph graphify-out/graph.json \
  --community "Enhanza" --relation contains

# outbound leg: TOON from an LLM → strict JSON for machine consumers
cat response.toon | rust/toon/bin/graph_to_toon --decode
```

Serializer: `rust/toon/graph_to_toon.rs` — a dependency-free, single-file binary whose
functionality contract is documented in its own header comments. It is the sole runtime
of the pipeline; behavior is pinned at the CLI level by `tests/test_toon_serializer.py`
(cases ported from the TOON spec's normative rules), and `tests/conftest.py` builds the
binary on demand wherever `rustc` exists. TypeScript call sites route through
`src/ai-core/toon-serializer.ts` via `GraphManager.snapshotToToon()`.

The pipeline is enforced per prompt by hooks in `.claude/settings.json`, so it does not
depend on the agent remembering it:

- `UserPromptSubmit` → `scripts/hooks/toon_prompt_context.sh` injects a one-line
  pipeline assertion into context on every prompt.
- `PreToolUse` (Bash) → `scripts/hooks/toon_graphify_pipe.py` auto-appends
  `| rust/toon/bin/graph_to_toon --passthrough` to bare
  `graphify query|path|explain` invocations, and stays silent when the binary has not
  been built. `--passthrough` forwards anything the serializer does not recognize
  unchanged, so the rewrite can never break a command.

Hook behavior is pinned by `tests/test_toon_pipeline_hooks.py`.

Fallback graph snapshot command in this repo:

```bash
.claude/commands/infra/lint-and-graph.sh
```

This writes `.claude/graph-state.json` so the project always has a local graph artifact.

## 3. AgentMemory integration

[AgentMemory](https://github.com/rohitg00/agentmemory) is a **user-level service, not a
repository dependency**: a global npm install that runs a SQLite-backed memory engine on
`:3111` and keeps all state in `~/.agentmemory`. Every integration leg below is
timeout-guarded, so a checkout — or a CI runner — without the server behaves exactly as
before it existed.

One-time setup per machine:

```bash
npm install -g @agentmemory/agentmemory
agentmemory                       # start the server on :3111
agentmemory connect claude-code   # register the MCP server + lifecycle hooks
```

What the repository does with it:

- `scripts/sync_context.sh` mirrors each context-sync entry to
  `POST /agentmemory/remember` after writing the local checkpoint. The committed
  artifacts (`.claude/memory.md`, `.claude/agentmemory.json`, `.claude/checkpoints/`)
  remain the source of truth; the server is an enrichment index over them. Override the
  target with `AGENTMEMORY_URL`; an absent server means a silent skip and exit 0.
- `src/ai-core/memory-store.ts` exposes `AgentMemoryClient` (`health`, `remember`,
  `recall` via `/agentmemory/smart-search`) and `createBridgedMemoryStore()`, which
  probes the server and falls back to the in-memory `MemoryStore`. TypeScript call
  sites route through this wrapper, never raw fetch calls.
- `tests/test_agentmemory_bridge.py` pins the contract with a stub HTTP server, so the
  suite needs neither Node nor the real service.

Deliberately **not** done, and why:

- The upstream plugin's 15 skills and 12 lifecycle hooks stay at user level, installed
  by `agentmemory connect`. Vendoring them into `skill-packs/` would surface
  `/remember`, `/recall`, and `/forget` as new collisions in the skill-map scan.
- No repo-level lifecycle hooks for it: the plugin already observes sessions globally,
  and duplicating that in `.claude/settings.json` would break the no-duplicate-
  mechanisms rule while slowing every Bash call.
- Optional: set `CLAUDE_MEMORY_BRIDGE=true` to sync AgentMemory with Claude Code's own
  `MEMORY.md`, avoiding a third divergent memory store.

## 4. dbt Labs translated skills

dbt-labs/dbt-agent-skills patterns are incorporated and translated to dbt Core in:

- `.claude/skills/dbt-labs-core-translation/`
- `.claude/skills/using-dbt-for-analytics-engineering-core/`
- `.claude/skills/running-dbt-commands-core/`
- `.claude/skills/building-dbt-semantic-layer-core/`
- `.claude/skills/adding-dbt-unit-test-core/`
- `.claude/skills/working-with-dbt-mesh-core/`
- `.claude/skills/troubleshooting-dbt-job-errors-core/`

## 5. Unified context sync

Use:

```bash
./scripts/sync_context.sh "dbt build --select state:modified+"
```

This command:

1. Updates local markdown and JSON project memory.
2. Generates an up-to-date local graph snapshot.
3. Persists a checkpoint payload in `.claude/checkpoints/`.

## 6. Suggested flow in PRs

1. Run dbt command(s) and analyzers.
2. Run `./scripts/sync_context.sh "<summary>"`.
3. Include any generated mermaid output from `scripts/model_dependency_analyzer.py --mermaid` in PR notes.
4. Run tests (`pytest -q`).

## 7. Activating a skill stack

Use:

```bash
./scripts/activate_skill_stack.sh dbt-skills
```

This layers shared GitHub skills first, then overlays the selected domain pack.

## 8. Portability checks

Use:

```bash
./scripts/marketplace_portability_check.sh
```

This validates plugin manifests and checks large SKILL.md portability constraints.
