#!/usr/bin/env python3
"""Name every graphify community after what it actually contains.

`graphify` clusters the graph and hands back `Community 0 … Community N`. The skill's
Step 5 asks an agent to name them, which works for the dozen largest and leaves the
rest as placeholders — on this repository, 1785 communities of which 1767 read
`Community <n>`. The aggregated `graph.html` view draws *one node per community*, so
those placeholders are not a cosmetic detail: they are the entire picture.

**Names are derived, never keyed by community id.** Community ids are an output of
clustering — they are not stable across rebuilds, so a hand-authored `{id: name}` map is
correct exactly until the next `graphify update` and silently wrong afterwards, with no
error to notice. Deriving the name from the members means a rebuild renames correctly on
its own.

The derivation, in order:

1. **Dominant `source_file`** (a plurality of members, at least `MIN_SHARE`). In this
   repository one file is one concern — `connector_alignment_check.py` is the connector
   convention checks, `test_dbt_column_lineage.py` is the column-lineage tests — so the
   file that most members came from names the group better than any single symbol in it.
2. **Dominant directory prefix**, for a community spread across many files. A
   111-member community covering every model under `packages/fortnox/models/` has no
   majority file — its biggest is a `sources.yml` at 15% — so file-dominance alone
   calls the Fortnox connector "Auto Config", after a macro invoked everywhere.
3. **Highest-degree member**, when neither holds. The structural hub is what a reader
   would call it.
4. **The node itself**, for the 1432 singletons. Measured on this graph: every one of
   them is degree 0, and 928 carry no `source_file` either — they are AST references to
   imported symbols (`TokenStream`, `Self`, `Default`) that clustering could not place.
   "Self" is a truer name for that community than "Community 464"; `borrow_context`
   would name them after a neighbouring file, and never fires here because they have no
   neighbours.

Path shapes are read as this repository's own layout (skills, commands, agents, rules,
dbt models, macros, Wren MDL, use-cases), because a name like "Fortnox Bi Dim Company"
is worth more than "dbt model" and costs one rule to get.

Collisions are qualified, not silently merged — two communities dominated by the same
file are told apart by the directory that differs, and the largest keeps the bare name.
The one exception is isolated singletons: `Self` split across eleven one-node
communities is one symbol, not eleven, so they are allowed to share the name. A
qualifier that invents a distinction is worse than a repeated name.

    python3 scripts/graphify_community_names.py --dry-run     # preview, writes nothing
    python3 scripts/graphify_community_names.py --apply       # graph.json + labels file
    python3 scripts/graphify_community_names.py --apply --min-size 3
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
GRAPH = REPO / "graphify-out" / "graph.json"
LABELS = REPO / "graphify-out" / ".graphify_labels.json"

# A file has to account for at least this share of a community's members before it is
# allowed to name it. Below that the community genuinely spans concerns and the
# structural hub is the honest answer.
MIN_SHARE = 0.34

# Directory-prefix threshold, deliberately looser than MIN_SHARE. A domain cluster is
# spread thin across many files by construction — no single one will hit 34% — but its
# members still live under one package or one skill, which is the thing to name.
DIR_SHARE = 0.30

# Directories that hold everything and therefore identify nothing. A community named
# after one of these is no better labelled than "Community 41".
CONTAINER_NAMES = {
    "Claude", "Skill Packs", "Dbt Skills", "Github Skills", "Wren Skills", "Skill Map",
    "Use Cases", "Dbt Project", "Packages", "Src", "Rust", "Public", "Artifacts",
    "Enhanza Analytics", "Example Order Revenue Mart", "Code Skills", "Ai Core",
    "Graphify Out", "External", "Repo", "Root", "Templates", "Knowledge",
}

# Symbols that are never what a community is *about* — language builtins, typing
# imports, and stdlib names that the AST pass attaches to every module that mentions
# them. Used only when picking a hub; never suppresses a singleton's own name.
HUB_STOPWORDS = {
    "any", "dict", "list", "optional", "tuple", "set", "path", "self", "default",
    "none", "true", "false", "str", "int", "bool", "float", "sequence", "iterable",
    "mapping", "callable", "union", "type", "object", "exception", "runtimeerror",
    "valueerror", "keyerror", "systemexit", "namespace", "counter", "defaultdict",
}

_WORD_FIXES = {
    "dbt": "dbt", "sql": "SQL", "yml": "YAML", "yaml": "YAML", "json": "JSON",
    "toon": "TOON", "api": "API", "cli": "CLI", "ci": "CI", "erp": "ERP",
    "bi": "BI", "mdl": "MDL", "ui": "UI", "pr": "PR", "rtk": "RTK", "ast": "AST",
    "id": "ID", "url": "URL", "http": "HTTP", "csv": "CSV", "ttl": "TTL",
    "mcp": "MCP", "crm": "CRM", "scd": "SCD", "erd": "ERD", "pii": "PII",
    "miniyaml": "Mini YAML", "genbi": "GenBI", "wrenai": "WrenAI",
    "xdist": "xdist", "conftest": "conftest", "graphify": "graphify",
}


def _display(path: Path) -> str:
    """Repo-relative when it is inside the repo, absolute when it is not.

    `Path.relative_to` raises rather than falling back, so printing the result of
    `--apply --graph /tmp/...` crashed after the write had already landed.
    """
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def humanise(token: str) -> str:
    """`dbt_column_lineage` -> `Dbt Column Lineage`, with known acronyms preserved."""
    token = re.sub(r"[-_.]+", " ", token.strip())
    token = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", token)
    words = [w for w in token.split() if w]
    if not words:
        return ""
    return " ".join(_WORD_FIXES.get(w.lower(), w[:1].upper() + w[1:]) for w in words)


def _parts(source_file: str) -> List[str]:
    return [p for p in source_file.replace("\\", "/").split("/") if p]


def name_from_path(source_file: str) -> Optional[str]:
    """A functional name for the file, read as this repository's layout."""
    if not source_file:
        return None
    parts = _parts(source_file)
    if not parts:
        return None
    fname = parts[-1]
    stem = fname.rsplit(".", 1)[0]
    lower = [p.lower() for p in parts]

    # --- harness assets -------------------------------------------------------------
    if fname == "SKILL.md" and len(parts) >= 2:
        return f"{humanise(parts[-2])} Skill"
    if "skills" in lower and len(parts) >= 2:
        i = lower.index("skills")
        if i + 1 < len(parts):
            owner = humanise(parts[i + 1])
            return f"{owner} Skill Refs" if fname != "SKILL.md" else f"{owner} Skill"
    if "commands" in lower:
        return f"/{stem} Command"
    if "agents" in lower:
        return f"{humanise(stem)} Agent"
    if "rules" in lower and fname.endswith(".md"):
        return f"{humanise(stem)} Rules"

    # --- dbt ------------------------------------------------------------------------
    if fname.endswith(".sql"):
        if "macros" in lower:
            return f"{humanise(stem)} Macro"
        if "models" in lower:
            return humanise(stem)
        if "tests" in lower:
            return f"{humanise(stem)} Test"
        return humanise(stem)
    if fname in ("sources.yml", "schema.yml", "properties.yml") and len(parts) >= 2:
        return f"{humanise(parts[-2])} {humanise(stem)}"

    # --- Wren MDL -------------------------------------------------------------------
    if "wren" in lower:
        i = lower.index("wren")
        sub = lower[i + 1] if i + 1 < len(parts) else ""
        if sub in ("models", "views") and i + 2 < len(parts):
            kind = "Wren View" if sub == "views" else "Wren Model"
            return f"{humanise(parts[i + 2])} ({kind})"
        if sub == "knowledge":
            return f"Wren Knowledge: {humanise(stem)}"
        return f"Wren {humanise(stem)}"

    # --- ontology -------------------------------------------------------------------
    if "ontology" in lower:
        return f"Ontology: {humanise(stem)}"

    # --- tests, CI, docs ------------------------------------------------------------
    if stem.startswith("test_"):
        return f"{humanise(stem[5:])} Tests"
    if "workflows" in lower:
        return f"CI: {humanise(stem)}"
    if "issues" in lower:
        return f"Issue: {humanise(stem)}"
    if lower[0] == "docs" or fname.isupper() or stem.isupper():
        return humanise(stem)

    # --- code -----------------------------------------------------------------------
    if fname.endswith(".rs"):
        return humanise(stem)
    if stem.startswith("_"):
        return humanise(stem[1:])
    return humanise(stem)


