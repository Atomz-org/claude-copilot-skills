#!/usr/bin/env python3
"""Render a PR's impact subgraph and merge-gate results as a sticky comment.

Used by .github/workflows/pr-decision-diagram.yml. The document contains:

- a Mermaid flowchart of the PR's **impact subgraph** — the nodes in
  `graphify-out/graph.json` that this PR's diff actually touches, plus one hop
  of dependents and dependencies. Its shape is derived from the diff, so it
  differs per PR. `scripts/pr_impact_graph.py` does the graph work;
- a colour legend for that flowchart, naming only the classes it drew;
- a per-file table of touched symbols;
- the merge-gate results (branch naming, Conventional Commits, activation
  drift, portability, TOON build, tests) as a table with a verdict;
- a sticky-comment marker so the workflow updates one comment per PR.

This replaced an earlier diagram that drew the same fixed gate chain on every
PR — identical by construction, and therefore worthless as a diagram. The
gates now render as a table, and the diagram carries PR-specific structure.

A second section used to project the same changed paths onto the six-layer
stack from `public/code-skills-architecture.html`. It is removed, by the rule
above applied honestly: the stack is fixed, only the highlighting varied, and
on most PRs it highlighted the same two layers — a diagram that restates the
Files-changed tab in fewer words. It also cost a classification rule per naming
convention in this repository, which is upkeep for a section nobody read. The
page still documents the layer stack; nothing now claims to project it.

GitHub renders ```mermaid fences natively in PR comments and in
$GITHUB_STEP_SUMMARY, so the same document serves both. It also scales the
rendered SVG down to the container width, which makes the widest rank — not
any node limit — the thing that decides whether a diagram is readable at all.
The changed set is therefore capped, grouped by area once a PR is large, and
labelled with middle-clipped paths; the table below the diagram stays complete.

Security note: PR titles and branch names are attacker-controlled on fork
PRs. They reach this script via argv (passed from env in the workflow, never
shell-interpolated) and every label goes through _escape() before it lands in
Mermaid or markdown. Node labels come from graph.json, which is built from
the PR's own tree, so they are escaped on the same path.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pr_impact_graph import (  # noqa: E402
    file_impact,
    is_file_node,
    load_graph,
    parse_diff,
    rank_files,
    rank_pairs,
    seed_nodes,
)

MARKER = "<!-- pr-decision-diagram -->"

_STATUS_CLASS = {"pass": "pass", "fail": "fail", "skip": "skip"}
_STATUS_ICON = {"pass": "✅", "fail": "❌", "skip": "⏭️"}
_MAX_LABEL = 60
_DEFAULT_MAX_NEIGHBOURS = 10

# GitHub scales a Mermaid diagram down to the width of the comment container,
# so the binding constraint is the widest rank, not any hard node limit. These
# three numbers keep a large PR legible; the per-file table rendered directly
# below the diagram is what carries the complete list, so nothing capped here
# is lost — it only stops the diagram from duplicating the table badly.
_MAX_NODE_LABEL = 34
_MAX_CHANGED_NODES = 8
_GROUP_CHANGED_ABOVE = 12

# Paths whose contents are the AI harness rather than application code. A PR
# touching one of these gets the nested skill-map subgraph; a PR that only
# changes Python or CI does not, because the harness map would be identical on
# every such PR and a diagram that never varies carries no information.
_HARNESS_PREFIXES = (".claude/", "skill-packs/")

# The kinds that are actually dispatchable harness entry points. `markdown`
# is deliberately excluded: every doc file is a node, and counting them here
# would swamp the three numbers a reviewer is looking for.
_ENTRY_KINDS = ("skill", "command", "agent")

# Drawn in the harness subgraph's findings box, most-serious first. The first
# two are `GATE_ANALYZERS` in scripts/skill_map_scan.py — the silent-failure
# defects the gate budgets. `reference-broken` is shown but not budgeted; see
# that module for why. Severity is not filtered on: frontmatter-parse-error is
# only a `warn` upstream and still means a skill will not load.
_SHOWN_ANALYZERS = ("name-collision", "frontmatter-parse-error", "reference-broken")


def _escape(text: str) -> str:
    """Neutralize characters that break Mermaid labels or markdown tables."""
    out = (
        text.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "&#124;")
        .replace("`", "'")
        .replace("\n", " ")
    )
    return out


def _clip(text: str, limit: int = _MAX_LABEL) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _clip_path(text: str, limit: int = _MAX_NODE_LABEL) -> str:
    """Clip the middle of a path, keeping the first segment and the basename.

    Both ends carry identity and the middle rarely does. Clipping the tail
    rendered three different files under
    `skill-packs/skill-map/.claude/skills/harness-mapping/references/` as boxes
    with byte-identical labels. Clipping only the head fixes that but loses the
    root, which in this repository is exactly the pack-versus-mirror
    distinction — `skill-packs/…/commands/review.md` and
    `.claude/…/commands/review.md` are different files and must not read alike.

    Whole segments are dropped, never partial ones, so the result still reads
    as a path. The basename is always kept, even when it alone exceeds the
    budget: a box that cannot be identified is worse than a wide one.
    """
    if len(text) <= limit:
        return text
    segments = text.split("/")
    if len(segments) == 1:
        return text[: limit - 1] + "…"
    head, rest = segments[0], segments[1:]
    kept: list[str] = []
    for segment in reversed(rest):
        candidate = [segment] + kept
        if kept and len(head) + 3 + len("/".join(candidate)) > limit:
            break
        kept = candidate
    return f"{head}/…/" + "/".join(kept)


def _area(path: str) -> str:
    """The top-level directory a changed file belongs to."""
    head, sep, _ = path.partition("/")
    return head + "/" if sep else "(repo root)"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _legend(impact: dict, harness: bool) -> str:
    """A key for the classDef colours, listing only the ones actually drawn."""
    parts = ["🔵 changed"]
    if impact.get("dependents"):
        parts.append("🟣 dependents (blast radius)")
    if impact.get("dependencies"):
        parts.append("⚪ dependencies")
    if harness:
        parts += ["🟢 harness entry points", "🟠 structural findings"]
    return " · ".join(parts)


def parse_records(path: Path) -> list[dict]:
    """Parse `gate|status|detail` lines; unknown statuses become `skip`."""
    records = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split("|", 2)
        gate = parts[0].strip()
        status = parts[1].strip().lower() if len(parts) > 1 else "skip"
        detail = parts[2].strip() if len(parts) > 2 else ""
        if status not in _STATUS_CLASS:
            status = "skip"
        records.append({"gate": gate, "status": status, "detail": detail})
    return records


def _relation_label(relations: dict[str, int]) -> str:
    """`imports ×2, calls` — the relations collapsed into one file-level edge."""
    parts = []
    for relation, count in sorted(relations.items(), key=lambda kv: (-kv[1], kv[0])):
        parts.append(f"{relation} ×{count}" if count > 1 else relation)
    return _escape(", ".join(parts[:3]))


def build_impact(
    graph_path: Path | None,
    changed_files: list[str],
    diff_text: str,
    max_neighbours: int = _DEFAULT_MAX_NEIGHBOURS,
) -> dict:
    """Resolve the PR's diff against the graph into a renderable structure."""
    impact: dict = {
        "available": False,
        "reason": "",
        "changed": [],
        "dependents": [],
        "dependencies": [],
        "internal": [],
        "dropped": 0,
        "unextracted": [],
        "missing": [],
    }
    if not changed_files:
        impact["reason"] = "no changed files resolved for this PR"
        return impact
    index = load_graph(graph_path) if graph_path else None
    if index is None:
        impact["reason"] = "graphify-out/graph.json was not built for this run"
        return impact

    hunks = parse_diff(diff_text) if diff_text else {}
    seeds, missing, unextracted = seed_nodes(index, changed_files, hunks)
    impact["missing"] = missing
    impact["unextracted"] = unextracted
    if not seeds:
        impact["reason"] = "none of the changed files are represented in the code graph"
        return impact

    # The file node stands for the module scope rather than a symbol, so it
    # seeds the traversal but is not listed as one of the touched symbols.
    per_file: dict[str, list[str]] = {}
    for node in seeds:
        per_file.setdefault(node["source_file"], [])
        if not is_file_node(node):
            per_file[node["source_file"]].append(node.get("label") or node["id"])
    dependents, dependencies, internal = file_impact(index, seeds, set(changed_files))
    kept_dependents, dropped_in = rank_files(dependents, max_neighbours)
    kept_dependencies, dropped_out = rank_files(dependencies, max_neighbours)
    kept_internal, dropped_internal = rank_pairs(internal, max_neighbours * 2)

    impact.update(
        available=True,
        changed=sorted(per_file.items(), key=lambda kv: (-len(kv[1]), kv[0])),
        dependents=kept_dependents,
        dependencies=kept_dependencies,
        internal=kept_internal,
        dropped=dropped_in + dropped_out + dropped_internal,
    )
    return impact


