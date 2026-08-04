"""Tests for annotating what each conformed column means.

An annotation is trusted by things that cannot check it — a BI tool summing a column, an
agent deciding whether a field may reach a dashboard. Nothing downstream errors when it is
wrong, so the failure modes are all silent and each has a test that reproduces it:

1. **Inventing an enum.** A closed domain is a claim about an upstream system. A wrong one
   passes every `accepted_values` test it generates, because it generated them.
2. **Defaulting additivity.** Rule 11 wants the decision recorded. Assuming `additive` is
   how a stock balance gets summed across time and the dashboard looks plausible.
3. **Missing PII.** Rule 17. A quasi-identifier nobody flagged is a disclosure, and the
   name shapes are deliberately high-recall for that reason.
4. **Losing evidence silently.** The cast harvester reads `cast(nullif(x,'') as string) C`,
   the ordinary form here. A regex that only reads the unwrapped form drops the type for
   most columns and they abstain for no stated reason, with the output still looking whole.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import column_annotations as ca  # noqa: E402

ENHANZA = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics"
needs_memory = pytest.mark.skipif(
    not (ENHANZA / "ontology/column-memory.json").exists(),
    reason="no committed column-memory.json on this branch",
)

MEMORY = {
    "contracts": [{
        "concept": "dim_customers",
        "columns": [
            {"column": "CustomerNumber", "carried_by": ["fortnox", "shopify"]},
            {"column": "TotalToPay", "carried_by": ["fortnox"]},
            {"column": "RecipientEmail", "carried_by": ["shopify"]},
            {"column": "FinancialStatus", "carried_by": ["shopify"]},
        ],
    }]
}

SCHEMA = """version: 2
models:
  - name: shopify_bi_fact_orders_staging
    columns:
      - name: FinancialStatus
        description: Shopify payment state. Closed domain defined by the Shopify API.
        data_tests:
          - accepted_values:
              values:
                - pending
                - paid
                - refunded
      - name: CustomerNumber
        description: The customer's number in the source system.
"""

SQL = """select
  cast(o.total_price as float64) TotalToPay
  , cast(nullif(o.email,'') as string) RecipientEmail
