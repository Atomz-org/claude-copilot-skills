---
description: Define a metric in MetricFlow and validate it, or answer a question from the semantic layer
argument-hint: <metric to define, or a business question to answer>
---

Handle this semantic-layer request: **$ARGUMENTS**

Load `semantic-layer-metricflow`. Work out which of the two modes applies — if the request
is ambiguous, ask, because they are not interchangeable.

**dbt Core scope:** MetricFlow runs locally via `dbt-metricflow` and the `mf` CLI. The
hosted Semantic Layer API that BI tools connect to is dbt Cloud only. On Core, serve BI by
exporting `saved_queries` into tables.

---

## Mode A — the metric exists: answer the question

**Query it. Do not write ad-hoc SQL** — ad-hoc SQL is how the second definition gets born.

```bash
mf list metrics                              # does it exist?
mf list dimensions --metrics revenue         # what can you group by?

mf query --metrics revenue,order_count \
         --group-by metric_time__quarter,customer__region \
         --where "{{ Dimension('customer__region') }} = 'EMEA'" \
         --order -metric_time__quarter --limit 20
```

1. If the metric does not exist, **define it** (Mode B) rather than answering with ad-hoc
   SQL — unless the question is genuinely one-off.
2. If the requested slice is unavailable, the dimension is missing from the semantic model,
   not from the query.
3. **State the metric definition alongside the number.** A number without its definition is
   how two dashboards start disagreeing.
4. If the answer surprises you, `--explain` and read the generated SQL before believing it.
5. Use `metric_time` rather than a model-specific time column, so metrics from different
   semantic models align on one timeline.

---

## Mode B — define a new metric

### 1. Semantic model first

Semantic models sit on **marts**, never staging — the semantic layer describes the
business; staging describes a source system.

Build order: entities (the join keys) → dimensions → measures → metrics.

Every `type: time` dimension needs `type_params.time_granularity`. This is the single most
common validation failure.

### 2. Pick the metric type

| Type | Use |
|---|---|
| `simple` | one measure, optionally filtered |
| `ratio` | numerator / denominator |
| `derived` | arithmetic over other metrics, with optional time offsets |
| `cumulative` | running or windowed accumulation (`window` **xor** `grain_to_date`) |
| `conversion` | did an entity that did A go on to do B within a window |

### 3. Write it

Patterns: [templates/dbt-patterns.md](../../../templates/dbt-patterns.md).

Details that cause most of the failures:

- **Filters use Jinja objects with the `entity__dimension` prefix**:
  `{{ Dimension('order__order_status') }}`, not `order_status`.
- `fill_nulls_with: 0` — without it, empty periods break `offset_window` arithmetic.
- `join_to_timespine: true` emits a row per spine period, including empty ones.
- `offset_window` (a duration back) ≠ `offset_to_grain` (the start of a period).
- Derived `expr` is real SQL — always `nullif` the denominator.
- Cumulative metrics, offsets, and `join_to_timespine` all **require a time spine** whose
  end date runs **past** your fact data.

### 4. Validate — offline first, then MetricFlow

```bash
dbt parse
python scripts/semantic_layer_validator.py --path models/ --strict   # seconds, no warehouse
mf validate-configs
mf list metrics
```

### 5. Check the number — not optional

```bash
mf query --metrics <metric> --group-by metric_time__month --explain
```

Take the generated SQL and compare one period against a hand-written query you trust.

**A metric that validates and returns the wrong number is worse than no metric**, because
it carries the semantic layer's authority. Do this once per metric at definition time, and
record the check in the metric's `description`.

### 6. Serve it on dbt Core

```yaml
saved_queries:
  - name: weekly_revenue_by_region
    query_params:
      metrics: [revenue, order_count]
      group_by: [TimeDimension('metric_time', 'week'), Dimension('customer__region')]
    exports:
      - name: weekly_revenue_by_region
        config: {export_as: table, schema: bi_marts}
```

Schedule `dbt sl export` after the marts build. BI reads a plain table, but the metric is
still defined once in YAML.

---

## Mode C — two dashboards disagree

This is the problem the semantic layer exists for. Diagnose in order:

1. **Definition** — different filters (cancelled orders, test accounts, internal customers).
   Nine times in ten, this is it.
2. **Grain / time basis** — order date vs ship date; calendar vs fiscal 4-4-5.
3. **Timezone** — UTC vs local, and where the day boundary falls.
4. **Freshness** — different snapshots of the same table.
5. **Fan-out** — one joined to a 1:N table and double-counted.

Compare the two with `mf query ... --explain` and diff the SQL.

The fix is one MetricFlow definition and both dashboards reading it. **Record the old
definitions in the metric's `description`** — that is what stops the argument recurring in
six months.

---

## Rules that bind here

[Rules 42–45](../../rules/analytics-engineering-rules.md): a metric is defined once, in the
semantic layer; semantic models sit on marts; every semantic model declares its primary
entity, `agg_time_dimension`, and every time dimension's granularity; metrics validate
before they ship.

## Output

- the semantic model and metric YAML;
- the validator and `mf validate-configs` results;
- **the number checked against a known-good query**, with both shown;
- the definition in plain English, ready to paste into the metric's `description`;
- for a disagreement: which definition was right, and why.
