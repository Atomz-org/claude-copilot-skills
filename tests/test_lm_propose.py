"""Tests for the language-model proposal layer.

A generated field is trusted by things that cannot check it — the same property that makes
annotations dangerous, with a generator that is fluent enough to be plausible about
anything. Every failure mode below produced a wrong answer that read correctly, so each has
a test that reproduces it:

1. **Answering an item nobody asked about.** The cheapest signal that the model worked from
   recall rather than from the batch it was handed.
2. **Citing evidence that is not there.** "The Fortnox API documents this as a percentage"
   is a sentence, not a citation. The item's own name does not count either — restating the
   question is the shape a confident fabrication takes.
3. **Contradicting the evidence it was given.** `Manufacturer` casts to string in every
   connector; an answer calling it an additive currency measure was accepted until the
   deriver's own CONFLICT rule was applied to the model too.
4. **Inventing an enum.** The one error here that generates the test which would have
   caught it.
5. **Promoting without review.** The proposal is a staging file. If `--promote` moved
   unreviewed entries, the review step would be decorative and the provenance a lie.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import _miniyaml  # noqa: E402
import lm_propose as lm  # noqa: E402

MEMORY = {
    "contracts": [{
        "concept": "dim_articles",
        "conformed": ["ArticleNumber", "Manufacturer", "PriceBeforeDiscount"],
        "columns": [
            {"column": "ArticleNumber", "carried_by": ["fortnox", "shopify"]},
            {"column": "Manufacturer", "carried_by": ["fortnox", "shopify"]},
            {"column": "PriceBeforeDiscount", "carried_by": ["fortnox"]},
        ],
    }],
    "bindings": [
        {"concept": "dim_articles", "connector": "fortnox", "column": "Manufacturer",
         "source_model": "fortnox_api__articles", "source_column": "Manufacturer",
         "transform": "direct"},
        {"concept": "dim_articles", "connector": "fortnox", "column": "PriceBeforeDiscount",
         "source_model": "favrit_api__orderline", "source_column": "unit_price",
         "transform": "derived"},
    ],
}

SCHEMA = """version: 2
models:
  - name: fortnox_bi_dim_articles_staging
    columns:
      - name: ArticleNumber
        description: The article number indicated on the line where applicable.
"""

SQL = """select
  cast(a.manufacturer as string) Manufacturer
  , cast(a.unit_price as float64) PriceBeforeDiscount
from x
"""

SOURCES = """version: 2
sources:
  - name: fortnox_api
    tables:
      - name: customers
        columns:
          - name: CustomerNumber
          - name: Name
          - name: OrgId
"""


def _tree(tmp_path: Path) -> Path:
    use_case = tmp_path / "skill-packs/dbt-skills/use-cases/demo"
    models = use_case / "dbt_project/models"
    models.mkdir(parents=True)
    (models / "schema.yml").write_text(SCHEMA, encoding="utf-8")
    (models / "sources.yml").write_text(SOURCES, encoding="utf-8")
    (models / "articles.sql").write_text(SQL, encoding="utf-8")
    (use_case / "ontology").mkdir(parents=True)
    (use_case / "ontology/column-memory.json").write_text(json.dumps(MEMORY), encoding="utf-8")
    return use_case


def _bind(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(lm, "REPO", tmp_path)
    monkeypatch.setattr(lm._paths, "REPO", tmp_path, raising=False)
    monkeypatch.setattr(lm.ca, "REPO", tmp_path)
    monkeypatch.setattr(lm.rt, "REPO", tmp_path, raising=False)


def _apply(use_case: Path, answers: list) -> dict:
    return lm.apply_answers(use_case, "demo", "annotations", answers, None, check=True)


# --- the batch ------------------------------------------------------------------------

def test_the_batch_ships_the_evidence_rather_than_asking_for_recall(tmp_path, monkeypatch) -> None:
    """A model asked "what is Manufacturer?" recalls; one handed its casts, its lineage and
    its concept's other columns reads. Only the second answer can be checked."""
    use_case = _tree(tmp_path)
    _bind(tmp_path, monkeypatch)
    batch = lm.build_batch(use_case, "demo", "annotations", None)
    item = {i["id"]: i for i in batch["items"]}["Manufacturer"]
    assert item["cast_types"] == ["string"]
    assert item["lineage"][0]["source_model"] == "fortnox_api__articles"
    assert "ArticleNumber" in item["concept_siblings"]
    assert item["carried_by_count"] == 2


