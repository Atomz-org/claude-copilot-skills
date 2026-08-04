# Semantic-layer alignment — dbt and WrenAI

**Question:** can WrenAI use the ontologies and topologies so that the semantic layer is the
same for both dbt and WrenAI?

**Answer:** yes — and there is a measured reason to do it now. The semantic layer is **not**
currently the same across the two, and the gap is a wrong number, not a cosmetic difference.

The "measured" sections were reproduced against the committed state of
`example-order-revenue-mart` before the fix. The compiler that closes the gap lives in
`scripts/wren_context_sync.py` (`build_metric_views`): every MetricFlow metric and saved
query compiles to an MDL **view** of the same name, so `SELECT * FROM revenue` through the
engine returns 277,183.41 — the metric — for BI and agents alike. Cubes are no longer
generated; committed ones are deleted as generation-owned orphans on the next sync.

Two things the compilation surfaced, worth keeping:

- **wren-core registers parameterized `DECIMAL(p, s)` as Utf8** when planning a view
  statement, so aggregates over decimal columns fail to plan inside views while model
  queries work. Workaround: generated SQL CASTs bare decimal measure columns to their own
  catalog type (a no-op at execution). Upstream fix staged at
  `external/patches/wren-core-parameterized-decimal.patch`.
- **The equivalence check is only as good as its oracle.** First-pass oracle SQL for
  `revenue_trailing_28d` added the revenue filter — but the dbt metric declares *none*, so
  it is trailing gross order total, cancelled orders included. The view compiles the
  definition as written; whether the definition should carry the filter is a dbt-side
  modeling question, now visible instead of buried.

Context for the integration as a whole: [WRENAI_INTEGRATION.md](WRENAI_INTEGRATION.md) and
[../.claude/rules/wren-rules.md](../.claude/rules/wren-rules.md).

## The divergence, measured

`revenue` is defined in MetricFlow as the measure `order_total` filtered to
`order_status != 'cancelled'`. The Wren cube carries the **unfiltered** measure:

```
MDL cube measure  orders.order_total  = 289,470.66
dbt metric        revenue             = 277,183.41      ← 4.4% apart
MDL cube measure  orders.order_count  = 492
dbt metric        order_count         = 470
```

Reproduce:

```bash
.venv-wren/bin/python -c "
import duckdb
c=duckdb.connect('skill-packs/dbt-skills/use-cases/example-order-revenue-mart/dbt_project/dev.duckdb',read_only=True)
q=lambda s: c.sql(s).fetchone()[0]
print('MDL cube measure  orders.order_total  =', q('select sum(order_amount_usd) from marts.fct_orders'))
print('dbt metric        revenue             =', q(\"select sum(order_amount_usd) from marts.fct_orders where order_status <> 'cancelled'\"))
print('MDL cube measure  orders.order_count  =', q('select count(order_id) from marts.fct_orders'))
print('dbt metric        order_count         =', q(\"select count(order_id) from marts.fct_orders where order_status <> 'cancelled'\"))
"
```

Ask dbt for `revenue` and Wren for `order_total` and you get two numbers that are each
internally consistent. That is exactly the "two dashboards disagree" failure that
[analytics rule 42](../.claude/rules/analytics-engineering-rules.md) exists to prevent,
reproduced inside the integration meant to prevent it.

## Why it diverges

The now-removed `build_cubes()` built cubes from `sm.get("measures")` — the **semantic
model's** measures. `man.metrics` never reached a cube; it went to
`knowledge/rules/semantic-metrics.md` as prose. So the filter, the ratio, and the offset
window existed only as English for the text-to-SQL layer to read.

An LLM query might have honoured them. A `wren cube` query could not — there was no
`revenue` in the MDL to honour.

The ontology has the same shape of problem, one level up. `concepts_markdown()` writes all 58
concepts as a markdown bullet list, and the compiled MDL reports `views: 0`. The conformed
entity is narrated, never planned against.

## The second gap: this path had never run

The two halves lived in different use-cases (state before the fix):

| Use-case | MetricFlow | ontology + topology | `wren/` |
|---|---|---|---|
| `example-order-revenue-mart` | ✅ 2 semantic models, 7 metrics | ❌ `column-memory.json` only | ✅ 13 models, 2 cubes |
| `enhanza-analytics` | ❌ none | ✅ 58 concepts, 19 connectors, 92 mappings | ❌ absent |

So `concepts_markdown()` and `drift_markdown()` produced nothing in the committed state — the
ontology→Wren path was unexercised code. It is now proven on `enhanza-analytics`: 176
models imported (272 dropped for missing column info, stated in the payload), 101
relationships, 58 concepts and the conformed column contracts in `knowledge/`, the
whole project served over MCP. Two further upstream defects surfaced at that scale and
got the workaround-plus-patch treatment: alias collisions across connectors (21) and
the `[mcp]` extra resolving an incompatible mcp 2.x.

