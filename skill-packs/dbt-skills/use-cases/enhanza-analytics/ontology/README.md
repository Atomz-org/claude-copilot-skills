# Enhanza ERP/CRM ontology

A conformed vocabulary for what the connectors supply, generated from the dbt project rather
than maintained beside it.

```
ontology/
  core/
    erp.ttl          hand-authored — the minimal core
    crm.ttl          hand-authored — CRM as a module over the core
    connector.ttl    hand-authored — the alignment vocabulary
  connectors/*.ttl   GENERATED — one per connector
  topology/*.ttl     GENERATED — concept coverage across connectors
  index.json         GENERATED — the machine-facing projection (see "Serving it")
  reference/*.csv    hand-authored — the only values sample data may use
  connectors.yml     hand-authored — the catalogue, and the extension point
  ontology.yml       hand-authored — this use-case's namespace and its own concepts
```

Regenerate as part of everything else derived from the project:

```bash
python3 scripts/use_case_sync.py --use-case enhanza-analytics
python3 scripts/use_case_sync.py --all --check      # the CI gate form
```

`connectors/`, `topology/`, and `index.json` are rewritten; edits there are lost.
`scripts/ontology_generator.py` still runs standalone when only the ontology is in question.

## Why it is generated

The facts an extension asserts are already recorded three times over, and all three are kept
current by something other than goodwill:

| Fact | Source | Kept true by |
|---|---|---|
| which connectors exist, and what each supplies | `global_configs('all_available_sources')` | `tests/test_enhanza_connector_registry.py` |
| which models and sources exist | `manifest.json` | dbt writes it |
| which source column became which conformed column | `scripts/dbt_column_lineage.py` | it parses the SQL |

A hand-written ontology would be a fourth statement of the same thing and the only one with
nothing keeping it honest. So it is derived, and `tests/test_ontology_generator.py` fails if
the checked-in files no longer match the project.

## Design

