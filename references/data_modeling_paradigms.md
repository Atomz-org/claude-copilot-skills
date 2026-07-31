# Data Modeling Paradigms

How the major warehouse modeling approaches map onto dbt Core, and how to choose between
them. Loaded on demand by the
[data-modeling](../.claude/skills/data-modeling/SKILL.md) skill.

## Decision table

| Paradigm | Optimizes for | Pick when | Do not pick when |
|---|---|---|---|
| **Kimball (star)** | query simplicity, BI consumption | analytics and BI are the consumers | you have hundreds of volatile sources and a legal audit requirement |
| **Inmon (3NF core + marts)** | integration, single version of truth | many downstream systems, regulated industry, long-lived enterprise store | a small team that needs delivery this quarter |
| **Data Vault 2.0** | auditability, source volatility, parallel load | sources change shape often, full lineage is a legal requirement | your team is under ~5 people or nobody has run one before |
| **One Big Table** | read simplicity, ML serving | one consumer that joins badly; feature tables | multiple consumers with different grains |
| **Activity Schema** | behavioral/product analytics | entity streams, funnel and sequence questions | financial reconciliation, anything with subledgers |
| **Medallion** | nothing — it is a naming convention | your platform docs use the words | you think it answers a modeling question |

**The default is Kimball marts on dbt's staging/intermediate layers.** Everything else is
a response to a constraint. If you cannot name the constraint out loud, you do not have it.

## Kimball — dimensional / star schema

Facts surrounded by dimensions, one star per business process, dimensions conformed
across stars.

```
models/
├── staging/          stg_<source>__<entity>     1:1 with source, rename + cast
├── intermediate/     int_<entity>_<verbed>      joins, fan-out resolution
└── marts/
    ├── core/         dim_date, dim_customer     conformed — shared dimensions
    ├── sales/        fct_sales, dim_dealer
    └── inventory/    fct_inventory_daily
```

Conformed dimensions live in a shared `core/` domain, not inside the first mart that
needed them. A `dim_customer` under `marts/sales/` will be copied by the marketing team
within a quarter, and then there are two.

**What it costs you:** fan-out discipline is entirely manual. Nothing in dbt prevents a
mixed-grain fact — only the grain sentence, the tests, and review do.

Depth: [dimensional_modeling.md](dimensional_modeling.md).

## Inmon — normalized core with dependent marts

A 3NF integrated layer holding the enterprise model, with dimensional marts built from it.

```
staging/  →  core (3NF, integrated, subject-oriented)  →  marts (star schemas)
```

In dbt this is a **third layer**, not a different tool: `models/core/` sits between
intermediate and marts and is normalized rather than dimensional.

Worth it when several *different systems* consume the warehouse — not just BI — and they
disagree about shape. The cost is real: you build every entity twice, once normalized and
once dimensional, and time-to-first-dashboard roughly doubles.

## Data Vault 2.0

Three object types, designed so that a source schema change never forces a rewrite:

| Object | Holds | Key |
|---|---|---|
| **Hub** | one row per business key, ever | hash of the business key |
| **Link** | one row per relationship between hubs | hash of the participating hub keys |
| **Satellite** | descriptive attributes with `load_date`, insert-only history | hub/link key + `load_date` |

```sql
-- models/vault/hubs/hub_vehicle.sql
select distinct
    {{ dbt_utils.generate_surrogate_key(['vin']) }} as vehicle_hk,
    vin                                             as vehicle_bk,
    current_timestamp                               as load_date,
    'inventory_system'                              as record_source
from {{ ref('stg_inventory__vehicles') }}
where vin is not null
```

```sql
-- models/vault/satellites/sat_vehicle_details.sql
{{ config(materialized='incremental', unique_key=['vehicle_hk', 'load_date']) }}

select
    {{ dbt_utils.generate_surrogate_key(['vin']) }}                        as vehicle_hk,
    current_timestamp                                                      as load_date,
    {{ dbt_utils.generate_surrogate_key(['make','model','trim_level']) }}  as hash_diff,
    make, model, trim_level, condition_grade,
    'inventory_system'                                                     as record_source
from {{ ref('stg_inventory__vehicles') }}
{% if is_incremental() %}
  -- insert only when the hash_diff changed: this is the whole change-detection mechanism
  where {{ dbt_utils.generate_surrogate_key(['make','model','trim_level']) }} not in (
      select hash_diff from {{ this }}
  )
{% endif %}
```

**The honest trade-off.** You get auditability, insert-only history, and source changes
that add a satellite instead of altering a table. You pay 3–5x the object count, and the
raw vault is unqueryable by analysts — you *must* build a dimensional "information mart"
on top, so this is Kimball **plus** a vault, never instead of it.

