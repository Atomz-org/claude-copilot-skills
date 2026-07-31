"""Tests for the /new-connector command, its skill, and the scaffold script.

Two things are under test:

1. **Presence and indexing** — the command/skill lifecycle rules in
   `.claude/rules/standards.md` require a SKILL.md, a matching command playbook, and an
   entry in the skills index.
2. **Convention detection** — the scaffold's whole premise is that it copies the target
   project's existing layout rather than imposing one. That is verified against both real
   projects in this repository, which happen to use different conventions, plus synthetic
   projects for the shapes neither of them covers.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import new_connector  # noqa: E402

# `example-order-revenue-mart` ships on the default branch and is the use-case the
# always-available assertions run against. Domain use-cases such as `enhanza-analytics`
# arrive on feature branches, so tests that need one skip rather than fail when it is
# absent — a repo-level suite must not go red because of which branch is checked out.
BASE_USE_CASE = "example-order-revenue-mart"
REGISTRY_USE_CASE = "enhanza-analytics"


def _use_case_present(slug: str) -> bool:
    # The manifest, not the directory: a branch switch leaves the empty directory tree
    # behind, so `dbt_project/` existing proves nothing.
    return any(REPO.glob(f"skill-packs/*/use-cases/{slug}/dbt_project/dbt_project.yml"))


needs_registry_use_case = pytest.mark.skipif(
    not _use_case_present(REGISTRY_USE_CASE),
    reason=f"{REGISTRY_USE_CASE} is not checked out on this branch",
)


# ---------------------------------------------------------------------------------------
# Presence and indexing
# ---------------------------------------------------------------------------------------

COMMAND_COPIES = [
    ".claude/commands/analytics/new-connector.md",
    ".claude/commands/new-connector.md",
    "skill-packs/dbt-skills/.claude/commands/new-connector.md",
]
SKILL_COPIES = [
    ".claude/skills/connector-onboarding/SKILL.md",
    "skill-packs/dbt-skills/.claude/skills/connector-onboarding/SKILL.md",
]


@pytest.mark.parametrize("rel", COMMAND_COPIES + SKILL_COPIES)
def test_artifact_exists(rel):
    assert (REPO / rel).is_file(), f"{rel} is missing"


@pytest.mark.parametrize("rel", SKILL_COPIES)
def test_skill_declares_frontmatter(rel):
    text = (REPO / rel).read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{rel} has no frontmatter"
    front = text.split("---", 2)[1]
    assert "name: connector-onboarding" in front
    assert "description:" in front


@pytest.mark.parametrize("rel", COMMAND_COPIES)
def test_command_declares_frontmatter(rel):
    front = (REPO / rel).read_text(encoding="utf-8").split("---", 2)[1]
    assert "description:" in front
    assert "argument-hint:" in front


@pytest.mark.parametrize("rel", COMMAND_COPIES + SKILL_COPIES)
def test_routes_through_the_git_skill(rel):
    """A connector lands as a commit. The command must not invent its own git flow."""
    text = (REPO / rel).read_text(encoding="utf-8")
    assert "git-standard.sh" in text, f"{rel} does not route commits through git-standard.sh"
    assert "git-commit-quality" in text or "git-standard.sh" in text


@pytest.mark.parametrize("rel", COMMAND_COPIES + SKILL_COPIES)
def test_requires_the_use_case_to_exist_first(rel):
    """Rule 1: no model before a use-case spec."""
    assert "new-use-case" in (REPO / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", SKILL_COPIES)
def test_oversized_skill_splits_into_references(rel):
    """Mirrors scripts/marketplace_portability_check.sh so the failure surfaces in pytest."""
    skill = REPO / rel
    if skill.stat().st_size > 8192:
        assert (skill.parent / "references").is_dir(), (
            f"{rel} exceeds the 8192-byte pack limit and has no references/ directory"
        )


def test_pack_skill_copy_matches_the_root_one():
    """The two copies are duplicates by design; drift between them is a defect."""
    root = REPO / ".claude/skills/connector-onboarding"
    pack = REPO / "skill-packs/dbt-skills/.claude/skills/connector-onboarding"
    root_files = {p.relative_to(root): p.read_bytes() for p in root.rglob("*.md")}
    pack_files = {p.relative_to(pack): p.read_bytes() for p in pack.rglob("*.md")}
    assert root_files == pack_files


def test_indexed_by_intent():
    index = (REPO / ".claude/commands/skills-index.md").read_text(encoding="utf-8")
    assert "new-connector" in index, "new-connector is not discoverable from skills-index.md"
    assert "connector-onboarding" in index, "the skill it loads is not named in the index"


def test_command_points_at_the_skill_by_name():
    """The command is the entry point; the skill is what it loads. Keep the link explicit.

    They are deliberately named differently — see
    `test_no_command_shares_a_name_with_a_skill` — so nothing resolves the one from the
    other. Only this string does.
    """
    for rel in COMMAND_COPIES:
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "`connector-onboarding` skill" in text, f"{rel} does not name the skill it loads"


def _skill_names(skills_dir: Path) -> set[str]:
    return {p.parent.name for p in skills_dir.glob("*/SKILL.md")}


def _command_names(commands_dir: Path) -> set[str]:
    # Only the top level: a command in a subdirectory is namespaced (`/analytics:foo`) and
    # cannot collide with a bare skill name.
    return {p.stem for p in commands_dir.glob("*.md")} - {"skills-index"}


def test_no_command_shares_a_name_with_a_skill():
    """A command and a skill with the same name resolve to one `/name`, and the command loses.

    This is what hid `/new-connector` from the slash-command list while `/new-use-case`
    showed: `new-use-case` is a command whose skill is separately named
    `analytics-request-framing`, so there was nothing to collide with. `new-connector` was a
    command *and* a skill, the skill won the name, and the command became unreachable from
    the menu. Renaming the skill to `connector-onboarding` restored parity.

    The failure is silent — no error, the command simply stops being listed — so it needs a
    test rather than a convention.
    """
    roots = [REPO / ".claude"] + sorted(REPO.glob("skill-packs/*/.claude"))
    collisions = {}
    for root in roots:
        skills, commands = root / "skills", root / "commands"
        if not (skills.is_dir() and commands.is_dir()):
            continue
        shared = _skill_names(skills) & _command_names(commands)
        if shared:
            collisions[str(root.relative_to(REPO))] = sorted(shared)

    assert not collisions, (
        "a command name is shadowed by a same-named skill, so the command will not be "
        f"listed: {collisions}. Rename the skill and have the command load it by name, the "
        "way /new-use-case loads `analytics-request-framing`."
    )


def test_scaffold_script_is_executable_python():
    script = REPO / "scripts/new_connector.py"
    result = subprocess.run(
        [sys.executable, str(script), "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "--use-case" in result.stdout
    assert "--tables" in result.stdout


# ---------------------------------------------------------------------------------------
# Infix detection
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "remainder,expected",
    [
        ("_bi_dim_customers", "_bi_"),
        ("_erp_bi_fact_orders", "_erp_bi_"),
        ("__customers", "__"),
        # The dbt-labs separator wins outright: without the `len >= 2` rule this would be
        # read as the infix `__order_` and every scaffolded model would be misnamed.
        ("__order_lines", "__"),
        # No entity prefix present, so only the first token is the layer.
        ("_flat_incoming_goods", "_flat_"),
        ("_reports_rolling_sum", "_reports_"),
        ("_invoices", "_"),
    ],
)
def test_infix_of(remainder, expected):
    assert new_connector._infix_of(remainder) == expected


def test_vote_picks_the_majority_family_not_the_common_prefix():
    """The reason detection votes instead of taking a longest common prefix.

    A real connector directory carries several naming families at once. Their longest
    common prefix is `_`, which is not a convention anyone chose.
    """
    remainders = (
        ["_bi_dim_customers"] * 50
        + ["_flat_incoming_goods"] * 14
        + ["_reports_rolling_sum"] * 6
        + ["_base_v2_invoices"]
    )
    assert new_connector._vote_infix(remainders) == "_bi_"


def test_vote_on_empty_input_is_empty():
    assert new_connector._vote_infix([]) == ""


# ---------------------------------------------------------------------------------------
# Detection against the real projects in this repository
# ---------------------------------------------------------------------------------------


@needs_registry_use_case
def test_detects_the_registry_driven_project():
    """enhanza-analytics: connector-prefixed names, an adapter layer, and a registry."""
    conv = new_connector.detect(new_connector.find_use_case(REGISTRY_USE_CASE))

    assert conv.staging_model("shopify", "dim_customers") == "shopify_bi_dim_customers_staging"
    assert conv.adapter_model("shopify", "dim_customers") == "shopify_erp_bi_dim_customers"
    assert conv.bi_model("shopify", "dim_customers") == "shopify_bi_dim_customers"
    assert conv.bi_dir_suffix == "_bi"
    assert conv.source_suffix == "_api"
    assert conv.registry_macro is not None
    assert conv.has_auto_config is True


def test_detects_the_dbt_labs_shaped_project():
    """example-order-revenue-mart: the connector name sits mid-filename, no adapter layer."""
    conv = new_connector.detect(new_connector.find_use_case(BASE_USE_CASE))

    assert conv.staging_model("stripe", "charges") == "stg_stripe__charges"
    assert conv.adapter_infix is None, "this project has no unified adapter layer to detect"
    assert conv.bi_dir_suffix is None
    assert conv.registry_macro is None


@needs_registry_use_case
def test_two_real_projects_detect_differently():
    """The premise of the command: two projects, two layouts, one command."""
    a = new_connector.detect(new_connector.find_use_case(REGISTRY_USE_CASE))
    b = new_connector.detect(new_connector.find_use_case(BASE_USE_CASE))
    assert a.staging_model("x", "y") != b.staging_model("x", "y")


def test_unknown_use_case_names_the_available_ones():
    with pytest.raises(SystemExit) as excinfo:
        new_connector.find_use_case("no-such-use-case")
    message = str(excinfo.value)
    assert BASE_USE_CASE in message
    assert "new-use-case" in message, "the error should point at the command that fixes it"


# ---------------------------------------------------------------------------------------
# Argument handling
# ---------------------------------------------------------------------------------------


def test_table_model_names_are_never_guessed():
    """Whether `customers` becomes `dim_customers` is a modeling decision, not a default."""
    assert new_connector.parse_tables("customers") == [("customers", "customers")]
    assert new_connector.parse_tables("customers=dim_customers") == [
        ("customers", "dim_customers")
    ]
    assert new_connector.parse_tables("a, b=fact_b ,") == [("a", "a"), ("b", "fact_b")]


def _run(*args):
    return subprocess.run(
        [sys.executable, str(REPO / "scripts/new_connector.py"), *args],
        capture_output=True,
        text=True,
        cwd=REPO,
    )


def test_unified_concept_without_a_table_is_rejected():
    """An adapter reads its own connector's staging model, so the model must exist."""
    result = _run(
        "shopify", "--use-case", BASE_USE_CASE,
        "--tables", "customers", "--unified-concepts", "fact_invoices",
    )
    assert result.returncode != 0
    assert "fact_invoices" in result.stderr


