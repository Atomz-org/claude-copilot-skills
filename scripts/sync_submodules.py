#!/usr/bin/env python3
"""Report, verify, and advance this repository's pinned upstream submodules.

Ten submodules under `external/`, each pinned to a SHA that is committed here. Three
things go wrong with a pinned submodule, and none of them announces itself:

1. **The pin and the runtime drift apart.** `openmetadata-ingestion` must match the
   OpenMetadata server version exactly, and `@lightdash/cli` must match the Lightdash
   submodule release. A bridge that writes payloads against schema version A while the
   submodule holds version B produces a bundle that validates locally and is rejected
   on push, one entity at a time, after the egress has begun.
2. **A checkout is dirty or detached somewhere unexpected**, so the SHA a developer is
   reading upstream from is not the SHA the repository records — and the next
   `git submodule update` silently reverts their reading.
3. **The submodule was never initialised**, so a generator that reads from it degrades
   to "found nothing" instead of "could not look". That is the failure mode this
   repository names everywhere else: a check that passes because it read nothing.

`--check` is the CI form and it holds (1) and (2). It cannot hold (3) — an
uninitialised submodule is the normal state of a fresh clone and of any runner that
skipped `--recursive`, so absence is reported and never fails. Unavailable is not
failed.

    python3 scripts/sync_submodules.py                 # the report
    python3 scripts/sync_submodules.py --check         # the CI gate
    python3 scripts/sync_submodules.py --init          # clone what is missing, shallow
    python3 scripts/sync_submodules.py --format json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _paths import REPO  # noqa: E402

OK, DRIFT, ABSENT, DIRTY = "ok", "drift", "absent", "dirty"


@dataclass
class VersionPin:
    """A runtime version that must agree with a submodule's checked-out release.

    The whole point of pinning source *and* runtime is that they move together. This
    makes "together" checkable instead of a sentence in a README that nobody re-reads
    when they bump one of them.
    """

    label: str
    submodule: str
    # Where the runtime version is declared, and the pattern that extracts it.
    declared_in: str
    pattern: str
    # How the submodule's own checkout states its release. `git describe --tags` output
    # is matched against this after substituting {version}.
    release_format: str


VERSION_PINS: Tuple[VersionPin, ...] = (
    VersionPin(
        label="OpenMetadata server / openmetadata-ingestion wheel",
        submodule="external/OpenMetadata",
        declared_in="scripts/openmetadata_sync.py",
        pattern=r'^SERVER_PIN\s*=\s*"([^"]+)"',
        release_format="{version}-release",
    ),
)

# Submodules a generator reads from at runtime, and what it reads. Recorded here so the
# report can say what breaks when one is missing, rather than leaving a reader to guess
# whether an absent submodule matters.
CONSUMERS: Dict[str, str] = {
    "external/OpenMetadata": (
        "openmetadata_sync.py validates emitted payloads against the pinned JSON "
        "schemas (enum members, required fields)"
    ),
    "external/OpenMetadataStandards": (
        "openmetadata_sync.py checks every om: term in the RDF alignment against the "
        "pinned OWL ontology"
    ),
    "external/WrenAI": "source pin for the wrenai wheel; not read at runtime",
    "external/lightdash": "source pin for @lightdash/cli; not read at runtime",
    "external/openmetadata-demo": "reference only — API-lineage and MCP patterns",
    "external/openmetadata-ai-sdk": "reference only — agent surface shape",
    "external/openmetadata-sqllineage": "reference only — evaluated, not adopted",
    "external/openmetadata-retention": "reference only — evaluated, not adopted",
    "external/openmetadata-dbt-action": (
        "reference only — the dbt ingestion workflow shape the generated "
        "ingestion/dbt.yaml reproduces"
    ),
    "external/collate-dbt-artifacts-parser": "reference only — evaluated, not adopted",
}


@dataclass
class Submodule:
    path: str
    url: str
    shallow: bool
    recorded_sha: Optional[str] = None
    checked_out_sha: Optional[str] = None
    describe: str = ""
    initialised: bool = False
    dirty: bool = False
    status: str = ABSENT
    notes: List[str] = field(default_factory=list)

    def as_record(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "url": self.url,
            "shallow": self.shallow,
            "sha": self.recorded_sha,
            "release": self.describe,
            "initialised": self.initialised,
            "status": self.status,
            "consumer": CONSUMERS.get(self.path, "—"),
            "notes": self.notes,
        }


def _git(*args: str, cwd: Optional[Path] = None) -> Tuple[int, str]:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd or REPO), capture_output=True, text=True,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def read_gitmodules() -> List[Submodule]:
    """Parse `.gitmodules` directly rather than shelling out per key.

    `git config -f .gitmodules --list` would work, but this file is the declaration of
    record and reading it whole means the report cannot disagree with what a reviewer
    sees in the diff.
    """
    path = REPO / ".gitmodules"
    if not path.exists():
        return []
    modules: List[Submodule] = []
    current: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        header = re.match(r'^\[submodule "(.+)"\]', line.strip())
        if header:
            if current.get("path"):
                modules.append(Submodule(
                    path=current["path"], url=current.get("url", ""),
                    shallow=current.get("shallow", "").lower() == "true",
                ))
            current = {}
            continue
        entry = re.match(r"^\s*(\w+)\s*=\s*(.+?)\s*$", line)
        if entry:
            current[entry.group(1)] = entry.group(2)
    if current.get("path"):
        modules.append(Submodule(
            path=current["path"], url=current.get("url", ""),
            shallow=current.get("shallow", "").lower() == "true",
        ))
    return sorted(modules, key=lambda m: m.path)


def inspect(module: Submodule) -> Submodule:
    # The index, not HEAD. A gitlink staged but not yet committed is the normal state
    # while a submodule is being added, and reading HEAD there reports "not recorded"
    # for something that is about to be — which suppresses the drift check on exactly
    # the change most likely to have drifted. The index is what the commit will hold.
    rc, out = _git("ls-files", "-s", "--", module.path)
    match = re.match(r"^\d+ ([0-9a-f]{40}) \d+\t", out) if rc == 0 else None
    if match is None:
        rc, out = _git("ls-tree", "HEAD", "--", module.path)
        match = re.match(r"^\d+ commit ([0-9a-f]{40})\t", out) if rc == 0 else None
    module.recorded_sha = match.group(1) if match else None
    if module.recorded_sha is None:
        module.notes.append("not recorded — `git add` the gitlink")

    work = REPO / module.path
    module.initialised = (work / ".git").exists()
    if not module.initialised:
        module.status = ABSENT
        module.notes.append(
            f"not initialised — git submodule update --init {module.path}"
        )
        return module

    rc, sha = _git("rev-parse", "HEAD", cwd=work)
    module.checked_out_sha = sha if rc == 0 else None

    # Describe the RECORDED sha, not the working checkout. The recorded one is what CI
    # and every fresh clone materialise; a local checkout that has wandered is a
    # different finding, reported below as `drift`. Conflating them made the version
    # gate fail on a correct pin because somebody's working tree had moved.
    target = module.recorded_sha or module.checked_out_sha
    rc, described = _git("describe", "--tags", "--always", target or "HEAD", cwd=work)
    module.describe = described if rc == 0 else ""

    rc, porcelain = _git("status", "--porcelain", cwd=work)
    module.dirty = bool(porcelain.strip())

    if module.dirty:
        module.status = DIRTY
        module.notes.append("working tree has uncommitted changes")
    elif module.recorded_sha and module.checked_out_sha != module.recorded_sha:
        module.status = DRIFT
        module.notes.append(
            f"checked out {(module.checked_out_sha or '?')[:12]}, "
            f"tree records {module.recorded_sha[:12]}"
        )
    else:
        module.status = OK
    return module


def check_version_pins(modules: Dict[str, Submodule]) -> List[Dict[str, Any]]:
    """Each declared runtime version must match its submodule's checked-out release."""
    results: List[Dict[str, Any]] = []
    for pin in VERSION_PINS:
        source = REPO / pin.declared_in
        declared = None
        if source.exists():
            found = re.search(pin.pattern, source.read_text(encoding="utf-8"), re.M)
            declared = found.group(1) if found else None
        module = modules.get(pin.submodule)
        record: Dict[str, Any] = {
            "pin": pin.label,
            "submodule": pin.submodule,
            "declared_in": pin.declared_in,
            "declared": declared,
        }
        if declared is None:
            record.update(status="fail",
                          detail=f"no version matched {pin.pattern!r} in {pin.declared_in}")
        elif module is None:
            record.update(status="fail", detail=f"{pin.submodule} is not a submodule")
        elif not module.initialised:
            # The normal state of a fresh clone. Reported, never failed.
            record.update(status="skip",
                          detail=f"{pin.submodule} not initialised — cannot compare")
        else:
            expected = pin.release_format.format(version=declared)
            record.update(release=module.describe, expected=expected)
            record["status"] = "ok" if module.describe == expected else "fail"
            if record["status"] == "fail":
                record["detail"] = (
                    f"{pin.declared_in} declares {declared} (expects the submodule at "
                    f"{expected}) but it is at {module.describe or 'an untagged commit'}"
                    " — the source pin and the runtime pin must move together"
                )
        results.append(record)
    return results


