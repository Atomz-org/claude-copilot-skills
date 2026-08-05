"""Repository, use-case, and dbt-project location — resolved in exactly one place.

Every analyzer in `scripts/` needs the same four answers: where the repository root
is, where a use-case slug lives, which dbt project a manifest belongs to, and where
that use-case's manifest would be. Before this module those answers were written out
four times (`use_case_dir`), twice (`project_root_of`), and twenty-three times (the
`Path(__file__).resolve().parent` bootstrap) — with two of the four `use_case_dir`
copies dying on a missing slug and the other two returning `None`.

That split is real and both halves are kept, as two named functions rather than one
function with two behaviours:

    use_case_dir(slug)          -> Optional[Path]   caller handles absence
    require_use_case_dir(slug)  -> Path             absence is fatal, with a message

**Nothing here is cached, on purpose.** The glob is a directory listing three levels
deep over a handful of packs — microseconds — while `use_case_sync.py --init <slug>`
creates a use-case and then immediately syncs it *in the same process*. A cache
populated before the `mkdir` would report the new use-case as missing, which is a
correctness bug traded for an unmeasurable saving.

**The root is a parameter, not a closure.** Every lookup takes `repo` and defaults to
`REPO` only when the caller passes nothing. `new_connector`, `use_case_sync`, and
`wren_context_sync` are all driven against a throwaway tree by
`monkeypatch.setattr(module, "REPO", tmp_path)`, so a helper that read a module-global
at call time would silently search the real repository instead. Each of those modules
keeps a one-line binding that forwards its own `REPO`; the logic still lives here once.

Standard library only, matching `_manifest` and `_miniyaml`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

# scripts/_paths.py -> scripts/ -> <repo root>
REPO: Path = Path(__file__).resolve().parent.parent

#: Every use-case lives under its owning pack, per `.claude/rules/standards.md`.
USE_CASE_GLOB = "skill-packs/*/use-cases/{slug}"


def bootstrap() -> Path:
    """Put `scripts/` on `sys.path` so sibling helpers import under any CWD.

    These files are run as scripts (`python3 scripts/x.py`), not as a package, so
    `_manifest` and `_miniyaml` are only importable once their directory is on the
    path. Returns the repository root so a caller can do both in one line.
    """
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    return REPO


def use_case_dir(slug: str, repo: Optional[Path] = None) -> Optional[Path]:
    """The directory for `slug`, or None when no pack declares it."""
    root = REPO if repo is None else Path(repo)
    for path in sorted(root.glob(USE_CASE_GLOB.format(slug=slug))):
        if path.is_dir():
            return path
    return None


def require_use_case_dir(slug: str, repo: Optional[Path] = None) -> Path:
    """`use_case_dir`, but a missing slug exits 2 with the known slugs listed."""
    found = use_case_dir(slug, repo)
    if found is not None:
        return found
    known = ", ".join(all_use_cases(repo)) or "none"
    print(
        f"ERROR: no use-case '{slug}' under skill-packs/*/use-cases/\n"
        f"  Known use-cases: {known}",
        file=sys.stderr,
    )
    raise SystemExit(2)


def all_use_cases(repo: Optional[Path] = None) -> List[str]:
    """Every use-case slug in the repository, sorted, dotfiles excluded."""
    root = REPO if repo is None else Path(repo)
    return sorted(
        path.name
        for path in root.glob("skill-packs/*/use-cases/*")
        if path.is_dir() and not path.name.startswith(".")
    )


def project_root_of(manifest: Path, use_case: Optional[Path] = None) -> Optional[Path]:
    """The dbt project directory a manifest belongs to.

    `original_file_path` in a manifest is relative to the dbt project root, not the
    repository root, so the two have to be joined to get a path any other tool would
    recognise.

    Three strategies, in order, which together are the union of the two hand-written
    copies this replaced — neither caller loses a fallback it had:

    1. Walk up from the manifest to a directory holding `dbt_project.yml`. Covers
       both `<project>/target/` and the committed `<use-case>/artifacts/prod/`.
    2. If a use-case is known, its sibling `<use-case>/dbt_project/`.
    3. Walk up again looking for any `<ancestor>/dbt_project/dbt_project.yml`, which
       resolves `artifacts/prod/manifest.json` with no use-case passed in.

    Returns None when none resolve; callers decide whether that is fatal.
    """
    manifest = Path(manifest)
    for candidate in (manifest.parent, *manifest.parents):
        if (candidate / "dbt_project.yml").is_file():
            return candidate
    if use_case is not None:
        sibling = Path(use_case) / "dbt_project"
        if (sibling / "dbt_project.yml").is_file():
            return sibling
    for candidate in manifest.parents:
        sibling = candidate / "dbt_project"
        if (sibling / "dbt_project.yml").is_file():
            return sibling
    return None


def default_manifest(use_case: Path) -> Optional[Path]:
    """The manifest a use-case would use, live target first, committed prod second."""
    for candidate in (
        Path(use_case) / "dbt_project" / "target" / "manifest.json",
        Path(use_case) / "artifacts" / "prod" / "manifest.json",
    ):
        if candidate.is_file():
            return candidate
    return None
