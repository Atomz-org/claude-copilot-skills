"""Behavior tests for the Rust TOON serializer (rust/toon/graph_to_toon.rs).

The binary is the sole runtime of the Graphify → TOON → LLM → JSON pipeline;
its functionality contract lives as comments in the Rust source. These tests
pin that contract at the CLI level — encode shape, decode values, strict-mode
rejections, delimiters, the graphify text and graph.json inbound modes, the
--decode outbound leg, and the --passthrough guarantee the PreToolUse hook
relies on. Cases are ported from the TOON spec's normative rules (quoting
MUST-list, escape table, number canonicalization, tabular eligibility,
list-form fallback, length-marker validation).
"""
from __future__ import annotations

import json
import subprocess

import pytest


def run(toon_binary, stdin: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(toon_binary), *args], input=stdin,
        capture_output=True, text=True, timeout=60,
    )


def encode(toon_binary, doc) -> str:
    result = run(toon_binary, json.dumps(doc))
    assert result.returncode == 0, result.stderr
    return result.stdout.rstrip("\n")


def decode(toon_binary, text: str, *args: str):
    result = run(toon_binary, text, "--decode", *args)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def roundtrip(toon_binary, doc):
    return decode(toon_binary, encode(toon_binary, doc))


# ---------------------------------------------------------------------------
# Scalars and quoting
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "s",
    [
        "",                # empty
        " leading",        # leading whitespace
        "trailing ",       # trailing whitespace
        "true", "false", "null",    # literal look-alikes
        "42", "-3.5", "1e5", "+7",  # numeric-like
        "a:b", 'say "hi"', "back\\slash",
        "arr[0]", "brace{x}",
        "a,b",             # active delimiter
        "-flag", "#comment",
        "line\nbreak", "tab\there",
    ],
)
def test_strings_on_the_quoting_must_list_roundtrip(toon_binary, s):
    assert roundtrip(toon_binary, {"v": s}) == {"v": s}
    assert encode(toon_binary, {"v": s}).startswith('v: "')  # really quoted


def test_plain_strings_stay_unquoted(toon_binary):
    assert encode(toon_binary, {"v": "snow"}) == "v: snow"


def test_number_canonicalization(toon_binary):
    assert encode(toon_binary, {"a": -0.0}) == "a: 0"
    assert encode(toon_binary, {"a": 2.50}) == "a: 2.5"
    assert encode(toon_binary, {"a": 3.0}) == "a: 3"
    assert encode(toon_binary, {"a": 1e22}) == "a: 1e+22"


def test_scalar_types_survive_decode(toon_binary):
    doc = {"i": 7, "f": 2.5, "t": True, "n": None, "s": "x"}
    assert roundtrip(toon_binary, doc) == doc


def test_root_primitive_forms(toon_binary):
    assert decode(toon_binary, "42") == 42
    assert decode(toon_binary, "hello world") == "hello world"


# ---------------------------------------------------------------------------
# Empty forms, roots, arrays
# ---------------------------------------------------------------------------

def test_empty_document_and_empty_containers(toon_binary):
    assert encode(toon_binary, {}) == ""
    assert decode(toon_binary, "") == {}
    assert encode(toon_binary, []) == "[]"
    assert decode(toon_binary, "[]") == []
    assert encode(toon_binary, {"k": []}) == "k: []"
    assert decode(toon_binary, "k[0]:") == {"k": []}  # legacy empty form
    assert roundtrip(toon_binary, {"outer": {"deep": 1}, "empty": {}}) == {
        "outer": {"deep": 1}, "empty": {},
    }


def test_inline_primitive_array(toon_binary):
    assert encode(toon_binary, {"alerts": ["frost", "wind"]}) == "alerts[2]: frost,wind"


def test_root_and_keyed_tabular_arrays(toon_binary):
    doc = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    text = encode(toon_binary, doc)
    assert text.splitlines()[0] == "[2]{id,name}:"
    assert decode(toon_binary, text) == doc

    keyed = {"rows": [{"id": 1, "v": "a"}, {"id": 2, "v": None}]}
    text = encode(toon_binary, keyed)
    assert text.splitlines()[0] == "rows[2]{id,v}:"
    assert "id" not in text.splitlines()[1]  # fields are not repeated per row
    assert decode(toon_binary, text) == keyed


