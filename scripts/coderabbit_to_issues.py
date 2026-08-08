#!/usr/bin/env python3
"""CodeRabbit review findings -> GitHub issues, and back again when they resolve.

CodeRabbit posts each finding as a pull-request *review comment* whose first line is a
fixed header:

    _🔒 Security & Privacy_ | _🟠 Major_ | _⚡ Quick win_

A review thread is the right place to *discuss* a finding and the wrong place to *track*
one: it is invisible from a board, it disappears when the PR is closed, and nothing counts
it. This moves the ones worth tracking — Major and Minor by default — into issues on a
GitHub Project, and closes them again when the thread they came from is resolved.

Two directions, one script:

    --pr N / --all-open   findings -> issues        (create, idempotent)
    --reconcile           resolved threads -> closed issues

Both are no-ops without `--write`. That is the default because this writes to a real
tracker: a dry run prints exactly what it would do and exits 0.

What makes it idempotent
------------------------

Every issue body carries a marker naming the review comment it came from:

    <!-- coderabbit-comment-id: 3732681291 -->

The mapping is rebuilt by **listing** the `coderabbit` label and parsing bodies, never by
GitHub's search index. Search lags behind writes by up to a minute, and CodeRabbit posts a
whole review at once — so a search-backed lookup duplicates the issues it was added to
prevent, intermittently, under exactly the load it will meet in practice.

What it will not do
-------------------

**A finding with no severity header is not a finding.** CodeRabbit also posts summaries,
walkthroughs, and nitpick digests as ordinary comments. Only review comments carrying the
header become issues, and only at or above `--min-severity`.

**A reply is never a finding.** `in_reply_to_id` means somebody is discussing an existing
thread, and the thread already has its issue.

**An unavailable project is not a failure** (the rule the rest of this repository runs on).
`GITHUB_TOKEN` cannot write to an organisation ProjectV2 — that needs a PAT with `project`
scope in `CODERABBIT_PROJECT_TOKEN`. Without it the issue is still created and the run says
the project step was skipped, rather than failing and creating nothing.

Usage:
    python3 scripts/coderabbit_to_issues.py --repo O/R --pr 84
    python3 scripts/coderabbit_to_issues.py --repo O/R --all-open --write
    python3 scripts/coderabbit_to_issues.py --repo O/R --reconcile --write
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

# The header CodeRabbit puts on the first line of every finding. Validated against every
# review comment on this repository's open pull requests: 28 of 28 parse.
HEADER = re.compile(
    r"^_([^_]+)_\s*\|\s*_(🔴|🟠|🟡|🔵|🟢|⚪)\s*([A-Za-z]+)_(?:\s*\|\s*_([^_]+)_)?\s*$"
)

# The finding's one-line title. Anchored at line start rather than matched whole-line: two
# of those 28 put the title and its first sentence on one line, and requiring `$` dropped
# both — and they were the two that also hide behind a collapsed `<details>` block, so the
# fallback would have been a file path.
BOLD = re.compile(r"^\*\*(.+?)\*\*")

# CodeRabbit's own machine-readable remediation, which is the useful half for an agent.
AI_PROMPT = re.compile(
    r"<summary>🤖 Prompt for AI Agents</summary>\s*```(.*?)```", re.S)

MARKER = "<!-- coderabbit-comment-id: {id} -->"
MARKER_RE = re.compile(r"<!--\s*coderabbit-comment-id:\s*(\d+)\s*-->")

LABEL = "coderabbit"
SEVERITY_LABEL = "severity: {severity}"

# Ordered worst-first. `--min-severity minor` therefore means "major and minor".
SEVERITIES = ("critical", "major", "minor", "trivial")

PROJECT_TOKEN_ENV = "CODERABBIT_PROJECT_TOKEN"


# ---------------------------------------------------------------------------------------
# Parsing — pure, and the only part with interesting behaviour
# ---------------------------------------------------------------------------------------


@dataclass
class Finding:
    comment_id: int
    severity: str
    category: str
    effort: str
    title: str
    path: str
    line: Optional[int]
    url: str
    pr: int
    body: str
    ai_prompt: str = ""

    @property
    def marker(self) -> str:
        return MARKER.format(id=self.comment_id)


def parse_header(body: str) -> Optional[Tuple[str, str, str]]:
    """(category, severity, effort) from the first line, or None if it is not a finding."""
    first = body.splitlines()[0].strip() if body.strip() else ""
    match = HEADER.match(first)
    if not match:
        return None
    return match.group(1).strip(), match.group(3).strip().lower(), (match.group(4) or "").strip()


def parse_title(body: str) -> Optional[str]:
    """The first bolded line outside a fenced block.

    Fenced blocks are skipped because CodeRabbit's `<details>` sections carry whole shell
    scripts, and a `**` inside one is markdown emphasis in a comment, not the finding's
    title.
    """
    fenced = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = BOLD.match(stripped)
        if match:
            return match.group(1).strip()
    return None


def parse_ai_prompt(body: str) -> str:
    match = AI_PROMPT.search(body)
    return match.group(1).strip() if match else ""


def as_finding(comment: Dict[str, Any], pr: int) -> Optional[Finding]:
    """One review comment -> a Finding, or None where it is not one."""
    if comment.get("in_reply_to_id"):
        return None
    if not re.search("coderabbit", (comment.get("user") or {}).get("login", ""), re.I):
        return None
    body = comment.get("body") or ""
    header = parse_header(body)
    if header is None:
        return None
    category, severity, effort = header
    title = parse_title(body)
    if not title:
        # Never invent one: a finding whose title cannot be read is reported by the caller
        # rather than filed under its file path, which reads like a real title and is not.
        return None
    return Finding(
        comment_id=int(comment["id"]), severity=severity, category=category, effort=effort,
        title=title, path=comment.get("path") or "", line=comment.get("line"),
        url=comment.get("html_url") or "", pr=pr, body=body,
        ai_prompt=parse_ai_prompt(body),
    )


def at_or_above(severity: str, floor: str) -> bool:
    if severity not in SEVERITIES:
        return False
    return SEVERITIES.index(severity) <= SEVERITIES.index(floor)


def issue_title(finding: Finding) -> str:
    """`path: Title`, truncated to GitHub's limit.

    The path leads because a board shows titles and nothing else, and "Guard against a
    parent model that is absent" is not locatable on its own.
    """
    stem = finding.path.rsplit("/", 1)[-1] if finding.path else f"PR #{finding.pr}"
    title = f"{stem}: {finding.title}".rstrip(".")
    return title if len(title) <= 250 else title[:247] + "..."


def issue_body(finding: Finding) -> str:
    where = finding.path + (f":{finding.line}" if finding.line else "")
    out = [
        f"**{finding.severity.title()}** · {finding.category}"
        + (f" · {finding.effort}" if finding.effort else ""),
        "",
        f"Found by CodeRabbit on #{finding.pr}, in `{where}`.",
        "",
        f"> {finding.title}",
        "",
        f"[Open the review thread]({finding.url})",
    ]
    if finding.ai_prompt:
        out += ["", "<details><summary>CodeRabbit's remediation prompt</summary>", "",
                "```", finding.ai_prompt, "```", "", "</details>"]
    out += [
        "",
        "---",
        "*Filed by `scripts/coderabbit_to_issues.py`. It closes automatically when the "
        "review thread is resolved — resolve the thread, do not close this by hand, or "
        "the reconciler will have nothing to key on.*",
        "",
        finding.marker,
    ]
    return "\n".join(out)


def markers_in(text: str) -> List[int]:
    return [int(m) for m in MARKER_RE.findall(text or "")]


# ---------------------------------------------------------------------------------------
# GitHub — thin wrappers, so the logic above stays testable
# ---------------------------------------------------------------------------------------


def gh(args: Sequence[str], token: Optional[str] = None) -> str:
    env = dict(os.environ)
    if token:
        env["GH_TOKEN"] = token
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, env=env, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip()[:500])
    return proc.stdout


def gh_json(args: Sequence[str], token: Optional[str] = None) -> Any:
    return json.loads(gh(args, token) or "null")


def open_pull_requests(repo: str) -> List[int]:
    rows = gh_json(["pr", "list", "--repo", repo, "--state", "open", "--limit", "100",
                    "--json", "number"]) or []
    return [int(r["number"]) for r in rows]


def review_comments(repo: str, pr: int) -> List[Dict[str, Any]]:
    return gh_json(["api", "--paginate",
                    f"repos/{repo}/pulls/{pr}/comments?per_page=100"]) or []


THREADS_QUERY = """
query($owner:String!, $name:String!, $pr:Int!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    pullRequest(number:$pr) {
      state
      reviewThreads(first:100, after:$cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { isResolved comments(first:1) { nodes { databaseId } } }
      }
    }
  }
}
"""


def resolved_comment_ids(repo: str, pr: int) -> Tuple[set, str]:
    """({comment id whose thread is resolved}, pull request state)."""
    owner, name = repo.split("/", 1)
    resolved: set = set()
    cursor, state = None, "UNKNOWN"
    while True:
        args = ["api", "graphql", "-f", f"query={THREADS_QUERY}",
                "-F", f"owner={owner}", "-F", f"name={name}", "-F", f"pr={pr}"]
        if cursor:
            args += ["-F", f"cursor={cursor}"]
        data = gh_json(args)["data"]["repository"]["pullRequest"]
        state = data["state"]
        threads = data["reviewThreads"]
        for node in threads["nodes"]:
            comments = node["comments"]["nodes"]
            if node["isResolved"] and comments:
                resolved.add(int(comments[0]["databaseId"]))
        if not threads["pageInfo"]["hasNextPage"]:
            return resolved, state
        cursor = threads["pageInfo"]["endCursor"]


def existing_issues(repo: str) -> Dict[int, Dict[str, Any]]:
    """{review comment id: issue}, built by listing the label rather than by searching.

    Search is eventually consistent and CodeRabbit posts a whole review at once, so a
    search-backed lookup duplicates issues intermittently under exactly the load this meets.

    Paginated through the REST endpoint rather than `gh issue list --limit N`. Any limit is
    a silent truncation of *this* set, and this set is what stops the script re-filing:
    the 1001st issue is not seen, so its finding is filed again, and again on every review
    after that. `--paginate` merges the pages into one array — the documented behaviour for
    a JSON-array response, and the reason `--slurp` (which wraps pages instead, and would
    need flattening) is wrong here.
    """
    rows = gh_json(["api", "--paginate",
                    f"repos/{repo}/issues?labels={LABEL}&state=all&per_page=100"]) or []
    out: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        # The issues endpoint returns pull requests as well; they carry this key.
        if row.get("pull_request"):
            continue
        issue = {
            "number": row["number"],
            "body": row.get("body") or "",
            # REST says `open`/`closed`; `gh issue list --json` says `OPEN`/`CLOSED`, and
            # the reconciler compares against the upper form.
            "state": (row.get("state") or "").upper(),
            "title": row.get("title") or "",
        }
        for comment_id in markers_in(issue["body"]):
            out[comment_id] = issue
    return out


def ensure_labels(repo: str, write: bool) -> None:
    """Create the labels this script files under. `gh label create` is not idempotent, so
    the failure is swallowed — the only reason it fails here is that it already exists."""
    wanted = [(LABEL, "d4c5f9", "Filed from a CodeRabbit review finding")]
    wanted += [(SEVERITY_LABEL.format(severity=s), c, f"CodeRabbit {s} finding")
               for s, c in (("critical", "b60205"), ("major", "d93f0b"),
                            ("minor", "fbca04"), ("trivial", "c2e0c6"))]
    for name, colour, description in wanted:
        if not write:
            continue
        try:
            gh(["label", "create", name, "--repo", repo, "--color", colour,
                "--description", description])
        except RuntimeError:
            pass


ADD_TO_PROJECT = """
mutation($project:ID!, $content:ID!) {
  addProjectV2ItemById(input:{projectId:$project, contentId:$content}) { item { id } }
}
"""


def project_id(owner: str, number: int, token: str) -> str:
    for scope in ("organization", "user"):
        query = ("{%s(login:\"%s\"){projectV2(number:%d){id}}}" % (scope, owner, number))
        try:
            data = gh_json(["api", "graphql", "-f", f"query={query}"], token)["data"]
        except RuntimeError:
            continue
        holder = (data or {}).get(scope) or {}
        if holder.get("projectV2"):
            return holder["projectV2"]["id"]
    raise RuntimeError(f"no ProjectV2 #{number} on {owner}")


def add_to_project(node_id: str, project: str, token: str) -> None:
    gh(["api", "graphql", "-f", f"query={ADD_TO_PROJECT}",
        "-F", f"project={project}", "-F", f"content={node_id}"], token)


# ---------------------------------------------------------------------------------------
# The two directions
# ---------------------------------------------------------------------------------------


def collect(repo: str, prs: Sequence[int], floor: str) -> Tuple[List[Finding], List[str]]:
    findings: List[Finding] = []
    unreadable: List[str] = []
    for pr in prs:
        for comment in review_comments(repo, pr):
            finding = as_finding(comment, pr)
            if finding is None:
                body = comment.get("body") or ""
                login = (comment.get("user") or {}).get("login", "")
                if (re.search("coderabbit", login, re.I) and not comment.get("in_reply_to_id")
                        and parse_header(body) and not parse_title(body)):
                    unreadable.append(f"#{pr} comment {comment['id']}: header but no title")
                continue
            if at_or_above(finding.severity, floor):
                findings.append(finding)
    return findings, unreadable


def create(repo: str, prs: Sequence[int], floor: str, write: bool,
           project: Optional[int]) -> Dict[str, Any]:
    findings, unreadable = collect(repo, prs, floor)
    known = existing_issues(repo)
    token = os.environ.get(PROJECT_TOKEN_ENV, "").strip()

    created: List[Dict[str, Any]] = []
    skipped = [f.comment_id for f in findings if f.comment_id in known]
    todo = [f for f in findings if f.comment_id not in known]

    ensure_labels(repo, write)
    resolved_project: Optional[str] = None
    project_note = ""
    if project and todo:
        if not token:
            project_note = (f"no ${PROJECT_TOKEN_ENV} — issues created, project #{project} "
                            "not touched (GITHUB_TOKEN cannot write an org ProjectV2)")
        elif write:
            try:
                resolved_project = project_id(repo.split("/", 1)[0], project, token)
            except RuntimeError as exc:
                project_note = f"project #{project} unavailable: {exc}"

    for finding in todo:
        entry = {"comment_id": finding.comment_id, "severity": finding.severity,
                 "pr": finding.pr, "title": issue_title(finding)}
        if write:
            url = gh(["issue", "create", "--repo", repo,
                      "--title", issue_title(finding), "--body", issue_body(finding),
                      "--label", LABEL,
                      "--label", SEVERITY_LABEL.format(severity=finding.severity)]).strip()
            entry["url"] = url.splitlines()[-1] if url else ""
            if resolved_project and entry["url"]:
                number = entry["url"].rsplit("/", 1)[-1]
                node = gh_json(["issue", "view", number, "--repo", repo, "--json", "id"])
                try:
                    add_to_project(node["id"], resolved_project, token)
                    entry["project"] = True
                except RuntimeError as exc:
                    project_note = f"project add failed: {exc}"
        created.append(entry)

    return {"action": "create", "pull_requests": list(prs), "min_severity": floor,
            "findings": len(findings), "created": created, "already_filed": len(skipped),
            "unreadable": unreadable, "project_note": project_note, "written": write}


def reconcile(repo: str, prs: Sequence[int], write: bool) -> Dict[str, Any]:
    """Close every issue whose review thread is resolved, or whose PR closed unmerged."""
    known = existing_issues(repo)
    open_issues = {cid: row for cid, row in known.items() if row.get("state") == "OPEN"}
    closed: List[Dict[str, Any]] = []
    for pr in prs:
        resolved, state = resolved_comment_ids(repo, pr)
        # A pull request closed without merging takes its findings with it: the code they
        # were about was never shipped. Closed `not planned`, so it stays distinguishable
        # from a finding somebody actually dealt with. Its comment ids are fetched once,
        # and only when the case arises — the resolved path needs no second call at all.
        abandoned = state == "CLOSED"
        on_this_pr = (
            {int(c["id"]) for c in review_comments(repo, pr)} if abandoned else set())
        for comment_id, row in list(open_issues.items()):
            resolved_here = comment_id in resolved
            if not resolved_here and not (abandoned and comment_id in on_this_pr):
                continue
            reason = "completed" if resolved_here else "not planned"
            entry = {"issue": row["number"], "comment_id": comment_id, "reason": reason,
                     "pr": pr}
            if write:
                gh(["issue", "close", str(row["number"]), "--repo", repo,
                    "--reason", reason,
                    "--comment", (f"The CodeRabbit thread on #{pr} was resolved."
                                  if resolved_here
                                  else f"#{pr} was closed without merging.")])
            closed.append(entry)
            open_issues.pop(comment_id, None)
    return {"action": "reconcile", "pull_requests": list(prs),
            "open_before": len(known), "closed": closed, "written": write}


# ---------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--repo", required=True, help="owner/name")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--pr", type=int, help="one pull request")
    target.add_argument("--all-open", action="store_true", help="every open pull request")
    parser.add_argument("--reconcile", action="store_true",
                        help="close issues whose thread is resolved, instead of creating")
    parser.add_argument("--min-severity", choices=SEVERITIES, default="minor")
    parser.add_argument("--project", type=int, help="ProjectV2 number to add issues to")
    parser.add_argument("--write", action="store_true", help="actually create or close")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    prs = [args.pr] if args.pr else open_pull_requests(args.repo)
    payload = (reconcile(args.repo, prs, args.write) if args.reconcile
               else create(args.repo, prs, args.min_severity, args.write, args.project))

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    done, todo = ("closed", "close") if args.reconcile else ("created", "create")
    rows = payload.get(done) or []
    scope = ", ".join(f"#{p}" for p in payload["pull_requests"]) or "nothing"
    print(f"{scope}: {len(rows)} issue(s) {done if payload['written'] else 'to ' + todo}")
    for row in rows[:60]:
        if args.reconcile:
            print(f"  #{row['issue']} <- comment {row['comment_id']} ({row['reason']})")
        else:
            print(f"  [{row['severity']}] {row['title']}")
    if not args.reconcile:
        print(f"  {payload['findings']} finding(s) at or above {payload['min_severity']}, "
              f"{payload['already_filed']} already filed")
        for reason in payload["unreadable"]:
            print(f"  [unreadable] {reason}")
        if payload["project_note"]:
            print(f"  note: {payload['project_note']}")
    if not payload["written"]:
        print("\ndry run — nothing written; add --write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
