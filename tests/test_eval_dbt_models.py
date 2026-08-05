"""Tests for the model eval — the run-eval-shaped harness over generated dbt models.

An eval is believed or it is switched off, and the two ways it stops being believed are
both about classification rather than about counting:

1. **Blaming the wrong artifact.** Sixteen of the first run's nineteen failures were in an
   *upstream staging* model the generated one merely depends on. Scored as defects of the
   generator, the report said "1 of 19 passed" about the one artifact that was demonstrably
   fine.
2. **Counting an absent fixture as a defect.** The sample seeds write one scalar string per
   column, so any model that unnests an array or indexes a JSON document fails — which the
   seeds README states as scope, not as breakage.

The third property is the one taken straight from run-eval: expectations are labelled from
outside the run. Every column, enum, PII class, and supplier the eval checks comes from the
ontology; none is read off the relation it is judging.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import eval_dbt_models as ev  # noqa: E402


# --- classification -------------------------------------------------------------------

def test_a_failure_in_an_upstream_model_is_not_a_verdict_on_the_generated_one() -> None:
    reason = ("fortnox_bi_fact_invoice_rows_staging: execution failed: Binder Error: "
              "something went wrong")
    assert ev.classify(reason, "logic_bi_fact_invoice_rows") == "upstream-unbuildable"


def test_a_failure_in_the_model_itself_is_unbuildable() -> None:
    reason = "logic_bi_fact_invoice_rows: execution failed: Binder Error: something odd"
    assert ev.classify(reason, "logic_bi_fact_invoice_rows") == "unbuildable"


@pytest.mark.parametrize("reason", [
    'logic_bi_dim_company: execution failed: Malformed JSON at byte 0. Input: "municipality_value_1"',
    "fortnox_bi_fact_vouchers_staging: execution failed: UNNEST requires a single list as input",
    'fortnox_bi_fact_offers_staging: execution failed: Referenced column "Labels" not found in FROM clause!',
    'fortnox_bi_fact_stocktakings_staging: execution failed: Table "s" does not have a column named "id"',
])
def test_a_placeholder_seed_meeting_nested_sql_is_an_absent_fixture(reason: str) -> None:
    """One scalar string per column is what the seed generator writes. Every shape here is
    that string arriving where the SQL expected an array or a document — the seeds README
    calls JSON-fed models out of scope, and a score that counts them is meaningless."""
    assert ev.classify(reason, "logic_bi_fact_vouchers") == "no-sample"


def test_an_ambiguous_column_is_its_own_class_and_a_real_defect() -> None:
    """BigQuery resolves an unqualified column with two tables in scope; DuckDB refuses.
    The same ambiguity that let a source contract claim columns nobody established, showing
    up here as a portability defect — so it is neither a fixture problem nor the
    generator's."""
    reason = ('fortnox_bi_fact_salary_transactions_staging: execution failed: Binder Error: '
              'Ambiguous reference to column name "Date" (use: "st.Date" or "fy.Date")')
    assert ev.classify(reason, "logic_bi_fact_salary_transactions") == "ambiguous-sql"


def test_absent_fixtures_and_upstream_failures_are_not_scored() -> None:
    """A gate that goes red on a correct state gets switched off, taking the real findings
    with it — the rule every optional path in this repository follows."""
    assert "no-sample" in ev.NOT_A_FAILURE
    assert "upstream-unbuildable" in ev.NOT_A_FAILURE
    assert "ambiguous-sql" not in ev.NOT_A_FAILURE
    assert "pii-leak" not in ev.NOT_A_FAILURE


def test_every_failure_class_carries_a_sentence() -> None:
    """A class nobody can act on is a class that gets ignored."""
    scored = set(ev.FAILURE_CLASSES)
    assert "pii-leak" in scored and "contract-miss" in scored and "label-mismatch" in scored
    assert all(len(v) > 40 for v in ev.FAILURE_CLASSES.values())


# --- expectations come from the ontology ----------------------------------------------

def test_the_case_is_labelled_from_the_ontology_not_the_relation() -> None:
    entry = {
        "concept": "dim_company", "model": "logic_bi_dim_company",
        "union": "erp_bi_dim_company", "suppliers": ["fortnox", "visma_eaccounting"],
        "conformed": 3,
        "columns": [
            {"column": "OrgId", "role": "identifier", "pii": "none", "domain": None},
            {"column": "Status", "role": "dimension", "pii": "none",
             "domain": {"closed": True, "values": ["active"], "source": "the API"}},
        ],
        "withheld_pii": ["Email"], "unannotated": 1,
    }
    case = ev._case(entry, {"visma_eaccounting": "Visma eAccounting"})

    assert case["expect_columns"] == ["DataSource", "OrgId", "Status"]
    assert case["identifiers"] == ["OrgId"]
    assert case["domains"] == {"Status": ["active"]}
    assert case["forbidden_columns"] == ["Email"], "the PII the model must not carry"
    assert case["labels"]["visma_eaccounting"] == "Visma eAccounting"


def test_the_ontology_label_is_what_a_supplier_must_match() -> None:
    """Found by running it: the ontology publishes `Visma eAccounting` and the union writes
    `Visma e-Accounting`. An agent filtering by the published name gets zero rows and no
    error, which is why this is its own class rather than an attribution gap."""
    assert "label-mismatch" in ev.FAILURE_CLASSES
    assert "zero rows" in ev.FAILURE_CLASSES["label-mismatch"]


def test_duckdb_absent_is_exit_3(monkeypatch, capsys) -> None:
    monkeypatch.setattr(ev, "duckdb", None)
    assert ev.main(["--use-case", "enhanza-analytics"]) == ev.SKIP_EXIT