def test_nested_uniform_columns_fold_into_header(toon_binary):
    doc = {"forecast": [
        {"day": "Mon", "temp": {"min": -2, "max": 4}},
        {"day": "Tue", "temp": {"min": 1, "max": 7}},
    ]}
    text = encode(toon_binary, doc)
    assert text.splitlines()[0] == "forecast[2]{day,temp{min,max}}:"
    assert text.splitlines()[1] == "  Mon,-2,4"
    assert decode(toon_binary, text) == doc


def test_non_uniform_arrays_fall_back_to_list_form(toon_binary):
    doc = {"items": [[1, 2], [], {}, {"a": 1, "b": {"c": 2}}, "plain", 7]}
    text = encode(toon_binary, doc)
    lines = text.splitlines()
    assert lines[0] == "items[6]:"
    assert lines[1] == "  - [2]: 1,2"
    assert lines[2] == "  - []"  # empty array item, distinct from bare hyphen
    assert lines[3] == "  -"     # bare hyphen == empty object item
    assert decode(toon_binary, text) == doc


def test_delimiters_declared_in_bracket(toon_binary):
    doc = {"rows": [{"k": "a,b", "n": 1}, {"k": "c", "n": 2}]}
    result = run(toon_binary, json.dumps(doc), "--delimiter", "pipe")
    assert result.stdout.splitlines()[0] == "rows[2|]{k|n}:"
    assert result.stdout.splitlines()[1] == "  a,b|1"  # comma unquoted under pipe
    assert decode(toon_binary, result.stdout) == doc

    result = run(toon_binary, json.dumps({"vals": ["a", "b c"]}), "--delimiter", "tab")
    assert result.stdout.rstrip("\n") == "vals[2\t]: a\tb c"


# ---------------------------------------------------------------------------
# Strict-mode validation (decode exits non-zero)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad",
    [
        "a[3]: x,y",                       # inline count mismatch
        "r[2]{a,b}:\n  1,2",               # row count mismatch
        "r[1]{a,b}:\n  1,2,3",             # row width mismatch
        "l[2]:\n  - x",                    # list item count mismatch
        "a:\n   b: 1",                     # 3-space indent
        "a: 1\n  b: 2",                    # over-indent without open scope
        "a:\n\tb: 1",                      # tab indentation
        "envs[2:]{r,n}:\n  p: e,6",        # keyed tabular form (unsupported)
        "a: 1\na: 2",                      # duplicate key
        'v: "\\ud800"',                    # lone surrogate
        'v: "unterminated',                # unterminated quote
    ],
)
def test_strict_violations_are_rejected(toon_binary, bad):
    assert run(toon_binary, bad, "--decode").returncode != 0


def test_no_strict_tolerates_count_mismatch(toon_binary):
    assert decode(toon_binary, "a[3]: x,y", "--no-strict") == {"a": ["x", "y"]}


def test_colon_without_space_is_a_scalar_not_an_entry(toon_binary):
    assert decode(toon_binary, "l[1]:\n  - file.md:L23") == {"l": ["file.md:L23"]}


# ---------------------------------------------------------------------------
# Graphify text mode
# ---------------------------------------------------------------------------

GRAPHIFY_SAMPLE = """\
Traversal: BFS depth=2 | Start: ['GraphManager'] | 3 nodes found

[!] TRUNCATED: showing 2 of 3 nodes (~500-token budget).

NODE GraphManager [src=src/ai-core/graph-manager.ts loc=L14 community=Repository Baseline Workflow]
NODE Use-Case Path Policy [src=.claude/skills/dbt-skill/SKILL.md loc=None community=Analytics Engineering Rules (Binding dbt Core Rules)]
EDGE GraphManager --contains [EXTRACTED]--> snapshot() at=src/ai-core/graph-manager.ts:L27
EDGE GraphManager --conceptually_related_to [INFERRED]--> Use-Case Path Policy
"""