## The architecture: one definition, two compilations

Not "keep two semantic layers in sync" — extend the doctrine
[wren rule 4](../.claude/rules/wren-rules.md) already applies to metrics so that it covers
entities and concepts as well. dbt and the ontology stay authoritative; MDL becomes compiled
output, never hand-authored.

| Source of truth | Wren MDL primitive | At assessment time |
|---|---|---|
| MetricFlow measure | cube `measures` | ✅ |
| MetricFlow dimension | cube `dimensions` / `time_dimensions` | ✅ |
| MetricFlow entity | `relationships.yml` | ⚠️ derived from dbt *tests* — a physical FK graph, not the entity graph |
| MetricFlow metric (filter / ratio) | **MDL view** | ❌ prose only ← the wrong number |
| Ontology concept | **MDL view** over the adapter union | ❌ prose only |
| Ontology property → source column | model column `properties` | ❌ prose only |
| Topology coverage / drift | knowledge caveat | ❌ absent |

Views are the vehicle, and they are already first-class in the pinned CLI:
`wren context validate` performs a **view SQL dry-plan**, so a compiled metric is verifiable
with no warehouse and no credentials. That fits the existing
[wren rule 6](../.claude/rules/wren-rules.md) no-warehouse gate rather than needing a new one.

The ontology payoff is larger than the metric fix. `dim_accounts` is realized by 5 connectors
with 5 different raw column names. Compiling the concept to a view gives Wren one queryable
`dim_accounts` with conformed column names — the thing the ontology asserts and that nothing
today can execute.

## The part that will not be exact

`revenue_growth_mom` (derived, 1-month offset) and `revenue_trailing_28d` (cumulative window)
have no MDL primitive. Two options:

| Option | Correctness | Cost |
|---|---|---|
| Prose in `semantic-metrics.md` | silently wrong for any non-LLM query | none — this is today |
| Generated MDL view | correct | the formula now exists twice: MetricFlow YAML **and** generated SQL |

Recommendation: take the view, treat MetricFlow as authoritative, and carry the generated
header contract every other artifact here already carries. It is a real second copy and
should not be presented as anything else. Simple and ratio metrics compile exactly.

## Scope, and where it stands

1. **Compile metrics to MDL views — done.** `build_metric_views()` compiles simple,
   ratio, derived (offset), cumulative (window / grain-to-date), and saved queries;
   8/8 on the example project, each equal to a hand-written oracle. Cubes are no
   longer generated; committed ones deleted as generation-owned orphans.
2. **Ontology concepts as MDL views — deliberately not built.** The conformed concept
   *is already a dbt model* here (the `erp_union()` marts), and those models are in the
   MDL after import. Compiling a second union in Wren SQL would duplicate dbt logic —
   the exact thing the bridge refuses to do. The ontology's job in the MDL is context
   (`knowledge/rules/ontology-concepts.md`, column contracts), and that now ships.
3. **MetricFlow entities into `relationships.yml` — not done.** `relationships.yml` is
   importer-owned (wren rule 1); overwriting it from the bridge would break the
   disjoint-generators contract. Revisit only with an upstream seam.
4. **Drift into `knowledge/caveats/` — done** (`adapter-drift.md`, when drift exists).

Proven on `enhanza-analytics` (which now has a `wren/` project), and the
**equivalence gate** is `tests/test_wren_semantic_equivalence.py`: every metric view
row-for-row against an oracle restating its definition — a metric that drifts from its
view fails a test instead of surfacing in a dashboard.

## Appendix — CLI surface this relies on

```console
$ .venv-wren/bin/wren context --help
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ import        Import a Wren project from an external source.                 │
│ init          Initialize a new Wren project.                                 │
│ validate      Validate MDL project: YAML structure + view SQL dry-plan +     │
│               description checks.                                            │
│ build         Build into target/mdl.json for the engine.                     │
│ show          Show the current project context (models, views,               │
│               relationships).                                                │
│ instructions  Print business rules (knowledge/rules/ + legacy                │
│               instructions.md) for LLM consumption.                          │
│ set-profile   Bind a connection profile to this project.                     │
│ upgrade       Upgrade project schema_version to enable new features.         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

`wren context validate` is the gate that makes compiled views reviewable without a warehouse.
`wren cube` was the structured query surface that bypassed every metric definition — with
cubes no longer generated, the governed surface for a metric is its view, over SQL and MCP
alike.