def test_the_batch_is_ranked_by_how_many_connectors_carry_the_column(tmp_path, monkeypatch) -> None:
    """A reviewer who stops halfway should have spent the budget on the columns whose one
    answer covers the most (column, connector) pairs."""
    use_case = _tree(tmp_path)
    _bind(tmp_path, monkeypatch)
    items = lm.build_batch(use_case, "demo", "annotations", None)["items"]
    assert [i["carried_by_count"] for i in items] == sorted(
        (i["carried_by_count"] for i in items), reverse=True)


def test_an_already_annotated_column_is_not_asked_about_again(tmp_path, monkeypatch) -> None:
    use_case = _tree(tmp_path)
    _bind(tmp_path, monkeypatch)
    (use_case / "ontology/annotations.yml").write_text(
        'version: 1\ncolumns:\n  Manufacturer:\n    role: dimension\n'
        '    pii: none\n    definition: "Who made it."\n', encoding="utf-8")
    ids = {i["id"] for i in lm.build_batch(use_case, "demo", "annotations", None)["items"]}
    assert "Manufacturer" not in ids and "ArticleNumber" in ids


# --- the four refusals ----------------------------------------------------------------

def test_an_answer_for_an_item_that_was_never_asked_is_dropped(tmp_path, monkeypatch) -> None:
    use_case = _tree(tmp_path)
    _bind(tmp_path, monkeypatch)
    result = _apply(use_case, [{
        "id": "ColumnThatDoesNotExist", "role": "measure", "additivity": "additive",
        "unit": "currency", "pii": "none", "definition": "Revenue of the thing.",
        "confidence": "high", "evidence_used": ["the source system documents this"],
    }])
    assert result["accepted"] == 0
    assert "not an item in this batch" in result["drop_reasons"][0]


def test_evidence_that_names_nothing_in_the_item_is_dropped(tmp_path, monkeypatch) -> None:
    use_case = _tree(tmp_path)
    _bind(tmp_path, monkeypatch)
    result = _apply(use_case, [{
        "id": "Manufacturer", "role": "dimension", "pii": "none",
        "definition": "The party that produced the goods, per the vendor's catalogue.",
        "confidence": "high", "evidence_used": ["I know how ERP systems model this"],
    }])
    assert result["accepted"] == 0
    assert any("names nothing in the item" in r for r in result["drop_reasons"])


def test_citing_the_columns_own_name_is_not_evidence(tmp_path, monkeypatch) -> None:
    """"The Incoterms standard defines these terms" grounded on the token `terms` for
    `TermsOfDelivery`. Restating the question is the shape a fabrication takes."""
    use_case = _tree(tmp_path)
    _bind(tmp_path, monkeypatch)
    result = _apply(use_case, [{
        "id": "Manufacturer", "role": "dimension", "pii": "none",
        "definition": "The party that produced the goods, per the vendor's catalogue.",
        "confidence": "high",
        "evidence_used": ["the manufacturer is recorded on every article of this kind"],
    }])
    assert result["accepted"] == 0
    assert any("names nothing in the item" in r for r in result["drop_reasons"])


def test_an_answer_contradicting_its_own_casts_is_dropped(tmp_path, monkeypatch) -> None:
    """`Manufacturer` casts to string everywhere. The deriver abstains on exactly this
    conflict rather than guessing which side is wrong; so does the model's answer."""
    use_case = _tree(tmp_path)
    _bind(tmp_path, monkeypatch)
    result = _apply(use_case, [{
        "id": "Manufacturer", "role": "measure", "additivity": "additive",
        "unit": "currency", "pii": "none",
        "definition": "Total charged to us by the maker of the article.",
        "confidence": "high",
        "evidence_used": ["lineage: fortnox_api__articles.Manufacturer direct"],
    }])
    assert result["accepted"] == 0
    assert any("contradicts its own evidence" in r for r in result["drop_reasons"])


def test_a_definition_that_only_rearranges_the_name_is_dropped(tmp_path, monkeypatch) -> None:
    use_case = _tree(tmp_path)
    _bind(tmp_path, monkeypatch)
    result = _apply(use_case, [{
        "id": "Manufacturer", "role": "dimension", "pii": "none",
        "definition": "The manufacturer.", "confidence": "high",
        "evidence_used": ["lineage: fortnox_api__articles direct"],
    }])
    assert result["accepted"] == 0
    assert any("rearranges the column name" in r for r in result["drop_reasons"])


