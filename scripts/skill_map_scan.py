#!/usr/bin/env python3
"""Run skill-map's deterministic scanner over this repository's harness files.

skill-map (https://github.com/PackMaaan/skill-map) has two halves. The scanner
is pure code: it walks Markdown, parses frontmatter, resolves references between
skills/commands/agents, and emits a graph plus analyzer issues. The other half
is a probabilistic layer that queues LLM jobs for an agent to execute.

**Only the first half is reachable from this module, by construction.** Every
`sm` invocation goes through `_run_sm()`, which refuses any verb outside
`DETERMINISTIC_VERBS`. That allowlist is the no-LLM guarantee, and
`tests/test_skill_map_pack.py` pins it against the probabilistic verb families
(`jobs`, `agent`, `findings`, `refresh`) so a future edit cannot quietly add one.
No API key is read, none is needed, and the scan runs offline once the CLI is
resolved.

Resolution order for the CLI, so CI and a laptop behave the same:

1. `SKILL_MAP_BIN` if set (an absolute path to an `sm` binary),
2. `sm` on PATH,
3. `npx -y @skill-map/cli@<PINNED_VERSION>` when Node is present.

When none resolve, the scan is *unavailable* rather than failed: `main` returns
EXIT_UNAVAILABLE and callers record a `skip`. A repository check must not turn
red because a runner has no Node on it.

Usage:

    python scripts/skill_map_scan.py --summary
    python scripts/skill_map_scan.py --check --max-errors 0
    python scripts/skill_map_scan.py --json out.json --mermaid harness.mmd
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Pinned so the issue set cannot change shape under CI without a visible diff.
PINNED_VERSION = "0.99.1"

# The deterministic surface. `scan` is the only verb this module actually needs
# today; the rest are listed because they are the read-only verbs a human may
# reasonably be told to run from the skill, and keeping one allowlist means the
# skill's documentation and this module's guard cannot disagree.
#
# Deliberately ABSENT, and asserted absent by the tests: `jobs *` (enqueue and
# claim LLM work), `agent *` (installs the job-processing skill), `findings *`
# (reads probabilistic judgments), and `refresh` (recomputes enrichment rows).
DETERMINISTIC_VERBS = frozenset({
    "init",
    "scan",
    "check",
    "list",
    "show",
    "orphans",
    "export",
    "graph",
    "version",
    "doctor",
})

# Verb families that reach the probabilistic layer. Named explicitly so the
# guard's error message can say *why* a verb is rejected, and so the test that
# pins the no-LLM property has something concrete to assert against.
PROBABILISTIC_VERBS = frozenset({"jobs", "agent", "findings", "refresh"})

EXIT_OK = 0
EXIT_ISSUES = 1
EXIT_ERROR = 2
EXIT_UNAVAILABLE = 3

# Analyzers whose findings are silent-failure defects: the harness loads
# something other than what the author meant, and nothing else in this
# repository checks for it. These, at any severity, are what --check budgets.
#
# `reference-broken` is deliberately absent despite being the highest-volume
# error the scan produces. tests/test_docs_links.py already owns broken relative
# links, knows about the pack/mirror duality, and is authoritative; this
# analyzer additionally cannot tell a dead link from a path merely written about
# in prose. Budgeting on it would drown the gate in false positives.
#
# Severity is not part of the filter: `frontmatter-parse-error` is only a `warn`
# upstream, but a skill whose frontmatter will not parse silently stops existing
# for any strict consumer, which is exactly the failure this gate is for.
GATE_ANALYZERS = ("name-collision", "frontmatter-parse-error")


class SkillMapUnavailable(RuntimeError):
    """No usable `sm` CLI on this machine."""


def _sm_command() -> list[str]:
    """Resolve the CLI, preferring an installed binary over a network fetch."""
    override = os.environ.get("SKILL_MAP_BIN")
    if override:
        if not Path(override).is_file():
            raise SkillMapUnavailable(f"SKILL_MAP_BIN={override} is not a file")
        return [override]
    local = shutil.which("sm")
    if local:
        return [local]
    npx = shutil.which("npx")
    if npx:
        return [npx, "-y", f"@skill-map/cli@{PINNED_VERSION}"]
    raise SkillMapUnavailable(
        "no `sm` on PATH and no `npx` to fetch it; "
        "install with `npm i -g @skill-map/cli` or set SKILL_MAP_BIN"
    )


def _sm_env() -> dict[str, str]:
    """Environment that keeps the scan quiet, offline-ish, and reproducible."""
    env = dict(os.environ)
    env.update(
        SKILL_MAP_TELEMETRY="0",   # no analytics egress from a CI run
        SM_NO_UPDATE_CHECK="1",    # no version ping on every invocation
        NO_COLOR="1",              # ANSI codes would corrupt --json consumers
    )
    return env


def _run_sm(
    verb: str,
    *args: str,
    cwd: Path,
    timeout: int = 600,
    stdout_path: Path | None = None,
) -> subprocess.CompletedProcess:
    """Invoke one deterministic `sm` verb. Anything else is a programming error.

    The guard is a hard failure rather than a warning: the point of this module
    is that reading it tells you no LLM can be involved, and a guard that can be
    talked past would not support that claim.

    `stdout_path` exists because the CLI is a Node program, and Node's stdout is
    asynchronous on a pipe: a process that exits before the buffer drains loses
    everything past the OS pipe capacity (64 KiB here). A full ScanResult for
    this repository is several hundred KiB, so capturing it through a pipe
    truncates it mid-token. Writing to a real file makes the descriptor
    synchronous and the output whole.
    """
    if verb in PROBABILISTIC_VERBS:
        raise ValueError(
            f"`sm {verb}` reaches skill-map's probabilistic layer; this runner is "
            "deterministic-only by design"
        )
    if verb not in DETERMINISTIC_VERBS:
        raise ValueError(f"`sm {verb}` is not on the deterministic allowlist")
    argv = [*_sm_command(), verb, *args]
    if stdout_path is None:
        return subprocess.run(
            argv, cwd=str(cwd), env=_sm_env(),
            capture_output=True, text=True, timeout=timeout,
        )
    with stdout_path.open("wb") as sink:
        proc = subprocess.run(
            argv, cwd=str(cwd), env=_sm_env(),
            stdout=sink, stderr=subprocess.PIPE, timeout=timeout,
        )
    return subprocess.CompletedProcess(
        proc.args, proc.returncode, "", (proc.stderr or b"").decode("utf-8", "replace")
    )


def scan(root: Path, timeout: int = 600) -> dict:
    """Return skill-map's ScanResult for `root` as a dict.

    `sm scan` exits non-zero when it *finds* content issues, which is the normal
    case for any real repository — so the exit code is not an error signal here.
    Only unparseable stdout means the scan genuinely failed.
    """
    root = root.resolve()
    # `sm scan` needs a provisioned .skill-map/ project. Bootstrapping it is
    # idempotent, and its own exit code is ignored for the same reason as above.
    if not (root / ".skill-map").is_dir():
        try:
            _run_sm("init", "--json", cwd=root, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise SkillMapUnavailable(f"`sm init` timed out after {timeout}s") from exc

    with tempfile.TemporaryDirectory() as tmp:
        sink = Path(tmp) / "scan.json"
        try:
            proc = _run_sm("scan", "--json", cwd=root, timeout=timeout, stdout_path=sink)
        except subprocess.TimeoutExpired as exc:
            raise SkillMapUnavailable(f"`sm scan` timed out after {timeout}s") from exc
        stdout = sink.read_text(encoding="utf-8", errors="replace").strip()

    if not stdout:
        raise SkillMapUnavailable(
            f"`sm scan --json` produced no output (exit {proc.returncode}): "
            f"{proc.stderr.strip()[:300]}"
        )
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise SkillMapUnavailable(f"`sm scan --json` output was not JSON: {exc}") from exc


def summarize(result: dict) -> dict:
    """Collapse a ScanResult into the counts a gate and a diagram both need."""
    issues = result.get("issues") or []
    nodes = result.get("nodes") or []

    by_severity: collections.Counter = collections.Counter()
    by_analyzer: collections.Counter = collections.Counter()
    for issue in issues:
        severity = issue.get("severity", "info")
        analyzer = issue.get("analyzerId", "unknown")
        by_severity[severity] += 1
        by_analyzer[(severity, analyzer)] += 1

    kinds = collections.Counter(node.get("kind", "unknown") for node in nodes)
    gate_findings = sum(
        count for (_, analyzer), count in by_analyzer.items()
        if analyzer in GATE_ANALYZERS
    )
    return {
        "nodes": len(nodes),
        "links": len(result.get("links") or []),
        "issues": len(issues),
        "errors": by_severity.get("error", 0),
        "warnings": by_severity.get("warn", 0),
        "gate_findings": gate_findings,
        "kinds": dict(sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_analyzer": {
            f"{severity}:{analyzer}": count
            for (severity, analyzer), count in sorted(
                by_analyzer.items(), key=lambda kv: (-kv[1], kv[0])
            )
        },
        "duration_ms": (result.get("stats") or {}).get("durationMs"),
    }


def collisions(result: dict, limit: int = 6) -> list[str]:
    """Name-collision messages — two harness entries answering to one name."""
    out = []
    for issue in result.get("issues") or []:
        if issue.get("analyzerId") != "name-collision":
            continue
        nodes = issue.get("nodeIds") or []
        out.append(", ".join(nodes) if nodes else issue.get("message", "").split("\n")[0])
        if len(out) >= limit:
            break
    return out


def render_summary(summary: dict, collision_list: list[str]) -> str:
    lines = [
        f"skill-map: {summary['nodes']} nodes, {summary['links']} links, "
        f"{summary['issues']} issues "
        f"({summary['errors']} error / {summary['warnings']} warn)",
        "  kinds: " + ", ".join(f"{k}={v}" for k, v in summary["kinds"].items()),
    ]
    if summary["by_analyzer"]:
        lines.append("  analyzers:")
        for key, count in list(summary["by_analyzer"].items())[:10]:
            lines.append(f"    {count:4}  {key}")
    for collision in collision_list:
        lines.append(f"  collision: {collision}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--root", type=Path, default=Path.cwd(), help="project root to scan")
    ap.add_argument("--json", type=Path, help="write the raw ScanResult here")
    ap.add_argument("--summary-json", type=Path, help="write the collapsed summary here")
    ap.add_argument("--summary", action="store_true", help="print a human summary")
    ap.add_argument("--check", action="store_true", help="exit 1 when over threshold")
    ap.add_argument(
        "--max-errors",
        type=int,
        default=None,
        help=(
            "budget of GATE_ANALYZERS findings for --check "
            "(name-collision, frontmatter-parse-error; default: report only)"
        ),
    )
    ap.add_argument("--timeout", type=int, default=600, help="per-verb timeout in seconds")
    args = ap.parse_args(argv)

    try:
        result = scan(args.root, timeout=args.timeout)
    except SkillMapUnavailable as exc:
        print(f"skill-map unavailable: {exc}", file=sys.stderr)
        return EXIT_UNAVAILABLE
    except ValueError as exc:  # allowlist guard tripped — a code defect
        print(f"skill-map runner refused a verb: {exc}", file=sys.stderr)
        return EXIT_ERROR

    summary = summarize(result)
    collision_list = collisions(result)

    if args.json:
        args.json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.summary_json:
        payload = dict(summary, collisions=collision_list)
        args.summary_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if args.summary or not (args.json or args.summary_json):
        print(render_summary(summary, collision_list))

    if args.check and args.max_errors is not None:
        if summary["gate_findings"] > args.max_errors:
            print(
                f"skill-map: {summary['gate_findings']} finding(s) across "
                f"{', '.join(GATE_ANALYZERS)} exceeds budget of {args.max_errors}",
                file=sys.stderr,
            )
            return EXIT_ISSUES
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
