"""Tests for extracting the dbt models the ontology declares and the project never built.

A generator that writes SQL is trusted by a build that will happily execute nonsense, so
each failure mode below is one where the output *runs* and is wrong:

1. **Inventing business logic.** The hand-written models rename and concatenate; a
   generator guessing at that ships plausible columns nobody asked for.
2. **Inventing a key.** No grain is declared for these concepts, so a `unique` test would
   assert a grain nobody chose — and pass, until the day two connectors overlap.
3. **Carrying PII forward.** The mart is what BI and an agent read (rule 17).
4. **`select *`.** A new upstream column then appears in a consumer-facing model with no
   diff and no decision (rule 25).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import ontology_to_dbt as gen  # noqa: E402
from _manifest import Manifest  # noqa: E402

ENHANZA = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics"
needs_artifacts = pytest.mark.skipif(
    not (ENHANZA / "ontology/column-annotations.json").exists()
    or not (ENHANZA / "dbt_project/target/manifest.json").exists(),
    reason="needs the committed ontology artifacts and a manifest",
)

ENTRY = {
    "concept": "dim_customers",
    "model": "logic_bi_dim_customers",
    "union": "erp_bi_dim_customers",
    "suppliers": ["fortnox", "shopify"],
    "conformed": 5,
    "columns": [
        {"column": "CustomerNumber", "role": "identifier", "additivity": None,
         "unit": None, "pii": "none", "definition": "The customer's number.", "domain": None},
        {"column": "FinancialStatus", "role": "dimension", "additivity": None, "unit": None,
         "pii": "none", "definition": "Payment state.",
         "domain": {"closed": True, "values": ["paid", "pending"],
                    "source": "Shopify Admin API"}},
    ],
    "withheld_pii": ["Email"],
    "unannotated": 2,
}


def test_the_model_projects_only_what_the_ontology_records() -> None:
    sql = gen.render_model(ENTRY)
    assert "d0.CustomerNumber" in sql and "d0.FinancialStatus" in sql
    assert "d0.DataSource" in sql, "a unioned row that cannot be attributed is not usable"
    assert "Email" not in sql, "pii: direct never reaches a consumer-facing model (rule 17)"


def test_the_model_enumerates_rather_than_stars() -> None:
    """`select *` puts a new upstream column in front of a consumer with no decision."""
    sql = gen.render_model(ENTRY)
    assert "select *" not in sql and "d0.*" not in sql


def test_the_enabled_gate_comes_from_the_ontology_not_from_typing() -> None:
    sql = gen.render_model(ENTRY)
    assert "any_source_enabled(['fortnox', 'shopify'])" in sql
    assert "ref('erp_bi_dim_customers')" in sql


def test_no_unique_test_is_generated() -> None:
    """Rule 5. No grain is declared for these concepts, and a `unique` on a guessed key
    passes until the first tenant with two connectors — the eval measures candidate-key
    uniqueness instead and reports it as evidence."""
    schema = gen.render_schema([ENTRY])
    assert "- unique" not in schema
    assert "grain is declared" in schema or "no grain is declared" in schema.lower()


def test_tests_come_from_the_facets() -> None:
    schema = gen.render_schema([ENTRY])
    assert "- not_null" in schema, "an identifier that is null identifies nothing"
    assert "accepted_values" in schema and "- paid" in schema and "- pending" in schema


def test_the_description_is_the_recorded_meaning() -> None:
    """Rule 34, and the reason a column reaches this file at all: somebody wrote down what
    it means. Nothing is paraphrased into existence here."""
    schema = gen.render_schema([ENTRY])
    assert "The customer's number." in schema
    assert "2 conformed column(s) are not annotated yet" in schema
    assert "1 direct-PII column(s) are withheld" in schema


def test_facets_travel_with_the_column_as_meta() -> None:
    """The mart is what an agent reads before writing SQL; role and additivity have to be
    on the column, not only in a separate artifact."""
    schema = gen.render_schema([ENTRY])
    assert "role: identifier" in schema and "role: dimension" in schema


@needs_artifacts
def test_the_gap_closes_and_stays_closed() -> None:
    """The generator is idempotent by construction: a concept it has filled is no longer a
    gap, so a second run writes nothing. Asserting a non-empty gap would pass once and fail
    forever after — the invariant is that every union either has a business model or is
    still reported."""
    man = Manifest.load(str(ENHANZA / "dbt_project/target/manifest.json"))
    entries, _stats = gen.gap_concepts(ENHANZA, man)
    names = {e["concept"] for e in entries}
    models = {n.get("name") for n in man.nodes.values() if n.get("resource_type") == "model"}

    assert "dim_articles" not in names, "logic_bi_dim_articles already exists"
    for concept in ("dim_company", "fact_stockbalance"):
        assert (f"{gen.LOGIC_PREFIX}{concept}" in models) or (concept in names), (
            f"{concept} has a union, so it is either realised or reported as a gap"
        )
    for entry in entries:
        assert all(c.get("pii") != "direct" for c in entry["columns"])


@needs_artifacts
def test_every_generated_model_carries_its_marker() -> None:
    """The marker is what tells the eval which models it owns, and a later reader which
    file not to hand-edit."""
    written = sorted((ENHANZA / "dbt_project" / gen.LAYER_DIR).glob("logic_bi_*.sql"))
    generated = [p for p in written if gen.GENERATED_MARKER in p.read_text(encoding="utf-8")]
    assert generated, "the models this script wrote"
    for path in generated:
        body = path.read_text(encoding="utf-8")
        assert "select *" not in body
        assert "ref('erp_bi_" in body
