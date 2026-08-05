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

## Layout: one connector, one dbt package

Every connector is a standalone dbt package under `packages/<source>/`, installed by one
line in the root `packages.yml` and gated per tenant by `is_<source>_enabled` in the root
`dbt_project.yml`. Those are two different dials on purpose: `packages.yml` decides what
is *installed* (composition, per deployment); the vars decide what is *enabled* (tenancy,
per run). The root project — `enhanza_erp_bi` — owns the unified layer, the marts, the
mechanism macros, and the registry; `packages/core/` owns the shared reference sources.

Two placements are dbt Core's rules, not this project's taste. Mechanism macros and the
registry live in the **root** project because dbt resolves an unqualified macro call
through the calling package and the root only — never a sibling package. The tenancy
gates live in the **root** `dbt_project.yml` because dbt fully renders CLI vars only
there; the same gate declared inside a package's own yml read its default and silently
disabled all 70 Fortnox BI models (the graph emitter's coverage gate caught it).

## Layers a connector passes through

```
<source>_api                     packages/<source>/models/sources.yml — raw, one schema per tenant
  └─ <source>_bi_<model>_staging  packages/<source>/models/staging/ — rename, cast, coerce
       └─ <source>_bi_<model>     packages/<source>/models/<source>_bi/ — user-facing, {{ auto_config() }}
  └─ <source>_erp_bi_<concept>    packages/<source>/models/staging/ — adapter to the common schema
       └─ erp_bi_<concept>        models/erp/ — union across sources, registry-driven (root)
            └─ logic_bi_*         models/logic_bi/ — business logic, contracted (root)
                 └─ Cube          semantic layer consumed by app.enhanza.com
```

Two distinct jobs live in `packages/<source>/models/staging/`:

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

This writes the package skeleton under `packages/<source>/` — its `dbt_project.yml`, the
staging and adapter stubs, the `<source>_bi` one-liners — and prints the `packages.yml`
install line, the `sources.yml` block, and the registry entry to paste. It never
overwrites an existing file. Everything it emits is a stub with `[NEEDS INPUT]` markers
where a real column list belongs — it saves the typing, not the modeling.

### 2. Declare the raw source

Add the block to the package's own `packages/<source>/models/sources.yml` — the connector
owns its source declaration. The source name is `<source>_api`, not `<source>` — every
existing staging model calls `source('fortnox_api', ...)`, and a bare
`source('fortnox', ...)` will not resolve.

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

- The key (`shopify`) must match the `is_<key>_enabled` var, the `packages/<key>/`
  directory, and the `<key>_erp_bi_*` filename prefix. These are string-matched at
  compile time, not resolved — a mismatch produces silence, not an error.
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

Alignment first. It needs no warehouse, no profile, and no parse, so it runs in CI and on a
laptop alike — and it catches the defects that otherwise surface as an unrelated-looking
failure three steps later:

```bash
python3 scripts/connector_alignment_check.py \
    --use-case enhanza-analytics --connector shopify --check
```

It reads the conventions off the connectors already on disk (via
`scripts/new_connector.py`'s `detect()`, so the scaffolder and the checker cannot disagree
about what the convention is) and reports:

| Check | What it catches |
|---|---|
| `hardcoded-source` | a `FROM database.schema.table` — invisible to lineage, `--select`, and state comparison |
| `unregistered-connector` | staging models with no `all_available_sources` entry; `erp_union()` will never union them |
| `test-syntax` | generic tests using the dbt ≥1.10 `arguments:` nesting under a project pinned below it |
| `no-enable-var` | a missing `is_<source>_enabled` default, so a `--vars` typo silently disables the connector |
| `alias-collision` | two models resolving to one relation in one schema (needs `--manifest`) |
| `adapter-column-drift` | your adapter omits a column its peers supply (needs `--manifest` + `sqlglot`) |
| `undeclared-schema` | a new model directory with no `+schema` (needs `--manifest`) |
| `no-source-block` / `no-freshness` | rules 13 and 14 |
| `naming` / `undocumented-model` | drift from the project's own staging and adapter shapes |

Everything above the `--manifest` line looks only at the connector's **own** files. Whether
it *conflicts* with the models already in the project is a different question, and it needs
a manifest — so run the check a second time after parsing:

```bash
./skill-packs/dbt-skills/use-cases/enhanza-analytics/artifacts/refresh.sh

python3 scripts/connector_alignment_check.py \
    --use-case enhanza-analytics --connector shopify \
    --manifest skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project/target/manifest.json \
    --check
```

With `--manifest` every model in the project is compared, and the collisions **this
connector participates in** are reported — the project's pre-existing drift is not dumped on
top of them. A new `shopify_bi_dim_customers` landing in a dataset that already owns
`dim_customers` fails here, naming both models, rather than at `dbt build` naming two models
that each look fine.

#### Adapter columns

With `sqlglot` installed the same run compares your adapter's **columns** against the other
adapters for the same concept. This is the check that used to require a warehouse:
`erp_union()` stacks one adapter per enabled source, so an adapter missing a column its
peers carry produces a union that is only wrong when **two** connectors are on at once —
`dbt build --select tag:<your connector>` passes, and the failure waits for a tenant who has
both.

It found this on first run:

```
[error] adapter-column-drift: `visma_economic_erp_bi_dim_articles` is missing 1 column(s)
        that 5 other adapter(s) supply: Active; it has isActive that no other adapter does
        — likely the same column under a different name
```

Note that `dim_customers` adapters legitimately use `isActive` while `dim_articles` adapters
use `Active`. The check compares within a concept, not across the project, so both
conventions stand and only the outlier is reported.

To see the column mapping each existing connector uses before writing yours:

```bash
python3 scripts/dbt_column_lineage.py \
    --manifest skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project/target/manifest.json \
    --column OrgName
```

```
seventime_erp_bi_dim_company.OrgName        <- seventime_api__companyinformation.companyName  [renamed]
upsales_erp_bi_dim_company.OrgName          <- upsales_api__self.client                       [renamed]
visma_economic_erp_bi_dim_company.OrgName   <- visma_economic_api__self.company               [renamed]
tripletex_erp_bi_dim_company.OrgName        <- tripletex_api__division.name                   [renamed]
```

That is the contract your adapter has to satisfy: same output name, whatever your source
calls it. `sqlglot` is optional — without it this check is skipped rather than guessed.

Then the build:

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

### 8. Refresh the graph

`graphify` has no SQL parser. A `.sql` file enters the graph as an isolated node with no
symbols and no edges, so a new connector's models are present but unreachable until the dbt
DAG is re-ingested. Before this was wired up, all 393 `.sql` nodes in the repository sat at
degree 0 and the only dbt entity with any edges was a `schema.yml` node.

```bash
./skill-packs/dbt-skills/use-cases/enhanza-analytics/artifacts/refresh.sh
python3 scripts/dbt_manifest_to_graphify.py \
    --manifest skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project/target/manifest.json \
    --merge
```

`refresh.sh` parses with **every** connector enabled, which is the part that is easy to get
wrong. Connectors are gated behind `is_<source>_enabled` vars that all default to false, so
`dbt parse` with defaults writes a manifest holding a fraction of the project — the one
committed here before this existed had 72 of 359 models and 66 of 981 dependency edges,
internally consistent and silently partial. The emitter's coverage gate compares the
manifest against the `.sql` files on disk and refuses to emit below 95%.

### 9. Test and document

Minimum bar per model: `unique` and `not_null` on the primary key, `relationships` on every
foreign key into a conformed dimension, and a description that states the grain rather than
restating the model name. Add the connector's row to the source contract in
[source-contract.md](source-contract.md).

## Definition of done

- [ ] `sources.yml` block with `loaded_at_field` and `freshness`
- [ ] Registry entry, alphabetically placed, currency stated or deliberately omitted
- [ ] `is_<source>_enabled` declared in `dbt_project.yml` vars, connector tag added
- [ ] `+schema:` declared for every new model directory — see *One directory, one dataset*
- [ ] One staging model per raw table, columns enumerated
- [ ] One adapter per claimed ERP concept, columns matching the other adapters
- [ ] `<source>_bi` one-liners for the user-facing layer
- [ ] `python3 scripts/connector_alignment_check.py --connector <source> --check` green
- [ ] `pytest tests/test_enhanza_connector_registry.py` green
- [ ] `dbt build --select tag:<source>` green, and green again unioned with Fortnox
- [ ] `unique`/`not_null` on every PK, `relationships` on every FK
- [ ] `artifacts/refresh.sh` re-run and the graphify fragment committed
- [ ] Row added to [source-contract.md](source-contract.md)
- [ ] Rollback path stated: which commit, and whether a `--full-refresh` is needed

## One directory, one dataset

`model_alias()` strips the connector prefix, so `fortnox_bi_dim_accounts`,
`tripletex_bi_dim_accounts`, `logic_bi_dim_accounts` and `erp_bi_dim_accounts` all resolve to
the bare relation `dim_accounts`. 38 aliases in this project are claimed by more than one
model, and that is intended — the **dataset**, not the table name, is what separates them.

What makes it work is a `+schema` on every model directory in `dbt_project.yml`. Without one
a directory falls back to `target.schema` and competes with every other directory that also
lacks one; dbt then refuses to parse with more than a narrow subset of connectors enabled,
reporting *"two resources with the database representation"* and naming two models that have
nothing wrong with them. This is why `generate_schema_name` exists.

A new connector therefore adds a `+schema` for each directory it introduces:

```yaml
    staging:
      shopify:
        +schema: shopify_staging     # <source>_staging
    shopify_bi:
      +schema: shopify_bi            # the user-facing dataset
```

`connector_alignment_check.py --manifest ...` fails on an alias collision *within* a dataset,
which is the only kind that is a defect.

## Known drift to resolve

| Item | State |
|---|---|
| `xledger` `fact_vouchers` | Registry claim removed; no `xledger_erp_bi_fact_vouchers` adapter exists. Restore the claim in the same commit that adds the adapter. **[NEEDS INPUT]** — does Xledger supply vouchers? |
| `favrit` `default_currency` | Omitted; Favrit is multi-currency and the tenant default is unconfirmed. **[NEEDS INPUT]** |
| `source('fortnox', ...)` in docs | [source-conventions.md](source-conventions.md) writes the source name without the `_api` suffix that `sources.yml` and every staging model actually use. |
| `*_scaffold` models | `dim_customers_scaffold`, `orders_mart_scaffold`, `stg_sales_orders_scaffold` are starter placeholders, not part of the Enhanza DAG. Tagged `scaffold`; remove when no longer needed. |
| Source freshness | 8 of 10 connectors have a `sources.yml` block with no `loaded_at_field`, so `dbt source freshness` cannot run for them — rule 14. Reported as `no-freshness` by the alignment check. **[NEEDS INPUT]** per connector: which column carries the load timestamp? |
| `fortnox_base_v2_invoices` | Matches neither the staging nor the adapter naming shape, and has no `schema.yml` entry. Either rename to the convention or document why it is exempt. |
| Tested keys | 332 of 359 models have no column carrying both `unique` and `not_null` — rule 21. Reported by `dbt_manifest_to_graphify.py` on every run. |
