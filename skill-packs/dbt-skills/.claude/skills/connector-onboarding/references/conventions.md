# How connector conventions are detected

`scripts/new_connector.py` does not have a house style. It reads the target project's
busiest existing connector and copies what it finds, so two use-cases with different layouts
get different output from the same command.

## What gets detected

| Property | Learned from | Example A | Example B |
|---|---|---|---|
| model prefix | filename before the connector name | `` | `stg_` |
| staging infix | filename between connector and model name | `_bi_` | `__` |
| staging suffix | trailing `_staging`, or absent | `_staging` | `` |
| adapter infix | non-`_staging` files in the same directory | `_erp_bi_` | *(none)* |
| source-aligned dir | `models/<connector><suffix>/` across all connectors | `_bi` | *(none)* |
| source suffix | the `- name:` entry in `sources.yml` | `_api` | `` |
| registry | a macro containing `all_available_sources` | present | absent |
| `auto_config` | a macro of that name | present | absent |

Example A is `enhanza-analytics` → `shopify_bi_dim_customers_staging`,
`shopify_erp_bi_dim_customers`, `models/shopify_bi/`, source `shopify_api`.
Example B is `example-order-revenue-mart` → `stg_stripe__charges`, no adapter layer, no
registry.

## Why it votes instead of taking a common prefix

A real connector directory carries several naming families at once. The reference project's
`staging/fortnox/` holds:

| Family | Files |
|---|---|
| `_bi_` | 50 |
| `_erp_bi_` | 27 |
| `_flat_` | 14 |
| `_reports_` | 6 |
| `_base_` | 1 |

Their longest common prefix is `_`, which is not a convention anyone chose. Detection
computes the infix of each file independently and takes the majority.

Per-file infix rules, in order:

1. **Two or more leading underscores → that is the whole infix.** `__order_lines` yields
   `__`, the dbt-labs separator. Without this rule it would read as `__order_` and every
   scaffolded model would be misnamed.
2. **Cut at the first entity prefix** (`dim_`, `fact_`, `stg_`, `int_`, `agg_`, `brg_`,
   `mart_`). `_bi_dim_customers` → `_bi_`; `_erp_bi_fact_orders` → `_erp_bi_`.
3. **No entity prefix → keep the first token.** `_flat_incoming_goods` → `_flat_`.

`flat_` and `reports_` are deliberately *not* entity prefixes: they are layer names in at
least one real project, and listing them would collapse those infixes to `_`.

## Where the connector name sits

Two shapes are supported, because both are real:

```
fortnox_bi_dim_customers_staging     connector leads
stg_shopify__customers               connector in the middle, after a layer prefix
```

Detection splits each filename around the connector name and votes on both halves, so the
prefix (`stg_`) and the infix (`__`) are learned separately.

## The source-aligned directory

Detected across **every** connector, not just the reference one. In the reference project
the busiest connector is also the oldest and predates the `<connector>_bi/` convention its
successors follow — `models/fortnox/` versus `models/favrit_bi/` and
`models/tripletex_bi/`. Voting across all of them picks `_bi`, which is what a new connector
should use.

## When detection is wrong

It prints what it detected precisely so a human can catch this. Override:

```bash
--staging-infix _bi_       # the layer token between connector and model name
--adapter-infix _erp_bi_   # the unified-adapter token
--source-suffix _api       # the sources.yml suffix
```

`--source-suffix` matters when a project is internally inconsistent: detection copies what
the project already does, which is right for consistency and wrong when the existing
practice is the thing being corrected.

## Fallback

A project with no connector directories at all falls back to the dbt-labs convention —
`staging/<source>/stg_<source>__<table>.sql` — and says so in its output. The fallback is
reported, never silent.

## What is never generated

`sources.yml`, the connector registry, and `dbt_project.yml` are printed to paste by hand.
They are the connector's contract: a reviewer should see them as a hand-written diff, and
generated config gets skimmed. Existing files are never overwritten.