def name_from_dir(directory: str) -> Optional[str]:
    """A functional name for a directory that a community's members share.

    The rule that file-dominance cannot express: a 111-member community spanning every
    model under `packages/fortnox/models/` has no majority file — its biggest single
    file is a `sources.yml` at 15% — so file-dominance falls through to the
    highest-degree symbol and calls the Fortnox connector "Auto Config", after a macro
    that happens to be called everywhere. The directory is what the group is.
    """
    parts = _parts(directory)
    if not parts:
        return None
    lower = [p.lower() for p in parts]

    if "packages" in lower:
        i = lower.index("packages")
        if i + 1 < len(parts):
            return f"{humanise(parts[i + 1])} Package"
    if "skills" in lower:
        i = lower.index("skills")
        if i + 1 < len(parts):
            return f"{humanise(parts[i + 1])} Skill"
    if lower[-1] == "agents":
        return "Agents"
    if lower[-1] == "commands":
        return "Commands"
    if lower[-1] == "rules":
        return "Rules"
    if lower[-1] == "references" and len(parts) >= 2:
        return f"{humanise(parts[-2])} References"
    if "macros" in lower:
        i = lower.index("macros")
        tail = parts[i + 1] if i + 1 < len(parts) else None
        return f"{humanise(tail)} Macros" if tail else "dbt Macros"
    if "models" in lower:
        i = lower.index("models")
        tail = parts[i + 1] if i + 1 < len(parts) else None
        if "wren" in lower:
            return f"{humanise(tail)} (Wren Model)" if tail else "Wren Models"
        return f"{humanise(tail)} Models" if tail else "dbt Models"
    if "wren" in lower:
        i = lower.index("wren")
        tail = parts[i + 1] if i + 1 < len(parts) else None
        return f"Wren {humanise(tail)}" if tail else "Wren Project"
    if "ontology" in lower:
        return "Ontology"
    if lower[-1] in ("tests", "scripts", "docs", "seeds", "snapshots", "hooks", "workflows"):
        return humanise(parts[-1])

    # Anything that resolves no further than a container — the repo root, `.claude/`,
    # a pack root, a use-case root — is not a name. "Enhanza Analytics" describes a
    # third of the repository, so a community called that says nothing; the structural
    # hub is more informative. Deliberately returns None so `derive` falls through.
    tail = humanise(parts[-1])
    if tail in CONTAINER_NAMES or "use-cases" in lower and lower.index("use-cases") == len(parts) - 2:
        return None
    return tail or None