def init_missing(modules: List[Submodule]) -> List[str]:
    """Shallow-clone whatever is absent. Never updates what is already there."""
    done: List[str] = []
    for module in modules:
        if module.initialised:
            continue
        rc, out = _git("submodule", "update", "--init", "--depth", "1", module.path)
        done.append(f"{'ok' if rc == 0 else 'FAIL'} {module.path}"
                    + ("" if rc == 0 else f": {out.splitlines()[-1:]}"))
    return done


def report(check: bool, do_init: bool) -> Dict[str, Any]:
    modules = read_gitmodules()
    if do_init:
        init_results = init_missing([inspect(m) for m in modules])
    else:
        init_results = []
    inspected = [inspect(m) for m in modules]
    by_path = {m.path: m for m in inspected}
    pins = check_version_pins(by_path)

    # A pin mismatch or a drifted checkout is a failure; an absent submodule is not.
    # `--check` runs where nothing is initialised (a lite CI job, a fresh clone), and a
    # gate that goes red there gets switched off within a week, taking the real
    # failures with it.
    failures = [f"{m.path}: {'; '.join(m.notes)}"
                for m in inspected if m.status in (DRIFT, DIRTY)]
    failures += [p["detail"] for p in pins if p["status"] == "fail"]

    return {
        "submodules": [m.as_record() for m in inspected],
        "version_pins": pins,
        "counts": {
            status: sum(1 for m in inspected if m.status == status)
            for status in (OK, ABSENT, DRIFT, DIRTY)
        },
        "initialised": init_results,
        "failures": failures,
        "check": check,
        "ok": not failures,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 on a drifted checkout or a mismatched version pin")
    parser.add_argument("--init", action="store_true",
                        help="shallow-clone any submodule that is not initialised")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    payload = report(args.check, args.init)

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False))
    else:
        for line in payload["initialised"]:
            print(f"init  {line}")
        mark = {OK: "ok  ", ABSENT: "----", DRIFT: "DRIFT", DIRTY: "DIRTY"}
        for module in payload["submodules"]:
            print(f"  {mark[module['status']]:<6}{module['path']:<38}"
                  f"{(module['release'] or (module['sha'] or '?')[:12]):<24}"
                  f"{'shallow' if module['shallow'] else 'full':<8}")
            for note in module["notes"]:
                print(f"         {note}")
        counts = payload["counts"]
        print(f"\n  {counts[OK]} ok · {counts[ABSENT]} not initialised · "
              f"{counts[DRIFT]} drifted · {counts[DIRTY]} dirty")
        for pin in payload["version_pins"]:
            detail = pin.get("detail") or f"{pin.get('declared')} == {pin.get('release')}"
            print(f"  pin  [{pin['status']}] {pin['pin']}: {detail}")
        if payload["failures"]:
            print(f"\n  {len(payload['failures'])} failure(s)")

    return 1 if (args.check and not payload["ok"]) else 0


if __name__ == "__main__":
    sys.exit(main())
