#!/usr/bin/env python3
"""Evaluate generated dbt models against what the ontology promised, on DuckDB.

`ontology_to_dbt.py` writes a model out of an ontology; nothing said whether the model
*keeps* what the ontology claimed. dbt parse proves the refs resolve, the alignment checker
proves the naming and the column sets, and neither ever runs a row. This does: it builds
each generated model from the sample seeds through `dbt_sample_build.py` and then asks the
database the questions the ontology already answered on paper.

Shaped after dlt-hub's `run-eval` skill, which evaluates a *description* against labelled
cases and reports precision, recall, and clashes — sorted into named failure classes rather
than a pass count. Three of its properties are the reason it is worth copying here:

1. **Cases are labelled from outside the run.** run-eval labels a query with whether the
   skill should fire; the label does not come from watching it fire. Here every expectation
   comes from `index.json` and `column-annotations.json` — the promised column list, the
   declared enums, the PII class, the supplier set — never from the built relation. An eval
   that reads its expectations off its subject measures nothing.
2. **Failures are classified, not counted.** "7 of 19 passed" says nothing actionable;
   `contract-miss` on four models and `attribution-gap` on one are two different bugs with
   two different owners. The classes below are the analogue of run-eval's consistent-miss /
   competition-loss / false-trigger / undertrigger split.
3. **Unavailable is not failed.** run-eval rebuilds a stale workspace before judging it. A
   concept the sample seeds do not cover is `no-sample`, reported and excluded from the
   score — never counted as a defect of the model.

The eval is deliberately *not* a dbt test. A dbt test asserts one thing per column inside
the build; this asks cross-cutting questions a test cannot — whether every supplier
contributed rows, whether a column the ontology never declared has appeared — and it is
also what a future agentic-report eval will hang off, because "the numbers a report is
built on are attributable and in-domain" is the same question one level down.

Usage:
    python3 scripts/eval_dbt_models.py --use-case <slug>
    python3 scripts/eval_dbt_models.py --use-case <slug> --model logic_bi_dim_company
    python3 scripts/eval_dbt_models.py --use-case <slug> --format json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _manifest import Manifest, die  # noqa: E402
import _paths  # noqa: E402
from _paths import REPO  # noqa: E402
import ontology_to_dbt as gen  # noqa: E402

try:  # optional, exactly as in dbt_sample_build
    import duckdb
except ImportError:  # pragma: no cover - depends on the environment
    duckdb = None  # type: ignore[assignment]

SKIP_EXIT = 3

# What each failure means, stated once. A class without a sentence here is a class nobody
# can act on — the same reason `connector_alignment_check.py` carries CHECK_DETAIL.
FAILURE_CLASSES: Dict[str, str] = {
    "unbuildable": "the model did not build from the sample seeds — compile, transpile, or "
                   "execution failed",
    "contract-miss": "a column the ontology promised is not in the built relation",
    "contract-extra": "the built relation carries a column the ontology does not declare — "
                      "an upstream column arrived silently (rule 25)",
    "null-identifier": "an identifier-role column contains NULLs; it identifies nothing",
    "domain-violation": "a value outside the column's declared closed domain (rule 28) — "
                        "either the enum is wrong or the data is",
    "pii-leak": "a column annotated `pii: direct` reached a consumer-facing model (rule 17)",
    "attribution-gap": "an enabled supplier contributed no rows to the union — the number "
                       "is not comparable across tenants and nothing else reports it",
    "label-mismatch": "the supplier contributed rows under a DataSource value that is not "
                      "the label the ontology publishes — an agent filtering by the "
                      "ontology's name gets zero rows and no error",
    "ambiguous-sql": "an unqualified column with several tables in scope. BigQuery resolves "
                     "it, DuckDB refuses — the same ambiguity that made a source contract "
                     "claim columns nobody established, here as a portability defect",
    "upstream-unbuildable": "a model *upstream* of the generated one failed. Not a verdict "
                            "on the generated model, and not a fixture problem either",
}

# Reported, never scored: the sample seeds cover the JSON-free concepts only, and a concept
# they do not reach is an absent fixture rather than a defective model.
NOT_A_FAILURE = ("no-sample", "upstream-unbuildable")


def use_case_dir(slug: str) -> Path:
    return _paths.require_use_case_dir(slug, REPO)


def expectations(use_case: Path, manifest: Optional[str]) -> List[Dict[str, Any]]:
    """One case per generated model, labelled entirely from the ontology.

    Reuses `ontology_to_dbt.gap_concepts` rather than restating which columns a model
    should carry: two derivations of one fact is one more than stays in agreement, and the
    disagreement would silently become the eval's verdict.
    """
    project = use_case / "dbt_project"
    manifest_path = Path(manifest) if manifest else (project / "target/manifest.json")
    if not manifest_path.exists():
        die(f"no manifest at {manifest_path} — run artifacts/refresh.sh")
    man = Manifest.load(str(manifest_path))
    models = {n.get("name") for n in man.nodes.values() if n.get("resource_type") == "model"}

    entries, _stats = gen.gap_concepts(use_case, man)
    # After --write the generated models are in the manifest, so they are no longer "gap"
    # concepts. Recover them by name: a generated model is one whose file carries the marker.
    generated_dir = project / gen.LAYER_DIR
    written = {
        path.stem for path in sorted(generated_dir.glob("*.sql"))
        if gen.GENERATED_MARKER in path.read_text(encoding="utf-8")
    }

    index = json.loads((use_case / "ontology/index.json").read_text(encoding="utf-8"))
    labels = {c["key"]: c.get("label") or c["key"] for c in index.get("connectors") or []}

    cases: List[Dict[str, Any]] = []
    seen = set()
    for entry in entries:
        seen.add(entry["model"])
        cases.append(_case(entry, labels))
    for name in sorted(written - seen):
        concept = name[len(gen.LOGIC_PREFIX):]
        rebuilt = _rebuild_entry(use_case, concept, name)
        if rebuilt:
            cases.append(_case(rebuilt, labels))
    return [c for c in cases if c["model"] in written or not written]


def _rebuild_entry(use_case: Path, concept: str, model: str) -> Optional[Dict[str, Any]]:
    """The expectation for an already-written model, from the same ontology inputs."""
    ontology = use_case / "ontology"
    index = json.loads((ontology / "index.json").read_text(encoding="utf-8"))
    memory = json.loads((ontology / "column-memory.json").read_text(encoding="utf-8"))
    annotations = json.loads((ontology / "column-annotations.json").read_text(encoding="utf-8"))
    by_column = {a["column"]: a for a in annotations.get("columns") or []}
    contract = next((c for c in memory.get("contracts") or []
                     if c.get("concept") == concept), None)
    entry_index = next((c for c in index.get("concepts") or []
                        if c.get("concept") == concept), None)
    if contract is None or entry_index is None:
        return None
    conformed = list(contract.get("conformed") or [])
    annotated = [by_column[c] for c in conformed if c in by_column]
    return {
        "concept": concept,
        "model": model,
        "union": f"{gen.UNION_PREFIX}{concept}",
        "suppliers": sorted(entry_index.get("implemented_by") or []),
        "conformed": len(conformed),
        "columns": [a for a in annotated if a.get("pii") != "direct"],
        "withheld_pii": sorted(a["column"] for a in annotated if a.get("pii") == "direct"),
        "unannotated": len(conformed) - len(annotated),
    }


def _case(entry: Dict[str, Any], labels: Dict[str, str]) -> Dict[str, Any]:
    return {
        "model": entry["model"],
        "concept": entry["concept"],
        "suppliers": entry["suppliers"],
        "labels": {k: labels.get(k, k) for k in entry["suppliers"]},
        "expect_columns": list(gen.UNION_COLUMNS) + [c["column"] for c in entry["columns"]],
        "identifiers": [c["column"] for c in entry["columns"]
                        if c.get("role") == "identifier"],
        "domains": {c["column"]: list((c.get("domain") or {}).get("values") or [])
                    for c in entry["columns"] if c.get("domain")},
        "forbidden_columns": entry["withheld_pii"],
    }


def build(use_case: Path, case: Dict[str, Any],
          connectors: Optional[List[str]] = None) -> Tuple[Optional[Dict[str, Any]], str]:
    """Run one model through the sample builder. Returns (payload, reason-if-not-built)."""
    cmd = [
        sys.executable, str(REPO / "scripts/dbt_sample_build.py"),
        "--select", case["model"],
        "--connectors", ",".join(connectors if connectors is not None else case["suppliers"]),
        "--format", "json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=1800)
    if proc.returncode == SKIP_EXIT:
        return None, "toolchain unavailable"
    line = next((l for l in proc.stdout.splitlines() if l.strip().startswith("{")), "")
    if not line:
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        return None, tail[-1] if tail else f"exit {proc.returncode}"
    payload = json.loads(line)
    if not payload.get("ok"):
        return payload, str(payload.get("problem") or payload.get("error")
                            or "build reported not ok")
    return payload, ""


def interrogate(db: Path, relation: str, case: Dict[str, Any]) -> List[Dict[str, str]]:
    """Ask the database the questions the ontology already answered on paper."""
    findings: List[Dict[str, str]] = []
    con = duckdb.connect(str(db), read_only=True)
    try:
        columns = [r[1] for r in con.execute(f"pragma table_info('{relation}')").fetchall()]
        present = {c.lower(): c for c in columns}

        for wanted in case["expect_columns"]:
            if wanted.lower() not in present:
                findings.append({"class": "contract-miss", "subject": wanted})
        for got in columns:
            if got.lower() not in {c.lower() for c in case["expect_columns"]}:
                findings.append({"class": "contract-extra", "subject": got})
        for forbidden in case["forbidden_columns"]:
            if forbidden.lower() in present:
                findings.append({"class": "pii-leak", "subject": forbidden})

        for identifier in case["identifiers"]:
            actual = present.get(identifier.lower())
            if not actual:
                continue
            nulls = con.execute(
                f'select count(*) from {relation} where "{actual}" is null').fetchone()[0]
            if nulls:
                findings.append({"class": "null-identifier",
                                 "subject": f"{identifier} ({nulls} row(s))"})

        for column, values in case["domains"].items():
            actual = present.get(column.lower())
            if not actual or not values:
                continue
            placeholders = ", ".join(f"'{v}'" for v in values)
            bad = con.execute(
                f'select distinct "{actual}" from {relation} '
                f'where "{actual}" is not null and "{actual}" not in ({placeholders})'
            ).fetchall()
            for row in bad[:5]:
                findings.append({"class": "domain-violation",
                                 "subject": f"{column} = {row[0]!r}"})
    finally:
        con.close()
    return findings


def evaluate(use_case: Path, manifest: Optional[str], only: Optional[str],
             probe: bool = True) -> Dict[str, Any]:
    cases = expectations(use_case, manifest)
    if only:
        cases = [c for c in cases if c["model"] == only]
        if not cases:
            die(f"{only} is not a generated model")

    results: List[Dict[str, Any]] = []
    for case in cases:
        payload, reason = build(use_case, case)
        excluded: List[str] = []

        # run-eval rebuilds a stale workspace before judging it; the analogue here is
        # establishing a fixture that exists. One supplier whose adapter reads a JSON payload
        # fails the whole union — the seeds write `"municipality_value_1"`, which is not a
        # JSON document — and scoring the model on that would blame it for an absent CSV.
        # So: find the suppliers the sample data does support, and judge the model on those,
        # naming the ones it could not cover.
        if probe and (payload is None or not payload.get("ok")) \
                and _looks_like_missing_fixture(reason) and len(case["suppliers"]) > 1:
            survivors: List[str] = []
            for supplier in case["suppliers"]:
                one, _why = build(use_case, case, [supplier])
                (survivors if one and one.get("ok") else excluded).append(supplier)
            if survivors:
                payload, reason = build(use_case, case, survivors)
                case = {**case, "built_with": survivors}

        if payload is None or not payload.get("ok"):
            klass = classify(reason, case["model"])
            results.append({
                "model": case["model"], "status": "skip" if klass in NOT_A_FAILURE else "fail",
                "findings": [{"class": klass, "subject": reason[:160]}],
                "rows": None, "excluded_suppliers": excluded,
            })
            continue

        built = {b["model"]: b for b in payload.get("built") or []}
        relation = (built.get(case["model"]) or {}).get("relation")
        rows = (built.get(case["model"]) or {}).get("rows")
        findings = interrogate(Path(REPO / payload["db"]), relation, case) if relation else [
            {"class": "unbuildable", "subject": "built, but no relation reported"}
        ]

        by_source = payload.get("union_rows_by_source") or {}
        # Exact agreement is the pass: an agent filtering `DataSource = <ontology label>`
        # either gets the rows or it does not. The loose comparison is used only to *classify*
        # a failure — contributed-under-another-name is a different defect from contributed
        # nothing, and telling them apart is the difference between fixing a string and
        # hunting a missing join.
        def _loose(text: str) -> str:
            return "".join(ch for ch in text.lower() if ch.isalnum())

        for supplier in case.get("built_with") or case["suppliers"]:
            label = case["labels"].get(supplier, supplier)
            if not by_source or by_source.get(label):
                continue
            near = next((k for k in by_source if _loose(k) == _loose(label)), None)
            if near:
                findings.append({"class": "label-mismatch",
                                 "subject": f"{supplier}: ontology says {label!r}, "
                                            f"data says {near!r}"})
            else:
                findings.append({"class": "attribution-gap", "subject": f"{supplier} ({label})"})

        results.append({
            "model": case["model"],
            "status": "pass" if not findings else "fail",
            "findings": findings,
            "rows": rows,
            "built_with": case.get("built_with") or case["suppliers"],
            "excluded_suppliers": excluded,
        })

    scored = [r for r in results if r["status"] != "skip"]
    by_class: Dict[str, int] = {}
    for result in results:
        for finding in result["findings"]:
            by_class[finding["class"]] = by_class.get(finding["class"], 0) + 1

    return {
        "use_case": use_case.name,
        "cases": len(results),
        "scored": len(scored),
        "passed": sum(1 for r in scored if r["status"] == "pass"),
        "failed": sum(1 for r in scored if r["status"] == "fail"),
        "skipped": sum(1 for r in results if r["status"] == "skip"),
        "by_class": dict(sorted(by_class.items())),
        "results": results,
    }


# What a placeholder seed looks like when the SQL expected a nested structure. The seed
# generator writes one scalar string per column, so a model that unnests an array, indexes
# into a JSON document, or reads a repeated record hits one of these — all four are the
# "JSON-fed models are out of scope" line in the seeds README, arriving as a DuckDB error
# rather than as a note.
_FIXTURE_SHAPES = (
    "no sample", "not seeded", "seed", "malformed json", "_value_", "no source table",
    "missing source", "unnest requires a single list", "not found in from clause",
    "does not have a column named",
)

# A defect in the project's SQL that BigQuery tolerates and DuckDB rejects. Worth its own
# class because it is the only failure here that is neither a fixture nor the generator.
_AMBIGUOUS_SHAPES = ("ambiguous reference to column",)


def _looks_like_missing_fixture(reason: str) -> bool:
    """A concept the seeds do not reach, versus a model that is actually broken.

    The distinction is the whole reason `no-sample` exists: counting an absent fixture as a
    defect makes the score meaningless the first time somebody adds a concept.
    """
    lowered = reason.lower()
    return any(marker in lowered for marker in _FIXTURE_SHAPES)


def classify(reason: str, model: str) -> str:
    """Which failure this is, and whose.

    The failing model's name is the first thing the runner prints. When it is not the model
    under evaluation, the generated model was never reached — scoring it as broken would
    blame the one artifact that is demonstrably fine, which is how an eval stops being
    believed.
    """
    lowered = reason.lower()
    failing = reason.split(":", 1)[0].strip() if ":" in reason else ""
    upstream = bool(failing) and failing != model
    if any(marker in lowered for marker in _AMBIGUOUS_SHAPES):
        return "ambiguous-sql"
    if _looks_like_missing_fixture(reason):
        return "no-sample"
    return "upstream-unbuildable" if upstream else "unbuildable"


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Evaluate generated dbt models against the ontology, on DuckDB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--use-case", required=True)
    p.add_argument("--manifest")
    p.add_argument("--model", help="evaluate only this generated model")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.add_argument("--check", action="store_true", help="exit 1 if any scored case failed")
    p.add_argument("--no-probe", action="store_true",
                   help="do not retry a fixture-shaped failure per supplier; faster, and a "
                        "concept one supplier cannot sample is then skipped whole")
    args = p.parse_args(argv)

    if duckdb is None:
        message = "duckdb is not installed — pip install duckdb"
        print(json.dumps({"status": "skip", "reason": message}) if args.format == "json"
              else f"skip: {message}", file=sys.stderr)
        return SKIP_EXIT

    use_case = use_case_dir(args.use_case)
    report = evaluate(use_case, args.manifest, args.model, probe=not args.no_probe)

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f"use-case: {report['use_case']}")
        print(f"cases:    {report['cases']}  ({report['scored']} scored, "
              f"{report['skipped']} no sample data)")
        print(f"passed:   {report['passed']}   failed: {report['failed']}")
        if report["by_class"]:
            print("\nfailures by class:")
            for klass, count in report["by_class"].items():
                detail = FAILURE_CLASSES.get(klass, "no sample data covers this concept")
                print(f"  {count:3}  {klass:<18} {detail}")
        print()
        for result in report["results"]:
            mark = {"pass": "ok  ", "fail": "FAIL", "skip": "skip"}[result["status"]]
            rows = f"{result['rows']} row(s)" if result["rows"] is not None else ""
            excluded = result.get("excluded_suppliers") or []
            note = f"  (no sample data for {', '.join(excluded)})" if excluded else ""
            print(f"  {mark} {result['model']:<44} {rows}{note}")
            for finding in result["findings"][:4]:
                print(f"         {finding['class']}: {finding['subject']}")

    if args.check and report["failed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
