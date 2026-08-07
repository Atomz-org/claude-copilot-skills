"""Tests for the no-`select *` gate and the cited column deriver.

These two exist to make an explicit column contract reachable without inventing one, so
the properties worth pinning are the ones separating "derived from a citable schema" from
"plausible":

1. **The gate distinguishes a star that reaches the output from one that does not.**
   Rule 27 names `with source as (select * from ref())` as the house import-CTE style, so
   a gate that flagged it would argue with the rules it enforces.
2. **The baseline may only shrink.** A baseline that can grow is a mute button.
3. **A derived column carries a citation or is absent.** There is no "probably has an
   email field" path.
4. **Two ingestion tools are never merged into one contract.** Fivetran's `property_email`
   and dlt's `email` are the same field under two loaders; a table declaring both matches
   no warehouse and fails every staging model that correctly reads one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import no_star_check as ns  # noqa: E402
import source_schema_derive as ssd  # noqa: E402

ENHANZA = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics"

needs_enhanza = pytest.mark.skipif(
    not (ENHANZA / "dbt_project").exists(), reason="enhanza-analytics not on this branch",
)


# ---------------------------------------------------------------------------------------
# The gate: which stars matter
# ---------------------------------------------------------------------------------------


def _verdicts(sql: str):
    return [f.verdict for f in ns.classify(sql, "m.sql")]


def test_a_star_in_an_import_cte_is_not_a_finding() -> None:
    """Rule 27 names this form; the outer select does the enumerating."""
    sql = "with source as (select * from {{ ref('x') }})\nselect a, b from source"
    assert _verdicts(sql) == [ns.STAR_IN_IMPORT_CTE]


def test_a_star_in_the_output_select_is_a_finding() -> None:
    assert _verdicts("select * from {{ ref('x') }}") == [ns.STAR_IN_OUTPUT]


def test_a_star_beside_a_macro_still_reaches_the_output() -> None:
    """`select *, {{ add_erp_fields(...) }}` — the adapter shape. The model's schema is
    still whatever upstream carries."""
    sql = "select *, {{ add_erp_fields(columns=['OrgId']) }}\nfrom {{ ref('x') }}"
    assert _verdicts(sql) == [ns.STAR_IN_OUTPUT]


def test_a_star_split_across_lines_is_found() -> None:
    """The house formatting for these models puts the star on its own line."""
    assert _verdicts("select\n  *\nfrom {{ ref('x') }}") == [ns.STAR_IN_OUTPUT]


def test_count_star_is_not_a_star() -> None:
    assert _verdicts("select count(*) as n from {{ ref('x') }}") == []


def test_jinja_parentheses_do_not_shift_the_depth() -> None:
    """`{{ source('a','b') }}` contributes parens no SQL parser sees.

    Counting them would read the outermost select as nested and silently pass every
    staging model — the exact models this gate exists for.
    """
    assert _verdicts("select * from {{ source('a', 'b') }}") == [ns.STAR_IN_OUTPUT]


def test_a_star_inside_a_comment_is_not_a_finding() -> None:
    sql = "-- select * from old_table\nselect a from {{ ref('x') }}"
    assert _verdicts(sql) == []


def test_dbt_utils_star_is_reported_but_never_failed() -> None:
    """It expands to an explicit list, so the SQL that runs is enumerated — but the list
    comes from upstream, which is a choice worth seeing."""
    verdicts = _verdicts("select {{ dbt_utils.star(from=ref('x')) }} from {{ ref('x') }}")
    assert ns.MACRO_STAR in verdicts
    assert ns.STAR_IN_OUTPUT not in verdicts


def test_snapshots_and_tests_are_out_of_scope() -> None:
    """Rule 24 requires snapshotting the raw source; a snapshot that enumerated columns
    would quietly stop capturing a new one, which is the history it exists to keep."""
    for excluded in ("snapshots", "tests", "macros", "analyses"):
        assert excluded in ns.EXCLUDED_DIRS


# ---------------------------------------------------------------------------------------
# The gate: the baseline only shrinks
# ---------------------------------------------------------------------------------------


def _project(tmp_path: Path, models: dict) -> Path:
    use_case = tmp_path / "uc"
    (use_case / "dbt_project" / "models").mkdir(parents=True)
    for name, sql in models.items():
        (use_case / "dbt_project" / "models" / name).write_text(sql, encoding="utf-8")
    return use_case


def test_a_new_star_cannot_be_added_to_the_baseline(tmp_path: Path, monkeypatch) -> None:
    """The whole mechanism. A baseline that grows silences the gate that wrote it."""
    use_case = _project(tmp_path, {"a.sql": "select * from {{ ref('x') }}"})
    monkeypatch.setattr(ns, "REPO", tmp_path)
    monkeypatch.setattr(ns._paths, "REPO", tmp_path, raising=False)
    monkeypatch.setattr(ns, "use_case_dir", lambda slug: use_case)

    first = ns.report("uc", check=False, update=True)          # bootstrap
    assert first["status"] in ("changed", "ok")
    assert first.get("bootstrapped") is True

    (use_case / "dbt_project/models/b.sql").write_text(
        "select * from {{ ref('y') }}", encoding="utf-8")
    second = ns.report("uc", check=False, update=True)
    assert second["status"] == "fail"
    assert "may only" in second["reason"]


def test_a_fixed_model_leaves_the_baseline(tmp_path: Path, monkeypatch) -> None:
    use_case = _project(tmp_path, {"a.sql": "select * from {{ ref('x') }}"})
    monkeypatch.setattr(ns, "REPO", tmp_path)
    monkeypatch.setattr(ns._paths, "REPO", tmp_path, raising=False)
    monkeypatch.setattr(ns, "use_case_dir", lambda slug: use_case)
    ns.report("uc", check=False, update=True)

    (use_case / "dbt_project/models/a.sql").write_text(
        "select a, b from {{ ref('x') }}", encoding="utf-8")
    result = ns.report("uc", check=False, update=True)
    assert result["removed_from_baseline"] == ["models/a.sql"]
    baseline = json.loads((use_case / "artifacts/star-baseline.json").read_text())
    assert baseline["models"] == []


@needs_enhanza
def test_the_committed_baseline_is_current() -> None:
    """A stale baseline hides a star that has already landed."""
    result = ns.report("enhanza-analytics", check=True, update=False)
    assert result["status"] == "ok", result.get("reason")


# ---------------------------------------------------------------------------------------
# The deriver: a citation or nothing
# ---------------------------------------------------------------------------------------


def test_singular_and_plural_match_but_a_prefix_does_not() -> None:
    """`deal_pipelines` normalises to `deal_pipeline`, which starts with `deal`.

    A prefix rule matched it to dlt's `deal` object on the first real run and gave the
    pipeline table `amount`, `closedate` and `dealname` — deal properties attributed to a
    pipeline. An honest miss costs a lookup; a wrong match generates the tests that
    enforce it.
    """
    tables = {"company": [], "deal": []}
    assert ssd.match_table("companies", tables)[0] == "company"
    assert ssd.match_table("deal", tables)[0] == "deal"
    assert ssd.match_table("deal_pipelines", tables) is None


def test_a_vendor_load_column_is_never_declared_as_ours() -> None:
    """`_fivetran_synced` is the reference connector's bookkeeping. This project lands
    `_dlt_id`; declaring the other would fail every staging model for not reading a
    column that will never exist."""
    for name in ("_fivetran_synced", "_fivetran_deleted", "_airbyte_ab_id"):
        assert ssd.VENDOR_LOAD_COLUMNS.match(name), name
    for name in ("_dlt_id", "id", "property_name"):
        assert not ssd.VENDOR_LOAD_COLUMNS.match(name), name


def test_a_doc_reference_description_is_dropped() -> None:
    """Fivetran describes columns with `{{ doc(...) }}` against blocks in *their* package.
    Carried across, `dbt parse` fails outright — found by promoting them and running it."""
    assert ssd.DOC_REFERENCE.search("{{ doc('_fivetran_synced') }}")
    assert not ssd.DOC_REFERENCE.search("The ID of the company.")


def test_every_reference_declares_the_loader_whose_names_it_lands() -> None:
    """Without it the two conventions merge and the contract matches no warehouse."""
    for connector, refs in ssd.REFERENCES.items():
        assert refs, connector
        for ref in refs:
            assert ref.loader, f"{connector}: {ref.cite} declares no loader"
            assert ref.kind in ssd.PARSERS, f"{connector}: no parser for {ref.kind}"


def test_dlt_outranks_fivetran_here_because_this_repository_loads_with_dlt() -> None:
    ranks = {r.loader: r.rank for r in ssd.REFERENCES["hubspot"]}
    assert ranks["dlt"] < ranks["fivetran"]


def test_the_fivetran_parser_reads_tables_and_columns() -> None:
    text = (
        "sources:\n"
        "  - name: hubspot\n"
        "    tables:\n"
        "      - name: company\n"
        "        columns:\n"
        "          - name: id\n"
        "            description: The ID of the company.\n"
        "          - name: domain\n"
        "      - name: deal\n"
        "        columns:\n"
        "          - name: deal_id\n"
    )
    tables = ssd.parse_fivetran_src_yml(text)
    assert [c["name"] for c in tables["company"]] == ["id", "domain"]
    assert tables["company"][0]["description"] == "The ID of the company."
    assert [c["name"] for c in tables["deal"]] == ["deal_id"]


def test_the_dlt_parser_reads_the_default_property_tuples() -> None:
    text = (
        'DEFAULT_COMPANY_PROPS = (\n    "createdate",\n    "domain",\n)\n'
        'DEFAULT_DEAL_PROPS: List[str] = ["amount", "dealname"]\n'
    )
    parsed = ssd.parse_dlt_settings(text)
    assert [c["name"] for c in parsed["company"]] == ["createdate", "domain"]
    assert [c["name"] for c in parsed["deal"]] == ["amount", "dealname"]


@needs_enhanza
def test_the_committed_reference_cache_carries_its_citations() -> None:
    """A cached schema with no citation is a recollection with a filename."""
    path = ssd.CACHE_DIR / "hubspot.json"
    if not path.exists():
        pytest.skip("hubspot reference cache not refreshed on this branch")
    cache = json.loads(path.read_text(encoding="utf-8"))
    assert cache["sources"], "cache holds no sources"
    for source in cache["sources"]:
        assert source["cite"] and source["url"].startswith("https://")
        assert source["loader"] and isinstance(source["rank"], int)


@needs_enhanza
def test_the_promoted_contract_carries_no_foreign_naming_convention() -> None:
    """The union bug, pinned where it would land: a table declaring both `email` and
    `property_email` matches no warehouse."""
    sources = (ENHANZA / "dbt_project/packages/hubspot/models/sources.yml")
    if not sources.exists():
        pytest.skip("hubspot package not on this branch")
    text = sources.read_text(encoding="utf-8")
    assert "property_" not in text, (
        "a Fivetran-convention column reached this project's source contract; "
        "this repository lands dlt names"
    )
    assert "_fivetran_" not in text
