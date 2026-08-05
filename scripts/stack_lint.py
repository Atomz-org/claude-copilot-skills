#!/usr/bin/env python3
"""Check a branch against the stacked-delivery grammar, and the one rule stacks need here.

Two things this repository cannot learn from GitHub's stack feature itself:

1. **The branch grammar.** `<type>/<TICKET>-<lane>-<topic>-<NN>-<layer>` carries the lane
   (platform vs a client code) and the layer ordinal. GitHub does not care; humans, CODEOWNERS
   routing, and `git branch --list` ordering all do. The existing gate only checks the
   `<type>/` prefix, so everything after it has been unenforced.

2. **Generated artifacts belong to the top layer only.** Every layer that runs
   `use_case_sync.py` rewrites the same wholesale-regenerated files, so a stack whose middle
   layers commit artifacts collides with itself — the conflict class `.gitattributes`
   documents, produced internally by one delivery instead of by two. Concentrating
   regeneration in the top layer keeps lower diffs reviewable and leaves one place for the
   currency gate to pass.

Rule 2 is checked against *sibling branches*: layers sharing a ticket, lane, and topic form
one stack, and any layer that is not the highest ordinal among them must not touch a
generated path. With no siblings there is no stack, so the check reports `skip` rather than
inventing a verdict.

Advisory by default — `--check` is the gate form. A branch that does not parse is reported,
never rewritten: renaming someone's branch out from under them loses their push.

Usage:
    python3 scripts/stack_lint.py                      # the current branch
    python3 scripts/stack_lint.py --branch <name> --base main
    python3 scripts/stack_lint.py --check --format json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent

TYPES = ("feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci",
         "chore", "revert")

# <type>/<TICKET>-<lane>-<topic>-<NN>-<layer>. The ticket may be `no-ticket`, which is why
# the lane is matched positionally rather than by hunting for the first digit run.
GRAMMAR = re.compile(
    r"^(?P<type>" + "|".join(TYPES) + r")/"
    r"(?P<ticket>[A-Za-z0-9]+-[A-Za-z0-9]+|no-ticket)-"
    r"(?P<lane>[a-z0-9]+)-"
    r"(?P<topic>[a-z0-9][a-z0-9-]*?)-"
    r"(?P<ordinal>\d{2})-"
    r"(?P<layer>[a-z0-9-]+)$"
)

# The legacy form the repository used before stacks: <type>/<ticket>-<description>.
# Still valid for a standalone change; it simply is not a stack layer.
LEGACY = re.compile(r"^(?P<type>" + "|".join(TYPES) + r")/[A-Za-z0-9._-]+$")

# Wholesale-regenerated paths. Kept in step with `.gitattributes` merge=generated plus the
# activation mirror, which that file cannot express as a merge rule.
GENERATED_GLOBS = (
    "skill-packs/*/use-cases/*/artifacts/graphify-fragment.json",
    "skill-packs/*/use-cases/*/ontology/column-memory.json",
    "skill-packs/*/use-cases/*/ontology/index.json",
    "skill-packs/*/use-cases/*/ontology/**/*.ttl",
    "skill-packs/*/use-cases/*/dbt_project/seeds/sample/*.csv",
    "skill-packs/*/use-cases/*/wren/**",
    ".claude/**",
    "references/**",
    "templates/**",
    "graphify-out/**",
)


def git(*args: str) -> str:
    proc = subprocess.run(["git", *args], capture_output=True, text=True, cwd=REPO)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def current_branch() -> str:
    return git("branch", "--show-current")


def parse(branch: str) -> Optional[Dict[str, str]]:
    m = GRAMMAR.match(branch)
    return m.groupdict() if m else None


def is_generated(path: str) -> bool:
    p = Path(path)
    for glob in GENERATED_GLOBS:
        if p.full_match(glob) if hasattr(p, "full_match") else _match(p, glob):
            return True
    return False


def _match(path: Path, glob: str) -> bool:
    """PurePath.full_match is 3.13+; this repository targets 3.11."""
    import fnmatch
    # `**` must cross directory separators, which fnmatch does not do on its own.
    pattern = glob.replace("**", "\x00").replace("*", "[^/]*").replace("\x00", ".*")
    return re.fullmatch(pattern, str(path)) is not None


def sibling_layers(parsed: Dict[str, str]) -> List[int]:
    """Ordinals of every branch sharing this one's ticket, lane, and topic."""
    prefix = f"{parsed['type']}/{parsed['ticket']}-{parsed['lane']}-{parsed['topic']}-"
    names = git("branch", "--all", "--format=%(refname:short)").splitlines()
    ordinals: List[int] = []
    for name in names:
        name = name.strip()
        for candidate in (name, name.replace("origin/", "", 1)):
            if candidate.startswith(prefix):
                got = parse(candidate)
                if got:
                    ordinals.append(int(got["ordinal"]))
                break
    return sorted(set(ordinals))


