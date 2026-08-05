"""Tests for public/decision-path.html and the docs page that serves it.

The sibling of `tests/test_architecture_diagram.py`, and it exists because the
page it guards had already rotted in two ways that nothing caught:

1. **It contradicted itself.** The stat strip claimed 3,460 nodes / 6,030 edges
   / 248 clusters while the footer of the same file claimed 3,312 / 4,997 / 585.
   Both describe one graph. A reader has no way to know which is current, and no
   test compared them, because there was no test.

2. **It contradicted the artifact and the other page.** It stated 359 dbt
   models, 66 seeds and 688 lineage links where the committed
   `graphify-fragment.json` says 378, 121 and 706 — while
   `test_architecture_diagram.py` was already pinning 378 from that same file.
   `docs/index.mdx` embedded both pages, so it stated 359 *and* 378 models.

The split this file enforces is the one the architecture page established:

- A figure derived from a **committed** artifact carries `data-metric` and is
  checked against that artifact. No rebuild, no warehouse, no dbt.
- A figure that needs a **rebuild** — the size of the code graph — is a snapshot
  and is deliberately *not* pinned, because a gate that goes red when somebody
  runs `graphify update` is a gate that gets switched off. What is enforced
  instead is that the snapshot agrees with itself everywhere it appears and that
  the footer names the command re-deriving it.

The headline check differs from the architecture page's for the same reason. On
that page the stat strip is artifact-derived, so nothing in it may be unpinned.
Here the strip *is* the graph, so requiring `data-metric` on it would demand a
gate we just argued must not exist; the strip is held to internal consistency.

This page also renders through `<canvas>` rather than SVG, so the geometry tests
in the architecture file have no analogue: there are no boxes to overlap and no
labels to overflow. What it does share is being served under a strict CSP, which
is what `test_the_page_is_self_contained` catches before it ships.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

PAGE = REPO / "public/decision-path.html"
DOC = REPO / "docs/decision-path.mdx"
DOCS_INDEX = REPO / "docs/index.mdx"
ENHANZA = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics"
FRAGMENT = ENHANZA / "artifacts/graphify-fragment.json"

pytestmark = pytest.mark.skipif(not PAGE.is_file(), reason="decision-path page not on this branch")

needs_fragment = pytest.mark.skipif(
    not FRAGMENT.exists(), reason="needs the committed graphify fragment"
)

# A dbt node that is a table in the warehouse sense. `macro` and `analysis` are
# neither, and an edge touching one is not a table-to-table link.
TABLE_KINDS = {"model", "source", "seed"}


def page_text() -> str:
    return PAGE.read_text(encoding="utf-8")


def _fragment() -> dict:
    return json.loads(FRAGMENT.read_text(encoding="utf-8"))


def _kind_count(kind: str) -> int:
    """Counted in the *committed* fragment, never the manifest.

    The manifest is not committed — 3.0 MB and churning on every model edit — so
    the fragment is the only file that can answer "how many dbt models are there"
    in a fresh clone with no dbt and no warehouse. Same reason it exists at all.
    """
    return sum(1 for n in _fragment().get("nodes", []) if n.get("dbt_resource_type") == kind)


def _lineage_edges() -> int:
    """Both ends must be tables.

    Counting edges by their source alone gives 707 rather than 706 here, because
    one dbt node points at something that is not a table. The page says
    "table-to-table links", so the definition has to be symmetric or the number
    means something the sentence does not.
    """
    frag = _fragment()
    kind = {n["id"]: n.get("dbt_resource_type") for n in frag.get("nodes", [])}
    return sum(
        1
        for e in frag.get("edges", [])
        if kind.get(e["source"]) in TABLE_KINDS and kind.get(e["target"]) in TABLE_KINDS
    )


METRICS = {
    "dbt_models": lambda: _kind_count("model"),
    "source_tables": lambda: _kind_count("source"),
    "seeds": lambda: _kind_count("seed"),
    "macros": lambda: _kind_count("macro"),
    "dbt_edges": lambda: len(_fragment().get("edges", [])),
    "lineage_edges": _lineage_edges,
}


def pinned_claims(html: str) -> list[tuple[str, int]]:
    """Every `data-metric` element as (key, the first integer it displays)."""
    out = []
    for key, body in re.findall(r'data-metric="([^"]+)"[^>]*>([^<]*)<', html):
        digits = re.search(r"[\d,]+", body)
        assert digits, f"data-metric={key!r} shows no number: {body!r}"
        out.append((key, int(digits.group(0).replace(",", ""))))
    return out


# --- the numbers that come from a committed artifact ----------------------------------

@needs_fragment
@pytest.mark.parametrize("path", [PAGE, DOC], ids=lambda p: p.name)
def test_every_pinned_number_matches_the_artifact_it_claims(path: Path) -> None:
    """Both the HTML page and the MDX page that frames it state these figures, so
    both are checked. Two files stating one number is how they came to disagree."""
    claims = pinned_claims(path.read_text(encoding="utf-8"))
    assert claims, f"{path.name} states no pinned figures at all"
    wrong = []
    for key, shown in claims:
        assert key in METRICS, f"data-metric={key!r} has no resolver in this test"
        actual = METRICS[key]()
        if shown != actual:
            wrong.append(f"{key}: {path.name} says {shown}, the fragment says {actual}")
    assert not wrong, "stale — " + "; ".join(wrong)


@needs_fragment
def test_the_embedded_dataset_agrees_with_the_fragment() -> None:
    """The interactive diagrams read `#ddata`, not the prose. Correcting the
    sentence and leaving the dataset behind fixes only what a reader sees first."""
    data = json.loads(
        re.search(
            r'<script id="ddata" type="application/json">(.*?)</script>', page_text(), re.S
        ).group(1)
    )
    stats = data["stats"]
    for key, metric in (
        ("models", "dbt_models"),
        ("sources", "source_tables"),
        ("seeds", "seeds"),
        ("macros", "macros"),
        ("edgesAll", "dbt_edges"),
        ("lineage", "lineage_edges"),
    ):
        assert stats[key] == METRICS[metric](), (
            f"#ddata.stats.{key} is {stats[key]}, the fragment says {METRICS[metric]()}"
        )


@needs_fragment
def test_every_connector_the_page_lists_carries_its_real_model_count() -> None:
    """The bar chart claimed `logic` had 17 models where the fragment says 36, and
    omitted `tempo` entirely — so the chart under-reported the project by one whole
    connector while looking complete."""
    data = json.loads(
        re.search(
            r'<script id="ddata" type="application/json">(.*?)</script>', page_text(), re.S
        ).group(1)
    )
    shown = {c["name"]: c["n"] for c in data["connectors"]}
    actual: dict[str, int] = {}
    for node in _fragment().get("nodes", []):
        if node.get("dbt_resource_type") != "model":
            continue
        connector = node.get("dbt_connector")
        if connector:
            actual[connector] = actual.get(connector, 0) + 1
    assert shown == actual, f"page: {sorted(shown.items())}; fragment: {sorted(actual.items())}"


@needs_fragment
def test_the_prose_counts_the_same_connectors_the_chart_draws() -> None:
    """"eleven source systems" over a twelve-bar chart is the kind of drift a
    reader trusts precisely because it is written out in words."""
    words = {11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen"}
    connectors = {
        n.get("dbt_connector")
        for n in _fragment().get("nodes", [])
        if n.get("dbt_resource_type") == "model" and n.get("dbt_connector")
    }
    word = words.get(len(connectors))
    assert word, f"{len(connectors)} connectors — add the number word to this test"
    assert f"The {word} source systems" in page_text()


# --- the numbers that need a rebuild, and so are snapshots ----------------------------

GRAPH_SNAPSHOT = re.compile(
    r"snapshot: ([\d,]+) nodes, ([\d,]+) edges, ([\d,]+) communities"
)


def test_the_graph_snapshot_agrees_with_itself() -> None:
    """The bug this file was written for. The strip and the footer describe one
    graph, so they may be out of date together but never differently."""
    html = page_text()
    strip = dict(
        (k.strip(), v.strip())
        for v, k in re.findall(
            r'<span class="stat-v">([^<]+)</span><span class="stat-k">([^<]+)</span>', html
        )
    )
    footer = GRAPH_SNAPSHOT.search(html)
    assert footer, "the footer does not state the graph snapshot in the expected form"
    for label, group in (("nodes", 1), ("edges", 2), ("clusters", 3)):
        assert strip[label] == footer.group(group), (
            f"stat strip says {strip[label]} {label}, footer says {footer.group(group)}"
        )


def test_the_unpinned_snapshot_names_the_command_that_re_derives_it() -> None:
    """A figure nobody can check is a figure nobody should trust."""
    html = page_text()
    assert "Not pinned, because it needs a rebuild" in html
    assert "graphify update ." in html
    assert "Every figure on this page is measured, not illustrative" in html


# --- how it is served ------------------------------------------------------------------

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
    assert html.index(':root[data-theme="dark"]') > html.index("@media (prefers-color-scheme: dark)")


def test_the_page_carries_a_description_for_the_docs_site() -> None:
    assert re.search(r'<meta name="description" content="[^"]{40,}"', page_text())


# --- how the documentation site serves it ---------------------------------------------

def test_the_docs_page_embeds_it_at_the_path_it_is_served_from() -> None:
    """`public/` is the static-asset root, so `public/x.html` serves at `/x.html`.
    An iframe src and a file path that disagree render an empty frame and no error."""
    assert PAGE.parent.name == "public", "the docs site serves assets from public/"
    assert f'src="/{PAGE.name}"' in DOC.read_text(encoding="utf-8")


def test_the_overview_links_to_the_page_rather_than_restating_it() -> None:
    """The section used to live in the overview. Two copies of a budget table and a
    lineage count is exactly how this page came to disagree with the artifact, so
    the index links and states nothing a reader has to keep in sync."""
    index = DOCS_INDEX.read_text(encoding="utf-8")
    assert 'href="/decision-path"' in index, "the overview does not link to the page"
    for moved in ("| `--budget` | nodes kept |", "flowchart LR\n    S0["):
        assert moved not in index, f"the overview still restates moved content: {moved!r}"


def test_the_docs_page_declares_its_place_in_the_sidebar() -> None:
    """Without frontmatter the page is published but unreachable by navigation."""
    head = DOC.read_text(encoding="utf-8").split("---")[1]
    for key in ("title:", "description:", "sidebar:", "label:", "order:"):
        assert key in head, f"frontmatter is missing {key!r}"