def dominant_dir(members: List[Dict[str, Any]], floor: float) -> Optional[str]:
    """The deepest directory prefix shared by at least `floor` of the members."""
    dirs = [_parts(str(n.get("source_file") or "")) [:-1] for n in members
            if n.get("source_file")]
    dirs = [d for d in dirs if d]
    if not dirs:
        return None
    need = max(2, int(len(members) * floor))
    best: Optional[str] = None
    for depth in range(max(len(d) for d in dirs), 0, -1):
        counts = Counter("/".join(d[:depth]) for d in dirs if len(d) >= depth)
        prefix, hits = counts.most_common(1)[0]
        if hits >= need:
            best = prefix
            break
    return best


def pick_hub(members: List[Dict[str, Any]], degree: Dict[str, int]) -> Optional[str]:
    """Highest-degree member, skipping builtins that decorate every module."""
    ranked = sorted(members, key=lambda n: -degree.get(n["id"], 0))
    for n in ranked:
        label = str(n.get("label") or "").strip()
        if label and label.lower().strip("() ") not in HUB_STOPWORDS:
            return label
    return str(ranked[0].get("label") or "").strip() if ranked else None


def clean_label(label: str) -> str:
    """A node label made presentable as a group name."""
    label = label.strip()
    if label.endswith("()"):
        label = label[:-2]
    if label.startswith("."):
        label = label[1:]
    # Prose nodes (extracted doc sentences) make terrible group names; clip them.
    if len(label) > 46:
        label = label[:43].rstrip() + "…"
    return label


# Words that carry no identity — a file extension, or the `test_` prefix that both the
# name and its candidate qualifier already agree on. Ignoring them is what makes
# "dbt Column Lineage Tests · Test dbt Column Lineage Py" resolve to the bare name.
_NOISE_TOKENS = {"test", "tests", "py", "sh", "md", "json", "yml", "yaml", "rs", "ts", "sql"}


def _redundant(candidate: str, base: str) -> bool:
    """True when a qualifier adds no information to the name it qualifies.

    Redundant in either direction: "Add ERP Fields · Add ERP Fields Macro" merely
    extends the name, and "dbt Column Lineage Tests · test_dbt_column_lineage.py"
    merely restates it.
    """
    c, b = _tokens(candidate), _tokens(base)
    return not c or c <= b or b <= c


