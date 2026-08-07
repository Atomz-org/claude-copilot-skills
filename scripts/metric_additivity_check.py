#!/usr/bin/env python3
"""The gate between meaning and number: measures checked against column annotations.

`ontology/column-annotations.json` records what each conformed column IS — whether
SUM() over it means anything (additivity), and whether it may reach a consumer at
all (PII). `models/semantic/*.yml` records what the project computes. Before this
gate, nothing connected them: a measure `agg: sum` over `PriceAfterDiscount` — a
per-unit price, annotated non_additive — passed `dbt parse`, MetricFlow validation,
the wren compile, and every dashboard it fed. The annotation layer knew the number
was wrong; nothing asked it.

Needs no manifest and no warehouse: both inputs are committed files, so the gate
runs identically on a fresh clone and in CI. `tests/test_metric_additivity_check.py`
runs it against the real use-case, which makes the test suite the enforcement
(this repo's rule: the gate is the existing suite, not a separate CI step).

The rules, each the mechanical form of an analytics rule:

- **sum over non_additive → error** (rule 11). A per-unit price summed across
  lines is a number that parses, plots, and means nothing.
- **sum over semi_additive without a non_additive_dimension window → error**
  (rule 11). A balance summed across time double-counts every open invoice per
  day it stays open; the window (`window_choice: min|max`) is what pins the sum
  to a point in time.
- **sum over an unannotated column → warn, never silence** (rule 5's abstention,
  carried through). The store does not know, so this gate says "unknown", names
  the column, and points at the annotation workflow. Erroring here would go red
  on correct-but-unannotated states and get the gate switched off; silence would
  read as "checked and fine".
- **direct-PII column exposed as a dimension or measure → error** (rule 17).
  The semantic layer is the serving surface; a direct identifier that reaches it
  reaches every dashboard downstream.

Aggregations other than `sum` are not gated: count/count_distinct are meaningful
on any grain, min/max/avg are order statistics, and average-of-non-additive is
precisely the correct treatment. The gate exists for the one aggregation whose
correctness depends on a fact the SQL does not carry.

Usage:
    python3 scripts/metric_additivity_check.py --use-case enhanza-analytics
    python3 scripts/metric_additivity_check.py --use-case enhanza-analytics --check
    python3 scripts/metric_additivity_check.py --use-case <slug> --format json

Exit codes: 0 clean (or skip), 1 errors under --check, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _miniyaml as miniyaml  # noqa: E402
from _paths import require_use_case_dir  # noqa: E402

ERROR, WARN = "error", "warn"

CHECK_DETAIL = {
    "sum-over-non-additive": "SUM() over a column annotated non_additive is meaningless",
    "sum-over-semi-additive-unwindowed":
        "semi_additive needs a non_additive_dimension window pinning the sum to a point in time",
    "sum-over-unannotated": "additivity UNKNOWN — annotate before trusting this sum",
    "pii-exposed": "direct-PII column surfaced as a dimension or measure (rule 17)",
}


def load_annotations(use_case_dir: Path) -> Dict[str, Dict[str, Any]]:
    path = use_case_dir / "ontology" / "column-annotations.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {row["column"]: row for row in data.get("columns", [])}


def semantic_files(use_case_dir: Path) -> List[Path]:
    semantic_dir = use_case_dir / "dbt_project" / "models" / "semantic"
    if not semantic_dir.is_dir():
        return []
    return sorted(semantic_dir.glob("*.yml"))


def _column_of(entry: Dict[str, Any]) -> str:
    """The column a measure or dimension reads: expr when set, else the name."""
    expr = entry.get("expr")
    # An expr with spaces or parens is a computed expression, not a bare column —
    # nothing to look up, and guessing a column out of it would be inventing.
    if isinstance(expr, str) and expr.strip() and " " not in expr and "(" not in expr:
        return expr.strip()
    if isinstance(expr, str) and expr.strip():
        return ""  # computed: not checkable against a single annotation
    return str(entry.get("name", ""))


def check_semantic_model(sm: Dict[str, Any], annotations: Dict[str, Dict[str, Any]],
                         source_file: str) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []
    name = sm.get("name", "?")

    for measure in sm.get("measures", []) or []:
        column = _column_of(measure)
        record = annotations.get(column) if column else None

        if measure.get("agg") == "sum":
            additivity = record.get("additivity") if record else None
            if record and additivity == "non_additive":
                findings.append({
                    "check": "sum-over-non-additive", "severity": ERROR,
                    "semantic_model": name, "measure": measure.get("name", "?"),
                    "column": column, "file": source_file,
                    "detail": record.get("definition") or "",
                })
            elif record and additivity == "semi_additive" \
                    and not measure.get("non_additive_dimension"):
                findings.append({
                    "check": "sum-over-semi-additive-unwindowed", "severity": ERROR,
                    "semantic_model": name, "measure": measure.get("name", "?"),
                    "column": column, "file": source_file,
                    "detail": "add non_additive_dimension: {name: <time dim>, "
                              "window_choice: min|max}",
                })
            elif not record or not additivity:
                findings.append({
                    "check": "sum-over-unannotated", "severity": WARN,
                    "semantic_model": name, "measure": measure.get("name", "?"),
                    "column": column or measure.get("name", "?"), "file": source_file,
                    "detail": "annotate via ontology/annotations.yml, then "
                              "column_annotations.py --use-case <slug>",
                })

        if record and record.get("pii") == "direct":
            findings.append({
                "check": "pii-exposed", "severity": ERROR,
                "semantic_model": name, "measure": measure.get("name", "?"),
                "column": column, "file": source_file,
                "detail": "direct PII in a measure",
            })

    for dim in sm.get("dimensions", []) or []:
        column = _column_of(dim)
        record = annotations.get(column) if column else None
        if record and record.get("pii") == "direct":
            findings.append({
                "check": "pii-exposed", "severity": ERROR,
                "semantic_model": name, "measure": dim.get("name", "?"),
                "column": column, "file": source_file,
                "detail": "direct PII in a dimension",
            })

    return findings


def run(use_case_dir: Path) -> Dict[str, Any]:
    files = semantic_files(use_case_dir)
    if not files:
        return {"status": "skip",
                "reason": "no models/semantic/ — nothing to check; add semantic "
                          "models to gate them"}

    annotations = load_annotations(use_case_dir)
    annotation_note = None
    if not annotations:
        # Without the store every sum is unknown: the gate still runs, but says
        # what it could not see rather than reporting a clean bill it cannot back.
        annotation_note = ("no ontology/column-annotations.json — every sum reports "
                          "as unannotated; run column_annotations.py first")

    findings: List[Dict[str, str]] = []
    models_checked = 0
    for path in files:
        doc = miniyaml.load(path.read_text(encoding="utf-8")) or {}
        for sm in doc.get("semantic_models", []) or []:
            models_checked += 1
            findings.extend(check_semantic_model(sm, annotations, path.name))

    return {
        "status": "ok",
        "semantic_models": models_checked,
        "errors": [f for f in findings if f["severity"] == ERROR],
        "warnings": [f for f in findings if f["severity"] == WARN],
        "note": annotation_note,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--use-case", required=True)
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if any error finding exists")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    use_case_dir = require_use_case_dir(args.use_case)
    report = run(use_case_dir)

    if args.format == "json":
        print(json.dumps({**report, "checks": CHECK_DETAIL}, indent=2))
    elif report["status"] == "skip":
        print(f"skip: {report['reason']}")
    else:
        print(f"{report['semantic_models']} semantic model(s) checked")
        if report.get("note"):
            print(f"  [note] {report['note']}")
        for f in report["errors"] + report["warnings"]:
            print(f"  [{f['severity']:5s}] {f['check']}: {f['semantic_model']}."
                  f"{f['measure']} on column {f['column']!r} ({f['file']})")
            if f.get("detail"):
                print(f"          {f['detail']}")
        print(f"{len(report['errors'])} error(s), {len(report['warnings'])} warning(s)")

    if args.check and report["status"] == "ok" and report["errors"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