def load_skill_map(path: Path | None) -> dict | None:
    """Read the summary written by `skill_map_scan.py --summary-json`.

    Absent or unreadable means the scan did not run on this PR (no Node on the
    runner, say). That is a `skip`, not a failure, so every caller treats None
    as "draw no harness subgraph" rather than raising.
    """
    if not path or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def harness_files(changed_files: list[str]) -> list[str]:
    """The changed paths that are harness assets rather than application code."""
    return [p for p in changed_files if p.startswith(_HARNESS_PREFIXES)]


def render_harness(summary: dict, touched: list[str], indent: str = "    ") -> list[str]:
    """A nested subgraph describing the harness this PR just edited.

    Nested rather than free-standing because it is a property *of* the change:
    the outer box is the harness, and the two inner boxes are what it contains
    and what is structurally wrong with it. Only drawn when the PR actually
    touches `.claude/` or `skill-packs/`.
    """
    kinds = summary.get("kinds") or {}
    entries = [(k, kinds[k]) for k in _ENTRY_KINDS if kinds.get(k)]
    # by_analyzer keys are "<severity>:<analyzerId>"; collapse severities so one
    # analyzer is one box, and order by _SHOWN_ANALYZERS rather than by count so
    # a collision never sorts below 50 broken links.
    by_analyzer = summary.get("by_analyzer") or {}
    totals: dict[str, int] = {}
    for key, count in by_analyzer.items():
        analyzer = key.split(":", 1)[1] if ":" in key else key
        if analyzer in _SHOWN_ANALYZERS:
            totals[analyzer] = totals.get(analyzer, 0) + count
    structural = [(a, totals[a]) for a in _SHOWN_ANALYZERS if a in totals]

    n = len(touched)
    title = f"Harness map — skill-map ({n} file{'s' if n != 1 else ''} touched)"
    lines = [f'{indent}subgraph HARNESS["{_escape(title)}"]', f"{indent}    direction LR"]

    if entries:
        lines.append(f'{indent}    subgraph HKINDS["Entry points"]')
        for i, (kind, count) in enumerate(entries):
            lines.append(f'{indent}        HK{i}["{_escape(kind)}<br/>{count}"]:::harness')
        lines.append(f"{indent}    end")

    if structural:
        lines.append(f'{indent}    subgraph HISSUES["Structural findings"]')
        for i, (analyzer, count) in enumerate(structural):
            lines.append(
                f'{indent}        HI{i}["{_escape(analyzer)}<br/>{count}"]:::finding'
            )
        lines.append(f"{indent}    end")
    else:
        lines.append(f'{indent}    HI0["No structural findings"]:::harness')

    lines.append(f"{indent}end")
    return lines