def _pretty(label: str) -> str:
    """Humanise an identifier; leave prose alone.

    `senior-analytics-engineer` should read "Senior Analytics Engineer", but a label
    that already contains spaces came out of a document sentence and title-casing it
    produces "Github Skills (shared Foundation Pack)".
    """
    return humanise(label) if (re.search(r"[-_]", label) and " " not in label) else label


def _tokens(text: str) -> set:
    """Comparable word set, so a qualifier that restates the name can be detected."""
    return {w for w in re.split(r"[^a-z0-9]+", text.lower())
            if w and len(w) > 1 and w not in _NOISE_TOKENS}


def _qualifiers(members: List[Dict[str, Any]], degree: Dict[str, int]) -> List[str]:
    """Candidate distinguishers for two communities that derived the same name.

    Directory first: two `Fortnox Package` communities are told apart far better by
    `staging` vs `fortnox_bi` — the dbt layer they occupy — than by whichever macro
    happens to have the most edges.
    """
    out: List[str] = []
    shared = dominant_dir(members, DIR_SHARE)
    if shared:
        segs = _parts(shared)
        for seg in reversed(segs[-2:]):
            out.append(humanise(seg))
    hub = pick_hub(members, degree)
    if hub:
        out.append(clean_label(_pretty(hub)))
    return out


def borrow_context(members: List[Dict[str, Any]],
                   neighbour_files: Dict[str, Counter]) -> Optional[str]:
    """Where a community owns no file, name it by the file that reaches into it.

    1432 of this graph's communities are single AST references to an imported symbol —
    `Self`, `String`, `Option`, `Manifest` — carrying no `source_file` of their own.
    Named from the member alone they collide into `Self (7)`, `Self (8)`, which is
    accurate and useless. The module that *refers* to the symbol is the context a
    reader needs, and the edge to it is already in the graph.
    """
    seen: Counter = Counter()
    for n in members:
        seen.update(neighbour_files.get(n["id"], Counter()))
    if not seen:
        return None
    top, _ = seen.most_common(1)[0]
    return name_from_path(top)


def derive(members: List[Dict[str, Any]], degree: Dict[str, int],
           neighbour_files: Optional[Dict[str, Counter]] = None) -> Tuple[str, str]:
    """Return (name, basis) for one community.

    Order matters: one file that owns the community names it best (a module and its
    symbols); failing that the shared directory names it (a package, a skill, a dbt
    layer); only then the structural hub.
    """
    files = Counter(str(n.get("source_file") or "") for n in members if n.get("source_file"))
    if files:
        dom, count = files.most_common(1)[0]
        if count / len(members) >= MIN_SHARE:
            named = name_from_path(dom)
            if named:
                return named, "file"

    shared = dominant_dir(members, DIR_SHARE)
    if shared:
        named = name_from_dir(shared)
        if named:
            return named, "dir"

    hub = pick_hub(members, degree)

    # Borrowed context is only for a community that owns no file of its own. Applied
    # more widely it restates what the hub already says — a community whose hub is
    # `add_erp_fields` and whose neighbours are `add_erp_fields.sql` came out as
    # "Add ERP Fields · Add ERP Fields Macro".
    context = None
    if not any(n.get("source_file") for n in members):
        context = borrow_context(members, neighbour_files or {})

    if hub and context and not _redundant(context, hub):
        return f"{clean_label(_pretty(hub))} · {context}", "hub+ctx"
    if hub:
        return clean_label(_pretty(hub)), "hub"
    if context:
        return context, "ctx"
    return "Unnamed", "none"