def changed_files(base: str, branch: str) -> List[str]:
    merge_base = git("merge-base", base, branch)
    if not merge_base:
        return []
    out = git("diff", "--name-only", f"{merge_base}..{branch}")
    return [line for line in out.splitlines() if line.strip()]


def lint(branch: str, base: str) -> Dict[str, Any]:
    findings: List[Dict[str, str]] = []
    parsed = parse(branch)

    if branch in ("main", "master"):
        return {
            "branch": branch, "ok": False, "findings": [{
                "check": "branch-grammar", "severity": "error",
                "detail": "on the trunk; this repository does not accept commits to main",
                "fix": "git switch -c feat/<TICKET>-<lane>-<topic>-01-<layer>",
            }], "stack": None,
        }

    if not parsed:
        severity = "warn" if LEGACY.match(branch) else "error"
        detail = (
            "valid legacy name, but not a stack layer — fine for a standalone change"
            if severity == "warn" else
            "does not match <type>/<TICKET>-<lane>-<topic>-<NN>-<layer>"
        )
        findings.append({
            "check": "branch-grammar", "severity": severity, "detail": detail,
            "fix": "see docs/BRANCHING_STRATEGY.md, or open the Stacked Delivery Plan issue "
                   "template to generate names",
        })
        return {
            "branch": branch,
            "ok": severity != "error",
            "findings": findings,
            "stack": None,
        }

    siblings = sibling_layers(parsed)
    ordinal = int(parsed["ordinal"])
    top = max(siblings) if siblings else ordinal
    stack = {
        "ticket": parsed["ticket"], "lane": parsed["lane"], "topic": parsed["topic"],
        "ordinal": ordinal, "layers": siblings, "is_top": ordinal >= top,
    }

    if len(siblings) > 4:
        findings.append({
            "check": "stack-size", "severity": "warn",
            "detail": f"{len(siblings)} layers; four is the stated maximum",
            "fix": "split the delivery into two stacks",
        })

    # The rule that makes stacks work here.
    if len(siblings) > 1 and ordinal < top:
        touched = [f for f in changed_files(base, branch) if is_generated(f)]
        if touched:
            findings.append({
                "check": "artifact-layer", "severity": "error",
                "detail": (
                    f"layer {ordinal:02d} of {top:02d} commits {len(touched)} generated "
                    f"file(s) (e.g. {touched[0]}); regeneration belongs to the top layer"
                ),
                "fix": "git checkout <parent> -- <paths>, then regenerate in the top layer "
                       "with python3 scripts/use_case_sync.py --use-case <slug>",
            })

    return {
        "branch": branch,
        "ok": not any(f["severity"] == "error" for f in findings),
        "findings": findings,
        "stack": stack,
    }


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Lint a branch against the stacked-delivery grammar and layer rules.")
    p.add_argument("--branch", help="default: the current branch")
    p.add_argument("--base", default="origin/main", help="trunk to diff against")
    p.add_argument("--check", action="store_true", help="exit 1 on any error finding")
    p.add_argument("--format", choices=("text", "json"), default="text")
    args = p.parse_args(argv)

    branch = args.branch or current_branch()
    if not branch:
        print("not on a branch (detached HEAD); nothing to lint")
        return 0

    base = args.base
    if not git("rev-parse", "--verify", base):
        base = "main" if git("rev-parse", "--verify", "main") else branch

    result = lint(branch, base)

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False))
    else:
        stack = result["stack"]
        if stack:
            layers = ", ".join(f"{n:02d}" for n in stack["layers"]) or "01"
            position = "top" if stack["is_top"] else f"layer {stack['ordinal']:02d}"
            print(f"{branch}\n  stack {stack['ticket']} / {stack['lane']} / "
                  f"{stack['topic']} — layers [{layers}], this is the {position}")
        else:
            print(branch)
        for f in result["findings"]:
            print(f"  {f['severity'].upper():<5} {f['check']}: {f['detail']}")
            print(f"        fix: {f['fix']}")
        if not result["findings"]:
            print("  ok    grammar and layer rules satisfied")

    return 1 if (args.check and not result["ok"]) else 0


if __name__ == "__main__":
    sys.exit(main())