def test_a_closed_domain_without_a_source_loses_the_domain_not_the_answer(
    tmp_path, monkeypatch
) -> None:
    """Rule 5. The enum is the one field that generates the test which would have caught
    it, so it goes; the role and the definition were separately evidenced and stay."""
    use_case = _tree(tmp_path)
    _bind(tmp_path, monkeypatch)
    result = _apply(use_case, [{
        "id": "Manufacturer", "role": "dimension", "pii": "none",
        "definition": "The party that produced the goods, named on the article record.",
        "domain": {"closed": True, "values": ["ACME", "GLOBEX"]},
        "confidence": "high",
        "evidence_used": ["lineage: fortnox_api__articles.Manufacturer direct"],
    }])
    assert result["accepted"] == 1
    assert any("closed domain without values or a citable source" in r
               for r in result["drop_reasons"])


def test_a_measure_without_additivity_is_dropped(tmp_path, monkeypatch) -> None:
    use_case = _tree(tmp_path)
    _bind(tmp_path, monkeypatch)
    result = _apply(use_case, [{
        "id": "PriceBeforeDiscount", "role": "measure", "unit": "currency", "pii": "none",
        "definition": "Unit price of the line before any discount is applied.",
        "confidence": "high",
        "evidence_used": ["lineage: favrit_api__orderline.unit_price derived"],
    }])
    assert result["accepted"] == 0
    assert any("must state additivity" in r for r in result["drop_reasons"])


def test_a_grounded_answer_survives_every_check(tmp_path, monkeypatch) -> None:
    """The refusals have to leave a correct answer alone, or the layer produces nothing."""
    use_case = _tree(tmp_path)
    _bind(tmp_path, monkeypatch)
    result = _apply(use_case, [{
        "id": "PriceBeforeDiscount", "role": "measure", "additivity": "non_additive",
        "unit": "currency", "pii": "none",
        "definition": "Unit price of the line before any discount is applied.",
        "confidence": "high",
        "evidence_used": ["lineage: favrit_api__orderline.unit_price derived — per unit"],
    }])
    assert result["accepted"] == 1 and result["dropped"] == 0


# --- taxonomy -------------------------------------------------------------------------

def _taxonomy_item() -> dict:
    return {"id": "dim_customers", "concept": "dim_customers", "core_class": "erp:Customer",
            "candidate_tables": [{"source": "fortnox_api", "table": "customers",
                                  "declared_columns": 3, "matched_because": "name match"}],
            "natural_key_candidates": [], "declared_columns": ["CustomerNumber", "Name", "OrgId"]}


def test_a_natural_key_no_table_declares_is_dropped() -> None:
    """A plausible key survives human review because it reads correctly, then breaks at the
    first `unique` test on a column that does not exist."""
    entry, problems = lm.validate_taxonomy({
        "id": "dim_customers", "accept": True,
        "grain": "one row per customer per organisation",
        "natural_key": ["CustomerId"], "confidence": "high",
        "evidence_used": ["declared_columns include CustomerNumber"],
    }, _taxonomy_item())
    assert entry is None
    assert any("no candidate table declares" in p for p in problems)


def test_an_entity_without_a_grain_is_dropped() -> None:
    """Rule 4, and the field this batch exists for. An invented grain never surfaces as a
    failure — the measure just double-counts while every test passes."""
    entry, problems = lm.validate_taxonomy({
        "id": "dim_customers", "accept": True, "natural_key": ["CustomerNumber"],
        "confidence": "high", "evidence_used": ["declared_columns"],
    }, _taxonomy_item())
    assert entry is None and any("no grain" in p for p in problems)


def test_a_rejected_mapping_is_recorded_as_a_rejection() -> None:
    """A name match the model rejects is a finding, not silence."""
    entry, problems = lm.validate_taxonomy(
        {"id": "dim_customers", "accept": False}, _taxonomy_item())
    assert entry is None and any("rejected by the model" in p for p in problems)


# --- promotion ------------------------------------------------------------------------

def _proposal(use_case: Path, body: str) -> None:
    path = lm.proposal_path(use_case, "annotations")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("version: 1\nsource: lm\n\ncolumns:\n" + body, encoding="utf-8")