Taken from the [Building Topology Ontology](https://w3id.org/bot#), which is deliberately
tiny — seven classes for an entire building — and defers everything else to extensions that
attach by `rdfs:subClassOf`. The same discipline here:

- **The core names only what several connectors agree on.** `dim_customers` is supplied by
  seven, so `erp:Customer` is core. A Fortnox-only notion is a subclass in `fortnox.ttl`,
  however useful. A core that grows with each connector is a union, not a conformed model,
  and stops being able to answer anything across sources.
- **Extensions attach, they do not replace.** `fortnox:Customer rdfs:subClassOf erp:Customer`.
- **CRM is a module, not a silo.** `crm:Opportunity` is an `erp:Document`; `crm:wonAs` points
  at the `erp:Order` it became. That single link is what lets a pipeline number reconcile
  against a booked one.

Where this departs from BOT is worth stating. BOT's alignment modules map one vocabulary onto
another and are checked by reading them. These map a vocabulary onto physical warehouse
tables, so they can be checked by *running* something:

```turtle
fortnox:Customer a owl:Class ;
    rdfs:subClassOf erp:Customer ;
    conn:dbtModel "fortnox_erp_bi_dim_customers" ;
    conn:sourceTable "fortnox_api.customers" .

fortnox:Customer conn:hasMapping fortnox:Customer-partyNumber-CustomerNumber .
fortnox:Customer-partyNumber-CustomerNumber a conn:Mapping ;
    conn:mapsToProperty erp:partyNumber ;
    conn:sourceColumn "CustomerNumber" ;
    conn:transform "direct" .
```

Every one of those claims is falsifiable against `manifest.json`, and
`test_every_declared_dbt_model_exists` falsifies them. An ontology whose claims cannot go
stale is one nobody has to trust.

## Competency questions

Following the [DLT ontology](https://dlt-ontology.github.io/)'s practice of stating what the
model is *for*, and answerable today from the generated files:

1. Which connectors supply `dim_customers`, and which of them are implemented? →
   `topology/concept-coverage.ttl`
2. What does each connector call the column behind `erp:partyNumber`? → `conn:sourceColumn`
   across `connectors/*.ttl`. Six connectors, six different names.
3. Which conformed concepts have exactly one supplier? → not yet conformed; a number from
   them cannot be benchmarked across tenants.
4. If a source renames a column, which conformed properties break? → `conn:Mapping` in
   reverse.
5. Which planned connectors would supply a concept nothing supplies today? →
   `expected_concepts` in `connectors.yml` against the topology.

## Serving it — `index.json` and MCP

The Turtle is normative and the JSON is a projection of it. Both come out of one generator
pass over one set of inputs, so neither can lead the other, and
`test_index_and_turtle_agree_on_every_model` fails if they ever disagree.

Why a projection exists at all: the eventual consumer is a server answering one question per
call, and every competency question above is a lookup in a list of like-shaped records.
Answering them from Turtle means shipping an RDF parser and a query engine to do what a dict
does directly — and `rdflib` is optional in this repository, so a server built on it would
fail to start wherever the parser is absent. Four uniform record lists also serialise
straight to TOON, which is what carries them into a model's context.

It is deliberately **not** JSON-LD. A `@context` covering these keys honestly would have to
reify `models` and `mappings` into graph shapes they do not have; one covering only the
prefixes would parse while dropping nearly every statement. A file that looks like RDF and
asserts almost nothing is worse than one that never claimed to be — so the prefixes are
published as data under `prefixes`, and the graph stays in the `.ttl` files.

`index.json` carries its own tool surface in `mcp_tools`, each entry naming the key that
backs it. A tool whose backing key disappeared would then break a test rather than a request:

| Tool | Backed by | Answers |
|---|---|---|
| `list_connectors` | `connectors` | every source system, its status, its enable var, what it supplies |
| `describe_concept` | `concepts` | one conformed concept: its core class and which connectors realise it |
| `locate_model` | `models` | the dbt model and source tables behind a (connector, concept) pair |
| `resolve_column` | `mappings` | which source column realises a conformed property, per connector, and how |
| `coverage_gaps` | `gaps` | concepts with a single supplier, and planned concepts nothing supplies |

`provenance` is what keeps a served answer honest: it records whether column lineage was
available and how many models parsed, were macro-only, or failed. A server that reports
`resolve_column` results without it is presenting a partial parse as a complete one.

Three properties make this servable rather than merely readable, and each is pinned by a
test — an MCP server is a long-running process against a file it does not control:

- **Every claim is falsifiable.** `conn:dbtModel` and `index.json`'s `dbt_model` name models
  that are in `manifest.json` or are not.
- **Identifiers are stable.** The namespace is pinned in `ontology.yml`, not derived from the
  directory name, so renaming a use-case does not silently reissue every IRI.
- **Regeneration is deterministic.** Same manifest, byte-identical output — an ETag or a
  content hash over `index.json` means the data changed, never that the generator ran again.

Nothing here builds a server. What it does is make one a thin read of one file, with no dbt,
no warehouse, and no RDF stack in the request path.

## Adding a connector

1. **Add a row to `connectors.yml`** with `status: planned`. That is the whole extension
   point — everything downstream is generated from it.
2. **Regenerate.** You get a stub with the expected concepts, marked `[NEEDS INPUT]`, and
   no invented tables or columns. This is deliberate: a planned connector's schema is not
   known here, and an ontology that looks finished and maps to nothing is worse than an
   obviously empty one ([rule 5](../../../../../.claude/rules/analytics-engineering-rules.md)).
3. **Build the connector** — `/new-connector`, then `../CONNECTORS.md`.
4. **Flip `status` to `implemented`** and regenerate. Now the classes carry real models,
   source tables, and column mappings, and the tests start holding you to them.

If a concept has no entry in `CONCEPT_CLASS`, generation reports it rather than guessing a
classification. Add it to `scripts/ontology_generator.py`.

### When the core has to change

A connector whose central subject has no core class is telling you something. Hogia Your
Landlord is a property-management system and its central subject is a lease against a unit;
neither is in the core, because no current connector has one. The rule is the same as BOT's:
add to the core only when a *second* connector needs the same concept. Until then it is a
subclass in that connector's own file.

## Sample data

`scripts/dbt_seed_generator.py` seeds the **sources**, not the models — 99 CSVs, 12 rows
each, from which `dbt build` derives all 359 models. Which columns to emit is read from the
parsed column lineage, so the sample data cannot fall behind the SQL that consumes it.

Values come from `reference/` and nowhere else, following
[microsoft/Ontology-Playground](https://github.com/microsoft/Ontology-Playground/tree/main/data/reference):
one source of truth for names, never invented at the point of use. A column with no reference
mapping gets a visibly fake placeholder (`address1_value_3`) rather than a plausible one —
`Bergen Bygg AS` is a real reference value and `address1_value_3` is obviously not data, and
neither can be mistaken for a fact.

**The seeds are wired to the sources**, through the project's own conventions rather than
a new one: a generated `properties.yml` gives each seed the alias and schema that
`generate_schema_name()` lands at exactly the relation `source()` resolves to under the
`demo` target with `uid: demo`. From there, `scripts/dbt_sample_build.py` builds the
unified union locally on DuckDB — dbt seeds and compiles, sqlglot transpiles the BigQuery
SQL, DuckDB executes — and requires every enabled connector to contribute rows. The full
how-to, scope, and troubleshooting: [dbt_project/seeds/sample/README.md](../dbt_project/seeds/sample/README.md).
