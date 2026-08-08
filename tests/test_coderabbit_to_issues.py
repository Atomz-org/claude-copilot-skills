"""Pins for the CodeRabbit -> issue bridge.

Every test here is on the pure half — parsing and rendering — because that is where being
wrong is silent. A GitHub call that fails is loud; a header regex that quietly matches
nothing files no issues and reports success, and a marker that does not round-trip files
the same finding twice on every review.

The header and title shapes are not invented: they were read off all 91 CodeRabbit review
comments on this repository's nine open pull requests, and the two derivation rules below
were each wrong first against that corpus.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import coderabbit_to_issues as cri  # noqa: E402


SIMPLE = (
    "_🗄️ Data Integrity & Integration_ | _🟠 Major_ | _⚡ Quick win_\n"
    "\n"
    "**Use one executable path for the selected use case.**\n"
    "\n"
    "Both instructions follow a repository-root synchronization command.\n"
)

# The shape that broke two of the derivation rules: the title sits *after* a collapsed
# details block holding a whole shell script, and shares its line with the first sentence.
BEHIND_DETAILS = (
    "_🔒 Security & Privacy_ | _🟠 Major_ | _⚡ Quick win_\n"
    "\n"
    "<details>\n"
    "<summary>🧩 Analysis chain</summary>\n"
    "\n"
    "```shell\n"
    "#!/bin/bash\n"
    "rg -n '**not a title**' scripts/\n"
    "```\n"
    "\n"
    "</details>\n"
    "\n"
    "**Prefix semantic-model and metric IDs by entity type.** When both share a file,\n"
    "`mint()` drops the metric.\n"
)


def _comment(body, cid=1, login="coderabbitai[bot]", **kw):
    row = {"id": cid, "body": body, "user": {"login": login}, "path": "scripts/x.py",
           "line": 12, "html_url": "https://example.invalid/c", "in_reply_to_id": None}
    row.update(kw)
    return row


# ---------------------------------------------------------------------------------------
# The header is what makes a comment a finding
# ---------------------------------------------------------------------------------------


def test_the_header_yields_category_severity_and_effort() -> None:
    assert cri.parse_header(SIMPLE) == (
        "🗄️ Data Integrity & Integration", "major", "⚡ Quick win")


def test_every_severity_marker_coderabbit_uses_is_recognised() -> None:
    for marker, word in (("🔴", "Critical"), ("🟠", "Major"), ("🟡", "Minor"),
                         ("🔵", "Trivial")):
        header = f"_📐 Maintainability_ | _{marker} {word}_ | _⚡ Quick win_\n\n**T.**\n"
        assert cri.parse_header(header)[1] == word.lower(), marker


def test_a_header_without_an_effort_column_still_parses() -> None:
    assert cri.parse_header("_🔒 Security_ | _🟠 Major_\n\n**T.**\n")[1] == "major"


def test_a_comment_with_no_header_is_not_a_finding() -> None:
    """CodeRabbit also posts walkthroughs, summaries and nitpick digests."""
    assert cri.parse_header("## Walkthrough\n\nThis PR adds ...") is None
    assert cri.as_finding(_comment("## Walkthrough\n\nx"), 1) is None


def test_a_human_comment_is_never_a_finding() -> None:
    assert cri.as_finding(_comment(SIMPLE, login="packmaaan"), 1) is None


def test_a_reply_is_never_a_finding() -> None:
    """A reply means somebody is discussing a thread that already has its issue."""
    assert cri.as_finding(_comment(SIMPLE, in_reply_to_id=99), 1) is None


# ---------------------------------------------------------------------------------------
# The title, which was wrong twice against the real corpus
# ---------------------------------------------------------------------------------------


def test_the_title_is_the_first_bolded_line() -> None:
    assert cri.parse_title(SIMPLE) == "Use one executable path for the selected use case."


def test_a_title_sharing_its_line_with_prose_is_still_read() -> None:
    """Matching whole-line `**...**$` dropped 2 of 91 — and they were the two that also
    hide behind a collapsed block, so the fallback would have been a bare file path."""
    assert cri.parse_title(BEHIND_DETAILS) == (
        "Prefix semantic-model and metric IDs by entity type.")


def test_bold_inside_a_fenced_block_is_not_the_title() -> None:
    """CodeRabbit's `<details>` sections carry whole shell scripts; `**` in one is a
    grep pattern, not the finding."""
    assert "not a title" not in (cri.parse_title(BEHIND_DETAILS) or "")


def test_a_finding_whose_title_cannot_be_read_is_refused_not_named_after_its_file() -> None:
    """A file path reads like a title and is not one. The caller reports it instead."""
    headed_only = "_🔒 Security_ | _🟠 Major_ | _⚡ Quick win_\n\nplain prose, no bold.\n"
    assert cri.parse_title(headed_only) is None
    assert cri.as_finding(_comment(headed_only), 1) is None


# ---------------------------------------------------------------------------------------
# Severity floor
# ---------------------------------------------------------------------------------------


def test_the_floor_includes_everything_worse_than_itself() -> None:
    """`--min-severity minor` must not exclude critical, which is the failure mode of an
    ordering read the wrong way round."""
    assert [s for s in cri.SEVERITIES if cri.at_or_above(s, "minor")] == [
        "critical", "major", "minor"]
    assert [s for s in cri.SEVERITIES if cri.at_or_above(s, "major")] == [
        "critical", "major"]


def test_an_unknown_severity_is_excluded_rather_than_assumed() -> None:
    assert cri.at_or_above("spicy", "trivial") is False


# ---------------------------------------------------------------------------------------
# Idempotency — the marker has to survive a round trip
# ---------------------------------------------------------------------------------------


def test_the_marker_round_trips_through_the_rendered_body() -> None:
    """Everything downstream keys on this. If the body renders a marker `markers_in`
    cannot read back, every review files its findings again."""
    finding = cri.as_finding(_comment(SIMPLE, cid=3732681291), 84)
    assert cri.markers_in(cri.issue_body(finding)) == [3732681291]


def test_a_body_with_no_marker_yields_nothing_rather_than_a_zero() -> None:
    assert cri.markers_in("an issue somebody wrote by hand") == []
    assert cri.markers_in("") == []


# ---------------------------------------------------------------------------------------
# Pagination — the documented shape, not the observed one
# ---------------------------------------------------------------------------------------
#
# `gh api --paginate` is documented as emitting one JSON array *per page*: "Each page is a
# separate JSON array. Pass --slurp to wrap all pages of JSON arrays or objects into an
# outer JSON array." The build on this machine merges them instead, so a bare `--paginate`
# parses cleanly here and would return only page one wherever it does not. That failure is
# silent — findings past the hundredth are never filed and no count is short — so both
# fetches use the shape gh states rather than the one it happens to produce.


def _pages(*pages):
    return lambda args, token=None: json.dumps(list(pages))


def test_review_comments_reads_every_page(monkeypatch) -> None:
    seen = {}

    def fake_gh(args, token=None):
        seen["args"] = list(args)
        return json.dumps([[{"id": 1}, {"id": 2}], [{"id": 3}]])

    monkeypatch.setattr(cri, "gh", fake_gh)
    rows = cri.review_comments("o/r", 84)
    assert "--slurp" in seen["args"], "a bare --paginate depends on undocumented merging"
    assert [r["id"] for r in rows] == [1, 2, 3], "pages were not flattened"


def test_a_pull_request_with_no_review_comments_yields_an_empty_list(monkeypatch) -> None:
    """`--slurp` returns `[[]]`, not `[]`, so the flatten has to survive an empty page."""
    monkeypatch.setattr(cri, "gh", _pages([]))
    assert cri.review_comments("o/r", 84) == []


def test_the_existing_issue_lookup_is_paginated_not_capped(monkeypatch) -> None:
    """Any `--limit` here is a silent truncation of the set that stops re-filing.

    The issue this lookup misses gets its finding filed again — and again on every review
    after that, because the duplicate is equally invisible.
    """
    seen = {}

    def fake_gh(args, token=None):
        seen["args"] = list(args)
        return json.dumps([[
            {"number": 5, "state": "open", "title": "t",
             "body": "x " + cri.MARKER.format(id=42)},
            # The issues endpoint returns pull requests too; they carry this key.
            {"number": 6, "state": "open", "title": "pr", "pull_request": {"url": "u"},
             "body": cri.MARKER.format(id=99)},
        ]])

    monkeypatch.setattr(cri, "gh", fake_gh)
    found = cri.existing_issues("o/r")
    assert "--paginate" in seen["args"], "a capped list silently stops deduplicating"
    assert "--slurp" in seen["args"]
    assert not any(a.startswith("--limit") for a in seen["args"])
    assert 42 in found and 99 not in found, "a pull request was mistaken for an issue"
    assert found[42]["state"] == "OPEN", "REST says `open`; the reconciler compares `OPEN`"


def test_the_title_leads_with_the_file_because_a_board_shows_nothing_else() -> None:
    finding = cri.as_finding(_comment(SIMPLE), 84)
    assert cri.issue_title(finding).startswith("x.py: Use one executable path")
    assert not cri.issue_title(finding).endswith(".")


def test_a_very_long_title_is_truncated_to_githubs_limit() -> None:
    body = "_🔒 Security_ | _🟠 Major_ | _⚡ Quick win_\n\n**" + "n" * 400 + "**\n"
    assert len(cri.issue_title(cri.as_finding(_comment(body), 1))) <= 250


# ---------------------------------------------------------------------------------------
# The body carries what an agent needs
# ---------------------------------------------------------------------------------------


def test_the_remediation_prompt_is_carried_into_the_issue() -> None:
    """CodeRabbit ships a machine-readable fix instruction; dropping it means whoever
    picks the issue up has to reopen the thread to get it."""
    body = SIMPLE + (
        "\n<details>\n<summary>🤖 Prompt for AI Agents</summary>\n\n"
        "```\nIn `@scripts/x.py` around lines 3-16, do the thing.\n```\n\n</details>\n")
    finding = cri.as_finding(_comment(body), 84)
    assert "around lines 3-16" in finding.ai_prompt
    assert "around lines 3-16" in cri.issue_body(finding)


def test_the_body_names_the_thread_and_the_severity() -> None:
    rendered = cri.issue_body(cri.as_finding(_comment(SIMPLE), 84))
    assert "**Major**" in rendered
    assert "https://example.invalid/c" in rendered
    assert "scripts/x.py:12" in rendered
    assert "#84" in rendered


def test_the_body_says_to_resolve_the_thread_not_close_the_issue() -> None:
    """Closing by hand strips the reconciler of the state it keys on, and the issue
    reopens on nothing — so the instruction has to be in the artifact, not a runbook."""
    assert "resolve the thread" in cri.issue_body(cri.as_finding(_comment(SIMPLE), 1))


# ---------------------------------------------------------------------------------------
# Live corpus — skipped where there is no network or no gh
# ---------------------------------------------------------------------------------------


def _gh_available() -> bool:
    import shutil
    import subprocess
    if not shutil.which("gh"):
        return False
    return subprocess.run(["gh", "auth", "status"], capture_output=True).returncode == 0


@pytest.mark.skipif(not _gh_available(), reason="no authenticated gh on this machine")
def test_the_parser_reads_every_finding_on_a_real_pull_request() -> None:
    """The corpus these rules were derived from. A regex that silently stops matching
    files nothing and reports success, which is the one failure this cannot afford."""
    repo = "Atomz-org/claude-copilot-skills"
    try:
        comments = cri.review_comments(repo, 84)
    except Exception:  # noqa: BLE001 - offline, rate-limited, or repo renamed
        pytest.skip("cannot reach the repository")
    headed = [c for c in comments
              if not c.get("in_reply_to_id")
              and "coderabbit" in (c.get("user") or {}).get("login", "").lower()
              and cri.parse_header(c.get("body") or "")]
    if not headed:
        pytest.skip("no CodeRabbit findings on this pull request any more")
    assert all(cri.as_finding(c, 84) for c in headed), "a headed finding failed to parse"
