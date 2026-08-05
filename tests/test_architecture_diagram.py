"""Tests for public/code-skills-architecture.html.

A hand-authored architecture page rots in three ways, and only one of them is
visible to a reader:

1. **Its numbers stop being true.** The page states 19 connectors and 378
   models. Nothing about an HTML file makes that false when a connector is
   added, so every figure derived from a *committed* artifact carries
   `data-metric` and is pinned here. Figures that come from a rebuild —
   the test count, the code-graph size — are deliberately **not** pinned: a
   gate that goes red because somebody added a test is a gate that gets
   switched off, so those are snapshots and the footer names the command that
   re-derives each.

2. **Its diagrams break silently.** An unclosed tag or a label wider than its
   box still renders *something*, so a browser will not report it and neither
   will a human skimming for content. Both SVGs are parsed as XML and every
   label is measured against the box it sits in.

3. **The docs site stops serving it.** `public/` is the static-asset root, so
   an iframe `src` and a file path that disagree render an empty frame and no
   error.

The page is also published as a Claude artifact, which serves it under a strict
CSP: an external font, stylesheet, or image would fail to load there while
looking fine locally. `test_the_page_is_self_contained` is what catches that
before it ships.
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import _miniyaml as miniyaml  # noqa: E402

PAGE = REPO / "public/code-skills-architecture.html"
ENHANZA = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics"

pytestmark = pytest.mark.skipif(not PAGE.is_file(), reason="architecture page not on this branch")


def page_text() -> str:
    return PAGE.read_text(encoding="utf-8")


def svg_blocks(html: str) -> list[str]:
    return re.findall(r"<svg\b.*?</svg>", html, re.S)


# --- the numbers ----------------------------------------------------------------------

def _index() -> dict:
    return json.loads((ENHANZA / "ontology/index.json").read_text(encoding="utf-8"))


def _column_memory() -> dict:
    return json.loads((ENHANZA / "ontology/column-memory.json").read_text(encoding="utf-8"))


def _fragment_kind(kind: str) -> int:
    """Count dbt nodes of one resource type in the *committed* graphify fragment.

    The manifest itself is not committed (3.0 MB, churns on every model edit),
    so the fragment is the only file in the tree that can answer "how many dbt
    models are there" in a fresh clone with no dbt and no warehouse. That is the
    same reason the fragment exists at all.
    """
    data = json.loads((ENHANZA / "artifacts/graphify-fragment.json").read_text(encoding="utf-8"))
    return sum(1 for n in data.get("nodes", []) if n.get("dbt_resource_type") == kind)


def _declared_source_columns() -> int:
    total = 0
    for path in (ENHANZA / "dbt_project").rglob("sources.yml"):
        if "target" in path.parts:
            continue
        doc = miniyaml.load(path.read_text(encoding="utf-8")) or {}
        for source in doc.get("sources") or []:
            for table in source.get("tables") or []:
                total += len(table.get("columns") or [])
    return total


METRICS = {
    "connectors": lambda: len(_index()["connectors"]),
    "concepts": lambda: len(_index()["concepts"]),
    "coverage_gaps": lambda: len(_index()["gaps"]),
    "annotated_columns": lambda: len(_index()["column_semantics"]),
    "bindings": lambda: len(_column_memory()["bindings"]),
    "contracts": lambda: len(_column_memory()["contracts"]),
    "dbt_models": lambda: _fragment_kind("model"),
    "seeds": lambda: _fragment_kind("seed"),
    "source_tables": lambda: _fragment_kind("source"),
    "declared_source_columns": _declared_source_columns,
    "ttl_files": lambda: len(list((ENHANZA / "ontology").rglob("*.ttl"))),
}

needs_artifacts = pytest.mark.skipif(
    not (ENHANZA / "ontology/index.json").exists()
    or not (ENHANZA / "artifacts/graphify-fragment.json").exists(),
    reason="needs the committed ontology artifacts",
)


def pinned_claims(html: str) -> list[tuple[str, int]]:
    """Every `data-metric` element as (key, the first integer it displays)."""
    out = []
    for key, body in re.findall(r'data-metric="([^"]+)"[^>]*>([^<]*)<', html):
        digits = re.search(r"[\d,]+", body)
        assert digits, f"data-metric={key!r} shows no number: {body!r}"
        out.append((key, int(digits.group(0).replace(",", ""))))
    return out


@needs_artifacts
def test_every_pinned_number_matches_the_artifact_it_claims() -> None:
    claims = pinned_claims(page_text())
    assert claims, "the page states no pinned figures at all"
    wrong = []
    for key, shown in claims:
        assert key in METRICS, f"data-metric={key!r} has no resolver in this test"
        actual = METRICS[key]()
        if shown != actual:
            wrong.append(f"{key}: page says {shown}, artifacts say {actual}")
    assert not wrong, "the page is stale — " + "; ".join(wrong)


@needs_artifacts
def test_the_headline_figures_are_all_pinned() -> None:
    """The stat strip is the part a reader trusts without checking, so nothing in
    it may be an unpinned snapshot."""
    strip = re.search(r'<div class="stats">(.*?)</div>\s*</header>', page_text(), re.S)
    assert strip, "stat strip not found"
    tiles = re.findall(r"<b\b([^>]*)>", strip.group(1))
    assert len(tiles) >= 4
    unpinned = [t for t in tiles if "data-metric=" not in t]
    assert not unpinned, f"headline figures with no artifact behind them: {unpinned}"


def test_unpinned_figures_carry_the_command_that_re_derives_them() -> None:
    """The test count and the graph size cannot be pinned without going red on a
    correct state, so the page owes the reader a way to check them."""
    html = page_text()
    assert "Every number on this page is measured, not estimated" in html
    for command in ("use_case_sync.py --all --check", "pytest -q --collect-only"):
        assert command in html, f"footer does not name `{command}`"


# --- the diagrams ---------------------------------------------------------------------

def test_svgs_are_well_formed() -> None:
    """A browser renders a broken SVG as best it can and says nothing."""
    blocks = svg_blocks(page_text())
    assert len(blocks) >= 2, "the data-flow and pipeline diagrams"
    for i, block in enumerate(blocks, 1):
        try:
            ET.fromstring(block)
        except ET.ParseError as exc:  # pragma: no cover - the assert carries the message
            pytest.fail(f"svg {i} is not well-formed: {exc}")


def test_every_diagram_declares_a_title_and_description() -> None:
    """The only way a screen reader gets anything out of a hand-drawn diagram."""
    for block in svg_blocks(page_text()):
        root = ET.fromstring(block)
        assert root.get("role") == "img"
        tags = {child.tag.split("}")[-1] for child in root}
        assert {"title", "desc"} <= tags


_ADVANCE = 0.601  # monospace advance width as a fraction of the font size
_CLASS_SIZE = {"t-title": 12, "t-sub": 10.5, "t-num": 11, "t-lane": 10.5,
               "t-edge": 10.5, "t-gate": 10}


def test_no_label_overflows_the_box_it_labels() -> None:
    """Measured, not eyeballed: SVG does not wrap or clip, so a label wider than
    its box silently overprints the next one. Three did, on the first draft."""
    problems = []
    for n, block in enumerate(svg_blocks(page_text()), 1):
        root = ET.fromstring(block)
        view = [float(v) for v in root.get("viewBox").split()]
        boxes = [
            tuple(float(r.get(k)) for k in ("x", "y", "width", "height"))
            for r in root.iter("rect")
            if "box" in (r.get("class") or "")
        ]
        for text in root.iter("text"):
            cls = text.get("class") or ""
            if cls not in _CLASS_SIZE or text.get("transform"):
                continue
            body = "".join(text.itertext())
            width = len(body) * _CLASS_SIZE[cls] * _ADVANCE
            x, y = float(text.get("x")), float(text.get("y"))
            left = x - width if text.get("text-anchor") == "end" else x
            if left + width > view[2] - 4:
                problems.append(f"svg {n}: {body!r} runs past the right edge")
            for bx, by, bw, bh in boxes:
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    if left + width > bx + bw - 4:
                        problems.append(f"svg {n}: {body!r} overflows its box")
                    break
    assert not problems, problems


def test_no_two_boxes_overlap() -> None:
    for n, block in enumerate(svg_blocks(page_text()), 1):
        root = ET.fromstring(block)
        boxes = [
            tuple(float(r.get(k)) for k in ("x", "y", "width", "height"))
            for r in root.iter("rect")
            if "box" in (r.get("class") or "")
        ]
        for i, (x1, y1, w1, h1) in enumerate(boxes):
            for x2, y2, w2, h2 in boxes[i + 1:]:
                overlap = x1 < x2 + w2 and x2 < x1 + w1 and y1 < y2 + h2 and y2 < y1 + h1
                assert not overlap, f"svg {n}: boxes at ({x1},{y1}) and ({x2},{y2}) overlap"


# --- how it is served -----------------------------------------------------------------

def test_the_page_is_self_contained() -> None:
    """Published under a CSP that blocks every external host. A webfont link or a
    remote image fails there while looking correct on a laptop."""
    html = page_text()
    external = re.findall(r'(?:src|href)="(?!#)(?:https?:)?//[^"]+', html)
    assert not external, external
    assert "@import" not in html


def test_both_themes_are_defined_and_the_toggle_wins() -> None:
    """The viewer's toggle stamps data-theme on the root, so a page that styles
    only the media query ignores it in one direction."""
    html = page_text()
    assert "@media (prefers-color-scheme: dark)" in html
    assert ':root[data-theme="dark"]' in html
    assert ':root[data-theme="light"]' in html
    dark_override = html.index(':root[data-theme="dark"]')
    media = html.index("@media (prefers-color-scheme: dark)")
    assert dark_override > media, "the explicit override must come after the media query"


def test_colour_is_never_the_only_encoding() -> None:
    """The palette validator WARNs below 3:1 against the light surface, and that
    warning is only dischargeable with visible labels."""
    html = page_text()
    assert 'class="legend"' in html
    for block in svg_blocks(html):
        root = ET.fromstring(block)
        boxes = sum(1 for r in root.iter("rect") if "box" in (r.get("class") or ""))
        labels = sum(1 for t in root.iter("text") if (t.get("class") or "") == "t-title")
        assert labels >= boxes, f"{boxes} boxes but only {labels} titled"


# --- how the documentation site serves it ---------------------------------------------

DOCS_INDEX = REPO / "docs/index.mdx"


def test_the_docs_site_embeds_the_page_at_the_path_it_is_served_from() -> None:
    """`public/` is the static-asset root, so `public/x.html` serves at `/x.html`.
    An iframe src and a file path that disagree render an empty frame and no
    error — the same silent failure the rest of this file exists to catch."""
    assert PAGE.parent.name == "public", "the docs site serves assets from public/"
    served = "/" + PAGE.name
    index = DOCS_INDEX.read_text(encoding="utf-8")
    assert f'src="{served}"' in index, f"docs/index.mdx does not embed {served}"


def test_the_page_carries_a_description_for_the_docs_site() -> None:
    """It is a page on a documentation site now, not only an artifact."""
    assert re.search(r'<meta name="description" content="[^"]{40,}"', page_text())