def test_promote_moves_nothing_that_was_not_reviewed(tmp_path, monkeypatch) -> None:
    """The proposal is a staging file. If promotion ignored the flag, the review step would
    be decorative and `source: lm` a claim nobody checked."""
    use_case = _tree(tmp_path)
    _bind(tmp_path, monkeypatch)
    _proposal(use_case, '  Manufacturer:\n    reviewed: false\n    confidence: high\n'
                        '    role: dimension\n    pii: none\n    definition: "Who made it."\n')
    result = lm.promote(use_case, "demo", "annotations", "medium", check=False)
    assert result["promoted"] == 0
    assert any("not reviewed" in h for h in result["held"])
    assert not (use_case / "ontology/annotations.yml").exists()


def test_promote_holds_an_answer_below_the_confidence_floor(tmp_path, monkeypatch) -> None:
    use_case = _tree(tmp_path)
    _bind(tmp_path, monkeypatch)
    _proposal(use_case, '  Manufacturer:\n    reviewed: true\n    confidence: low\n'
                        '    role: dimension\n    pii: none\n    definition: "Who made it."\n')
    result = lm.promote(use_case, "demo", "annotations", "medium", check=False)
    assert result["promoted"] == 0 and any("below medium" in h for h in result["held"])


def test_promote_never_overwrites_a_decision_already_in_the_file(tmp_path, monkeypatch) -> None:
    """Same rule as `--propose`: a generated candidate must never replace a human's call."""
    use_case = _tree(tmp_path)
    _bind(tmp_path, monkeypatch)
    decided = use_case / "ontology/annotations.yml"
    decided.write_text('version: 1\ncolumns:\n  Manufacturer:\n    role: text\n'
                       '    pii: none\n    definition: "Decided by hand."\n', encoding="utf-8")
    _proposal(use_case, '  Manufacturer:\n    reviewed: true\n    confidence: high\n'
                        '    role: dimension\n    pii: none\n    definition: "Who made it."\n')
    result = lm.promote(use_case, "demo", "annotations", "medium", check=False)
    assert result["promoted"] == 0
    assert any("already decided" in h for h in result["held"])
    assert "Decided by hand." in decided.read_text(encoding="utf-8")


def test_a_promoted_entry_keeps_its_provenance(tmp_path, monkeypatch) -> None:
    """After promotion the artifact reads as one file with one convention, and the comment
    plus `git log` is what says which lines a model drafted."""
    use_case = _tree(tmp_path)
    _bind(tmp_path, monkeypatch)
    _proposal(use_case, '  Manufacturer:\n    reviewed: true\n    confidence: high\n'
                        '    role: dimension\n    pii: none\n'
                        '    definition: "The party that produced the article."\n')
    result = lm.promote(use_case, "demo", "annotations", "medium", check=False)
    assert result["promoted"] == 1
    body = (use_case / "ontology/annotations.yml").read_text(encoding="utf-8")
    assert "promoted from proposals/annotations.lm.yml" in body
    assert "confidence high" in body
    loaded = _miniyaml.load(body) or {}
    assert loaded["columns"]["Manufacturer"]["role"] == "dimension"


def test_check_writes_nothing(tmp_path, monkeypatch) -> None:
    use_case = _tree(tmp_path)
    _bind(tmp_path, monkeypatch)
    _proposal(use_case, '  Manufacturer:\n    reviewed: true\n    confidence: high\n'
                        '    role: dimension\n    pii: none\n    definition: "Who made it."\n')
    lm.promote(use_case, "demo", "annotations", "medium", check=True)
    assert not (use_case / "ontology/annotations.yml").exists()


# --- the unattended backend -----------------------------------------------------------

def test_the_api_backend_skips_without_a_key_rather_than_failing(monkeypatch) -> None:
    """Unavailable is not failed — the same rule every optional dependency here follows."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = lm.run_anthropic({"instructions": "", "items": []}, "claude-sonnet-5")
    assert result["status"] == "skip" and "ANTHROPIC_API_KEY" in result["reason"]


@pytest.mark.skipif(
    not (REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics/"
         "ontology/proposals/annotations.lm.yml").exists(),
    reason="no committed lm proposal on this branch",
)
def test_the_committed_proposal_is_staged_not_decided() -> None:
    """It is a proposal on disk, so nothing in it may already read as reviewed."""
    path = (REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics/"
                   "ontology/proposals/annotations.lm.yml")
    entries = (_miniyaml.load(path.read_text(encoding="utf-8")) or {}).get("columns") or {}
    assert entries, "a committed proposal with no entries is noise"
    assert all(not (e or {}).get("reviewed") for e in entries.values())
