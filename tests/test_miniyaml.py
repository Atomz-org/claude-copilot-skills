"""Pins for scripts/_miniyaml.py, the PyYAML fallback.

Every test calls `_miniyaml.parse()` directly — never `load()` — because `load()`
prefers PyYAML when it is importable, and the developer machines always have it.
The fallback's defects therefore surface only in CI, which installs nothing but
pytest: a multi-line `expected_concepts: [a, b,` / `c]` in connectors.yml parsed
fine everywhere locally and failed every ontology test on the runner.
"""

import re
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


# ---------------------------------------------------------------------------------------
# The whole tree, not only the files this repo's own generators write
# ---------------------------------------------------------------------------------------
#
# The test above covers `connectors.yml`, which this repository emits itself and therefore
# formats to its own habits. Every gap found in this parser was in a file emitted by
# something else — `wren context import dbt` writes block sequences flush with their key,
# quoted scalars that wrap across lines, and `\uXXXX` escapes, and none of the three
# parsed. They were invisible locally because PyYAML is installed here and absent on CI,
# so the fallback path only ever ran on the runner.

# `#` inside a block scalar is literal text, and the lexer strips comments before the block
# scalar sees them. Fixing that means teaching the lexer about block-scalar state; this is
# a fixture illustrating a GitHub Actions workflow, not a file any tool here parses, so the
# limitation is recorded rather than fixed. A second entry here is a reason to fix it.
KNOWN_LEXER_LIMITS = {
    "tests/client-dbt-run.yml": "comments and blank lines inside a `run: |` block scalar",
}


def _repo_yaml():
    for root in ("skill-packs", ".claude", "scripts", "tests", "templates", "references"):
        for path in sorted((REPO / root).rglob("*.yml")):
            if not path.is_file():
                continue
            if {"target", "target-sample", "dbt_packages", ".wren", "node_modules"} & set(path.parts):
                continue
            yield path


def test_the_fallback_parses_every_yaml_file_in_the_repository():
    """The half that runs on a runner with no PyYAML — which is the only place it matters.

    A fallback that raises is worse than one that is imprecise: the caller gets no value at
    all, three frames from the key that owned the problem. Measured before the wren tree
    was read through it: 8 files raised.
    """
    seen = 0
    for path in _repo_yaml():
        seen += 1
        try:
            _miniyaml.parse(path.read_text(encoding="utf-8", errors="replace"))
        except _miniyaml.MiniYamlError as exc:
            raise AssertionError(f"{path.relative_to(REPO)}: {exc}") from None
    assert seen > 200, "glob went stale"


def test_the_fallback_agrees_with_pyyaml_across_the_repository():
    """Agreement is exact on structure and on every scalar up to whitespace inside a
    folded or quoted block — the lexer drops blank lines, so a blank line inside a quoted
    scalar cannot be recovered as the newline PyYAML makes of it."""
    yaml = pytest.importorskip("yaml")

    def squash(value):
        if isinstance(value, str):
            return re.sub(r"\s+", " ", value).strip()
        if isinstance(value, dict):
            return {k: squash(v) for k, v in value.items()}
        if isinstance(value, list):
            return [squash(v) for v in value]
        return value

    for path in _repo_yaml():
        rel = path.relative_to(REPO).as_posix()
        if rel in KNOWN_LEXER_LIMITS:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            expected = yaml.safe_load(text)
        except Exception:  # noqa: BLE001 - a file PyYAML rejects is not a comparison
            continue
        assert squash(_miniyaml.parse(text)) == squash(expected), rel
