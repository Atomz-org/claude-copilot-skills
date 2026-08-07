#!/usr/bin/env python3
"""Refuse a `select *` that reaches a model's output schema.

A star in a model's final select means the model has no column contract: whatever the
upstream relation carries becomes this model's schema, and an upstream change alters a
consumer-facing table with no diff in this repository to point at. Rule 25 says it must
not survive into a mart; measured here, it does not stop at marts — 109 of 662 model
files publish a star.

What this refuses, and what it deliberately does not
---------------------------------------------------

The check is **paren depth**, not a text match, because the two forms read almost alike
and only one of them is a defect:

    with source as (select * from {{ ref('x') }})     -- depth 1: the outer select
    select a, b from source                           --          enumerates. FINE.

    select *, {{ add_erp_fields(...) }}               -- depth 0: reaches the output
    from {{ ref('x') }}                               --          schema. REFUSED.

Rule 27 names the first form as the house style for an import CTE, so a gate that
flagged it would be arguing with the rules it exists to enforce. Measured: 22 files use
it, none of them a contract leak.

Three more exemptions, each because the star is correct there:

- **`snapshots/`** — rule 24 requires snapshotting the *raw source*, and a snapshot that
  enumerated columns would silently stop capturing a new one. That is the opposite of
  what a snapshot is for.
- **`tests/`, `macros/`, `analyses/`** — not models. A singular test is a query whose
  result is rows-that-should-not-exist; it has no consumers and no contract.
- **compiled output** — `target/`, `target-sample/`, `dbt_packages/` are build artifacts.

`{{ dbt_utils.star(...) }}` is reported separately and never fails. It expands to an
explicit list at compile time, so the SQL that runs is enumerated — but the list still
comes from the upstream relation, so it is a deliberate choice worth seeing rather than
a defect worth blocking.

The baseline, and why it only shrinks
-------------------------------------

109 offending models exist today. A gate that goes red on the state of the repository
the day it lands is a gate somebody disables within a week, and it takes the real
failures with it. So the known set is committed as a baseline and the gate fails only on
a model that is **not** in it: new work must enumerate, existing debt is visible and
countable, and `--update-baseline` can remove a fixed entry but **refuses to add one**.
That asymmetry is the whole mechanism — a baseline that could grow is just a mute button.

Usage:
    python3 scripts/no_star_check.py --use-case <slug>            # report
    python3 scripts/no_star_check.py --use-case <slug> --check    # the CI gate
    python3 scripts/no_star_check.py --use-case <slug> --update-baseline
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _paths  # noqa: E402

REPO = _paths.REPO

BASELINE_NAME = "star-baseline.json"

# Build artifacts and non-model SQL. `snapshots/` is the interesting one: rule 24 makes a
# star correct there, because a snapshot that enumerated columns would quietly stop
# capturing a column the source added — which is the history a snapshot exists to keep.
EXCLUDED_DIRS = ("target", "target-sample", "dbt_packages", "snapshots", "tests",
                 "macros", "analyses")

STAR_IN_OUTPUT = "star-in-output"
STAR_IN_IMPORT_CTE = "star-in-import-cte"
MACRO_STAR = "macro-star"
CLEAN = "clean"


def use_case_dir(slug: str) -> Path:
    return _paths.require_use_case_dir(slug, REPO)


# ---------------------------------------------------------------------------------------
# The classifier
# ---------------------------------------------------------------------------------------


def strip_noise(sql: str) -> str:
    """Remove comments and Jinja, keeping length-equivalent whitespace.

    Jinja has to go before parens are counted — `{{ source('a', 'b') }}` contributes two
    that no SQL parser would see, and one of them lands exactly where an import CTE opens.
    Replacing rather than deleting keeps every offset usable for line reporting.
    """
    def blank(match: re.Match) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))

    sql = re.sub(r"--[^\n]*", blank, sql)
    sql = re.sub(r"/\*.*?\*/", blank, sql, flags=re.S)
    sql = re.sub(r"\{\{.*?\}\}", blank, sql, flags=re.S)
    sql = re.sub(r"\{%.*?%\}", blank, sql, flags=re.S)
    sql = re.sub(r"\{#.*?#\}", blank, sql, flags=re.S)
    return sql


def _depth_at(text: str, position: int) -> int:
    """Parenthesis nesting depth at an offset, ignoring quoted strings."""
    depth = 0
    quote: Optional[str] = None
    for index, char in enumerate(text[:position]):
        if quote:
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
    return depth


@dataclass
class Finding:
    path: str
    verdict: str
    line: int
    snippet: str


def classify(sql: str, path: str) -> List[Finding]:
    """Every star in `sql`, with whether it reaches the model's output schema.

    A star at depth 0 is in the outermost select and therefore in the output. A star at
    depth >= 1 is inside a CTE or a subquery whose enclosing select does the enumerating.
    """
    body = strip_noise(sql)
    findings: List[Finding] = []

    for match in re.finditer(r"\bselect\s+(?:distinct\s+)?\*", body, re.I):
        verdict = STAR_IN_OUTPUT if _depth_at(body, match.start()) == 0 else STAR_IN_IMPORT_CTE
        line = body[:match.start()].count("\n") + 1
        findings.append(Finding(
            path=path, verdict=verdict, line=line,
            snippet=sql.splitlines()[line - 1].strip()[:100] if line <= len(sql.splitlines()) else "",
        ))

    for match in re.finditer(r"dbt_utils\.star\s*\(", sql):
        line = sql[:match.start()].count("\n") + 1
        findings.append(Finding(path=path, verdict=MACRO_STAR, line=line,
                                snippet=sql.splitlines()[line - 1].strip()[:100]))
    return findings


def model_files(project: Path) -> List[Path]:
    out: List[Path] = []
    for path in sorted(project.rglob("*.sql")):
        parts = set(path.relative_to(project).parts)
        if parts & set(EXCLUDED_DIRS):
            continue
        out.append(path)
    return out


# ---------------------------------------------------------------------------------------
# Scan and gate
# ---------------------------------------------------------------------------------------


def scan(project: Path) -> Dict[str, Any]:
    offenders: Dict[str, List[int]] = {}
    import_ctes: List[str] = []
    macro_stars: List[str] = []
    details: List[Finding] = []
    scanned = 0

    for path in model_files(project):
        scanned += 1
        rel = str(path.relative_to(project))
        for finding in classify(path.read_text(encoding="utf-8", errors="replace"), rel):
            details.append(finding)
            if finding.verdict == STAR_IN_OUTPUT:
                offenders.setdefault(rel, []).append(finding.line)
            elif finding.verdict == STAR_IN_IMPORT_CTE:
                import_ctes.append(rel)
            else:
                macro_stars.append(rel)

    return {
        "scanned": scanned,
        "offenders": {k: sorted(set(v)) for k, v in sorted(offenders.items())},
        "import_ctes": sorted(set(import_ctes)),
        "macro_stars": sorted(set(macro_stars)),
        "details": details,
    }


def load_baseline(use_case: Path) -> Tuple[Dict[str, Any], Path]:
    path = use_case / "artifacts" / BASELINE_NAME
    if not path.exists():
        return {"models": []}, path
    try:
        return json.loads(path.read_text(encoding="utf-8")), path
    except json.JSONDecodeError:
        return {"models": []}, path


def render_baseline(models: List[str]) -> str:
    payload = {
        "note": (
            "Models whose final select carries a `select *`, recorded so the gate is "
            "green on the state that existed when it landed. This list may only SHRINK: "
            "`--update-baseline` removes an entry that has been fixed and refuses to add "
            "one, because a baseline that can grow is a mute button. Every entry here is "
            "a model with no column contract — its output schema is whatever its upstream "
            "relation happens to carry."
        ),
        "generated_by": "scripts/no_star_check.py",
        "count": len(models),
        "models": sorted(models),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def report(slug: str, check: bool, update: bool) -> Dict[str, Any]:
    use_case = use_case_dir(slug)
    project = use_case / "dbt_project"
    if not project.exists():
        return {"status": "skip", "reason": f"no dbt_project in {slug}"}

    result = scan(project)
    baseline, baseline_path = load_baseline(use_case)
    known = set(baseline.get("models") or [])
    current = set(result["offenders"])

    new = sorted(current - known)
    fixed = sorted(known - current)

    payload: Dict[str, Any] = {
        "status": "ok",
        "use_case": slug,
        "scanned": result["scanned"],
        "offenders": len(current),
        "baseline": len(known),
        "new": new,
        "fixed": fixed,
        "import_ctes": len(result["import_ctes"]),
        "macro_stars": len(result["macro_stars"]),
        "baseline_path": str(baseline_path.relative_to(REPO)),
        "detail": {k: v for k, v in list(result["offenders"].items()) if k in set(new)},
    }

    if update:
        # Shrink only — *once a baseline exists*. Adding to one would let a new star be
        # waved through by re-running the tool that is supposed to catch it. The first
        # run is the exception and has to be: there is no baseline yet, so every offender
        # reads as new and the gate would refuse to record the state it was built to
        # record. Bootstrapping is a one-time act and the file is committed, so a second
        # bootstrap is visible as a deletion in the diff.
        bootstrap = not baseline_path.exists()
        if new and not bootstrap:
            payload["status"] = "fail"
            payload["reason"] = (
                f"{len(new)} model(s) carry a new `select *`; the baseline may only "
                "shrink. Enumerate the columns instead — "
                "scripts/source_schema_derive.py derives them from a cited source."
            )
            return payload
        content = render_baseline(sorted(current))
        changed = (baseline_path.read_text(encoding="utf-8")
                   if baseline_path.exists() else None) != content
        if changed:
            baseline_path.parent.mkdir(parents=True, exist_ok=True)
            baseline_path.write_text(content, encoding="utf-8")
        payload["status"] = "changed" if changed else "ok"
        payload["bootstrapped"] = bootstrap
        payload["removed_from_baseline"] = fixed
        return payload

    if check and new:
        payload["status"] = "fail"
        payload["reason"] = f"{len(new)} model(s) carry a `select *` in their output schema"
    return payload


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--use-case", required=True)
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if a model outside the baseline carries a star")
    parser.add_argument("--update-baseline", action="store_true",
                        help="remove fixed entries; refuses to add new ones")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    payload = report(args.use_case, args.check, args.update_baseline)

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False))
    elif payload["status"] == "skip":
        print(f"skip {args.use_case}: {payload['reason']}")
    else:
        print(f"{payload['scanned']} model file(s) scanned")
        print(f"  {payload['offenders']} carry a `select *` in their output schema "
              f"({payload['baseline']} baselined)")
        print(f"  {payload['import_ctes']} use it in an import CTE only (rule 27 — fine)")
        if payload["macro_stars"]:
            print(f"  {payload['macro_stars']} use dbt_utils.star() (reported, not failed)")
        for model in payload["new"]:
            lines = ", ".join(str(n) for n in payload["detail"].get(model, []))
            print(f"  [error] new star: {model}:{lines}")
        for model in payload["fixed"]:
            print(f"  [fixed] {model} — run --update-baseline to drop it")
        if payload.get("reason"):
            print(f"  {payload['reason']}")

    return 1 if payload["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