The `dbtvault` / `AutomateDV` package generates most of the boilerplate. Do not hand-write
a vault at scale.

Do not choose this because it sounds rigorous. Choose it when you can point at either a
regulator or a source system that changes shape more than once a quarter.

## One Big Table (wide / denormalized)

Every attribute a consumer might need, on one row, no joins.

```sql
{{ config(materialized='table') }}
select
    v.valuation_id, v.valuation_amount_usd, v.issued_at,
    veh.make, veh.model, veh.trim_level, veh.model_year,     -- from dim_vehicle
    c.customer_segment, c.country_code,                       -- from dim_customer
    d.dealer_name, d.dealer_region                            -- from dim_dealer
from {{ ref('fct_valuations') }} v
left join {{ ref('dim_vehicle') }}  veh using (vehicle_id)
left join {{ ref('dim_customer') }} c   using (customer_id)
left join {{ ref('dim_dealer') }}   d   using (dealer_id)
```

Legitimate when the consumer is a BI tool that joins badly, a reverse-ETL destination, or
an ML feature table. Build it **from** the star, never instead of it — otherwise the
dimension logic is duplicated in every wide table you make.

Costs: every upstream change touches it; it is the easiest place to fan out silently
(one bad `left join` to a non-unique dimension and every measure inflates); and it cannot
serve two grains, so the second consumer gets a second table.

## Activity Schema

One `activity_stream` table: entity, activity name, timestamp, feature columns. Temporal
joins ("first X after Y") replace dimensional joins.

```
customer_id | activity          | activity_at | feature_1 | feature_2
------------|-------------------|-------------|-----------|----------
c_001       | requested_valuation | 2026-01-04 | 'trade-in'| 18500
c_001       | visited_dealer      | 2026-01-06 | 'dealer_9'| null
```

Strong for product and behavioral analytics — funnels, sequences, time-to-event — with
one table to maintain. Weak everywhere numbers must reconcile: there is no grain
guarantee, the feature columns are untyped by convention, and finance will not accept it.

Fine as a *complement* to a star for a product analytics team. Not a replacement.

## Medallion (bronze / silver / gold)

A naming convention promoted by lakehouse platforms:

| Medallion | dbt equivalent |
|---|---|
| Bronze | raw / sources (often not dbt at all) |
| Silver | staging + intermediate |
| Gold | marts |

That is the whole mapping. It says nothing about grain, keys, conformance, or history —
the decisions that actually matter. If your team uses the words, keep them; do not mistake
having named the layers for having modeled the data.

## Mixing paradigms

Common and correct combinations:

| Combination | When |
|---|---|
| Vault core + Kimball marts | regulated, many sources — the standard Data Vault deployment |
| Kimball marts + OBT serving tables | BI tool or ML consumer needs one flat table |
| Kimball marts + activity stream | product analytics alongside finance reporting |
| 3NF core + Kimball marts | Inmon, by definition |

The rule that keeps this from becoming chaos: **one canonical layer, many serving
shapes.** Wide tables, activity streams, and aggregates are all derived *from* the
canonical models, never sources of truth themselves. A serving table that computes its own
business logic is a second definition, and it will drift.

## Choosing, in five questions

1. **Who consumes it?** BI only → Kimball. Multiple systems → add a normalized core. One
   ML pipeline → Kimball plus an OBT feature table.
2. **How volatile are the sources?** Reshaping more than quarterly, with audit
   requirements → consider a vault. Otherwise no.
3. **Is full history a legal requirement or a nice-to-have?** Legal → vault or rigorous
   SCD2. Nice-to-have → SCD2 on the dimensions that need it.
4. **How big is the team?** Under ~5 people → Kimball. A vault needs sustained ownership,
   and a half-built vault is worse than no vault.
5. **What is the question shape?** "Metric by dimension" → star. "What happened next" →
   activity schema. Both → both.

## Anti-patterns

- **Choosing a paradigm before writing a use-case spec.** The consumers decide the shape.
- **Data Vault because it sounds rigorous.** Name the regulator or the volatile source, or
  do not build it.
- **A raw vault with no information marts.** Analysts cannot query hubs and satellites,
  and they will build their own shadow marts instead.
- **OBT as the source of truth.** Business logic duplicated per wide table, guaranteed to
  drift.
- **Renaming folders to bronze/silver/gold and calling it a remodel.**
- **Two paradigms at the same layer** — half the marts dimensional, half wide, no rule
  about which. Consumers cannot tell which to trust.
- **A normalized core with no marts.** Every analyst rebuilds the same five joins, each
  slightly differently.