from x
"""


def _tree(tmp_path: Path) -> Path:
    use_case = tmp_path / "skill-packs/dbt-skills/use-cases/demo"
    models = use_case / "dbt_project/models"
    models.mkdir(parents=True)
    (models / "schema.yml").write_text(SCHEMA, encoding="utf-8")
    (models / "orders.sql").write_text(SQL, encoding="utf-8")
    (use_case / "ontology").mkdir(parents=True)
    (use_case / "ontology/column-memory.json").write_text(json.dumps(MEMORY), encoding="utf-8")
    return use_case


def _run(tmp_path: Path, monkeypatch, args: list) -> int:
    monkeypatch.setattr(ca, "REPO", tmp_path)
    monkeypatch.setattr(ca._paths, "REPO", tmp_path, raising=False)
    return ca.main(args)


# --- evidence -------------------------------------------------------------------------

def test_a_cast_wrapping_a_function_still_yields_its_type() -> None:
    """The regex this replaced read only the unwrapped form, so every
    `cast(nullif(...) as string)` — the ordinary shape here — lost its type in silence."""
    assert ca._scan_casts("cast(o.total_price as float64) TotalToPay") == [("TotalToPay", "float64")]
    assert ca._scan_casts("cast(nullif(c.city,'') as string) City") == [("City", "string")]
    assert ca._scan_casts("cast(a as int64) as Bar") == [("Bar", "int64")]
    assert ca._scan_casts("cast(broken as string") == []


def test_an_identifier_suffix_outranks_a_numeric_cast() -> None:
    """`OrderNumber` is an int64 and summing it is meaningless. The Swedish accounting
    reference states the same rule for account numbers: they are identifiers, not
    quantities, and arithmetic on them is always a bug."""
    assert ca.derive("OrderNumber", {"int64"}, None)["role"] == "identifier"
    assert ca.derive("AccountNumber", {"string"}, None)["role"] == "identifier"


def test_a_name_measure_conflicting_with_a_string_cast_abstains() -> None:
    """One of the two is wrong. Guessing produces a measure nobody can sum or a dimension
    nobody can group; abstaining names the conflict instead."""
    got = ca.derive("TotalWeirdness", {"string"}, None)
    assert got["abstained"] and got["role"] is None
    assert any("CONFLICT" in e for e in got["evidence"])


def test_additive_is_never_proposed_but_the_other_two_are() -> None:
    """Additive is what a reader already assumes, so proposing it removes the prompt to
    decide (rule 11) while adding nothing."""
    assert ca.derive("TotalToPay", {"float64"}, None)["additivity"] is None
    assert ca.derive("BalanceCarriedForward", {"float64"}, None)["additivity"] == "semi_additive"
    assert ca.derive("DiscountRate", {"float64"}, None)["additivity"] == "non_additive"


@pytest.mark.parametrize("name,expected", [
    ("RecipientEmail", "direct"), ("DeliveryPhone", "direct"),
    ("Address1", "quasi"), ("DeliveryName", "quasi"),
    ("OrderId", "none"),
])
def test_pii_shapes_are_high_recall_and_classed(name: str, expected: str) -> None:
    assert ca.derive(name, set(), None)["pii"] == expected


# --- proposing ------------------------------------------------------------------------

def test_a_declared_accepted_values_test_becomes_a_sourced_domain(tmp_path, monkeypatch) -> None:
    """The only enum values in the repository that are evidenced rather than recalled."""
    monkeypatch.setattr(ca, "REPO", tmp_path)
    use_case = _tree(tmp_path)
    result = ca.propose(use_case, {})
    domain = result["proposed"]["FinancialStatus"]["domain"]
    assert domain["values"] == ["pending", "paid", "refunded"]
    assert "Shopify API" in domain["source"]
    assert result["proposed"]["FinancialStatus"]["confidence"] == "high"


def test_definitions_are_harvested_not_invented(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ca, "REPO", tmp_path)
    use_case = _tree(tmp_path)
    result = ca.propose(use_case, {})
    assert result["proposed"]["CustomerNumber"]["definition"] == \
        "The customer's number in the source system."
    assert result["proposed"]["TotalToPay"]["definition"] == "", \
        "a column nobody described gets no definition, rather than a paraphrase"


def test_propose_refuses_to_overwrite_confirmed_annotations(tmp_path, monkeypatch) -> None:
    use_case = _tree(tmp_path)
    curated = use_case / "ontology/annotations.yml"
    curated.write_text("version: 1\ncolumns: {}\n", encoding="utf-8")
    assert _run(tmp_path, monkeypatch, ["--use-case", "demo", "--propose"]) == 1
    assert curated.read_text(encoding="utf-8") == "version: 1\ncolumns: {}\n"


# --- building -------------------------------------------------------------------------

def _write(use_case: Path, body: str) -> None:
    (use_case / "ontology/annotations.yml").write_text(
        "version: 1\ncolumns:\n" + body, encoding="utf-8")


def test_a_measure_without_additivity_is_a_problem(tmp_path, monkeypatch, capsys) -> None:
    use_case = _tree(tmp_path)
    _write(use_case, '  TotalToPay:\n    role: measure\n    definition: "What is owed."\n')
    assert _run(tmp_path, monkeypatch, ["--use-case", "demo"]) == 1
    assert "additivity" in capsys.readouterr().out


def test_a_closed_domain_without_a_source_is_refused(tmp_path, monkeypatch, capsys) -> None:
    """Rule 5. A wrong enum passes every accepted_values test, because it generated them."""
    use_case = _tree(tmp_path)
    _write(use_case,
           '  FinancialStatus:\n    role: dimension\n    definition: "Payment state."\n'
           "    domain:\n      closed: true\n      values:\n        - paid\n")
    assert _run(tmp_path, monkeypatch, ["--use-case", "demo"]) == 1
    assert "source" in capsys.readouterr().out


def test_a_placeholder_definition_is_a_problem(tmp_path, monkeypatch) -> None:
    use_case = _tree(tmp_path)
    _write(use_case, '  CustomerNumber:\n    role: identifier\n    definition: "TODO"\n')
    assert _run(tmp_path, monkeypatch, ["--use-case", "demo"]) == 1


def test_an_annotation_for_a_column_that_no_longer_exists_is_reported(
    tmp_path, monkeypatch, capsys
) -> None:
    use_case = _tree(tmp_path)
    _write(use_case, '  GhostColumn:\n    role: identifier\n    definition: "Nothing."\n')
    assert _run(tmp_path, monkeypatch, ["--use-case", "demo"]) == 1
    assert "GhostColumn" in capsys.readouterr().out


def test_a_valid_artifact_is_deterministic_and_carries_coverage(
    tmp_path, monkeypatch
) -> None:
    use_case = _tree(tmp_path)
    _write(use_case,
           '  CustomerNumber:\n    role: identifier\n    pii: none\n'
           '    definition: "The customer number."\n'
           '  RecipientEmail:\n    role: text\n    pii: direct\n'
           '    definition: "Order confirmation address."\n')
    assert _run(tmp_path, monkeypatch, ["--use-case", "demo"]) == 0
    artifact = use_case / "ontology/column-annotations.json"
    first = artifact.read_bytes()
    assert _run(tmp_path, monkeypatch, ["--use-case", "demo"]) == 0
    assert artifact.read_bytes() == first, "nothing run-dependent in the artifact"
    assert _run(tmp_path, monkeypatch, ["--use-case", "demo", "--check"]) == 0

    model = json.loads(artifact.read_text(encoding="utf-8"))
    assert model["provenance"]["annotated"] == 2
    assert model["provenance"]["pii_columns"] == 1
    # Partial coverage is first-class: the columns nobody annotated are named, not hidden.
    assert set(model["unannotated"]) == {"TotalToPay", "FinancialStatus"}


def test_a_use_case_without_column_memory_skips(tmp_path, monkeypatch, capsys) -> None:
    use_case = tmp_path / "skill-packs/dbt-skills/use-cases/demo"
    (use_case / "ontology").mkdir(parents=True)
    assert _run(tmp_path, monkeypatch, ["--use-case", "demo"]) == 0
    assert "skip" in capsys.readouterr().out


# --- the real project ------------------------------------------------------------------

@needs_memory
def test_the_committed_conformed_layer_is_readable_and_large() -> None:
    columns = ca.conformed_columns(ENHANZA)
    assert len(columns) > 200
    shared = [c for c, m in columns.items() if len(m["connectors"]) > 1]
    assert len(shared) > 100, "annotating at the conformed level is the leverage argument"


@needs_memory
def test_proposing_against_the_real_project_harvests_its_own_words() -> None:
    result = ca.propose(ENHANZA, {})
    assert result["harvested_definitions"] > 50, "definitions come from the project, not from us"
    assert "FinancialStatus" in result["declared_domains"]
    assert result["proposed"]["AccountNumber"]["role"] == "identifier"
