# Pinned figures

The page states numbers. Nothing about an HTML file makes a number false when a connector
is added, so the honest ones are checked and the uncheckable ones are labelled.

## The rule

- A figure derived from a **committed** artifact carries `data-metric="<key>"` and is
  verified by `test_every_pinned_number_matches_the_artifact_it_claims`.
- A figure that needs a **rebuild** — a test count, a code-graph size, a run that needs
  dbt or a warehouse — is *not* pinned. The footer names the command that re-derives it,
  and `test_unpinned_figures_carry_the_command_that_re_derives_them` checks the footer
  still does.

Pinning the second class is the tempting mistake. A gate that goes red because somebody
added a test is a gate that gets switched off, taking the real failures with it.

## The closed set of keys

`METRICS` in `tests/test_architecture_diagram.py` is the authority. A `data-metric`
attribute naming anything else fails the test rather than passing silently.

`ENHANZA` below is `skill-packs/dbt-skills/use-cases/enhanza-analytics`.

| `data-metric` | Resolver | Artifact |
|---|---|---|
| `connectors` | `len(index["connectors"])` | `ENHANZA/ontology/index.json` |
| `concepts` | `len(index["concepts"])` | same |
| `coverage_gaps` | `len(index["gaps"])` | same |
| `annotated_columns` | `len(index["column_semantics"])` | same |
| `bindings` | `len(column_memory["bindings"])` | `ENHANZA/ontology/column-memory.json` |
| `contracts` | `len(column_memory["contracts"])` | same |
| `dbt_models` | nodes with `dbt_resource_type == "model"` | `ENHANZA/artifacts/graphify-fragment.json` |
| `seeds` | nodes with `dbt_resource_type == "seed"` | same |
| `source_tables` | nodes with `dbt_resource_type == "source"` | same |
| `declared_source_columns` | `columns:` entries summed over every `sources.yml` | `ENHANZA/dbt_project/**/sources.yml` |
| `ttl_files` | `*.ttl` under the ontology | `ENHANZA/ontology/` |

## Why the model count comes from the fragment

`manifest.json` is 3.0 MB and churns on every model edit, so it is deliberately not
committed. `artifacts/graphify-fragment.json` is 736 KB, is committed, and is what
graphify consumes — which makes it the only file in the tree that can answer "how many
dbt models are there" in a fresh clone with no dbt and no warehouse.

That is the same reason the fragment exists at all. Reading the manifest here would make
the test unrunnable exactly where it is most needed: on a machine that has never parsed
the project.

## Adding a new pinned figure

1. Find the committed artifact that already states the fact. If the only source is a
   rebuild, stop — the figure is unpinnable, and it belongs in prose with its command in
   the footer.
2. Add a resolver to `METRICS`, keyed by the name you will use in the markup. Keep it a
   one-line lambda over an already-loaded artifact; a resolver that shells out makes the
   test slow and environment-dependent.
3. Add `data-metric="<key>"` to the element, with the number as its **first** integer.
   `pinned_claims` reads the first `[\d,]+` in the element body, so
   `<text data-metric="connectors">19 connectors</text>` works and
   `<text data-metric="connectors">connectors: 19</text>` also works — but an element
   showing no digits at all fails with an explicit message.
4. Thousands separators are fine; the parser strips commas.

## Extraction is regex, and that constrains the markup

`pinned_claims` matches `data-metric="([^"]+)"[^>]*>([^<]*)<`. The consequence:

- The number must sit in the element's **own** text node, not inside a nested `<span>`
  or `<tspan>`. A nested element ends the match at the opening `<` and the body reads
  empty.
- One `data-metric` per element. Two figures in one box are two elements.

Both are natural in SVG (`<text>` per line) and in the stat strip (`<b>` per tile), so the
constraint has never cost anything — but a nested-span refactor of the strip would break
every claim at once, and the failure message would say "shows no number", not "you nested it".
