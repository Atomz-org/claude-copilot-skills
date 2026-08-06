"""Tests for the `architecture-page` skill.

The skill documents a contract that lives in *another* file:
`tests/test_architecture_diagram.py` decides which `data-metric` keys exist, what
each label class weighs, and how wide a label may be. A skill that restates those
numbers is a second source of truth, and the copy is the one that goes stale —
silently, because nothing executes prose.

So the numbers are not restated on trust: every figure the skill states is
re-derived here from the test that enforces it. If the two disagree, this fails
and names which one moved.

The presence assertions are the ordinary pack rule — a skill exists in the pack
*and* in its activated mirror, because one relative link has to resolve in both.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "skill-packs/github-skills/.claude"
LIVE = REPO / ".claude"

SKILL = "skills/architecture-page/SKILL.md"
REFERENCES = (
    "skills/architecture-page/references/pinning.md",
    "skills/architecture-page/references/svg-contract.md",
)
COMMAND = "commands/architecture.md"

DIAGRAM_TEST = REPO / "tests/test_architecture_diagram.py"

# The two box widths the page draws with; the skill states a character budget for
# each. Anything wider is fine, but a documented width that the page no longer
# uses means the budget table describes a diagram nobody has.
DOCUMENTED_BOX_WIDTHS = (156, 230)
PADDING = 18  # 14px text inset + the test's 4px right margin


def _diagram_test_source() -> str:
    return DIAGRAM_TEST.read_text(encoding="utf-8")


def _metric_keys() -> set[str]:
    block = re.search(r"^METRICS = \{(.*?)^\}", _diagram_test_source(), re.S | re.M)
    assert block, "METRICS dict not found in tests/test_architecture_diagram.py"
    keys = set(re.findall(r'^\s*"([a-z_]+)":', block.group(1), re.M))
    assert keys, "METRICS parsed as empty"
    return keys


def _class_sizes() -> dict[str, float]:
    block = re.search(r"_CLASS_SIZE = \{(.*?)\}", _diagram_test_source(), re.S)
    assert block, "_CLASS_SIZE not found in tests/test_architecture_diagram.py"
    return {n: float(s) for n, s in re.findall(r'"([\w-]+)":\s*([\d.]+)', block.group(1))}


def _advance() -> float:
    m = re.search(r"_ADVANCE = ([\d.]+)", _diagram_test_source())
    assert m, "_ADVANCE not found in tests/test_architecture_diagram.py"
    return float(m.group(1))


# --- the pack rule --------------------------------------------------------------------

def test_the_skill_exists_in_the_pack_and_in_its_activated_mirror() -> None:
    for root in (PACK, LIVE):
        for rel in (SKILL, *REFERENCES, COMMAND):
            assert (root / rel).is_file(), f"missing {root / rel}"


def test_the_skill_name_matches_its_directory() -> None:
    """A frontmatter name that disagrees with the directory dispatches to neither."""
    text = (PACK / SKILL).read_text(encoding="utf-8")
    assert re.search(r"^name: architecture-page$", text, re.M), text[:200]


def test_the_skill_and_the_command_do_not_share_a_name() -> None:
    """A skill and a command answering to one name shadow each other and the command
    loses — the same rule that named `harness-mapping` rather than `skill-map`."""
    assert not (PACK / "commands/architecture-page.md").exists()
    assert not (PACK / "skills/architecture/SKILL.md").exists()


def test_the_skill_is_indexed_by_intent() -> None:
    index = (PACK / "commands/skills-index.md").read_text(encoding="utf-8")
    assert "`architecture-page` skill" in index
    assert "`architecture.md` command" in index


# --- the numbers the skill restates ---------------------------------------------------

def test_every_documented_metric_key_exists_and_none_is_missing() -> None:
    """`references/pinning.md` tabulates the pinnable keys. That set is decided by
    METRICS, so a key documented but not resolvable is advice that fails the gate,
    and a key resolvable but not documented is a pin nobody knows they can use."""
    doc = (PACK / "skills/architecture-page/references/pinning.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| `([a-z_]+)` \|", doc, re.M))
    actual = _metric_keys()
    assert documented == actual, (
        f"documented but unresolvable: {sorted(documented - actual)}; "
        f"resolvable but undocumented: {sorted(actual - documented)}"
    )


def test_the_label_budgets_are_derived_from_the_measurement_that_enforces_them() -> None:
    """The skill hands the author a character count per class per box width. It is
    `floor((width - 18) / (font-size * advance))`, and every input to that lives in
    the diagram test — so a change there must move these numbers."""
    doc = (PACK / "skills/architecture-page/references/svg-contract.md").read_text(encoding="utf-8")
    rows = re.findall(r"\| `(t-[\w-]+)` \| ([\d.]+)px \| (\d+) chars \| (\d+) chars \|", doc)
    assert rows, "no label-budget table found in references/svg-contract.md"

    sizes, advance = _class_sizes(), _advance()
    assert str(advance) in doc, f"the advance ratio {advance} is not stated in the skill"

    for name, stated_size, narrow, wide in rows:
        assert name in sizes, f"{name} has no size in _CLASS_SIZE"
        assert float(stated_size) == sizes[name], (
            f"{name}: skill says {stated_size}px, the test measures at {sizes[name]}px"
        )
        for width, stated in zip(DOCUMENTED_BOX_WIDTHS, (int(narrow), int(wide))):
            budget = math.floor((width - PADDING) / (sizes[name] * advance))
            assert stated == budget, (
                f"{name} in a {width}px box: skill says {stated} chars, "
                f"the measurement allows {budget}"
            )


def test_the_documented_box_widths_are_widths_the_page_actually_draws() -> None:
    page = (REPO / "public/code-skills-architecture.html").read_text(encoding="utf-8")
    drawn = {
        int(w)
        for tag, w in re.findall(r'<rect ([^>]*?)width="(\d+)"', page)
        if "box" in tag
    }
    missing = [w for w in DOCUMENTED_BOX_WIDTHS if w not in drawn]
    assert not missing, f"the skill budgets for box widths the page no longer uses: {missing}"


def test_the_skill_points_at_the_test_that_is_its_specification() -> None:
    text = (PACK / SKILL).read_text(encoding="utf-8")
    assert "tests/test_architecture_diagram.py" in text
    stated = re.search(r"(\d+) tests covering", text)
    assert stated, "the skill does not state how many tests the spec has"
    actual = len(re.findall(r"^def test_", _diagram_test_source(), re.M))
    assert int(stated.group(1)) == actual, (
        f"the skill says {stated.group(1)} tests, tests/test_architecture_diagram.py has {actual}"
    )
