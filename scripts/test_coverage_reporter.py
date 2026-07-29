#!/usr/bin/env python3
"""Report dbt Core test coverage, ranked by downstream blast radius.

Coverage as a bare percentage is a vanity metric. An untested model feeding six
dashboards matters far more than twelve untested leaf models — so gaps are ranked by
what depends on them, not alphabetically.

    dbt parse
    python scripts/test_coverage_reporter.py --manifest target/manifest.json \
        --layer marts --min-coverage 0.9 --strict
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _manifest import (  # noqa: E402
    Colors,
    Manifest,
    collect_tested_columns,
    has_primary_key_tests,
    header,
    layer_of,
    section,
    table,
)

# Whitespace-flexible: `case\n    when` is the common formatting, so a plain
# "case when" substring check misses most real models.
LOGIC_RE = re.compile(
    r"(\bcase\s+when\b|\bover\s*\(|\bregexp|\brlike\b|\bdate(add|diff|_trunc)\b|"
    r"\blag\s*\(|\blead\s*\(|\brow_number\s*\(|\bpercentile)",
    re.IGNORECASE,
)


class ModelCoverage:
    def __init__(self, uid: str, node: Dict[str, Any], man: Manifest,
                 tests: List[Dict[str, Any]]) -> None:
        self.uid = uid
        self.name = node.get("name", uid)
        self.layer = layer_of(node)
        self.node = node
        self.tests = tests
        self.downstream_models = len([
            u for u in man.descendants(uid)
            if u in man.nodes and man.nodes[u].get("resource_type") == "model"
        ])
        self.downstream_exposures = len([
            u for u in man.descendants(uid) if u.startswith("exposure.")
        ])
        self.generic = [t for t in tests if (t.get("test_metadata") or {}).get("name")]
        self.singular = [
            t for t in tests
            if t.get("resource_type") == "test" and not (t.get("test_metadata") or {}).get("name")
        ]
        self.unit = [t for t in tests if t.get("resource_type") == "unit_test"]
        self.has_pk = has_primary_key_tests(tests)
        self.tested_cols = collect_tested_columns(tests)

        raw = node.get("raw_code") or node.get("raw_sql") or ""
        self.has_logic = bool(LOGIC_RE.search(raw))

        cols = node.get("columns") or {}
        self.n_columns = len(cols)
        self.n_documented = len([
            c for c, m in cols.items() if (m or {}).get("description", "").strip()
        ])
        self.has_description = bool((node.get("description") or "").strip())

    @property
    def gaps(self) -> List[str]:
        out: List[str] = []
        if not self.tests:
            out.append("no tests at all")
            return out
        if not self.has_pk:
            out.append("no tested primary key")
        if self.has_logic and not self.unit:
            out.append("has logic, no unit test")
        if not self.has_description:
            out.append("no description")
        if self.layer == "marts" and self.n_columns and self.n_documented < self.n_columns:
            out.append(f"{self.n_columns - self.n_documented} undocumented column(s)")
        return out

    @property
    def risk(self) -> int:
        """Blast radius weighting: an exposure is worth several models."""
        return self.downstream_models + self.downstream_exposures * 5

    def as_dict(self) -> Dict[str, Any]:
        return {
            "model": self.name,
            "layer": self.layer,
            "generic_tests": len(self.generic),
            "singular_tests": len(self.singular),
            "unit_tests": len(self.unit),
            "has_primary_key_test": self.has_pk,
            "downstream_models": self.downstream_models,
            "downstream_exposures": self.downstream_exposures,
            "gaps": self.gaps,
        }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="dbt test coverage, ranked by downstream blast radius."
    )
    ap.add_argument("--manifest", default="target/manifest.json")
    ap.add_argument("--layer", help="restrict to one layer: staging | intermediate | marts")
    ap.add_argument("--min-coverage", type=float, default=0.0,
                    help="minimum fraction of models with a tested primary key (0-1)")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if coverage is below --min-coverage or any model has no tests")
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args()

    man = Manifest.load(args.manifest)
    tests_by_model = man.tests_by_model()

    coverage = [
        ModelCoverage(uid, node, man, tests_by_model.get(uid, []))
        for uid, node in man.models().items()
    ]
    if args.layer:
        coverage = [c for c in coverage if c.layer == args.layer]

    if not coverage:
        print(f"ERROR: no models matched"
              f"{' for layer ' + args.layer if args.layer else ''}.\n"
              f"  Layers present: "
              f"{', '.join(sorted({layer_of(n) for n in man.models().values()}))}",
              file=sys.stderr)
        return 2

    total = len(coverage)
    with_any = [c for c in coverage if c.tests]
    with_pk = [c for c in coverage if c.has_pk]
    needing_unit = [c for c in coverage if c.has_logic]
    with_unit = [c for c in needing_unit if c.unit]
    documented = [c for c in coverage if c.has_description]

    header(f"Test coverage — {man.project_name}"
           + (f" · layer: {args.layer}" if args.layer else ""))

    def pct(n: int, d: int) -> str:
        return f"{(n / d * 100 if d else 0):5.1f}%  ({n}/{d})"

    print(f"  models with any test        {pct(len(with_any), total)}")
    print(f"  models with a tested PK     {pct(len(with_pk), total)}")
    print(f"  models with logic, unit-tested {pct(len(with_unit), len(needing_unit))}")
    print(f"  models with a description   {pct(len(documented), total)}")

    # ---- per-layer breakdown
    section("By layer")
    layers: Dict[str, List[ModelCoverage]] = {}
    for c in coverage:
        layers.setdefault(c.layer, []).append(c)
    rows = []
    for layer, group in sorted(layers.items()):
        pk = len([c for c in group if c.has_pk])
        logic = [c for c in group if c.has_logic]
        rows.append([
            layer,
            str(len(group)),
            f"{pk / len(group) * 100:.0f}%",
            f"{len([c for c in logic if c.unit])}/{len(logic)}" if logic else "-",
            f"{len([c for c in group if c.has_description]) / len(group) * 100:.0f}%",
        ])
    table(rows, ["layer", "models", "PK tested", "unit-tested", "documented"])

    # ---- ranked gaps
    gapped = sorted(
        [c for c in coverage if c.gaps], key=lambda c: (-c.risk, c.name)
    )
    section(f"Gaps ranked by blast radius ({len(gapped)} models)")
    if not gapped:
        print(f"  {Colors.GREEN}None.{Colors.END}")
    else:
        table(
            [
                [
                    c.name,
                    c.layer,
                    str(c.downstream_models),
                    str(c.downstream_exposures) if c.downstream_exposures else "-",
                    "; ".join(c.gaps),
                ]
                for c in gapped[: args.top]
            ],
            ["model", "layer", "downstream", "exposures", "gaps"],
            max_width=46,
        )
        if len(gapped) > args.top:
            print(f"  ... and {len(gapped) - args.top} more")
        print("\n  Fix top-down. A model feeding an exposure is weighted 5x a model")
        print("  feeding only other models — that is what makes a gap urgent.")

    # ---- test mix
    section("Test mix")
    n_generic = sum(len(c.generic) for c in coverage)
    n_singular = sum(len(c.singular) for c in coverage)
    n_unit = sum(len(c.unit) for c in coverage)
    print(f"  generic: {n_generic} · singular: {n_singular} · unit: {n_unit}")
    kinds: Dict[str, int] = {}
    for c in coverage:
        for t in c.generic:
            name = (t.get("test_metadata") or {}).get("name", "?")
            kinds[name] = kinds.get(name, 0) + 1
    table(
        [[k, str(v)] for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])[:12]],
        ["generic test", "count"],
    )
    if n_unit == 0 and needing_unit:
        print(f"\n  {Colors.YELLOW}No unit tests, but {len(needing_unit)} model(s) contain")
        print(f"  CASE/window/regex/date logic. Data tests cannot catch a wrong formula")
        print(f"  that produces plausible values.{Colors.END}")

    pk_rate = len(with_pk) / total
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "project": man.project_name,
                    "layer": args.layer,
                    "total_models": total,
                    "pk_coverage": round(pk_rate, 4),
                    "models": [c.as_dict() for c in coverage],
                },
                fh,
                indent=2,
            )
        print(f"\n  Wrote {args.json_out}")

    if args.strict:
        failures = []
        if pk_rate < args.min_coverage:
            failures.append(
                f"primary-key coverage {pk_rate * 100:.1f}% < "
                f"required {args.min_coverage * 100:.1f}%"
            )
        untested = [c.name for c in coverage if not c.tests]
        if untested:
            failures.append(f"{len(untested)} model(s) with no tests: "
                            f"{', '.join(untested[:5])}")
        if failures:
            print(f"\n{Colors.RED}--strict failed:{Colors.END}")
            for f in failures:
                print(f"  - {f}")
            return 1
        print(f"\n{Colors.GREEN}--strict passed.{Colors.END}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
