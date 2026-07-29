#!/usr/bin/env python3
"""Analyze a dbt Core run: failures, timings, the critical path, and regressions.

Read this before changing code after a failure, and before optimizing anything for
speed. Optimizing a model that is not on the critical path changes wall-clock by zero.

    dbt build
    python scripts/run_results_analyzer.py --run-results target/run_results.json \
        --manifest target/manifest.json --top 15
    python scripts/run_results_analyzer.py --run-results target/run_results.json \
        --compare prod/run_results.json --slower-than 1.5
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
    fmt_seconds,
    header,
    load_json,
    section,
    table,
)

FAILURE_STATES = {"error", "fail", "runtime error"}


def short(uid: str) -> str:
    return uid.split(".")[-1]


def kind(uid: str) -> str:
    return uid.split(".")[0] if "." in uid else "node"


def load_results(path: str) -> Dict[str, Any]:
    data = load_json(path, "run_results.json")
    if not data.get("results"):
        print(
            f"WARNING: {path} contains no node results.\n"
            f"  `dbt parse` and `dbt compile` execute no nodes — use run_results.json\n"
            f"  from a `dbt build`, `dbt run`, or `dbt test`.",
            file=sys.stderr,
        )
    return data


def critical_path(man: Manifest, timings: Dict[str, float]) -> List[str]:
    """The slowest chain through the DAG, weighted by measured execution time.

    Wall-clock cannot go below this total no matter how many threads you add.
    """
    parents = man.parent_map()
    memo: Dict[str, tuple] = {}

    def best(uid: str, seen: Optional[frozenset] = None) -> tuple:
        if uid in memo:
            return memo[uid]
        seen = seen or frozenset()
        if uid in seen:
            return (0.0, [])
        own = timings.get(uid, 0.0)
        candidates = [
            best(p, seen | {uid})
            for p in (parents.get(uid) or [])
            if p in man.nodes
        ]
        if candidates:
            cost, chain = max(candidates, key=lambda c: c[0])
        else:
            cost, chain = 0.0, []
        result = (own + cost, chain + [uid])
        memo[uid] = result
        return result

    if not timings:
        return []
    scored = [best(uid) for uid in timings]
    return max(scored, key=lambda c: c[0])[1] if scored else []


def main() -> int:
    ap = argparse.ArgumentParser(description="Analyze a dbt run from run_results.json.")
    ap.add_argument("--run-results", default="target/run_results.json")
    ap.add_argument("--manifest", default="target/manifest.json",
                    help="optional; enables critical-path analysis and layer labels")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--compare", help="a previous run_results.json to diff against")
    ap.add_argument("--slower-than", type=float, default=1.5,
                    help="regression threshold as a ratio (1.5 = 50%% slower)")
    ap.add_argument("--min-seconds", type=float, default=1.0,
                    help="ignore regressions on nodes faster than this")
    ap.add_argument("--fail-on-error", action="store_true",
                    help="exit 1 if any node errored or a test failed")
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args()

    data = load_results(args.run_results)
    results = data.get("results", []) or []

    man: Optional[Manifest] = None
    if os.path.exists(args.manifest):
        man = Manifest.load(args.manifest)

    timings: Dict[str, float] = {}
    statuses: Dict[str, str] = {}
    messages: Dict[str, str] = {}
    failures: Dict[str, Any] = {}
    for r in results:
        uid = r.get("unique_id", "?")
        timings[uid] = float(r.get("execution_time") or 0.0)
        statuses[uid] = str(r.get("status", "?"))
        if r.get("message"):
            messages[uid] = str(r["message"])
        if r.get("failures") is not None:
            failures[uid] = r["failures"]

    header(f"dbt run analysis — {os.path.basename(args.run_results)}")
    elapsed = float(data.get("elapsed_time") or 0.0)
    total_node_time = sum(timings.values())
    meta = data.get("metadata", {}) or {}
    print(f"  dbt {meta.get('dbt_version', '?')} · "
          f"generated {meta.get('generated_at', '?')}")
    invocation_args = data.get("args", {}) or {}
    if invocation_args.get("which"):
        selectors = invocation_args.get("select") or []
        print(f"  command: dbt {invocation_args.get('which')}"
              + (f" --select {' '.join(selectors)}" if selectors else "")
              + (f" --target {invocation_args.get('target')}" if invocation_args.get("target") else ""))

    print(f"\n  wall-clock       {fmt_seconds(elapsed)}")
    print(f"  sum of node time {fmt_seconds(total_node_time)}")
    if elapsed > 0:
        ratio = total_node_time / elapsed
        print(f"  parallelism      {ratio:.1f}x", end="")
        if ratio < 1.5:
            print(f"  {Colors.YELLOW}(low — raise --threads, or you are on the "
                  f"critical path){Colors.END}")
        else:
            print()

    # ---- status breakdown
    by_status: Dict[str, int] = {}
    for status in statuses.values():
        by_status[status] = by_status.get(status, 0) + 1
    section("Status")
    table([[s, str(c)] for s, c in sorted(by_status.items(), key=lambda kv: -kv[1])],
          ["status", "count"])

    # ---- failures
    failed = [uid for uid, s in statuses.items() if s in FAILURE_STATES]
    if failed:
        section(f"Failures ({len(failed)}) — read these before changing anything")
        for uid in sorted(failed, key=lambda u: -timings.get(u, 0))[: args.top]:
            print(f"\n  {Colors.RED}{short(uid)}{Colors.END}  [{kind(uid)}]  "
                  f"status={statuses[uid]}"
                  + (f"  failing_rows={failures[uid]}" if failures.get(uid) else ""))
            msg = messages.get(uid, "").strip()
            if msg:
                for line in msg.splitlines()[:6]:
                    print(f"    {line}")
        print("\n  Fix upstream failures first — downstream 'skipped' nodes are")
        print("  consequences, not separate problems.")
    else:
        print(f"\n  {Colors.GREEN}No failures.{Colors.END}")

    # ---- slowest
    section(f"Slowest nodes (top {args.top})")
    slowest = sorted(timings.items(), key=lambda kv: -kv[1])[: args.top]
    rows = []
    for uid, secs in slowest:
        share = f"{secs / total_node_time * 100:4.1f}%" if total_node_time else "-"
        rows.append([short(uid), kind(uid), fmt_seconds(secs), share])
    table(rows, ["node", "type", "time", "share"])

    # ---- model vs test split
    model_time = sum(t for uid, t in timings.items() if uid.startswith("model."))
    test_time = sum(t for uid, t in timings.items()
                    if uid.startswith(("test.", "unit_test.")))
    snapshot_time = sum(t for uid, t in timings.items() if uid.startswith("snapshot."))
    seed_time = sum(t for uid, t in timings.items() if uid.startswith("seed."))
    if total_node_time:
        section("Time split")
        table(
            [
                ["models", fmt_seconds(model_time), f"{model_time/total_node_time*100:.0f}%"],
                ["tests", fmt_seconds(test_time), f"{test_time/total_node_time*100:.0f}%"],
                ["snapshots", fmt_seconds(snapshot_time), f"{snapshot_time/total_node_time*100:.0f}%"],
                ["seeds", fmt_seconds(seed_time), f"{seed_time/total_node_time*100:.0f}%"],
            ],
            ["kind", "time", "share"],
        )
        if test_time > total_node_time * 0.35:
            print(f"  {Colors.YELLOW}Tests are over a third of the run. Scope expensive")
            print(f"  ones with `where:`, tag them `nightly`, and exclude them from CI.{Colors.END}")

    # ---- critical path
    if man:
        path = critical_path(man, timings)
        if path:
            path_time = sum(timings.get(u, 0) for u in path)
            section(f"Critical path — {fmt_seconds(path_time)} "
                    f"({len(path)} nodes)")
            table([[short(u), fmt_seconds(timings.get(u, 0))] for u in path],
                  ["node", "time"])
            print(f"\n  Wall-clock cannot go below {fmt_seconds(path_time)} regardless of")
            print("  --threads. Optimizing a model NOT on this list changes nothing.")
            if elapsed and path_time / elapsed > 0.8:
                print(f"  {Colors.YELLOW}The critical path is {path_time/elapsed*100:.0f}% of")
                print(f"  wall-clock — you are latency-bound, not thread-bound.{Colors.END}")

    # ---- regression comparison
    regressions: List[List[str]] = []
    if args.compare:
        prev = load_results(args.compare)
        prev_timings = {
            r.get("unique_id"): float(r.get("execution_time") or 0.0)
            for r in prev.get("results", []) or []
        }
        prev_elapsed = float(prev.get("elapsed_time") or 0.0)
        section(f"Compared with {os.path.basename(args.compare)}")
        if prev_elapsed:
            delta = elapsed - prev_elapsed
            arrow = "slower" if delta > 0 else "faster"
            print(f"  wall-clock {fmt_seconds(prev_elapsed)} -> {fmt_seconds(elapsed)} "
                  f"({abs(delta/prev_elapsed)*100:.0f}% {arrow})")

        for uid, secs in timings.items():
            before = prev_timings.get(uid)
            if before is None or before < args.min_seconds:
                continue
            if secs / before >= args.slower_than:
                regressions.append([
                    short(uid), fmt_seconds(before), fmt_seconds(secs),
                    f"{secs / before:.1f}x",
                ])
        regressions.sort(key=lambda r: -float(r[3].rstrip("x")))
        print(f"\n  Regressions >= {args.slower_than}x on nodes over "
              f"{args.min_seconds}s: {len(regressions)}")
        table(regressions[: args.top], ["node", "before", "after", "factor"])

        new_nodes = set(timings) - set(prev_timings)
        gone = set(prev_timings) - set(timings)
        if new_nodes:
            print(f"\n  New in this run: {len(new_nodes)} "
                  f"({', '.join(sorted(short(u) for u in new_nodes)[:6])})")
        if gone:
            print(f"  Absent from this run: {len(gone)} "
                  f"({', '.join(sorted(short(u) for u in gone)[:6])})")
        if regressions:
            print("\n  Before optimizing: is it one node or all of them? All -> warehouse")
            print("  contention or thread count. One -> that model's SQL or data volume.")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "elapsed_time": elapsed,
                    "total_node_time": total_node_time,
                    "status_counts": by_status,
                    "failures": [
                        {"unique_id": u, "status": statuses[u],
                         "message": messages.get(u, ""), "failing_rows": failures.get(u)}
                        for u in failed
                    ],
                    "slowest": [{"unique_id": u, "seconds": s} for u, s in slowest],
                    "regressions": regressions,
                },
                fh,
                indent=2,
            )
        print(f"\n  Wrote {args.json_out}")

    if args.fail_on_error and failed:
        print(f"\n{Colors.RED}--fail-on-error: {len(failed)} node(s) failed.{Colors.END}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