def build_names(graph: Dict[str, Any], min_size: int) -> Dict[int, str]:
    nodes = graph["nodes"]
    links = graph.get("links") or graph.get("edges") or []
    degree: Counter = Counter()
    for e in links:
        degree[e.get("source")] += 1
        degree[e.get("target")] += 1

    comm: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for n in nodes:
        cid = n.get("community")
        if cid is not None:
            comm[cid].append(n)

    # Which files reach into each node, for communities that own no file themselves.
    file_of = {n["id"]: str(n.get("source_file") or "") for n in nodes}
    neighbour_files: Dict[str, Counter] = defaultdict(Counter)
    for e in links:
        s_id, t_id = e.get("source"), e.get("target")
        if file_of.get(t_id):
            neighbour_files[s_id][file_of[t_id]] += 1
        if file_of.get(s_id):
            neighbour_files[t_id][file_of[s_id]] += 1

    raw: Dict[int, Tuple[str, str]] = {}
    for cid, members in comm.items():
        if len(members) < min_size:
            raw[cid] = (f"Community {cid}", "skipped")
            continue
        raw[cid] = derive(members, degree, neighbour_files)

    # Disambiguate: a name that points at two different communities is worse than a
    # placeholder, so collisions are qualified by their hub symbol, then by size rank.
    by_name: Dict[str, List[int]] = defaultdict(list)
    for cid, (name, _) in raw.items():
        by_name[name].append(cid)

    final: Dict[int, str] = {}
    for name, cids in by_name.items():
        if len(cids) == 1 or name.startswith("Community "):
            for cid in cids:
                final[cid] = name
            continue
        # Isolated single-node communities that share a name share it because they ARE
        # the same symbol: `Self` referenced from eleven modules, given no file by the
        # AST pass and no edge to anything, which clustering then splits into eleven
        # one-node communities. Numbering them `Self (7)`, `Self (8)` asserts a
        # distinction that does not exist. Measured here: all 1432 singleton
        # communities are degree 0, and 928 of those carry no source_file at all.
        def _is_stray(c: int) -> bool:
            return len(comm[c]) == 1 and degree.get(comm[c][0]["id"], 0) == 0

        for cid in [c for c in cids if _is_stray(c)]:
            final[cid] = name
        cids = [c for c in cids if not _is_stray(c)]
        if not cids:
            continue
        cids.sort(key=lambda c: -len(comm[c]))
        used: set = set()
        for rank, cid in enumerate(cids):
            # The largest keeps the bare name. It is the one a reader means by it, and
            # suffixing every member of a collision makes the principal case look like
            # an also-ran — "dbt Column Lineage Tests (1)" for the 36-node community.
            if rank == 0:
                used.add(name)
                final[cid] = name
                continue
            qualified = None
            for cand in _qualifiers(comm[cid], degree):
                # A qualifier that only repeats words already in the name adds length
                # and no information — "dbt Column Lineage Tests · test_dbt_column_
                # lineage.py" is strictly worse than the bare name.
                if not _redundant(cand, name):
                    trial = f"{name} · {cand}"
                    if trial not in used:
                        qualified = trial
                        break
            if qualified is None:
                qualified = f"{name} ({rank + 1})"
            used.add(qualified)
            final[cid] = qualified
    return final


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", default=str(GRAPH))
    ap.add_argument("--min-size", type=int, default=1,
                    help="communities smaller than this keep their placeholder (default 1: name all)")
    ap.add_argument("--apply", action="store_true", help="write graph.json and the labels file")
    ap.add_argument("--dry-run", action="store_true", help="preview only (default)")
    ap.add_argument("--limit", type=int, default=25, help="rows to preview")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    args = ap.parse_args(argv)

    path = Path(args.graph)
    if not path.is_file():
        print(f"error: no graph at {path}", file=sys.stderr)
        return 2
    graph = json.loads(path.read_text(encoding="utf-8"))

    names = build_names(graph, args.min_size)
    comm_sizes = Counter(n.get("community") for n in graph["nodes"])
    placeholders = sum(1 for v in names.values() if v.startswith("Community "))

    if args.format == "json":
        print(json.dumps({
            "communities": len(names),
            "named": len(names) - placeholders,
            "placeholders": placeholders,
            "names": {str(k): v for k, v in sorted(names.items())},
        }, ensure_ascii=False))
    else:
        print(f"{len(names)} communities · {len(names) - placeholders} named · "
              f"{placeholders} left as placeholder")
        ranked = sorted(names.items(), key=lambda kv: -comm_sizes[kv[0]])
        for cid, name in ranked[: args.limit]:
            print(f"  {comm_sizes[cid]:>4}  c{cid:<5} {name}")
        if len(ranked) > args.limit:
            print(f"  ... {len(ranked) - args.limit} more (raise --limit)")

    if args.apply:
        for n in graph["nodes"]:
            cid = n.get("community")
            if cid in names:
                n["community_name"] = names[cid]
        path.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
        # The labels file belongs beside the graph it describes, not at a fixed repo
        # path: `--graph <elsewhere> --apply` would otherwise stamp that graph's names
        # over this repository's, and `graphify export html` would then draw one
        # graph's clusters with another's labels.
        labels_path = path.parent / LABELS.name
        labels_path.write_text(json.dumps({str(k): v for k, v in names.items()},
                                          ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {_display(path)} and {_display(labels_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
