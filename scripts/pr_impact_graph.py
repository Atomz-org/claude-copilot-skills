#!/usr/bin/env python3
"""Build a PR-specific impact subgraph from `graphify-out/graph.json`.

Used by scripts/pr_decision_diagram.py, which renders the result as the
Mermaid diagram in the PR comment. The previous diagram drew the same fixed
gate chain on every PR; this module makes the diagram a function of the PR's
actual content instead:

1. `parse_diff()` reads `git diff -U0 <base> HEAD` and records the changed
   line ranges per file.
2. `seed_nodes()` maps those ranges onto graph nodes. A node's span runs from
   its own line to the line before the next node in the same file, so an edit
   inside a function body still selects that function rather than nothing.
   Files whose changed nodes cannot be resolved fall back to every node in
   the file; files graphify does not extract at all (`.yml`, `.yaml`) are
   reported rather than silently dropped.
3. `file_impact()` walks the graph's cross-file edges one hop out from the
   seeds — inbound edges are dependents (what this PR can break), outbound
   edges are dependencies (what this PR now relies on).

Only cross-file edges become diagram edges: intra-file `contains` edges are
the 3:1 majority of the graph and say nothing about impact.

The graph is built in CI by `graphify update . --no-cluster`, which is
AST-only and needs no API key. That graph carries no `community` fields, so
nothing here may depend on them.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

# graphify does not extract these, so a changed file with one of these
# suffixes has no node and its absence from the diagram is expected.
UNEXTRACTED_SUFFIXES = (".yml", ".yaml", ".toml", ".cfg", ".ini", ".txt", ".lock")

# graphify emits a `rationale` node per docstring, one line below the symbol it
# documents. Kept out of the seed set: they are not symbols, they would double
# every function in the touched-symbol list, and their line would truncate the
# span of the symbol above them.
NON_SYMBOL_FILE_TYPES = ("rationale",)

# Edges that mean "A depends on B". `contains` is the file->symbol
# containment edge and is deliberately excluded.
DEPENDENCY_RELATIONS = (
    "imports",
    "imports_from",
    "calls",
    "indirect_call",
    "references",
    "uses",
    "extends",
    "inherits",
    "implements",
    "method",
    "defines",
)

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def parse_diff(text: str) -> dict[str, list[tuple[int, int]]]:
    """Map file path -> changed line ranges on the new side of a -U0 diff.

    A pure deletion hunk (`+c,0`) has no new-side lines; it is recorded as the
    single line it deletes against, so the surrounding symbol is still picked
    up as changed.
    """
    hunks: dict[str, list[tuple[int, int]]] = defaultdict(list)
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("+++ "):
            target = line[4:].strip()
            current = None if target == "/dev/null" else target[2:] if target.startswith("b/") else target
            continue
        if current is None or not line.startswith("@@"):
            continue
        match = _HUNK_RE.match(line)
        if not match:
            continue
        start = int(match.group(1))
        count = int(match.group(2)) if match.group(2) is not None else 1
        hunks[current].append((start, start + count - 1) if count else (start, start))
    return dict(hunks)


class GraphIndex:
    """Nodes and edges of graph.json, indexed for file- and line-lookups."""

    def __init__(self, graph: dict):
        self.nodes: dict[str, dict] = {}
        self.by_file: dict[str, list[dict]] = defaultdict(list)
        for node in graph.get("nodes", []):
            node_id = node.get("id")
            if not node_id:
                continue
            self.nodes[node_id] = node
            source = node.get("source_file")
            # by_file drives seed selection, so docstring nodes are excluded
            # here while staying in self.nodes for edge endpoint resolution.
            if source and node.get("file_type") not in NON_SYMBOL_FILE_TYPES:
                self.by_file[source].append(node)
        for nodes in self.by_file.values():
            nodes.sort(key=lambda n: (_line_of(n) or 0, n.get("label") or ""))
        self.edges = [
            edge
            for edge in graph.get("links", [])
            if edge.get("source") in self.nodes and edge.get("target") in self.nodes
        ]

    def file_of(self, node_id: str) -> str | None:
        node = self.nodes.get(node_id)
        return node.get("source_file") if node else None


def _line_of(node: dict) -> int | None:
    """`source_location` is `L<int>`, empty, or absent."""
    raw = str(node.get("source_location") or "")
    return int(raw[1:]) if raw.startswith("L") and raw[1:].isdigit() else None


def is_file_node(node: dict) -> bool:
    """The module-level node graphify emits per file, labelled with its name.

    `metadata.kind == "file"` is only set for a handful of languages, so the
    label/basename match is what actually identifies it.
    """
    source = node.get("source_file") or ""
    return bool(source) and (node.get("label") or "") == source.rsplit("/", 1)[-1]


def load_graph(path: Path) -> GraphIndex | None:
    if not path.is_file():
        return None
    try:
        return GraphIndex(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, OSError):
        return None


def _spans(nodes: list[dict]) -> list[tuple[dict, int, int]]:
    """Give each node the line span it owns: its line up to the next node's.

    Without this an edit inside a function body selects nothing, because a
    node's `source_location` is only its declaration line.
    """
    lined = [(n, _line_of(n)) for n in nodes]
    lined = [(n, ln) for n, ln in lined if ln is not None]
    spans = []
    for i, (node, line) in enumerate(lined):
        end = lined[i + 1][1] - 1 if i + 1 < len(lined) else 10**9
        spans.append((node, line, max(line, end)))
    return spans


def seed_nodes(
    index: GraphIndex, changed_files: list[str], hunks: dict[str, list[tuple[int, int]]]
) -> tuple[list[dict], list[str], list[str]]:
    """Select the graph nodes this PR actually touches.

    Returns (seeds, files_with_no_nodes, files_graphify_does_not_extract).
    """
    seeds: list[dict] = []
    missing: list[str] = []
    unextracted: list[str] = []
    for path in changed_files:
        nodes = index.by_file.get(path)
        if not nodes:
            (unextracted if path.endswith(UNEXTRACTED_SUFFIXES) else missing).append(path)
            continue
        ranges = hunks.get(path)
        if not ranges:
            seeds.extend(nodes)
            continue
        hit = [
            node
            for node, start, end in _spans(nodes)
            if any(start <= h_end and h_start <= end for h_start, h_end in ranges)
        ]
        # The file node owns the module scope — imports, constants, the header.
        # A change there reaches every symbol in the file, and seeding only the
        # file node would hide the dependents of those symbols entirely.
        if any(is_file_node(node) for node in hit):
            hit = nodes
        # A file with no line-resolvable nodes still changed; keep all of them
        # rather than reporting the file as unaffected.
        seeds.extend(hit or nodes)
    return seeds, missing, unextracted


def file_impact(
    index: GraphIndex, seeds: list[dict], changed_files: set[str]
) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], int], dict[tuple[str, str, str], int]]:
    """One hop out from the seeds over cross-file dependency edges.

    Returns (dependents, dependencies, internal). Dependents point *at* the
    changed code and are keyed by (file, relation); dependencies are what the
    changed code points at, keyed the same way. Internal edges run between two
    files that the PR itself changed and are keyed by (from, to, relation) —
    without them a self-contained PR draws a box of nodes and no edges.
    """
    seed_ids = {n["id"] for n in seeds}
    dependents: dict[tuple[str, str], int] = defaultdict(int)
    dependencies: dict[tuple[str, str], int] = defaultdict(int)
    internal: dict[tuple[str, str, str], int] = defaultdict(int)
    for edge in index.edges:
        relation = edge.get("relation")
        if relation not in DEPENDENCY_RELATIONS:
            continue
        src, tgt = edge["source"], edge["target"]
        src_file, tgt_file = index.file_of(src), index.file_of(tgt)
        if not src_file or not tgt_file or src_file == tgt_file:
            continue
        if src not in seed_ids and tgt not in seed_ids:
            continue
        if src_file in changed_files and tgt_file in changed_files:
            internal[(src_file, tgt_file, relation)] += 1
        elif tgt in seed_ids:
            dependents[(src_file, relation)] += 1
        elif src in seed_ids:
            dependencies[(tgt_file, relation)] += 1
    return dict(dependents), dict(dependencies), dict(internal)


def rank_files(edges: dict[tuple[str, str], int], limit: int) -> tuple[list[tuple[str, dict[str, int]]], int]:
    """Collapse (file, relation) counts to per-file entries, strongest first.

    Returns (kept, dropped_count) so the caller can state what was cut instead
    of silently truncating.
    """
    per_file: dict[str, dict[str, int]] = defaultdict(dict)
    for (path, relation), count in edges.items():
        per_file[path][relation] = count
    ordered = sorted(per_file.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))
    return ordered[:limit], max(0, len(ordered) - limit)


def rank_pairs(
    edges: dict[tuple[str, str, str], int], limit: int
) -> tuple[list[tuple[tuple[str, str], dict[str, int]]], int]:
    """Same collapse as rank_files(), for edges keyed by (from, to, relation)."""
    per_pair: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    for (src, tgt, relation), count in edges.items():
        per_pair[(src, tgt)][relation] = count
    ordered = sorted(per_pair.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))
    return ordered[:limit], max(0, len(ordered) - limit)
