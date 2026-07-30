# Enhanza Analytics use case

One dbt Core project that builds a warehouse per tenant from whichever subset of nine ERP
and POS systems that tenant has connected, and exposes governed metrics to app.enhanza.com
through Cube.

```
<source>_api_<uid>   raw, one BigQuery dataset per connector per tenant
  └─ staging          rename / cast / coerce, 1:1 with a raw table
       ├─ <source>_bi     source-aligned, user-facing
       └─ <source>_erp_bi adapter to the common ERP schema
            └─ erp_bi     unified across enabled sources — registry-driven
                 └─ logic_bi   business logic, 15 of 17 models under enforced contract
                      └─ Cube  semantic layer consumed by the app
```

## Adding a connector

**[CONNECTORS.md](CONNECTORS.md)** is the procedure. Short version:

```bash
python3 scripts/new_connector.py spiris --display-name "Spiris" \
    --erp-concepts dim_customers,fact_invoices
```

then paste three blocks — a `sources.yml` entry, a registry entry, and a
`dbt_project.yml` var — and write the adapter columns. **No edit to any `erp_bi_*` union
model is required**, because `global_configs('all_available_sources')` is the single source
of truth and `erp_union()` reads it.

Verify with `python3 -m pytest tests/test_enhanza_connector_registry.py -q`, which fails if
the registry and the models on disk disagree.

## Documents

| File | What it holds |
|---|---|
| [use-case-spec.md](use-case-spec.md) | the decision, consumer, grain, and verdict |
| [CONNECTORS.md](CONNECTORS.md) | how to onboard a new source system |
| [data-model-canvas.md](data-model-canvas.md) | entities, conformance, key construction, open modeling decisions |
| [bus-matrix.md](bus-matrix.md) | processes × conformed dimensions × connector coverage |
| [source-contract.md](source-contract.md) | what the nine connector APIs guarantee, and what is unverified |
| [deployment-runbook.md](deployment-runbook.md) | risk tiers, verification, rollback |
| [source-conventions.md](source-conventions.md) | source naming and staging guidance |
| [dbt-model-patterns.md](dbt-model-patterns.md) | layer conventions and example model names |
| [cube-metric-guidance.md](cube-metric-guidance.md) | Cube metric guidance for app-facing analytics |
| [skills/enhanza-business-logic/SKILL.md](skills/enhanza-business-logic/SKILL.md) | domain-specific business logic |
| [skills/enhanza-dbt-skill/SKILL.md](skills/enhanza-dbt-skill/SKILL.md) | dbt implementation guidance |

## The dbt project

[dbt_project/](dbt_project/) — roughly 430 models across nine connectors.

Three macro families carry most of the design; read them before changing a model:

| Macro | File | Role |
|---|---|---|
| `global_configs('all_available_sources')` | [macros/config/global_configs.sql](dbt_project/macros/config/global_configs.sql) | the connector registry — everything else reads it |
| `erp_union(concept)` | [macros/erp/erp_union.sql](dbt_project/macros/erp/erp_union.sql) | builds each unified model's `UNION ALL` from the registry |
| `add_erp_fields(columns)` | [macros/erp/add_erp_fields.sql](dbt_project/macros/erp/add_erp_fields.sql) | emits `DataSource`, `DefaultCurrency`, and the `<Column>ERP` cross-source keys |
| `auto_config(suffix)` | [macros/config/auto_config.sql](dbt_project/macros/config/auto_config.sql) | generates the whole body of a `<source>_bi` model |
| `source_is_enabled` / `model_is_provided` | [macros/enablement/model_enablement.sql](dbt_project/macros/enablement/model_enablement.sql) | decides whether a model exists for this run |

`auto_config()` is why most `<source>_bi/*.sql` files are a single line: the macro emits
both the `config()` and the `select * from {{ ref(model_name ~ '_staging') }}`. It keeps
~250 files to one line each, at the cost of lineage that static analysis cannot follow —
`dbt` resolves it correctly, `dbt ls` and the docs site show it, but a grep for `ref(` in
those files finds nothing.

## Running it

Every run needs a tenant. There is no default `uid`, deliberately.

```bash
cd dbt_project

dbt build --select tag:fortnox \
  --vars '{"uid": "<tenant>", "is_fortnox_enabled": true}'

dbt build --select tag:unified+ \
  --vars '{"uid": "<tenant>", "is_fortnox_enabled": true, "is_tripletex_enabled": true, "is_erp_enabled": true}'

dbt build --exclude tag:scaffold --vars '{"uid": "<tenant>", ...}'
```

Connector and layer tags come from [dbt_project/dbt_project.yml](dbt_project/dbt_project.yml).

## Known gaps

Tracked in the documents above rather than buried in code comments:

- **No source freshness anywhere.** None of the 17 sources declares `loaded_at_field` or
  `freshness:`, so `dbt source freshness` is a no-op and a dead connector is
  indistinguishable from a quiet one. See [source-contract.md](source-contract.md).
- **28 `foreign_key` constraints, 0 `relationships` tests.** BigQuery does not enforce the
  constraints (`warn_unenforced: False`), so nothing checks the joins.
  See [data-model-canvas.md](data-model-canvas.md).
- **No snapshots on any connector source**, so mutable source values are overwritten with
  no history.
- **Two registry items need a decision** — Xledger `fact_vouchers` and the Favrit default
  currency. Listed in [CONNECTORS.md](CONNECTORS.md#known-drift-to-resolve).
- **`*_scaffold` models** (`dim_customers_scaffold`, `orders_mart_scaffold`,
  `stg_sales_orders_scaffold`, `orders_scaffold_snapshot`) are starter placeholders from
  the initial import, not part of the Enhanza DAG. Tagged `scaffold` so a real build can
  exclude them; remove when no longer wanted.
