# Use Cases

One directory per data request. The method lives in [.claude/](../.claude/); the work lives
here.

## Structure

```
use-cases/<slug>/
├── use-case-spec.md          # written FIRST, before any model file
├── data-model-canvas.md      # entities, ERD, keys, grain — one per subject area
├── bus-matrix.md             # processes x dimensions, when there is more than one process
├── star-schema-spec.md       # one per business process
├── model-blueprint.md        # one per model, written before its SQL
├── source-contract.md        # one per unstable or externally-owned source
├── deployment-runbook.md     # for anything medium or high risk
└── incident-investigation.md # when something goes wrong
```

Templates for all eight are in [templates/](../templates/). The three modeling artifacts
are skipped when the use case is one model on one source with an obvious grain — they earn
their keep as soon as a second model or a second business process appears.

## Working sequence

1. **Frame** — `/new-use-case <request>` writes `use-cases/<slug>/use-case-spec.md`.
   Nothing is modeled until the decision sentence, the consumer, and the grain are written
   down. If the verdict is "not a dbt problem", that is a successful outcome — say where it
   belongs and stop.
2. **Model** — `/data-model <subject area>` writes the canvas, the bus matrix, and a star
   schema spec per business process. Entities, ERD with cardinality *and* optionality,
   keys, and a grain sentence per table. Skip for a single obvious model.
3. **Contract the sources** — `sources.yml` with freshness, one staging model per source
   table. Sources first: a mart on an unstable source is rework waiting to happen.
4. **Design** — `/dbt-model <concept>` writes the blueprint before the SQL. Grain, join
   cardinalities, materialization with a reason.
5. **Build** — staging → intermediate → marts, running `dbt build --select <model>` as you
   go. Never write three layers then run once.
6. **Test** — `/dbt-test <model>`. Data tests for the data, unit tests for the logic, and a
   test for every assumption in the spec.
7. **Document** — grain and meaning in descriptions, shared definitions in `docs` blocks,
   the consumer in `exposures:`.
8. **Define metrics** — `/dbt-semantic <metric>` if the request involves a metric definition.
9. **Ship** — breaking-change check, slim CI selector, stated rollback path, named owner.

## Naming

Use a slug that names the **business concept**, not the model: `order-revenue-mart`, not
`fct-orders`. One use case often produces several models, and the models get renamed while
the business question does not.

## Definition of done

- The spec exists and predates every model file.
- Every model states its grain, has a tested primary key, and has a description that says
  more than the model name.
- Every shared dimension is conformed — one key, one definition, one table — and every
  fact foreign key has a `relationships` test.
- Every model with real logic has a unit test; every assumption in the spec has a data test.
- `dbt build --select <new models>+` passes clean and reproduces under `--full-refresh`.
- Source freshness is declared for every source involved.
- Downstream impact was checked against the production manifest.
- The change has a stated rollback path and a named owner.
- Section 11 of the spec is filled in after delivery — what the spec got wrong, and the
  tests added because of it.

## Example

[example-order-revenue-mart/](../skill-packs/dbt-skills/use-cases/example-order-revenue-mart/) is a complete worked case on
synthetic data: a filled-in spec, sources with freshness, staging/intermediate/mart SQL, a
contracted `schema.yml`, semantic models with metrics, and synthetic dbt artifacts that
every script in [scripts/](../scripts/) runs against.

The synthetic project deliberately contains real defects, so you can see what each tool
finds and what its output looks like before pointing it at your own project.