def test_tables_are_required():
    result = _run("shopify", "--use-case", BASE_USE_CASE)
    assert result.returncode != 0
    assert "--tables" in result.stderr


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    use_case = _synthetic_use_case(tmp_path, monkeypatch)
    target = use_case / "dbt_project/models/staging/dryrun"

    assert new_connector.main(
        ["dryrun", "--use-case", "fake-uc", "--tables", "customers", "--dry-run"]
    ) == 0
    assert not target.exists(), "--dry-run created files"


def test_contract_files_are_printed_not_written(tmp_path, monkeypatch, capsys):
    """sources.yml, the registry, and dbt_project.yml must arrive as a hand-written diff."""
    _synthetic_use_case(tmp_path, monkeypatch, registry=True)
    new_connector.main(["dryrun", "--use-case", "fake-uc", "--tables", "customers", "--dry-run"])
    out = capsys.readouterr().out

    assert "paste these by hand" in out
    for expected in ("sources.yml", "all_available_sources", "dbt_project.yml"):
        assert expected in out, f"{expected} block not printed"
    assert "git-standard.sh" in out, "the commit step should be printed too"


def test_currency_is_omitted_rather_than_guessed(tmp_path, monkeypatch, capsys):
    """A wrong currency silently mis-values every row; NULL is at least visible."""
    _synthetic_use_case(tmp_path, monkeypatch, registry=True)

    new_connector.main(["a", "--use-case", "fake-uc", "--tables", "customers", "--dry-run"])
    without = capsys.readouterr().out
    assert "default_currency" in without and "NEEDS INPUT" in without

    new_connector.main(
        ["b", "--use-case", "fake-uc", "--tables", "customers", "--currency", "USD", "--dry-run"]
    )
    assert "'default_currency': 'USD'" in capsys.readouterr().out


