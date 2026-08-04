"""The ontology/topology visualiser: what it must never get wrong.

Three classes of failure matter here, and each has a test that fails on the specific
mistake rather than on a broad "it changed":

1. **Inventing structure.** The page is a picture of a contract. A relationship it draws
   that the ontology does not assert is a lie that looks authoritative.
2. **Hiding a disagreement.** The registry and the dbt project disagree about two links
   in enhanza-analytics. A page that silently reports either 110 or 112 is worse than one
   that reports both.
3. **Reaching the network.** The output is meant to open from `file://` and inside a
   strict CSP. One CDN reference breaks that everywhere at once, silently, in a way that
   looks fine on the machine that generated it.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import ontology_ui as ui  # noqa: E402

ENHANZA = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics"
INDEX = ENHANZA / "ontology" / "index.json"
PAGE = REPO / "public" / "enhanza-analytics-ontology.html"

needs_index = pytest.mark.skipif(
    not INDEX.is_file(), reason="no ontology/index.json; run use_case_sync.py --stage ontology"
)


def _index() -> dict:
    return json.loads(INDEX.read_text(encoding="utf-8"))


def _payload_of(html: str) -> dict:
    raw = re.search(r'id="payload">(.*?)</script>', html, re.S).group(1)
    return json.loads(raw.replace("<\\/", "</"))


# ---------------------------------------------------------------------------------------
# 1. plain language
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token,expected",
    [
        ("erp:LineItem", "Line item"),
        ("crm:Opportunity", "Opportunity"),
        ("dim_order_rows", "Order rows"),
        ("fact_work_orders", "Work orders"),
        ("erp:orgId", "Org ID"),
        ("erp:documentDate", "Document date"),
    ],
)
def test_humanise_drops_the_jargon(token: str, expected: str) -> None:
    """The reader does not know what a prefix or camelCase is, and should not have to."""
    assert ui.humanise(token) == expected


def test_humanise_never_returns_empty() -> None:
    """A label that renders as a blank card is worse than an ugly one."""
    for token in ("", ":", "erp:", "dim_", "___"):
        assert ui.humanise(token).strip()


def test_the_star_schema_split_is_named_in_plain_words() -> None:
    assert ui.thing_kind("dim_customers")[0] == "Reference data"
    assert ui.thing_kind("fact_orders")[0] == "Activity"
    # Anything off-convention is reported as such, not silently bucketed into one side.
    assert ui.thing_kind("weird_name")[0] == "Other"


# ---------------------------------------------------------------------------------------
# 2. it draws only what the ontology asserts
# ---------------------------------------------------------------------------------------


@needs_index
def test_every_drawn_link_exists_in_the_index() -> None:
    """No edge is invented. This is the whole basis for trusting the picture.

    `fact_*` sitting beside `dim_*` invites drawing a foreign key between them, and this
    ontology asserts none — only `providedBy`. A crow's foot here would be a contract the
    model never made (analytics rule 5).
    """
    index = _index()
    payload = ui.build_payload(index)

    declared_live = {(k, c["concept"]) for c in index["concepts"]
                     for k in (c.get("implemented_by") or [])}
    declared_planned = {(k, c["concept"]) for c in index["concepts"]
                        for k in (c.get("planned_by") or [])}

    for concept in payload["concepts"]:
        for key in concept["live"]:
            assert (key, concept["key"]) in declared_live
        for key in concept["planned"]:
            assert (key, concept["key"]) in declared_planned

    drawn = sum(len(c["live"]) + len(c["planned"]) for c in payload["concepts"])
    assert drawn == len(declared_live) + len(declared_planned)


@needs_index
def test_attributes_are_real_mappings_not_guesses() -> None:
    index = _index()
    payload = ui.build_payload(index)
    real = {(m["concept"], m["property"]) for m in index["mappings"]}
    for concept in payload["concepts"]:
        for attribute in concept["attributes"]:
            assert (concept["key"], attribute["property"]) in real
            assert attribute["columns"], "an attribute with no source column is not evidence"


@needs_index
def test_concept_and_connector_counts_match_the_index() -> None:
    index = _index()
    payload = ui.build_payload(index)
    assert payload["totals"]["concepts"] == len(index["concepts"])
    assert payload["totals"]["connectors"] == len(index["connectors"])
    assert payload["totals"]["gaps"] == len(index["gaps"])


# ---------------------------------------------------------------------------------------
# 3. the disagreement is surfaced, not averaged away
# ---------------------------------------------------------------------------------------


@needs_index
def test_links_declared_without_a_dbt_model_are_reported() -> None:
    """`implemented_by` is a claim; a model row is evidence. They disagree here.

    Measured on enhanza-analytics: 112 declared links, 110 with a model behind them.
    Reporting only the claim overstates coverage; reporting only the evidence hides that
    the registry is wrong. The page reports both and names the offending pairs.
    """
    index = _index()
    payload = ui.build_payload(index)
    totals = payload["totals"]

    assert totals["links"] == totals["links_with_model"] + totals["links_unbacked"]
    assert totals["links_with_model"] == len(index["models"])
    assert len(payload["unbacked"]) == totals["links_unbacked"]

    for row in payload["unbacked"]:
        concept = next(c for c in payload["concepts"] if c["key"] == row["concept"])
        assert row["connector"] in concept["live"], "still shown as declared"
        assert row["connector"] not in concept["models"], "and shown as lacking a model"


@needs_index
def test_a_consistent_index_reports_no_unbacked_links() -> None:
    """The check must be silent when the two sides agree — otherwise it is noise.

    Built by deleting the two model rows' disagreement rather than by hand-writing a
    fixture, so the assertion tracks the real shape of `index.json`.
    """
    index = _index()
    models = {(m["connector"], m["concept"]) for m in index["models"]}
    trimmed = json.loads(json.dumps(index))
    for concept in trimmed["concepts"]:
        concept["implemented_by"] = [
            k for k in (concept.get("implemented_by") or [])
            if (k, concept["concept"]) in models
        ]
    payload = ui.build_payload(trimmed)
    assert payload["totals"]["links_unbacked"] == 0
    assert payload["unbacked"] == []


# ---------------------------------------------------------------------------------------
# 4. the output is self-contained
# ---------------------------------------------------------------------------------------


@needs_index
def test_the_page_reaches_no_network() -> None:
    """It must open from file:// and under a CSP that blocks every other host."""
    html = ui.render_html(ui.build_payload(_index()))

    for pattern in ("<script src", "<link rel=\"stylesheet\"", "@import", "fetch(",
                    "XMLHttpRequest", "cdn.", "googleapis", "unpkg", "jsdelivr"):
        assert pattern not in html, f"external reference: {pattern}"

    # w3id.org IRIs are the ontology's own identifiers carried in the data, and the SVG
    # namespace is a constant — neither is fetched. Anything else would be.
    urls = {u for u in re.findall(r'https?://[^\s"\'<>)]+', html)}
    unexpected = {u for u in urls
                  if not u.startswith(("https://w3id.org/", "http://www.w3.org/2000/svg"))}
    assert not unexpected, f"unexpected URLs: {sorted(unexpected)[:5]}"