def render_mermaid(
    impact: dict,
    pr_number: str,
    head_ref: str,
    skill_map: dict | None = None,
    changed_files: list[str] | None = None,
) -> list[str]:
    """The impact subgraph: changed nodes boxed, one hop of neighbours around.

    When the PR touches harness files and a skill-map summary is available, a
    nested `HARNESS` subgraph is drawn alongside and linked from the changed set.
    """
    lines = [
        "```mermaid",
        "flowchart LR",
        "    classDef changed fill:#0969da,color:#ffffff,stroke:#0550ae",
        "    classDef dependent fill:#bf3989,color:#ffffff,stroke:#99286e",
        "    classDef dependency fill:#6e7781,color:#ffffff,stroke:#57606a",
        "    classDef empty fill:#6e7781,color:#ffffff,stroke:#57606a",
        "    classDef harness fill:#1f883d,color:#ffffff,stroke:#1a7f37",
        "    classDef finding fill:#9a6700,color:#ffffff,stroke:#7d4e00",
    ]
    hit = harness_files(changed_files or [])
    harness = render_harness(skill_map, hit) if (skill_map and hit) else []
    if not impact.get("available"):
        reason = impact.get("reason") or "impact analysis not run"
        lines += [
            f'    PR["PR #{_escape(pr_number)}<br/>{_escape(_clip(head_ref))}"]:::changed',
            f'    PR --> X["No impact subgraph<br/>{_escape(_clip(reason, 70))}"]:::empty',
        ]
        # A harness-only PR often has no code-graph impact at all. The harness
        # map is the whole story there, so it is drawn even on this branch.
        if harness:
            lines += harness
            lines.append("    PR --> HARNESS")
            lines += ["```", "", f"_{_legend(impact, True)}_", ""]
            return lines
        # Two nodes and no colour distinction worth explaining — no legend.
        lines += ["```", ""]
        return lines

    changed = impact["changed"]
    # Above the threshold, one box per top-level area rather than per file: at
    # that size the per-file boxes are scaled below legibility, and five area
    # boxes answer "what does this PR touch" better than thirty file boxes do.
    grouped = len(changed) > _GROUP_CHANGED_ABOVE
    lines.append(f'    subgraph CHANGED["Changed by PR #{_escape(pr_number)}"]')
    node_of: dict[str, str] = {}
    if grouped:
        areas: dict[str, int] = {}
        for path, _symbols in changed:
            area = _area(path)
            areas[area] = areas.get(area, 0) + 1
        for i, (area, count) in enumerate(sorted(areas.items(), key=lambda kv: (-kv[1], kv[0]))):
            node_of[area] = f"C{i}"
            label = f"{_escape(area)}<br/>{_plural(count, 'file')}"
            lines.append(f'        C{i}["{label}"]:::changed')
    else:
        for i, (path, symbols) in enumerate(changed[:_MAX_CHANGED_NODES]):
            node_of[path] = f"C{i}"
            touched = _plural(len(symbols), "symbol") if symbols else "module scope"
            label = f"{_escape(_clip_path(path))}<br/>{touched}"
            lines.append(f'        C{i}["{label}"]:::changed')
        overflow = len(changed) - _MAX_CHANGED_NODES
        if overflow > 0:
            label = f"+{_plural(overflow, 'more file')}<br/>see table below"
            lines.append(f'        CMORE["{label}"]:::changed')
    lines.append("    end")

    def _node_for(path: str) -> str | None:
        return node_of.get(_area(path)) if grouped else node_of.get(path)

    # Edges the PR draws inside itself, e.g. a new test importing a new module.
    # Grouping collapses several file pairs onto one area pair, so relations are
    # merged; a pair that collapses onto itself is a self-loop and is dropped.
    internal: dict[tuple[str, str], dict[str, int]] = {}
    for (src, tgt), relations in impact.get("internal", []):
        a, b = _node_for(src), _node_for(tgt)
        if a is None or b is None or a == b:
            continue
        bucket = internal.setdefault((a, b), {})
        for relation, count in relations.items():
            bucket[relation] = bucket.get(relation, 0) + count
    for (src, tgt), relations in internal.items():
        lines.append(f"    {src} -->|{_relation_label(relations)}| {tgt}")

    # Dependents point at the changed code — this is the blast radius.
    for i, (path, relations) in enumerate(impact["dependents"]):
        lines.append(f'    D{i}["{_escape(_clip_path(path))}"]:::dependent')
        lines.append(f"    D{i} -->|{_relation_label(relations)}| CHANGED")
    # Dependencies are what the changed code now relies on.
    for i, (path, relations) in enumerate(impact["dependencies"]):
        lines.append(f'    U{i}["{_escape(_clip_path(path))}"]:::dependency')
        lines.append(f"    CHANGED -->|{_relation_label(relations)}| U{i}")
    if not impact["dependents"] and not impact["dependencies"] and not internal:
        lines.append('    CHANGED --> N0["No cross-file dependents or dependencies"]:::empty')
    if harness:
        lines += harness
        lines.append(f'    CHANGED -.->|"edits {len(hit)} harness file(s)"| HARNESS')
    lines += ["```", "", f"_{_legend(impact, bool(harness))}_", ""]
    return lines