# ---------------------------------------------------------------------------------------
# Writing, against a synthetic project
# ---------------------------------------------------------------------------------------


def _synthetic_use_case(tmp_path, monkeypatch, registry: bool = False) -> Path:
    """A minimal project shaped like the registry-driven one, isolated from the repo.

    Built rather than borrowed so these assertions hold on any branch, whatever domain
    use-cases happen to be checked out.
    """
    use_case = tmp_path / "skill-packs" / "pack" / "use-cases" / "fake-uc"
    project = use_case / "dbt_project"
    models = project / "models"
    (models / "staging" / "acme").mkdir(parents=True)
    (models / "acme_bi").mkdir(parents=True)
    (project / "dbt_project.yml").write_text(
        'name: fake\nmodel-paths: ["models"]\n', encoding="utf-8"
    )
    for name in ("dim_customers", "fact_orders"):
        (models / "staging" / "acme" / f"acme_bi_{name}_staging.sql").write_text("select 1")
        (models / "staging" / "acme" / f"acme_erp_bi_{name}.sql").write_text("select 1")
        (models / "acme_bi" / f"acme_bi_{name}.sql").write_text("select 1")
    (models / "sources.yml").write_text(
        "version: 2\nsources:\n  - name: acme_api\n    tables:\n      - name: customers\n",
        encoding="utf-8",
    )
    if registry:
        macros = project / "macros" / "config"
        macros.mkdir(parents=True)
        (macros / "global_configs.sql").write_text(
            "{% macro global_configs(key) %}{% set config = "
            "{'all_available_sources': {}} %}{% endmacro %}",
            encoding="utf-8",
        )
    monkeypatch.setattr(new_connector, "REPO", tmp_path)
    return use_case


