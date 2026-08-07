"""Tests for scripts/metric_additivity_check.py.

The gate's value is that a wrong sum FAILS and an unknown sum is NAMED. Both
directions have a failure mode worth pinning:

- Too lax, and `sum(PriceAfterDiscount)` ships again — the exact defect the gate
  exists for, invisible to dbt, MetricFlow, and every dashboard downstream.
- Too strict, and a correct-but-unannotated project goes red, which is how a
  gate gets switched off within a week (this repo's recurring lesson).

The last test runs the real CLI against the real committed use-case: the
semantic layer was designed to respect the annotations, so a clean exit is the
standing proof that meaning and number still agree. If someone adds a sum over
an unannotated column, that test stays green (warn, not error) but the warning
is on the record; if they sum a non-additive column, the suite goes red.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import metric_additivity_check as gate  # noqa: E402

ENHANZA = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics"


def make_use_case(tmp_path: Path, semantic_yaml: str, annotations: list[dict]) -> Path:
    root = tmp_path / "uc"
    semantic_dir = root / "dbt_project" / "models" / "semantic"
    semantic_dir.mkdir(parents=True)
    (semantic_dir / "_semantic_models.yml").write_text(semantic_yaml, encoding="utf-8")
    ontology = root / "ontology"
    ontology.mkdir()
    (ontology / "column-annotations.json").write_text(
        json.dumps({"columns": annotations}), encoding="utf-8")
    return root


BASE = """\
version: 2
semantic_models:
  - name: demo
    model: ref('fct_demo')
    measures:
      - name: {measure}
        agg: {agg}
        expr: {expr}
{extra}"""


def test_sum_over_non_additive_is_an_error(tmp_path: Path) -> None:
    root = make_use_case(
        tmp_path,
        BASE.format(measure="unit_price_total", agg="sum", expr="UnitPrice", extra=""),
        [{"column": "UnitPrice", "additivity": "non_additive", "pii": "none"}],
    )
    report = gate.run(root)
    assert [f["check"] for f in report["errors"]] == ["sum-over-non-additive"]
    assert report["errors"][0]["column"] == "UnitPrice"


def test_semi_additive_without_window_errors_and_with_window_passes(tmp_path: Path) -> None:
    annotations = [{"column": "Balance", "additivity": "semi_additive", "pii": "none"}]

    bare = make_use_case(
        tmp_path,
        BASE.format(measure="open_balance", agg="sum", expr="Balance", extra=""),
        annotations,
    )
    report = gate.run(bare)
    assert [f["check"] for f in report["errors"]] == ["sum-over-semi-additive-unwindowed"]

    windowed = make_use_case(
        tmp_path / "w",
        BASE.format(
            measure="open_balance", agg="sum", expr="Balance",
            extra="        non_additive_dimension:\n"
                  "          name: invoice_date\n"
                  "          window_choice: max\n"),
        annotations,
    )
    report = gate.run(windowed)
    assert report["errors"] == []
    assert report["warnings"] == []


def test_sum_over_unannotated_warns_but_does_not_error(tmp_path: Path) -> None:
    root = make_use_case(
        tmp_path,
        BASE.format(measure="mystery_total", agg="sum", expr="Mystery", extra=""),
        [],  # empty store: everything is unknown
    )
    report = gate.run(root)
    assert report["errors"] == []
    assert [f["check"] for f in report["warnings"]] == ["sum-over-unannotated"]
    assert report["note"], "an absent store must be said, not implied"


def test_counts_are_not_gated(tmp_path: Path) -> None:
    """count/count_distinct are meaningful on any grain — additivity is a fact
    about sums."""
    root = make_use_case(
        tmp_path,
        BASE.format(measure="row_count", agg="count", expr="UnitPrice", extra=""),
        [{"column": "UnitPrice", "additivity": "non_additive", "pii": "none"}],
    )
    report = gate.run(root)
    assert report["errors"] == []
    assert report["warnings"] == []


def test_direct_pii_as_dimension_is_an_error(tmp_path: Path) -> None:
    yaml = """\
version: 2
semantic_models:
  - name: demo
    model: ref('fct_demo')
    dimensions:
      - name: email
        type: categorical
        expr: RecipientEmail
"""
    root = make_use_case(
        tmp_path, yaml,
        [{"column": "RecipientEmail", "additivity": None, "pii": "direct"}],
    )
    report = gate.run(root)
    assert [f["check"] for f in report["errors"]] == ["pii-exposed"]


def test_computed_expr_is_not_matched_against_a_single_column(tmp_path: Path) -> None:
    """`expr: a + b` names no one column; guessing one would be inventing."""
    root = make_use_case(
        tmp_path,
        BASE.format(measure="net", agg="sum", expr="'gross - fees'", extra=""),
        [{"column": "gross", "additivity": "non_additive", "pii": "none"}],
    )
    report = gate.run(root)
    assert report["errors"] == []


def test_no_semantic_dir_skips_with_a_reason(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    (root / "dbt_project" / "models").mkdir(parents=True)
    report = gate.run(root)
    assert report["status"] == "skip"
    assert "semantic" in report["reason"]


# --- the standing gate over the real use-case -----------------------------------------

def test_the_committed_semantic_layer_respects_the_annotations() -> None:
    """The enhanza semantic layer was designed against the annotation store —
    every summed column annotated additive or windowed semi-additive, PII
    withheld. This is the proof that stays true, or the suite goes red."""
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts/metric_additivity_check.py"),
         "--use-case", "enhanza-analytics", "--check", "--format", "json"],
        capture_output=True, text=True, timeout=60, cwd=REPO,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["status"] == "ok"
    assert report["semantic_models"] >= 6
    assert report["errors"] == []
