"""Documentation integrity tests.

Every relative markdown link in the repository must resolve. These broke silently once
already: skills and agents link to `../../references/<file>.md` and `../../templates/<file>.md`,
which resolve to the *pack root* while the file lives under `skill-packs/<pack>/` and to the
*repository root* once `scripts/activate_skill_stack.sh` copies the pack into `.claude/`.
Both locations therefore have to exist, and the activation script is what keeps them in
step. A regression here is invisible at runtime — an agent just follows a dead path — so it
is asserted here instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = {
    ".git",
    ".venv",
    ".venv-dbt",
    "node_modules",
    "graphify-out",
    "__pycache__",
    ".pytest_cache",
}

# [label](target) — the target group stops at the first closing paren, which is fine
# because none of the repository's link targets contain one.
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")

# Directories that ship inside a pack and are mirrored to the repository root on activation.
MIRRORED_ASSETS = ("references", "templates")


def _markdown_files() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*.md")
        if not any(part in SKIP_DIRS for part in path.parts)
    ]


def _relative_links(markdown: Path) -> list[str]:
    """Return the link targets in `markdown` that point at a path inside the repository."""
    targets: list[str] = []
    for _label, raw_target in LINK_RE.findall(markdown.read_text(encoding="utf-8")):
        target = raw_target.strip()
        if target.startswith(("http://", "https://", "#", "mailto:", "<")):
            continue
        # Command files legitimately contain templated or shell-expanded paths.
        if "$" in target or "{{" in target:
            continue
        path_part = target.split("#", 1)[0].strip()
        if path_part:
            targets.append(path_part)
    return targets


def test_markdown_files_are_discovered() -> None:
    """Guard against the glob silently matching nothing and vacuously passing."""
    assert len(_markdown_files()) > 50


@pytest.mark.parametrize(
    "markdown", _markdown_files(), ids=lambda p: str(p.relative_to(ROOT))
)
def test_relative_markdown_links_resolve(markdown: Path) -> None:
    broken = [
        target
        for target in _relative_links(markdown)
        if not (markdown.parent / target).resolve().exists()
    ]
    assert not broken, (
        f"{markdown.relative_to(ROOT)} has unresolvable relative links: {broken}"
    )


@pytest.mark.parametrize("asset", MIRRORED_ASSETS)
def test_pack_assets_are_mirrored_at_repository_root(asset: str) -> None:
    """`activate_skill_stack.sh` must leave the root mirror a superset of every pack copy.

    Skills reference these by a single relative path that has to resolve both inside the
    pack and after activation, so a file present in the pack but missing at the root is a
    dead link waiting to happen.
    """
    root_mirror = ROOT / asset
    pack_copies = sorted((ROOT / "skill-packs").glob(f"*/{asset}"))
    if not pack_copies:
        pytest.skip(f"no pack ships a {asset}/ directory")

    assert root_mirror.is_dir(), (
        f"{asset}/ is missing at the repository root; run scripts/activate_skill_stack.sh"
    )

    for pack_copy in pack_copies:
        missing = {
            item.name for item in pack_copy.glob("*.md")
        } - {item.name for item in root_mirror.glob("*.md")}
        assert not missing, (
            f"{pack_copy.relative_to(ROOT)} ships {sorted(missing)} but the root "
            f"{asset}/ mirror does not; re-run scripts/activate_skill_stack.sh"
        )


def test_activation_script_mirrors_every_asset_directory() -> None:
    """The mirroring loop is the mechanism behind the test above — keep them in sync."""
    script = (ROOT / "scripts" / "activate_skill_stack.sh").read_text(encoding="utf-8")
    for asset in MIRRORED_ASSETS:
        assert asset in script, (
            f"activate_skill_stack.sh no longer mirrors {asset}/, so links into it "
            f"will dangle once a pack is activated"
        )
