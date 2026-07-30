# Adding a connector

How to onboard a new source system — Spiris, NetSuite, Shopify, or anything else — into the
Enhanza dbt project.

The project is multi-tenant: one dbt project builds every customer's warehouse, and each
customer connects a different subset of sources. A connector is therefore not "some new
models"; it is an entry in a registry that a dozen macros read at compile time to decide
what exists for this run.

## The registry is the contract

`global_configs('all_available_sources')` in
[dbt_project/macros/config/global_configs.sql](dbt_project/macros/config/global_configs.sql)
is the single source of truth. Five things read it:

| Reader | Question it answers |
|---|---|
| `erp_union(concept)` | which sources does `erp_bi_<concept>` union? |
| `model_is_provided(concept)` | does any enabled source supply this concept? |
| `any_source_enabled([...])` | is at least one of these named sources on? |
| `add_erp_fields(columns)` | what `DataSource` and `DefaultCurrency` does this row carry? |
| `source_is_enabled(model)` | should this source-specific model exist for this run? |

Nothing else decides. If a connector is not in the registry it is invisible to the unified
layer, no matter how many models it ships — which is exactly how `favrit` shipped an
adapter and a gate in `erp_bi_fact_order_rows` while being absent from the registry
entirely, and how `xledger` claimed a `fact_vouchers` it had no adapter for.

[tests/test_enhanza_connector_registry.py](../../../../tests/test_enhanza_connector_registry.py)
now fails on both of those shapes. Run it before you open the PR.

## Layers a connector passes through

```
<source>_api                     sources.yml — raw, one schema per tenant
  └─ <source>_bi_<model>_staging  models/staging/<source>/ — rename, cast, coerce
       └─ <source>_bi_<model>     models/<source>_bi/ — user-facing, {{ auto_config() }}
  └─ <source>_erp_bi_<concept>    models/staging/<source>/ — adapter to the common schema
       └─ erp_bi_<concept>        models/staging/erp/ — union across sources, registry-driven
            └─ logic_bi_*         models/logic_bi/ — business logic, contracted
                 └─ Cube          semantic layer consumed by app.enhanza.com
```

Two distinct jobs live in `models/staging/<source>/`:

- **`<source>_bi_<model>_staging`** quarantines the raw source — renaming, casting, and
  coercion happen here and nowhere else. It feeds the source-aligned `<source>_bi` layer
  that users query directly.
- **`<source>_erp_bi_<concept>`** adapts the source's shape to the *common* ERP schema so
  it can be unioned with every other source. This is the one that must agree, column for
  column, with the other sources' adapters for the same concept.

A connector can ship the first without the second (Favrit's `dim_ratings` has no ERP
equivalent) but never the second without a registry claim.

## The procedure

### 1. Scaffold the skeleton

```bash
cd skill-packs/dbt-skills/use-cases/enhanza-analytics
python3 scripts/new_connector.py shopify \
    --display-name "Shopify" \
    --currency USD \
    --erp-concepts dim_customers,dim_articles,fact_orders,fact_order_rows
```

This writes the directory, the staging and adapter stubs, the `<source>_bi` one-liners, the
`sources.yml` block, and prints the registry entry to paste. It never overwrites an
existing file. Everything it emits is a stub with `[NEEDS INPUT]` markers where a real
column list belongs — it saves the typing, not the modeling.

### 2. Declare the raw source

Add the block to [dbt_project/models/sources.yml](dbt_project/models/sources.yml). The
source name is `<source>_api`, not `<source>` — every existing staging model calls
`source('fortnox_api', ...)`, and a bare `source('fortnox', ...)` will not resolve.

```yaml
  - name: shopify_api
    description: 'Shopify raw data'
    database: "{{ target.project | default(target.database) }}"
    schema: shopify_api_{{ var('uid') }}
    loaded_at_field: _loaded_at        # required — a source without freshness is an undocumented SLA
    freshness:
      warn_after: {count: 12, period: hour}
      error_after: {count: 24, period: hour}
    tables:
      - name: customers
      - name: orders
```

### 3. Register the connector

Add an alphabetically-placed entry to `all_available_sources`:

```jinja
'shopify': {
    'name': 'Shopify',
    'default_currency': 'USD',
    'enabled': var('is_shopify_enabled', 'False') | as_bool,
    'included_models': [
        'dim_customers',
        'dim_articles',
        'fact_orders',
        'fact_order_rows'
    ]
},
```

Three rules the tests enforce:

- The key (`shopify`) must match the `is_<key>_enabled` var, the
  `models/staging/<key>/` directory, and the `<key>_erp_bi_*` filename prefix. These are
  string-matched at compile time, not resolved — a mismatch produces silence, not an error.