@needs_index
def test_the_data_island_cannot_close_its_own_tag() -> None:
    """A value containing `</script>` would end the island and inject markup."""
    payload = ui.build_payload(_index())
    payload["concepts"][0]["label"] = "</script><img src=x onerror=alert(1)>"
    html = ui.render_html(payload)
    island = re.search(r'id="payload">(.*?)</script>', html, re.S).group(1)
    assert "onerror" not in html.split('<script type="application/json"')[0]
    assert "<\\/script>" in island
    assert json.loads(island.replace("<\\/", "</"))


@needs_index
def test_both_colour_modes_are_declared() -> None:
    """Dark mode is selected, not an automatic inversion, and the toggle must win."""
    html = ui.render_html(ui.build_payload(_index()))
    assert "prefers-color-scheme:dark" in html
    assert ':root[data-theme="dark"]' in html
    assert ':root:where(:not([data-theme="light"]))' in html


@needs_index
def test_coverage_states_are_never_colour_alone() -> None:
    """Status hue plus a glyph plus a text label — the printed and CVD case."""
    html = ui.render_html(ui.build_payload(_index()))
    for glyph in ("●", "○", "▲", "·"):
        assert glyph in html, f"missing glyph for a coverage state: {glyph}"
    assert "Live — a model exists today" in html
    assert "Declared, but no dbt model found" in html


@needs_index
def test_wide_content_scrolls_in_its_own_container() -> None:
    """A 19x58 grid must not make the page body scroll sideways."""
    html = ui.render_html(ui.build_payload(_index()))
    assert ".scroll{overflow-x:auto" in html.replace("\n", "")


@needs_index
def test_fragment_mode_omits_the_document_wrapper_but_keeps_its_styles() -> None:
    """Embeddable, and still styled — a fragment that inherits the host's CSS is a
    fragment that renders differently in every host."""
    fragment = ui.render_html(ui.build_payload(_index()), fragment=True)
    for tag in ("<!doctype", "<html", "<head>", "<body>"):
        assert tag not in fragment.lower()
    assert fragment.lstrip().startswith("<style>")
    assert 'id="payload"' in fragment


# ---------------------------------------------------------------------------------------
# 5. the CLI contract
# ---------------------------------------------------------------------------------------


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "ontology_ui.py"), *args],
        capture_output=True, text=True, cwd=str(REPO), timeout=300, check=False,
    )


@needs_index
def test_check_writes_nothing() -> None:
    before = PAGE.read_bytes() if PAGE.is_file() else None
    _run(["--use-case", "enhanza-analytics", "--check"])
    after = PAGE.read_bytes() if PAGE.is_file() else None
    assert before == after


def test_a_use_case_without_an_ontology_skips_rather_than_fails() -> None:
    """A gate that goes red on a correct state gets switched off within a week."""
    result = _run(["--use-case", "example-order-revenue-mart", "--check", "--format", "json"])
    assert result.returncode == 0
    row = json.loads(result.stdout)["results"][0]
    assert row["status"] == "skip"
    assert "index.json" in row["reason"], "a skip must name what is missing"


def test_an_unknown_use_case_skips_with_a_reason() -> None:
    result = _run(["--use-case", "no-such-use-case", "--check", "--format", "json"])
    assert result.returncode == 0
    assert json.loads(result.stdout)["results"][0]["status"] == "skip"


def test_no_arguments_is_an_error_not_a_silent_no_op() -> None:
    result = _run([])
    assert result.returncode != 0
    assert "--use-case" in result.stderr
