"""Tests for the MetricFlow derivation.

The properties worth pinning all separate "the project stated this" from "the column name
suggested it", because a semantic layer that guesses is worse than none: a metric carries
the layer's authority, so a wrong one is believed.

1. **A grain comes from a `unique` test.** Nothing else in a dbt project declares it, and
   `<Thing>Id` looks like a key in every model that carries it — including the union of six
   systems that each issued their own.
2. **`agg: sum` comes from a recorded additivity** (rule 11). Non-additive is not a measure,
   semi-additive needs a decision nobody made, and unrecorded is the assumption a reader
   already brings.
3. **Element names are unique inside a semantic model.** MetricFlow rejects a duplicate, and
   the key-plus-label pair (`MainAccountId` beside `MainAccount`) produces one by default.
4. **A foreign entity joins to something.** An identifier reaching no primary entity is
   reported, never emitted — the same rule the connector topology applies to a dangling id.
5. **A semantic layer with no time spine is not written at all.** dbt answers
   `Parsing Error ... none was found` and builds nothing, so the generator would take every
   manifest-reading stage down with it.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import ontology_to_semantic as ots  # noqa: E402
from _manifest import Manifest  # noqa: E402

ENHANZA = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics"


def _manifest(models, tests=(), time_spine=False):
    """A manifest holding the named models and (test kind, model, column) triples."""
    nodes = {}
    for name in models:
        nodes[f"model.p.{name}"] = {
            "resource_type": "model", "name": name, "package_name": "p",
            "original_file_path": f"models/{name}.sql",
        }
    if time_spine:
        nodes["model.p.metricflow_time_spine"] = {
            "resource_type": "model", "name": "metricflow_time_spine", "package_name": "p",
            "original_file_path": "models/metricflow_time_spine.sql",
        }
    for i, (kind, model, column) in enumerate(tests):
        nodes[f"test.p.t{i}"] = {
            "resource_type": "test", "test_metadata": {"name": kind},
            "column_name": column, "depends_on": {"nodes": [f"model.p.{model}"]},
        }
    return Manifest({"nodes": nodes})


def _facets(**by_column):
    return {name: {"column": name, **facets} for name, facets in by_column.items()}


def _derive(columns, facets, refusals=None, joinable=None, key="ThingId"):
    refusals = [] if refusals is None else refusals
    return ots.derive_model("dim_things", "logic_bi_dim_things", key, columns,
                            facets, joinable or {}, refusals), refusals


# ---------------------------------------------------------------------------------------
# The grain
# ---------------------------------------------------------------------------------------


def test_a_unique_test_is_what_declares_the_grain() -> None:
    man = _manifest(["logic_bi_dim_things"],
                    [("unique", "logic_bi_dim_things", "ThingId")])
    assert ots.tested_keys(man) == {"logic_bi_dim_things": ["ThingId"]}


def test_a_not_null_test_alone_declares_no_grain() -> None:
    """`not_null` says the value is never missing, never that it is unique."""
    man = _manifest(["logic_bi_dim_things"],
                    [("not_null", "logic_bi_dim_things", "ThingId")])
    assert ots.tested_keys(man) == {}


def test_a_model_with_no_unique_test_carries_no_key() -> None:
    """The refusal `derive()` raises on this is `no-unique-test`; the classifier is what
    decides it, and it decides by finding nothing."""
    assert ots.tested_keys(_manifest(["logic_bi_dim_things"])) == {}


def test_two_unique_columns_are_a_decision_not_a_composite_key() -> None:
    """Which of them is the grain is exactly what nobody wrote down."""
    man = _manifest(["logic_bi_dim_things"],
                    [("unique", "logic_bi_dim_things", "A"),
                     ("unique", "logic_bi_dim_things", "B")])
    assert ots.tested_keys(man)["logic_bi_dim_things"] == ["A", "B"]


# ---------------------------------------------------------------------------------------
# Additivity (rule 11)
# ---------------------------------------------------------------------------------------


def test_an_additive_measure_sums() -> None:
    model, _ = _derive(["ThingId", "Amount"],
                       _facets(Amount={"role": "measure", "additivity": "additive",
                                       "unit": "currency", "definition": "The amount."}))
    summed = [m for m in model.measures if m["expr"] == "Amount"]
    assert summed and summed[0]["agg"] == "sum"


def test_a_non_additive_measure_is_not_a_measure_at_all() -> None:
    model, refusals = _derive(
        ["ThingId", "Rate"],
        _facets(Rate={"role": "measure", "additivity": "non_additive"}))
    assert [m for m in model.measures if m["expr"] == "Rate"] == []
    assert any(r.kind == ots.NON_ADDITIVE for r in refusals)


def test_a_semi_additive_measure_needs_the_dimension_it_may_not_cross() -> None:
    model, refusals = _derive(
        ["ThingId", "Balance"],
        _facets(Balance={"role": "measure", "additivity": "semi_additive"}))
    assert [m for m in model.measures if m["expr"] == "Balance"] == []
    assert any(r.kind == ots.SEMI_ADDITIVE for r in refusals)


def test_an_unrecorded_additivity_is_refused_rather_than_assumed_summable() -> None:
    """`sum` is what a reader already assumes; emitting it makes the assumption authority."""
    model, refusals = _derive(
        ["ThingId", "Score"], _facets(Score={"role": "measure", "additivity": None}))
    assert [m for m in model.measures if m["expr"] == "Score"] == []
    assert any(r.kind == ots.UNRECORDED_ADDITIVITY for r in refusals)


def test_the_entity_count_is_exact_because_the_key_is_tested() -> None:
    model, _ = _derive(["ThingId"], _facets())
    count = model.measures[0]
    assert count["agg"] == "count_distinct" and count["expr"] == "ThingId"


# ---------------------------------------------------------------------------------------
# Withholding and abstaining
# ---------------------------------------------------------------------------------------


def test_a_direct_pii_column_is_withheld() -> None:
    """Rule 17. Still available upstream to anything with a reason to join it."""
    model, refusals = _derive(
        ["ThingId", "Email"],
        _facets(Email={"role": "dimension", "pii": "direct"}))
    assert all(c[1] != "Email" for c in model.categorical)
    assert any(r.kind == ots.PII_WITHHELD for r in refusals)


def test_a_timestamp_with_no_recorded_unit_has_no_granularity() -> None:
    """Rule 44 requires a granularity on every time dimension, and only the annotation's
    own `unit: date` evidences one."""
    model, refusals = _derive(
        ["ThingId", "SeenAt"],
        _facets(SeenAt={"role": "timestamp", "unit": None}))
    assert model.time_dimensions == []
    assert any(r.kind == ots.NO_TIME for r in refusals)


def test_several_time_dimensions_leave_the_aggregation_time_undecided() -> None:
    model, refusals = _derive(
        ["ThingId", "CreatedAt", "UpdatedAt"],
        _facets(CreatedAt={"role": "timestamp", "unit": "date"},
                UpdatedAt={"role": "timestamp", "unit": "date"}))
    assert model.agg_time_dimension is None
    assert any(r.kind == ots.AMBIGUOUS_TIME for r in refusals)


def test_one_time_dimension_becomes_the_aggregation_time() -> None:
    model, _ = _derive(["ThingId", "CreatedAt"],
                       _facets(CreatedAt={"role": "timestamp", "unit": "date"}))
    assert model.agg_time_dimension == "created_at"


# ---------------------------------------------------------------------------------------
# Names MetricFlow will accept
# ---------------------------------------------------------------------------------------


def test_a_key_and_its_label_do_not_both_become_main_account() -> None:
    """`dim_accounts` carries `MainAccountId` and `MainAccount`; stripping the suffix names
    both `main_account`, which MetricFlow rejects as a duplicate element."""
    columns = ("main_account_id", "main_account")
    assert ots.entity_name("MainAccountId", columns) == "main_account_id"
    assert ots.entity_name("MainAccount", columns) == "main_account"


def test_a_suffix_is_dropped_when_nothing_else_claims_the_name() -> None:
    assert ots.entity_name("CustomerId", ("customer_id",)) == "customer"


def test_every_element_name_in_a_generated_model_is_unique() -> None:
    """The invariant MetricFlow enforces, asserted over the real derivation."""
    payload = _real_derivation()
    for model in payload["models"]:
        names = ([model.primary[0]] + [f[0] for f in model.foreign]
                 + [d[0] for d in model.time_dimensions]
                 + [d[0] for d in model.categorical]
                 + [m["name"] for m in model.measures])
        assert len(names) == len(set(names)), f"{model.name}: duplicate element name"


# ---------------------------------------------------------------------------------------
# The entity graph is closed
# ---------------------------------------------------------------------------------------


def test_a_foreign_entity_resolves_only_to_a_declared_primary() -> None:
    model, _ = _derive(["ThingId", "OwnerId"],
                       _facets(OwnerId={"role": "identifier"}),
                       joinable={"OwnerId": "owner"})
    assert ("owner", "OwnerId") in model.foreign


def test_an_identifier_joining_to_nothing_is_reported_never_emitted() -> None:
    model, refusals = _derive(["ThingId", "OwnerId"],
                              _facets(OwnerId={"role": "identifier"}))
    assert model.foreign == []
    assert any(r.kind == ots.UNRESOLVED_ENTITY for r in refusals)


def test_every_foreign_entity_in_the_real_derivation_has_a_primary_somewhere() -> None:
    payload = _real_derivation()
    primaries = {m.primary[0] for m in payload["models"]}
    for model in payload["models"]:
        for name, _column in model.foreign:
            assert name in primaries, f"{model.name} joins to `{name}`, which nothing owns"


# ---------------------------------------------------------------------------------------
# The time spine
# ---------------------------------------------------------------------------------------


def test_a_project_with_no_time_spine_gets_no_file() -> None:
    """dbt does not degrade here — it refuses to parse, and every stage downstream of the
    manifest goes with it. Found by writing the file and running `dbt parse`."""
    assert ots.has_time_spine(_manifest(["a"], time_spine=False)) is False


def test_a_time_spine_is_recognised_by_its_declaration_not_only_its_name() -> None:
    man = Manifest({"nodes": {
        "model.p.calendar": {"resource_type": "model", "name": "calendar",
                             "time_spine": {"standard_granularity_column": "date_day"}},
    }})
    assert ots.has_time_spine(man) is True
    assert ots.has_time_spine(_manifest(["a"], time_spine=True)) is True


@pytest.mark.skipif(not (ENHANZA / "ontology" / "index.json").exists(),
                    reason="enhanza artifacts absent on this branch")
def test_the_spine_refusal_reports_the_work_it_is_holding_back() -> None:
    """A skip that hid the derivation would read as an absence of work rather than a
    blocker with a named remedy."""
    summary = ots.run("enhanza-analytics", None, write=False, check=False)
    if summary.get("status") != "skip":
        pytest.skip("this project now declares a time spine")
    # The manifest is gitignored, so a fresh clone — CI included — skips for want of it
    # long before reaching the spine. Asserting on that skip is asserting on the checkout.
    if "time spine" not in summary["reason"]:
        pytest.skip(f"blocked earlier: {summary['reason']}")
    assert summary["semantic_models"] > 0
    assert summary["changed"] == []


def test_a_skip_that_could_not_derive_reports_no_count(tmp_path) -> None:
    """The rejected half of the test above, pinned so it is not re-proposed.

    A reviewer periodically asks for `semantic_models` on every skip, for schema
    stability. The time-spine skip already has it — the derivation completed. The
    input-missing skips return before `derive()` runs, and `semantic_models: 0` there would
    say "we derived and found none" where the truth is "we could not look". Padding them
    would let the test above assert `0 > 0` on a fresh clone and report an absent manifest
    as a time-spine failure.
    """
    summary = ots.run("enhanza-analytics", tmp_path / "absent.json", write=False, check=False)
    assert summary == {"status": "skip",
                       "reason": "no manifest — run artifacts/refresh.sh"}


def test_no_consumer_reads_a_count_off_a_skip() -> None:
    """What makes the padding unnecessary rather than merely undesirable."""
    import use_case_sync  # noqa: PLC0415 - imported here to keep the module list honest
    source = inspect.getsource(use_case_sync.stage_semantic)
    assert 'status") == "skip"' in source, "the stage must return before reading a count"
    assert "get('semantic_models', 0)" in source, "and must default even after that"
    ots.report({"status": "skip", "reason": "no manifest"})  # must not raise


# ---------------------------------------------------------------------------------------
# The real derivation
# ---------------------------------------------------------------------------------------


def _real_derivation():
    manifest = ENHANZA / "dbt_project" / "target" / "manifest.json"
    if not manifest.exists() or not (ENHANZA / "ontology" / "index.json").exists():
        pytest.skip("enhanza manifest or ontology absent on this branch")
    return ots.derive(ENHANZA, Manifest.load(str(manifest)))


def test_the_derivation_reads_the_consumer_layer_not_the_per_connector_models() -> None:
    """Rule 7: declaring `customer` primary in nineteen `fortnox_bi_*`/`shopify_bi_*` models
    would be nineteen definitions of one entity."""
    payload = _real_derivation()
    assert payload["models"]
    for model in payload["models"]:
        assert model.dbt_model.startswith(ots.LOGIC_PREFIX)


def test_a_generated_file_parses_as_yaml_and_declares_what_it_generated() -> None:
    payload = _real_derivation()
    text = ots.render("enhanza-analytics", payload["models"])
    assert ots.GENERATED_MARKER in text
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(text)
    assert doc["version"] == 2
    assert len(doc["semantic_models"]) == len(payload["models"])
    for semantic in doc["semantic_models"]:
        primaries = [e for e in semantic["entities"] if e["type"] == "primary"]
        assert len(primaries) == 1, f"{semantic['name']}: rule 44 wants exactly one"
        if semantic.get("measures"):
            assert semantic["defaults"]["agg_time_dimension"]


def test_a_metric_exists_only_where_a_measure_does() -> None:
    payload = _real_derivation()
    text = ots.render("enhanza-analytics", payload["models"])
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(text) or {}
    measures = {m["name"] for s in doc["semantic_models"] for m in s.get("measures") or []}
    for metric in doc.get("metrics") or []:
        assert metric["type_params"]["measure"] in measures


# ---------------------------------------------------------------------------------------
# One name, one number
# ---------------------------------------------------------------------------------------
#
# A measure is named for its conformed column, and a conformed column is by definition
# shared: 7 of this project's 17 `measure` columns belong to more than one concept —
# `ContributionValue` to five, `Net` to four, both additive. MetricFlow requires measure
# and metric names unique across the whole manifest, so every one of those is a duplicate
# waiting on the `unique` test its concept still owes.


def _two_models_sharing_a_measure():
    shared = {"role": "measure", "additivity": "additive", "unit": "currency",
              "definition": "Contribution value."}
    out = []
    for concept, key in (("fact_orders", "OrderId"), ("fact_invoices", "InvoiceId")):
        refusals: list = []
        model = ots.derive_model(
            concept, f"{ots.LOGIC_PREFIX}{concept}", key,
            [key, "ContributionValue", "OrderDate"],
            {key: {"column": key, "role": "identifier"},
             "ContributionValue": {"column": "ContributionValue", **shared},
             "OrderDate": {"column": "OrderDate", "role": "timestamp", "unit": "date"}},
            {}, refusals)
        out.append(model)
    assert all(m.agg_time_dimension for m in out), "fixture must emit measures"
    return out


def test_two_concepts_measuring_the_same_column_do_not_collide() -> None:
    """Qualified, not deduplicated. `fact_orders.ContributionValue` and
    `fact_invoices.ContributionValue` are one column definition and two different numbers;
    keeping one publishes the orders value under a name a consumer reads as invoices."""
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(ots.render("toy", _two_models_sharing_a_measure()))

    names = [m["name"] for s in doc["semantic_models"] for m in s.get("measures") or []]
    assert len(names) == len(set(names)), f"duplicate measure name: {names}"
    metrics = [m["name"] for m in doc.get("metrics") or []]
    assert len(metrics) == len(set(metrics)), f"duplicate metric name: {metrics}"

    # Both survive — neither concept was dropped to make the names fit.
    assert sum("contribution_value" in n for n in metrics) == 2
    assert {"fact_orders__contribution_value",
            "fact_invoices__contribution_value"} <= set(metrics)


def test_every_metric_still_resolves_to_its_own_models_measure() -> None:
    """Uniqueness is worthless if the reference broke getting there."""
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(ots.render("toy", _two_models_sharing_a_measure()))
    by_model = {s["name"]: {m["name"] for m in s.get("measures") or []}
                for s in doc["semantic_models"]}
    for metric in doc["metrics"]:
        owner = metric["name"].split("__", 1)[0]
        assert metric["type_params"]["measure"] in by_model[owner], metric["name"]


def test_a_metric_name_does_not_depend_on_which_other_concepts_exist() -> None:
    """Qualifying only on collision would rename a published metric when an unrelated
    concept earns its `unique` test — and BI is bound to the name."""
    yaml = pytest.importorskip("yaml")
    both = _two_models_sharing_a_measure()
    alone = yaml.safe_load(ots.render("toy", both[:1]))
    together = yaml.safe_load(ots.render("toy", both))
    assert [m["name"] for m in alone["metrics"]] == [
        m["name"] for m in together["metrics"] if m["name"].startswith("fact_orders__")]


def test_the_label_stays_the_human_name_of_the_column() -> None:
    """The name disambiguates; the label is what a person reads, and two concepts
    measuring `ContributionValue` genuinely share one."""
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(ots.render("toy", _two_models_sharing_a_measure()))
    labels = {m["label"] for m in doc["metrics"] if "contribution_value" in m["name"]}
    assert labels == {"Contribution Value"}