- Every concept in `included_models` that has an `erp_bi_<concept>` union model must have a
  `<key>_erp_bi_<concept>.sql` adapter on disk.
- Omit `default_currency` rather than guessing it. `add_erp_fields()` emits a NULL
  `DefaultCurrency` for sources without one, which is honest; a wrong currency silently
  mis-values every row.

### 4. Declare the enable var

Add `is_shopify_enabled: false` to the `vars:` block in
[dbt_project/dbt_project.yml](dbt_project/dbt_project.yml), and the connector tag under
`models: → staging: → shopify:`.

### 5. Write the staging and adapter models

Per raw table, one `shopify_bi_<model>_staging.sql` that enumerates columns — no
`select *` past this layer. Per ERP concept, one `shopify_erp_bi_<concept>.sql` whose
output columns match the other sources' adapters for the same concept exactly:

```sql
{{ config(materialized='ephemeral', enabled = var('is_shopify_enabled', false)) }}

select
  CustomerId
  , CustomerNumber
  , Name
  {{ add_erp_fields(['CustomerId', 'CompanyId']) }}
from {{ ref('shopify_bi_dim_customers_staging') }}
```

Compare against `fortnox_erp_bi_dim_customers.sql` column by column. A column present in
one adapter and absent from another breaks the `UNION ALL` at compile time; a column in the
wrong *position* with a compatible type does not — it silently transposes the data.

### 6. Nothing to change in the unified layer

This is the point of the registry. `erp_bi_dim_customers.sql` is:

```sql
{{ config(materialized='ephemeral') }}

{{ erp_union('dim_customers') }}
```

It picks up Shopify the moment the registry claims `dim_customers` and
`is_shopify_enabled` is true. No edit. Before this refactor the same change meant adding a
five-line block to each of the ~30 `erp_bi_*` models the connector touched.

If the new concept has no `erp_bi_<concept>` model yet — because no source supplied it
before — create one. It is three lines.

### 7. Verify

```bash
# Registry invariants — runs without a warehouse
python3 -m pytest tests/test_enhanza_connector_registry.py -q

# Parse and compile with only the new connector on
cd skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project
dbt parse --vars '{"uid": "<tenant>", "is_shopify_enabled": true, "is_erp_enabled": true}'
dbt build --select tag:shopify --vars '{"uid": "<tenant>", "is_shopify_enabled": true}'

# Then with the connector alongside an existing one, which is what catches
# adapter column drift in the UNION ALL
dbt build --select tag:unified+ \
  --vars '{"uid": "<tenant>", "is_shopify_enabled": true, "is_fortnox_enabled": true, "is_erp_enabled": true}'

dbt source freshness --select source:shopify_api
```

`dbt build`, not `dbt run` then `dbt test` — build stops dependents when a test fails
instead of propagating bad data through the whole DAG.

### 8. Test and document

Minimum bar per model: `unique` and `not_null` on the primary key, `relationships` on every
foreign key into a conformed dimension, and a description that states the grain rather than
restating the model name. Add the connector's row to the source contract in
[source-contract.md](source-contract.md).

## Definition of done

- [ ] `sources.yml` block with `loaded_at_field` and `freshness`
- [ ] Registry entry, alphabetically placed, currency stated or deliberately omitted
- [ ] `is_<source>_enabled` declared in `dbt_project.yml` vars, connector tag added
- [ ] One staging model per raw table, columns enumerated
- [ ] One adapter per claimed ERP concept, columns matching the other adapters
- [ ] `<source>_bi` one-liners for the user-facing layer
- [ ] `pytest tests/test_enhanza_connector_registry.py` green
- [ ] `dbt build --select tag:<source>` green, and green again unioned with Fortnox
- [ ] `unique`/`not_null` on every PK, `relationships` on every FK
- [ ] Row added to [source-contract.md](source-contract.md)
- [ ] Rollback path stated: which commit, and whether a `--full-refresh` is needed

## Known drift to resolve

| Item | State |
|---|---|
| `xledger` `fact_vouchers` | Registry claim removed; no `xledger_erp_bi_fact_vouchers` adapter exists. Restore the claim in the same commit that adds the adapter. **[NEEDS INPUT]** — does Xledger supply vouchers? |
| `favrit` `default_currency` | Omitted; Favrit is multi-currency and the tenant default is unconfirmed. **[NEEDS INPUT]** |
| `source('fortnox', ...)` in docs | [source-conventions.md](source-conventions.md) writes the source name without the `_api` suffix that `sources.yml` and every staging model actually use. |
| `*_scaffold` models | `dim_customers_scaffold`, `orders_mart_scaffold`, `stg_sales_orders_scaffold` are starter placeholders, not part of the Enhanza DAG. Tagged `scaffold`; remove when no longer needed. |