@pytest.fixture
def fake_use_case(tmp_path, monkeypatch):
    return _synthetic_use_case(tmp_path, monkeypatch)


def test_writes_models_following_the_detected_layout(fake_use_case):
    rc = new_connector.main(
        [
            "shopify", "--use-case", "fake-uc",
            "--tables", "customers=dim_customers",
            "--unified-concepts", "dim_customers",
        ]
    )
    assert rc == 0
    models = fake_use_case / "dbt_project" / "models"
    assert (models / "staging/shopify/shopify_bi_dim_customers_staging.sql").is_file()
    assert (models / "staging/shopify/shopify_erp_bi_dim_customers.sql").is_file()
    assert (models / "shopify_bi/shopify_bi_dim_customers.sql").is_file()
    assert (models / "staging/shopify/schema.yml").is_file()


def test_staging_model_reads_the_api_suffixed_source(fake_use_case):
    new_connector.main(["shopify", "--use-case", "fake-uc", "--tables", "customers"])
    sql = (
        fake_use_case
        / "dbt_project/models/staging/shopify/shopify_bi_customers_staging.sql"
    ).read_text(encoding="utf-8")
    assert "source('shopify_api', 'customers')" in sql
    assert "NEEDS INPUT" in sql, "the column list must not be fabricated"


def test_adapter_points_at_its_own_connectors_staging_model(fake_use_case):
    new_connector.main(
        [
            "shopify", "--use-case", "fake-uc",
            "--tables", "orders=fact_orders", "--unified-concepts", "fact_orders",
        ]
    )
    sql = (
        fake_use_case / "dbt_project/models/staging/shopify/shopify_erp_bi_fact_orders.sql"
    ).read_text(encoding="utf-8")
    assert "ref('shopify_bi_fact_orders_staging')" in sql
    assert "acme_erp_bi_fact_orders.sql" in sql, "should name the adapter to diff against"


def test_existing_files_are_never_overwritten(fake_use_case):
    target = fake_use_case / "dbt_project/models/staging/shopify"
    target.mkdir(parents=True)
    keep = target / "shopify_bi_customers_staging.sql"
    keep.write_text("-- hand written, do not clobber\n", encoding="utf-8")

    new_connector.main(["shopify", "--use-case", "fake-uc", "--tables", "customers"])
    assert keep.read_text(encoding="utf-8") == "-- hand written, do not clobber\n"


def test_contract_files_are_left_untouched(fake_use_case):
    sources = fake_use_case / "dbt_project/models/sources.yml"
    before = sources.read_text(encoding="utf-8")
    new_connector.main(["shopify", "--use-case", "fake-uc", "--tables", "customers"])
    assert sources.read_text(encoding="utf-8") == before, "sources.yml must be pasted by hand"


def test_project_without_connectors_falls_back_to_dbt_labs_convention(tmp_path, monkeypatch):
    use_case = tmp_path / "skill-packs" / "pack" / "use-cases" / "bare"
    (use_case / "dbt_project" / "models").mkdir(parents=True)
    (use_case / "dbt_project" / "dbt_project.yml").write_text("name: bare\n", encoding="utf-8")
    monkeypatch.setattr(new_connector, "REPO", tmp_path)

    conv = new_connector.detect(use_case)
    assert conv.staging_model("stripe", "charges") == "stg_stripe__charges"
    assert conv.notes, "the fallback should be reported, not silent"


def test_missing_dbt_project_is_an_error(tmp_path, monkeypatch):
    use_case = tmp_path / "skill-packs" / "pack" / "use-cases" / "specless"
    use_case.mkdir(parents=True)
    monkeypatch.setattr(new_connector, "REPO", tmp_path)
    with pytest.raises(SystemExit, match="dbt_project.yml"):
        new_connector.detect(use_case)