def render(
    records: list[dict],
    pr_number: str,
    pr_title: str,
    head_ref: str,
    impact: dict | None = None,
    skill_map: dict | None = None,
    changed_files: list[str] | None = None,
) -> str:
    impact = impact or {"available": False, "reason": "impact analysis not run"}
    verdict_pass = all(r["status"] != "fail" for r in records)
    lines: list[str] = [
        MARKER,
        "",
        f"## PR #{_escape(pr_number)} — {_escape(_clip(pr_title, 100))}",
        "",
        "### Impact graph",
        "",
    ]
    lines += render_mermaid(impact, pr_number, head_ref, skill_map, changed_files)

    if impact.get("available"):
        # Every changed file, and every symbol in it. The diagram is the
        # summary — capped, grouped, and clipped to stay legible once GitHub
        # scales it — so this table has to be the complete record, or the PR
        # has no complete record anywhere. Individual names are still clipped:
        # that bounds one pathological identifier, without dropping any.
        lines += ["| Changed file | Symbols touched |", "|---|---|"]
        for path, symbols in impact["changed"]:
            shown = ", ".join(_escape(_clip(s, 40)) for s in sorted(symbols))
            lines.append(f"| {_escape(path)} | {shown or 'module scope'} |")
        lines.append("")
        if impact.get("dropped"):
            lines.append(
                f"_{impact['dropped']} further neighbour file(s) omitted from the "
                "diagram; only the most strongly connected are drawn._"
            )
        for key, note in (
            ("unextracted", "Not extracted by graphify (no nodes exist for this file type)"),
            ("missing", "Changed but absent from the code graph"),
        ):
            paths = impact.get(key) or []
            if paths:
                shown = ", ".join(f"`{_escape(p)}`" for p in sorted(paths)[:8])
                extra = f" (+{len(paths) - 8} more)" if len(paths) > 8 else ""
                lines.append(f"_{note}: {shown}{extra}._")
        lines.append("")

    lines += ["### Merge gates", "", "| Gate | Result | Detail |", "|---|---|---|"]
    for r in records:
        lines.append(
            f'| {_escape(r["gate"])} | {_STATUS_ICON[r["status"]]} {r["status"]} '
            f'| {_escape(r["detail"]) or "—"} |'
        )
    lines += [
        "",
        f"**Verdict: {'mergeable by repository standards' if verdict_pass else 'BLOCKED'}**",
        "",
        "_Generated by `.github/workflows/pr-decision-diagram.yml` on every push "
        "to this PR; this comment is updated in place._",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--input", type=Path, required=True, help="gate|status|detail lines")
    ap.add_argument("--pr-number", default="", help="PR number (from env, untrusted-safe)")
    ap.add_argument("--pr-title", default="", help="PR title (from env, escaped here)")
    ap.add_argument("--head-ref", default="", help="head branch name (from env, escaped here)")
    ap.add_argument("--graph", type=Path, help="graphify graph.json for the impact subgraph")
    ap.add_argument("--changed", type=Path, help="file listing the PR's changed paths")
    ap.add_argument("--diff", type=Path, help="`git diff -U0 <base> HEAD` output")
    ap.add_argument(
        "--max-neighbours",
        type=int,
        default=_DEFAULT_MAX_NEIGHBOURS,
        help="max dependent/dependency files drawn per direction",
    )
    ap.add_argument(
        "--skill-map",
        type=Path,
        help="skill_map_scan.py --summary-json output, for the nested harness subgraph",
    )
    ap.add_argument("--out", type=Path, required=True, help="markdown output path")
    args = ap.parse_args(argv)

    records = parse_records(args.input)
    if not records:
        print("pr_decision_diagram: no gate records found", file=sys.stderr)
        return 1

    changed_files = []
    if args.changed and args.changed.is_file():
        changed_files = [
            line.strip()
            for line in args.changed.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    diff_text = args.diff.read_text(encoding="utf-8") if args.diff and args.diff.is_file() else ""
    impact = build_impact(args.graph, changed_files, diff_text, args.max_neighbours)
    skill_map = load_skill_map(args.skill_map)

    args.out.write_text(
        render(
            records, args.pr_number, args.pr_title, args.head_ref,
            impact, skill_map, changed_files,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
