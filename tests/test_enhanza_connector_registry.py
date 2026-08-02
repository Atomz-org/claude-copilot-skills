"""Invariants that keep the Enhanza connector registry and the dbt models in sync.

`global_configs('all_available_sources')` is the single source of truth for which
connectors exist and which concepts each one supplies. `erp_union()` reads it to build
every `erp_bi_*` union. These tests fail when the registry and the models on disk drift
apart — the failure mode that let `favrit` ship without a registry entry and let `xledger`
claim `fact_vouchers` it had no adapter for.

See skill-packs/dbt-skills/use-cases/enhanza-analytics/CONNECTORS.md for the onboarding
procedure these invariants enforce.
"""

import re
from pathlib import Path

import pytest

PROJECT = (
    Path(__file__).resolve().parents[1]
    / "skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project"
)
MODELS = PROJECT / "models"
GLOBAL_CONFIGS = PROJECT / "macros/config/global_configs.sql"
# The unified layer moved from models/staging/erp to models/erp when the connectors were
# extracted into packages; accept whichever this checkout has.
ERP_DIR = next(
    (d for d in (MODELS / "erp", MODELS / "staging/erp") if d.is_dir()),
    MODELS / "erp",
)


def _all_available_sources():
    """Parse `{source_key: set(included_models)}` out of global_configs.sql.

    Deliberately a text parse: the alternative is booting dbt, which needs a warehouse
    profile that CI does not have.
    """
    text = GLOBAL_CONFIGS.read_text(encoding="utf-8")
    start = text.index("'all_available_sources': {")
    body = text[start + len("'all_available_sources': {") :]

    # Walk to the matching close brace so sibling config keys are never read as sources.
    depth, end = 1, None
    for i, ch in enumerate(body):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    assert end is not None, "unbalanced braces in all_available_sources"
    body = body[:end]

    sources, current, in_included = {}, None, False
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("{#") or line.startswith("-#}"):
            continue
        if not in_included:
            m = re.match(r"^'([a-z_0-9]+)':\s*\{$", line)
            if m:
                current = m.group(1)
                sources[current] = set()
                continue
        if line.startswith("'included_models': ["):
            in_included = True
            continue
        if in_included:
            if line.startswith("]"):
                in_included = False
                continue
            m = re.match(r"^'([a-z_0-9]+)',?$", line)
            if m and current:
                sources[current].add(m.group(1))
    return sources


def _erp_union_concepts():
    """Concepts that have a unified `erp_bi_<concept>` model."""
    out = {}
    for f in ERP_DIR.glob("erp_bi_*.sql"):
        concept = f.stem[len("erp_bi_") :]
        if concept.endswith("_staging"):
            concept = concept[: -len("_staging")]
        out[concept] = f
    return out


def _adapters():
    """`{(source, concept): path}` for every `<source>_erp_bi_<concept>.sql` on disk.

    Adapters live inside each connector's package after the split
    (packages/<source>/models/staging/); the root models/ tree is still scanned so the
    test keeps meaning the same thing on a pre-split checkout.
    """
    found = {}
    candidates = list(MODELS.rglob("*_erp_bi_*.sql")) + list(
        PROJECT.glob("packages/*/models/**/*_erp_bi_*.sql")
    )
    for f in candidates:
        if f.stem.startswith("erp_bi_"):
            continue
        source, concept = f.stem.split("_erp_bi_", 1)
        found[(source, concept)] = f
    return found


REGISTRY = _all_available_sources()
UNION_CONCEPTS = _erp_union_concepts()
ADAPTERS = _adapters()


def test_registry_is_not_empty():
    assert REGISTRY, "no sources parsed out of global_configs.sql"
    assert "fortnox" in REGISTRY


@pytest.mark.parametrize("source", sorted(REGISTRY))
def test_every_claimed_concept_has_an_adapter_model(source):
    """A source claiming a unified concept must ship the adapter that feeds the union.

    Without this, `erp_union()` emits a `ref()` to a model that does not exist and the
    project fails to parse — or, before erp_union, the claim silently did nothing while
    `model_is_provided()` kept answering true.
    """
    missing = [
        concept
        for concept in sorted(REGISTRY[source])
        if concept in UNION_CONCEPTS and (source, concept) not in ADAPTERS
    ]
    assert not missing, (
        f"{source} claims {missing} in included_models but "
        f"models/**/{source}_erp_bi_<concept>.sql is missing for each"
    )


@pytest.mark.parametrize("key", sorted(ADAPTERS))
def test_every_adapter_model_is_declared_in_the_registry(key):
    """An adapter with no registry claim never reaches the unified layer."""
    source, concept = key
    assert source in REGISTRY, (
        f"{ADAPTERS[key].name} exists but '{source}' has no entry in "
        f"global_configs('all_available_sources')"
    )
    if concept in UNION_CONCEPTS:
        assert concept in REGISTRY[source], (
            f"{ADAPTERS[key].name} exists but '{concept}' is not in "
            f"{source}.included_models, so erp_bi_{concept} will not union it"
        )


@pytest.mark.parametrize(
    "model", sorted(UNION_CONCEPTS.values(), key=lambda p: p.name), ids=lambda p: p.name
)
def test_union_models_carry_no_hardcoded_connector_gates(model):
    """erp_bi models must derive their sources from the registry, not hardcode them.

    A hardcoded `{% if var('is_<source>_enabled') %}` block is how the project drifted in
    the first place: it makes onboarding a connector an edit to ~30 files, and nothing
    checks the blocks against the registry.
    """
    text = model.read_text(encoding="utf-8")
    gates = set(re.findall(r"var\('is_([a-z_]+)_enabled'", text))
    gates.discard("erp")
    assert not gates, (
        f"{model.name} hardcodes {sorted(gates)}; use erp_union('<concept>') and let "
        f"global_configs('all_available_sources') decide"
    )


@pytest.mark.parametrize("source", sorted(REGISTRY))
def test_every_source_has_a_staging_directory(source):
    """A registry entry with no models behind it unions nothing, silently.

    Two layouts satisfy it: the monolith's models/staging/<source>/ and the package
    layout's packages/<source>/models/staging/.
    """
    monolith = MODELS / "staging" / source
    package = PROJECT / "packages" / source / "models" / "staging"
    assert monolith.is_dir() or package.is_dir(), (
        f"'{source}' is in the registry but neither models/staging/{source}/ nor "
        f"packages/{source}/models/staging/ exists"
    )


@pytest.mark.parametrize("source", sorted(REGISTRY))
def test_every_source_enable_var_has_a_declared_default(source):
    """`is_<source>_enabled` must be listed in dbt_project.yml `vars:`.

    An undeclared var silently defaults to False, so a typo removes a connector from every
    union with no error anywhere.
    """
    project_yml = (PROJECT / "dbt_project.yml").read_text(encoding="utf-8")
    assert f"is_{source}_enabled:" in project_yml, (
        f"is_{source}_enabled has no declared default in dbt_project.yml vars:"
    )