def test_graphify_text_parses_nodes_edges_and_meta(toon_binary):
    result = run(toon_binary, GRAPHIFY_SAMPLE)
    assert result.returncode == 0, result.stderr
    assert "nodes[2]{name,src,loc,community}:" in result.stdout
    doc = decode(toon_binary, result.stdout)
    assert doc["meta"]["traversal"].startswith("BFS depth=2")
    assert "TRUNCATED" in doc["meta"]["warning"]
    assert doc["nodes"][1]["loc"] is None  # loc=None literal becomes null
    assert doc["edges"][0]["at"] == "src/ai-core/graph-manager.ts:L27"
    assert doc["edges"][1] == {
        "source": "GraphManager",
        "relation": "conceptually_related_to",
        "kind": "INFERRED",
        "target": "Use-Case Path Policy",
        "at": None,
    }


def test_toon_is_smaller_than_json_for_uniform_rows(toon_binary):
    node = {"name": "GraphManager", "src": "src/ai-core/graph-manager.ts",
            "loc": "L14", "community": "Repository Baseline Workflow"}
    doc = {"nodes": [node] * 40}
    assert len(encode(toon_binary, doc)) < len(json.dumps(doc))


# ---------------------------------------------------------------------------
# graph.json subset mode
# ---------------------------------------------------------------------------

def _fake_graph(tmp_path):
    graph = {
        "nodes": [
            {"id": "n1", "label": "alpha", "source_file": "src/a.py",
             "source_location": "L1", "community_name": "Core"},
            {"id": "n2", "label": "beta", "source_file": "docs/b.md",
             "source_location": None, "community_name": "Docs",
             "metadata": {"kind": "file"}},
            {"id": "n3", "label": "gamma", "source_file": "src/c.py",
             "source_location": "L9", "community_name": "Core"},
        ],
        "links": [
            {"source": "n1", "target": "n3", "relation": "contains", "weight": 1.0},
            {"source": "n1", "target": "n2", "relation": "references"},
        ],
    }
    p = tmp_path / "graph.json"
    p.write_text(json.dumps(graph), encoding="utf-8")
    return p


def test_graph_subset_normalizes_to_uniform_rows(toon_binary, tmp_path):
    result = run(toon_binary, "", "--graph", str(_fake_graph(tmp_path)))
    assert result.returncode == 0, result.stderr
    # normalization drops per-row optional keys, so rows encode tabular
    assert "nodes[3]{id,label,src,loc,community}:" in result.stdout
    doc = decode(toon_binary, result.stdout)
    assert doc["meta"]["nodes_total"] == 3


def test_graph_subset_filters_drop_dangling_edges(toon_binary, tmp_path):
    p = _fake_graph(tmp_path)
    doc = decode(
        toon_binary,
        run(toon_binary, "", "--graph", str(p), "--community", "core").stdout,
    )
    assert [n["id"] for n in doc["nodes"]] == ["n1", "n3"]
    assert doc["edges"] == [{"source": "n1", "relation": "contains", "target": "n3"}]

    doc = decode(
        toon_binary,
        run(toon_binary, "", "--graph", str(p), "--limit-nodes", "1").stdout,
    )
    assert [n["id"] for n in doc["nodes"]] == ["n1"]
    assert doc["edges"] == []  # both edges lost an endpoint


# ---------------------------------------------------------------------------
# CLI contract: passthrough, stats, rejection
# ---------------------------------------------------------------------------

def test_passthrough_forwards_unrecognized_output_unchanged(toon_binary):
    prose = "Shortest path (1 hops):\n  A <--contains-- B\n"
    result = run(toon_binary, prose, "--passthrough")
    assert result.returncode == 0
    assert result.stdout == prose
    assert run(toon_binary, "", "--passthrough").returncode == 0  # empty stdin


def test_stats_go_to_stderr_not_stdout(toon_binary):
    result = run(toon_binary, json.dumps({"rows": [{"a": 1}, {"a": 2}]}), "--stats")
    assert result.returncode == 0
    assert "tokens" in result.stderr
    assert "tokens" not in result.stdout


def test_unrecognized_stdin_is_rejected_without_passthrough(toon_binary):
    result = run(toon_binary, "just some prose, neither JSON nor graphify output")
    assert result.returncode != 0
    assert "neither JSON nor graphify" in result.stderr
