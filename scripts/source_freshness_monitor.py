#!/usr/bin/env python3
"""Report dbt Core source freshness breaches, annotated with the models each one blocks.

A freshness breach only matters in proportion to what it feeds. This joins sources.json
against the manifest so the on-call person knows whether a stale source blocks an exec
dashboard or a model nobody reads.

    dbt source freshness
    python scripts/source_freshness_monitor.py --sources target/sources.json \
        --manifest target/manifest.json --strict

--strict exits 1 on any error-severity breach, which is how you gate a production build.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _manifest import (  # noqa: E402
    Colors,
    Manifest,
    header,
    load_json,
    section,
    table,
)

STATUS_RANK = {"error": 0, "runtime error": 1, "warn": 2, "pass": 3}


def fmt_age(seconds: Optional[float]) -> str:
    if seconds is None:
        return "?"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def fmt_criterion(crit: Optional[Dict[str, Any]]) -> str:
    if not crit or crit.get("count") is None:
        return "-"
    return f"{crit['count']}{str(crit.get('period', ''))[:1]}"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="dbt source freshness breaches, with downstream impact."
    )
    ap.add_argument("--sources", default="target/sources.json")
    ap.add_argument("--manifest", default="target/manifest.json",
                    help="optional; enables downstream impact annotation")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on any error-severity breach")
    ap.add_argument("--warn-is-error", action="store_true",
                    help="treat warn-severity breaches as failures too")
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args()

    data = load_json(args.sources, "sources.json")
    results = data.get("results", []) or []

    if not results:
        print(
            "ERROR: sources.json contains no results.\n"
            "  Run `dbt source freshness` first. If it ran and produced nothing, every\n"
            "  source either has `freshness: null` or has no freshness block at all —\n"
            "  which means the SLA is undocumented, not that it is met.",
            file=sys.stderr,
        )
        return 2

    man: Optional[Manifest] = None
    if os.path.exists(args.manifest):
        man = Manifest.load(args.manifest)

    rows: List[Dict[str, Any]] = []
    for r in results:
        uid = r.get("unique_id", "?")
        src = (man.sources.get(uid, {}) if man else {}) or {}
        label = (
            f"{src.get('source_name')}.{src.get('name')}"
            if src
            else uid.replace("source.", "").replace(".", ".", 1)
        )
        criteria = r.get("criteria", {}) or {}

        downstream_models: List[str] = []
        exposures: List[str] = []
        if man and uid in man.all_nodes():
            for d in man.descendants(uid):
                if d.startswith("exposure."):
                    exposures.append(man.exposures.get(d, {}).get("name", d))
                elif d in man.nodes and man.nodes[d].get("resource_type") == "model":
                    downstream_models.append(man.nodes[d].get("name", d))

        rows.append({
            "unique_id": uid,
            "source": label,
            "status": str(r.get("status", "?")),
            "age_seconds": r.get("max_loaded_at_time_ago_in_s"),
            "max_loaded_at": r.get("max_loaded_at"),
            "warn_after": fmt_criterion(criteria.get("warn_after")),
            "error_after": fmt_criterion(criteria.get("error_after")),
            "loaded_at_field": src.get("loaded_at_field") or r.get("loaded_at_field"),
            "downstream_models": sorted(downstream_models),
            "exposures": sorted(exposures),
        })

    rows.sort(key=lambda r: (STATUS_RANK.get(r["status"], 9),
                             -len(r["exposures"]), -len(r["downstream_models"])))

    header("Source freshness")
    counts: Dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("  " + " · ".join(f"{k}: {v}" for k, v in sorted(counts.items())))

    breaches = [r for r in rows if r["status"] in ("error", "warn", "runtime error")]

    if breaches:
        section(f"Breaches ({len(breaches)}) — ordered by downstream impact")
        table(
            [
                [
                    r["source"],
                    r["status"].upper(),
                    fmt_age(r["age_seconds"]),
                    f"{r['warn_after']}/{r['error_after']}",
                    str(len(r["downstream_models"])),
                    ", ".join(r["exposures"][:2]) or "-",
                ]
                for r in breaches
            ],
            ["source", "status", "age", "warn/err", "models", "exposures"],
            max_width=34,
        )

        blocking = [r for r in breaches if r["exposures"]]
        if blocking:
            print(f"\n  {Colors.RED}These breaches reach live exposures:{Colors.END}")
            for r in blocking:
                print(f"    {r['source']} ({fmt_age(r['age_seconds'])} old) blocks: "
                      f"{', '.join(r['exposures'])}")

        section("What to check")
        errors = [r for r in breaches if r["status"] == "error"]
        if len(errors) == len([r for r in rows if r["error_after"] != "-"]) and len(errors) > 1:
            print("  EVERY source with an SLA is stale. That is a platform problem — the")
            print("  EL job is down, or the warehouse timezone/clock changed. Escalate to")
            print("  the platform team rather than debugging models.")
        elif errors:
            print("  Some sources stale, others fine. Check those specific connectors and")
            print("  whether the upstream tables were renamed.")
        missing_field = [r for r in breaches if not r["loaded_at_field"]]
        if missing_field:
            print(f"\n  {Colors.YELLOW}No loaded_at_field on: "
                  f"{', '.join(r['source'] for r in missing_field)}{Colors.END}")
        print("\n  Reminder: loaded_at_field must be a WAREHOUSE LOAD timestamp, not a")
        print("  source-system updated_at. With updated_at, a dead pipeline looks fresh")
        print("  forever as long as one old row was recently edited.")
    else:
        print(f"\n  {Colors.GREEN}All checked sources are within their SLA.{Colors.END}")

    # Sources with no freshness configured at all — an undocumented SLA.
    if man:
        checked = {r["unique_id"] for r in rows}
        unchecked = []
        for uid, src in man.sources.items():
            if uid in checked:
                continue
            n_down = len([
                d for d in man.descendants(uid)
                if d in man.nodes and man.nodes[d].get("resource_type") == "model"
            ])
            unchecked.append([f"{src.get('source_name')}.{src.get('name')}", str(n_down)])
        if unchecked:
            section(f"Sources with no freshness check ({len(unchecked)})")
            table(sorted(unchecked, key=lambda r: -int(r[1]))[:20],
                  ["source", "downstream models"])
            print("  Each is an undocumented SLA. Add warn_after/error_after, or set")
            print("  `freshness: null` explicitly to record that opting out was a decision.")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump({"counts": counts, "sources": rows}, fh, indent=2)
        print(f"\n  Wrote {args.json_out}")

    if args.strict:
        bad = [r for r in rows if r["status"] in ("error", "runtime error")]
        if args.warn_is_error:
            bad += [r for r in rows if r["status"] == "warn"]
        if bad:
            print(f"\n{Colors.RED}--strict: {len(bad)} breach(es). "
                  f"Building on stale sources publishes stale numbers.{Colors.END}")
            return 1
        print(f"\n{Colors.GREEN}--strict passed.{Colors.END}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
