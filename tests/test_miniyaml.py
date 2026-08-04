"""Pins for scripts/_miniyaml.py, the PyYAML fallback.

Every test calls `_miniyaml.parse()` directly — never `load()` — because `load()`
prefers PyYAML when it is importable, and the developer machines always have it.
The fallback's defects therefore surface only in CI, which installs nothing but
pytest: a multi-line `expected_concepts: [a, b,` / `c]` in connectors.yml parsed
fine everywhere locally and failed every ontology test on the runner.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import _miniyaml  # noqa: E402


def test_flow_sequence_continues_across_lines():
    text = (
        "connectors:\n"
        "  - key: quickbooks\n"
        "    expected_concepts: [dim_company, dim_accounts,\n"
        "      dim_financial_years, fact_invoices]\n"
        "    status: planned\n"
    )
    row = _miniyaml.parse(text)["connectors"][0]
    assert row["expected_concepts"] == [
        "dim_company", "dim_accounts", "dim_financial_years", "fact_invoices",
    ]
    assert row["status"] == "planned"


def test_flow_mapping_continues_across_lines():
    text = "config: {materialized: view,\n  tags: [a, b]}\n"
    assert _miniyaml.parse(text)["config"] == {
        "materialized": "view", "tags": ["a", "b"],
    }


def test_a_bracket_inside_a_plain_scalar_does_not_start_folding():
    text = "desc: see [1 for details\nnext: 2\n"
    parsed = _miniyaml.parse(text)
    assert parsed["desc"] == "see [1 for details"
    assert parsed["next"] == 2


def test_brackets_inside_quotes_do_not_count():
    text = "value: ['a[', 'b]']\n"
    assert _miniyaml.parse(text)["value"] == ["a[", "b]"]


def test_an_unclosed_flow_collection_names_its_line():
    with pytest.raises(_miniyaml.MiniYamlError, match="unclosed flow"):
        _miniyaml.parse("value: [a, b,\n")


def test_the_committed_catalogues_parse_without_pyyaml():
    """The exact files CI choked on, parsed by the fallback itself."""
    catalogues = sorted(REPO.glob("skill-packs/*/use-cases/*/ontology/connectors.yml"))
    assert catalogues, "no connectors.yml found — glob went stale"
    for path in catalogues:
        parsed = _miniyaml.parse(path.read_text(encoding="utf-8"))
        assert "connectors" in parsed, path


def test_fallback_agrees_with_pyyaml_on_the_committed_catalogues():
    yaml = pytest.importorskip("yaml")
    for path in sorted(REPO.glob("skill-packs/*/use-cases/*/ontology/connectors.yml")):
        text = path.read_text(encoding="utf-8")
        assert _miniyaml.parse(text) == yaml.safe_load(text), path
